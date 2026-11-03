"""The usage-sharing routes over real HTTP (docs/architecture.md).

* `GET /api/usage` says, per group, its status, its CURRENT fingerprint and the
  browser capabilities the dashboard may turn on; and whether an environment
  switch has turned sharing off on this machine.
* `PUT /api/usage/consent` records an answer with its words, refuses an older
  scope with 409 `usage-catalogue-changed` and a bad answer with 422, and writes
  nothing when it refuses. The API's tally follows the answer at once.
* Preview is exactly what the next send carries, and leaves out a row that
  does not fit the catalogue instead of sending it as it stands.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from tests.api_errors import code_of, said
from tests.usage_fixtures import CONSENT_TEXT, NOW, share
from tracker.db.models import AppSetting
from tracker.usage_stats import consent, outbox
from tracker.usage_stats.registry import BROWSER_SCOPE, CATALOGUE, Group, fingerprint
from tracker.usage_stats.tally import TALLY

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]

CANARY = "zyxwv-robotics"


def _answer(**answers: bool) -> dict:
    return {
        "answers": answers,
        "text": CONSENT_TEXT,
        "locale": "en",
        "fingerprints": {group: fingerprint(Group(group)) for group in answers},
    }


async def test_the_state_of_an_install_nobody_has_asked(api_client, sharing_allowed) -> None:
    body = (await api_client.get("/api/usage")).json()
    assert [g["group"] for g in body["groups"]] == ["usage", "crashes", "questions"]
    for group in body["groups"]:
        assert group["status"] == "undecided"
        assert group["fingerprint"] == fingerprint(Group(group["group"]))
        assert group["browser_scope"] == list(BROWSER_SCOPE[Group(group["group"])])
    assert body["blocked_by"] is None
    assert body["install_id"] is None
    assert body["host"] == "https://eu.i.posthog.com"
    assert body["project_key"].startswith("phc_")


async def test_the_suite_switch_is_reported(api_client) -> None:
    body = (await api_client.get("/api/usage")).json()
    assert body["blocked_by"] == "ROLEBAND_NO_USAGE_STATS"


async def test_consent_is_recorded_and_the_tally_follows(api_client, db_session, sharing_allowed, monkeypatch) -> None:
    monkeypatch.setattr(TALLY, "usage", False)
    response = await api_client.put("/api/usage/consent", json=_answer(usage=True, questions=False))
    assert response.status_code == 200, response.text
    body = response.json()
    status = {g["group"]: g["status"] for g in body["groups"]}
    assert status == {"usage": "shared", "crashes": "undecided", "questions": "declined"}
    assert body["install_id"]
    stored = (await db_session.get(AppSetting, consent.SHARING_KEY)).value["groups"]
    assert stored["usage"]["text"] == CONSENT_TEXT
    assert TALLY.usage is True


async def test_an_older_scope_is_refused_and_nothing_written(api_client, db_session, sharing_allowed) -> None:
    payload = _answer(usage=True, crashes=True)
    payload["fingerprints"]["usage"] = "0" * 64
    response = await api_client.put("/api/usage/consent", json=payload)
    assert response.status_code == 409
    assert code_of(response.json()) == "usage-catalogue-changed"
    assert said(response.json())["detail"]
    assert response.json()["detail"]["params"] == {"groups": ["usage"]}
    assert await db_session.get(AppSetting, consent.SHARING_KEY) is None


@pytest.mark.parametrize(("key", "value"), [("text", "  "), ("locale", "english please")])
async def test_a_bad_answer_is_422_and_nothing_written(api_client, db_session, sharing_allowed, key, value) -> None:
    response = await api_client.put("/api/usage/consent", json=_answer(usage=True) | {key: value})
    assert response.status_code == 422
    assert code_of(response.json()) == "invalid-input"
    assert await db_session.get(AppSetting, consent.SHARING_KEY) is None


async def test_an_unknown_group_is_refused_by_the_schema(api_client, sharing_allowed) -> None:
    payload = _answer(usage=True)
    payload["answers"]["everything"] = True
    assert (await api_client.put("/api/usage/consent", json=payload)).status_code == 422


async def test_reset_replaces_the_install_id(api_client, sharing_allowed) -> None:
    first = (await api_client.put("/api/usage/consent", json=_answer(usage=True))).json()["install_id"]
    second = (await api_client.post("/api/usage/install-id/reset")).json()["install_id"]
    assert first and second and first != second


async def test_preview_is_the_next_body_and_leaves_out_what_does_not_fit(api_client, db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE)
    yesterday = (NOW - timedelta(days=1)).date()
    spec = CATALOGUE["daily_action"]
    await outbox.add_count(db_session, spec, {"action": "save_job"}, day=yesterday, at=NOW, by=3)
    # A row written around the recorder, with a company in it.
    await outbox.add_count(db_session, spec, {"action": f"follow:{CANARY}"}, day=yesterday, at=NOW)
    await db_session.commit()

    body = (await api_client.get("/api/usage/preview")).json()
    assert body["left_out"] == 1
    assert CANARY not in json.dumps(body)
    [event] = body["body"]["batch"]
    assert body["body"]["api_key"].startswith("phc_")
    assert event["event"] == "daily_action"
    assert event["properties"]["action"] == "save_job"
    assert event["properties"]["count"] == 3
    assert event["properties"]["$geoip_disable"] is True


async def test_sent_lists_what_left(api_client, db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE)
    spec = CATALOGUE["daily_action"]
    await outbox.add_count(db_session, spec, {"action": "save_job"}, day=NOW.date(), at=NOW)
    await db_session.commit()
    [row] = await outbox.pending(db_session, groups=[Group.USAGE], today=(NOW + timedelta(days=1)).date())
    await outbox.mark_sent(db_session, [row.id], now=NOW)
    await db_session.commit()
    events = (await api_client.get("/api/usage/sent")).json()["events"]
    assert [(e["name"], e["count"], e["group"]) for e in events] == [("daily_action", 1, "usage")]
