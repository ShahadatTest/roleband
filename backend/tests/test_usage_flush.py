"""The daily send posts exactly what the preview shows, once (docs/architecture.md).

Every request is answered by an `httpx.MockTransport`; nothing reaches PostHog.
Contracts:

* The body is `{"api_key", "batch"}`; every event carries the install ID, the
  GeoIP opt-out, a timestamp and a stable `uuid`; the preview is that body.
* Retryable failures (5xx, 429, no answer) leave rows claimed and retry after an
  hour, not before; a refusal (4xx) is never retried; a sent row is not sent
  again and the next send waits a day.
* A switch, an empty key, nothing shared and a maintenance wake send nothing;
  a switch decides before any database read.
* Scan health names families, never employers, and covers only days after the
  user shared usage.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.usage_fixtures import NOW, share
from tracker.config import get_settings
from tracker.db.models import (
    AppSetting,
    ScrapeRun,
    ScrapeSourceRun,
    SourceBinding,
    TrackedCompany,
    UsageEvent,
)
from tracker.platform.power import WAITING_FOR_FULL_WAKE, Power
from tracker.usage_stats import outbox, view
from tracker.usage_stats.consent import SHARING_KEY, get_sharing
from tracker.usage_stats.flush import RETRY_AFTER, flush_if_due
from tracker.usage_stats.install_id import get_install_id
from tracker.usage_stats.recorder import record_count, record_exception, record_milestone
from tracker.usage_stats.registry import CATALOGUE, Group

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]

YESTERDAY = NOW - timedelta(days=1)
AWAKE = Power(dark_wake=False, on_battery=True)
LID_SHUT = Power(dark_wake=True, on_battery=True)
CANARY = "zyxwv-robotics"


def _scope(db_session):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def scope():
        async with factory() as session:
            yield session

    return scope


class PostHog:
    """A stand-in for `/batch/`, answering `status` and keeping every request."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={"status": "Ok"})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def bodies(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]


async def _flush(db_session, posthog: PostHog, *, now=NOW, power=AWAKE, **kwargs) -> dict:
    async with posthog.client() as client:
        return await flush_if_due(scope=_scope(db_session), power=lambda: power, client=client, now=now, **kwargs)


async def _seed(db_session) -> None:
    await share(db_session, Group.USAGE, Group.CRASHES, now=YESTERDAY - timedelta(hours=1))
    await record_count(db_session, "daily_action", {"action": "save_job"}, now=YESTERDAY, by=3)
    await record_milestone(db_session, "first_job_saved", now=YESTERDAY)
    try:
        raise LookupError(f"no board for {CANARY}")
    except LookupError as exc:
        await record_exception(db_session, exc, source="api", now=YESTERDAY)
    await db_session.commit()


async def test_the_body_is_exact_and_the_preview_is_it(db_session, sharing_allowed) -> None:
    await _seed(db_session)
    preview = await view.preview(db_session, now=NOW)
    posthog = PostHog()
    result = await _flush(db_session, posthog)

    assert result["sent"] == 3 and result["outcome"] == "sent"
    [request] = posthog.requests
    assert str(request.url) == "https://eu.i.posthog.com/batch/"
    assert request.headers["user-agent"].startswith("RoleBand/")
    [body] = posthog.bodies()
    assert body == preview["body"]
    assert body["api_key"] == get_settings().usage_stats_project_key
    install_id = await get_install_id(db_session)
    events = {event["event"]: event for event in body["batch"]}
    assert set(events) == {"daily_action", "first_job_saved", "$exception"}
    for event in body["batch"]:
        assert set(event) == {"event", "properties", "timestamp", "uuid"}
        assert event["properties"]["distinct_id"] == install_id
        assert event["properties"]["$geoip_disable"] is True
        assert "$process_person_profile" not in event["properties"]
    assert events["daily_action"]["properties"]["count"] == 3
    assert events["daily_action"]["properties"]["day"] == YESTERDAY.date().isoformat()
    crash = events["$exception"]["properties"]
    assert crash["$exception_list"][0]["type"] == "LookupError"
    assert "value" not in crash["$exception_list"][0]
    assert CANARY not in json.dumps(body)


async def test_todays_heartbeat_waits_for_tomorrows_send(db_session, sharing_allowed) -> None:
    await _seed(db_session)
    await _flush(db_session, PostHog())
    [heartbeat] = (await db_session.execute(select(UsageEvent).where(UsageEvent.name == "daily_heartbeat"))).scalars()
    assert heartbeat.day == NOW.date() and heartbeat.sent_at is None
    tomorrow = PostHog()
    await _flush(db_session, tomorrow, now=NOW + timedelta(days=1))
    sent = {event["event"]: event for event in tomorrow.bodies()[0]["batch"]}
    assert "daily_heartbeat" in sent
    assert sent["daily_heartbeat"]["properties"]["$set"]["os"] in {"macos", "linux", "windows", "other"}


async def test_a_sent_row_is_not_sent_again_and_the_next_send_waits_a_day(db_session, sharing_allowed) -> None:
    await _seed(db_session)
    await _flush(db_session, PostHog())
    soon = PostHog()
    assert (await _flush(db_session, soon, now=NOW + timedelta(hours=3)))["reason"] == "not due"
    assert soon.requests == []
    forced = PostHog()
    await _flush(db_session, forced, now=NOW + timedelta(hours=3), force=True)
    # Forced past the day gate, there is nothing left of yesterday to send.
    assert forced.requests == []


@pytest.mark.parametrize("status", [500, 503, 429])
async def test_a_retryable_failure_retries_after_an_hour_not_before(db_session, sharing_allowed, status) -> None:
    await _seed(db_session)
    failing = PostHog(status)
    assert (await _flush(db_session, failing))["outcome"] == "retry"
    first_uuids = [e["uuid"] for e in failing.bodies()[0]["batch"]]
    too_soon = PostHog()
    await _flush(db_session, too_soon, now=NOW + RETRY_AFTER - timedelta(minutes=5))
    assert too_soon.requests == []
    retry = PostHog()
    result = await _flush(db_session, retry, now=NOW + RETRY_AFTER + timedelta(minutes=5))
    assert result["outcome"] == "sent"
    # The same events, under the same ids: PostHog de-duplicates an ambiguous retry.
    assert sorted(e["uuid"] for e in retry.bodies()[0]["batch"]) == sorted(first_uuids)


async def test_a_refusal_is_never_retried(db_session, sharing_allowed) -> None:
    await _seed(db_session)
    assert (await _flush(db_session, PostHog(400)))["outcome"] == "rejected"
    later = PostHog()
    await _flush(db_session, later, now=NOW + timedelta(days=2))
    sent = [e["event"] for body in later.bodies() for e in body["batch"]]
    assert "daily_action" not in sent and "$exception" not in sent


async def test_no_answer_is_a_retry(db_session, sharing_allowed) -> None:
    await _seed(db_session)

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(unreachable)) as client:
        result = await flush_if_due(scope=_scope(db_session), power=lambda: AWAKE, client=client, now=NOW)
    assert result["outcome"] == "retry"
    assert (await db_session.execute(select(UsageEvent).where(UsageEvent.sent_at.is_not(None)))).first() is None


async def test_a_lid_shut_mac_sends_nothing(db_session, sharing_allowed) -> None:
    await _seed(db_session)
    posthog = PostHog()
    assert (await _flush(db_session, posthog, power=LID_SHUT))["reason"] == WAITING_FOR_FULL_WAKE
    assert posthog.requests == []


@pytest.mark.parametrize("switch", ["ROLEBAND_NO_USAGE_STATS", "DO_NOT_TRACK", "CI"])
async def test_a_switch_decides_before_any_database_read(sharing_allowed, monkeypatch, switch) -> None:
    monkeypatch.setenv(switch, "1")

    def no_database():
        raise AssertionError("the switch should have ended the send before any database read")

    posthog = PostHog()
    async with posthog.client() as client:
        result = await flush_if_due(scope=no_database, power=lambda: AWAKE, client=client, now=NOW)
    assert result == {"sent": 0, "reason": f"switched off by {switch}"}
    assert posthog.requests == []


async def test_no_key_and_nothing_shared_send_nothing(db_session, sharing_allowed, monkeypatch) -> None:
    posthog = PostHog()
    assert (await _flush(db_session, posthog))["reason"] == "nothing shared"
    await _seed(db_session)
    monkeypatch.setattr(get_settings(), "usage_stats_project_key", "")
    assert (await _flush(db_session, posthog))["reason"] == "no project key"
    assert posthog.requests == []


@pytest.mark.parametrize("keep_crashes", [False, True])
async def test_revocation_before_claim_stops_new_rollups_and_pending_rows(db_session, sharing_allowed, keep_crashes) -> None:
    await _seed(db_session)
    await _source_run(db_session, "greenhouse", "ok", YESTERDAY)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    entered = 0

    @asynccontextmanager
    async def scope():
        nonlocal entered
        entered += 1
        if entered == 2:
            async with factory() as revocation:
                groups = [Group.USAGE] if keep_crashes else [Group.USAGE, Group.CRASHES]
                await share(revocation, *groups, shared=False, now=NOW)
                await revocation.commit()
            async with factory() as verify:
                assert not (await get_sharing(verify)).shared(Group.USAGE)
        async with factory() as session:
            yield session

    posthog = PostHog()
    async with posthog.client() as client:
        result = await flush_if_due(scope=scope, power=lambda: AWAKE, client=client, now=NOW, force=True)
    sent = [event["event"] for body in posthog.bodies() for event in body["batch"]]
    assert sent == (["$exception"] if keep_crashes else [])
    assert result["sent"] == int(keep_crashes)
    db_session.expire_all()
    rows = (await db_session.scalars(select(UsageEvent))).all()
    assert not any(row.name in {"daily_scan_health", "first_scan_finished", "daily_heartbeat"} for row in rows)
    assert all(row.withdrawn_at == NOW and row.sent_at is None for row in rows if row.consent_group == Group.USAGE.value)


async def test_claim_waits_for_a_consent_edit_already_in_progress(db_session, sharing_allowed) -> None:
    await _seed(db_session)
    await _source_run(db_session, "greenhouse", "ok", YESTERDAY)
    await db_session.commit()
    claim_reached, revoked = asyncio.Event(), asyncio.Event()

    class ClaimSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            if self.info.get("claim") and "pg_advisory_xact_lock" in str(statement):
                claim_reached.set()
            return await super().execute(statement, *args, **kwargs)

        async def get(self, entity, ident, **kwargs):
            row = await super().get(entity, ident, **kwargs)
            if self.info.get("claim") and entity is AppSetting and ident == SHARING_KEY:
                claim_reached.set()
                await revoked.wait()
            return row

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=ClaimSession)
    entered = 0

    @asynccontextmanager
    async def scope():
        nonlocal entered
        entered += 1
        async with factory(info={"claim": entered == 2}) as session:
            yield session

    async with factory() as revocation:
        await share(revocation, Group.USAGE, Group.CRASHES, shared=False, now=NOW)

        async def commit_revocation():
            await claim_reached.wait()
            await revocation.commit()
            revoked.set()

        committing = asyncio.create_task(commit_revocation())
        posthog = PostHog()
        try:
            async with asyncio.timeout(5), posthog.client() as client:
                result = await flush_if_due(scope=scope, power=lambda: AWAKE, client=client, now=NOW, force=True)
                await committing
        finally:
            if not committing.done():
                committing.cancel()
            await asyncio.gather(committing, return_exceptions=True)
    assert result == {"sent": 0, "reason": "nothing shared"}
    assert posthog.requests == []


async def test_a_row_that_no_longer_fits_is_rejected_unsent(db_session, sharing_allowed) -> None:
    await _seed(db_session)
    await outbox.add_count(db_session, CATALOGUE["daily_action"], {"action": f"follow:{CANARY}"}, day=YESTERDAY.date(), at=YESTERDAY)
    await db_session.commit()
    posthog = PostHog()
    result = await _flush(db_session, posthog)
    assert result["left_out"] == 1
    assert CANARY not in posthog.requests[0].content.decode()
    later = PostHog()
    await _flush(db_session, later, now=NOW + timedelta(days=2))
    assert CANARY not in "".join(r.content.decode() for r in later.requests)


async def _source_run(db_session, provider_key: str, outcome: str, at) -> None:
    slug = f"{CANARY}-{provider_key}-{uuid.uuid4().hex[:8]}"
    company = TrackedCompany(slug=slug, display=slug.title(), adapter=provider_key, status="active",
                             enabled=True, visible=True, source="catalog")
    db_session.add(company)
    await db_session.flush()
    binding = SourceBinding(company_slug=slug, connector_kind=provider_key, connector_id=CANARY)
    run = ScrapeRun(status="ok")
    db_session.add_all([binding, run])
    await db_session.flush()
    db_session.add(ScrapeSourceRun(
        run_id=run.id, binding_id=binding.id, company_slug=binding.company_slug, provider_key=provider_key,
        scan_mode="reconcile", outcome=outcome, started_at=at, finished_at=at,
    ))


async def test_scan_health_names_families_and_only_after_sharing(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE, now=NOW - timedelta(days=2))
    await _source_run(db_session, "greenhouse", "ok", YESTERDAY)
    await _source_run(db_session, "greenhouse", "ok", YESTERDAY)
    await _source_run(db_session, "apple", "failed", YESTERDAY)
    await _source_run(db_session, "oracle", "ok", YESTERDAY)
    # Before the user shared: never rolled up.
    await _source_run(db_session, "workday", "blocked", NOW - timedelta(days=4))
    await db_session.commit()
    posthog = PostHog()
    await _flush(db_session, posthog)
    health = sorted(
        (e["properties"]["family"], e["properties"]["outcome"], e["properties"]["count"])
        for e in posthog.bodies()[0]["batch"]
        if e["event"] == "daily_scan_health"
    )
    assert health == [("greenhouse", "ok", 2), ("single_company", "failed", 1), ("single_company", "ok", 1)]
    [first] = [e for e in posthog.bodies()[0]["batch"] if e["event"] == "first_scan_finished"]
    assert first["properties"]["outcome"] in {"ok", "failed"}
    body = posthog.requests[0].content.decode()
    assert CANARY not in body and "apple" not in body and "oracle" not in body
