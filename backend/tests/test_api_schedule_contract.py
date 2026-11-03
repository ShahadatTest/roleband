"""The schedule's response contract.

`tracker/api/schemas/ops.py` declares what `GET /api/schedule` and
`PATCH /api/schedule/{binding_id}` send and what the PATCH parses, over HTTP
(`tests/test_api_sync.py` calls the serializer and the handler directly). These tests hold the contract to its
sources:

1. **Vocabulary**: `mode` is the scheduler's `ScanMode`; the anchor bounds are
   the table's CHECK constraints; strings read back from tables with no CHECK
   constraint stay strings.
2. **The routes over real HTTP** against seeded Postgres rows
   (`tests/schedule_contract_seed.py`) with the ops clock and settings pinned:
   each shape's exact keys, which bindings are served, every status and the
   eligibility it implies, a move read back from the table and from the next
   GET, and every refusal leaving the table exactly as it was.
3. **Drift in both directions**: a key or a status the serializer produces
   without its model fails the response instead of reaching a client.
"""

from __future__ import annotations

from datetime import timedelta
from typing import get_args

import pytest
import pytest_asyncio
from fastapi.exceptions import ResponseValidationError
from sqlalchemy import CheckConstraint, select

from tests.api_errors import said
from tests.ops_contract_seed import NOW
from tests.schedule_contract_seed import (
    META_TIMEZONE,
    pin_schedule_environment,
    seed_schedule_contract,
)
from tracker.api.app import app
from tracker.api.routers import ops as ops_router
from tracker.api.schemas import ops as contract
from tracker.db.models import ProviderPressureState, SourceBinding, SyncScheduleState
from tracker.workflows.collection_types import ScanMode
from tracker.workflows.schedule_status import SCHEDULER_TICK_SECONDS

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")

# --------------------------------------------------------------------------- #
# 1. Vocabulary
# --------------------------------------------------------------------------- #


def test_the_mode_is_one_of_the_two_scan_modes_a_schedule_row_has_a_deadline_for():
    """`repair` and `shadow` are scan modes too, but the table stores no deadline or anchor for them."""
    modes = set(get_args(contract.ScheduleTimeUpdate.model_fields["mode"].annotation))
    assert modes == {ScanMode.DISCOVERY.value, ScanMode.RECONCILE.value}
    for mode in modes:
        assert {f"next_{mode}_at", f"{mode}_anchor_minute"} <= set(SyncScheduleState.__table__.columns.keys())


def test_both_routes_answer_the_contract_model_and_parse_its_body():
    routes = {(next(iter(r.methods)), r.path): r for r in app.routes if getattr(r, "path", "").startswith("/api/schedule")}
    assert routes[("GET", "/api/schedule")].response_model is contract.SchedulePayload
    patch = routes[("PATCH", "/api/schedule/{binding_id}")]
    assert patch.response_model is contract.SchedulePayload
    assert patch.body_field.field_info.annotation is contract.ScheduleTimeUpdate


def test_the_anchor_bounds_are_the_tables_check_constraints():
    checks = {c.name: str(c.sqltext) for c in SyncScheduleState.__table__.constraints if isinstance(c, CheckConstraint)}
    for mode in ("discovery", "reconcile"):
        assert f"{mode}_anchor_minute BETWEEN 0 AND 1439" in checks[f"ck_sync_schedule_{mode}_anchor_minute"]
    schema = contract.SchedulePayload.model_json_schema()["$defs"]["ScheduleBindingPayload"]["properties"]
    body = contract.ScheduleTimeUpdate.model_json_schema()["properties"]["local_minute"]
    for bounded in (schema["discovery_anchor_minute"]["anyOf"][0], schema["reconcile_anchor_minute"]["anyOf"][0], body):
        assert (bounded["minimum"], bounded["maximum"]) == (0, 1439)


@pytest.mark.parametrize(
    ("table", "fields"),
    [
        (SourceBinding, [(contract.ScheduleBindingPayload, "closure_capability")]),
        (SyncScheduleState, [(contract.ScheduleBindingPayload, "last_outcome")]),
        (ProviderPressureState, [(contract.ScheduleProviderPayload, "state"), (contract.ScheduleProviderPayload, "last_outcome"),
                                 (contract.ScheduleBindingPayload, "provider_state")]),
    ],
    ids=["binding", "schedule_state", "provider_pressure"],
)
def test_no_constraint_bounds_the_stored_strings_the_model_leaves_open(table, fields):
    bounded = [str(c.sqltext) for c in table.__table__.constraints if isinstance(c, CheckConstraint)]
    for model, name in fields:
        column = name if name not in ("provider_state", "state") else "state"
        assert not [text for text in bounded if column in text], f"a CHECK constraint now bounds {table.__tablename__}.{column}"
        assert model.model_fields[name].annotation in (str, str | None), f"{model.__name__}.{name}"


# --------------------------------------------------------------------------- #
# 2. The routes over HTTP
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def seeded(db_session, monkeypatch, tmp_path, no_escape):
    pin_schedule_environment(monkeypatch, tmp_path)
    return await seed_schedule_contract(db_session)


def _fields(model) -> list[str]:
    return list(model.model_fields)


def _iso(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def _get(api_client) -> dict:
    response = await api_client.get("/api/schedule")
    assert response.status_code == 200, response.text
    return response.json()


async def _table(db_session) -> list[tuple]:
    """Every stored column of every schedule row: what a move could write."""
    table = SyncScheduleState.__table__
    return [tuple(row) for row in (await db_session.execute(select(table).order_by(table.c.binding_id))).all()]


@pytest.mark.asyncio
async def test_the_schedule_serves_every_key_in_declared_order(api_client, seeded):
    body = await _get(api_client)
    assert list(body) == _fields(contract.SchedulePayload)
    assert all(list(row) == _fields(contract.ScheduleBindingPayload) for row in body["bindings"])
    assert all(list(row) == _fields(contract.ScheduleProviderPayload) for row in body["providers"])
    assert {k: body[k] for k in _fields(contract.SchedulePayload)[:5]} == {
        "generated_at": _iso(NOW), "enabled": True, "tick_seconds": SCHEDULER_TICK_SECONDS,
        "max_parallel_providers": 2, "authoritative_stale_hours": 30,
    }


@pytest.mark.asyncio
async def test_only_stable_bindings_of_enabled_companies_are_served_by_company_with_every_status(api_client, seeded):
    body = await _get(api_client)
    statuses = {row["company"]: row["status"] for row in body["bindings"]}
    assert list(statuses) == ["acme", "globex", "hooli", "initech", "meta", "umbrella"]
    assert statuses == {
        "acme": "scheduled", "globex": "manual", "hooli": "unscheduled",
        "initech": "cooldown", "meta": "policy_denied", "umbrella": "paused",
    }
    assert set(statuses.values()) == set(get_args(contract.ScheduleBindingPayload.model_fields["status"].annotation))
    assert {row["company"]: row["binding_id"] for row in body["bindings"]} == {
        slug: seeded.bindings[slug] for slug in statuses
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(("on_battery", "waiting"), [(True, "mains"), (False, None)], ids=["battery", "mains"])
async def test_a_mains_only_plan_says_it_waits_for_mains_while_on_battery(
    api_client, db_session, seeded, monkeypatch, on_battery, waiting
):
    from tracker.platform.power import Power
    from tracker.settings_store import SchedulePlanSettings, set_schedule_plan_settings

    await set_schedule_plan_settings(db_session, SchedulePlanSettings(mains_only=True))
    await db_session.commit()
    monkeypatch.setattr(ops_router, "read_power", lambda: Power(dark_wake=False, on_battery=on_battery))

    plan = (await _get(api_client))["plan"]
    assert (plan["mains_only"], plan["waiting"]) == (True, waiting)


@pytest.mark.asyncio
async def test_providers_count_the_served_bindings_and_a_denied_provider_reads_denied(api_client, seeded):
    body = await _get(api_client)
    assert [(p["provider"], p["state"], p["binding_count"]) for p in body["providers"]] == [
        ("ashby", "backoff", 1), ("greenhouse", "ready", 3), ("lever", "paused", 1), ("meta", "policy_denied", 1),
    ]
    ashby, _, _, meta = body["providers"]
    assert (ashby["cooldown_until"], ashby["last_outcome"]) == (_iso(NOW + timedelta(hours=3)), "blocked")
    assert {k: meta[k] for k in ("cooldown_until", "last_started_at", "last_finished_at", "last_outcome")} == dict.fromkeys(
        ("cooldown_until", "last_started_at", "last_finished_at", "last_outcome")
    )


@pytest.mark.asyncio
async def test_eligibility_follows_the_deadline_the_cooldown_and_the_provider_state(api_client, seeded):
    rows = {row["company"]: row for row in (await _get(api_client))["bindings"]}
    eligible = {slug: (row["eligible_discovery_at"], row["eligible_reconcile_at"]) for slug, row in rows.items()}
    assert eligible == {
        # discovery on, nothing in the way: each deadline as stored.
        "acme": (_iso(NOW + timedelta(hours=4)), _iso(NOW + timedelta(hours=22))),
        # discovery off; the queued manual sync pulled reconcile forward.
        "globex": (None, _iso(NOW - timedelta(minutes=10))),
        "hooli": (None, None),
        # the ashby cooldown holds back the overdue manual reconcile, not the later discovery.
        "initech": (_iso(NOW + timedelta(hours=4)), _iso(NOW + timedelta(hours=3))),
        "meta": (None, None),
        "umbrella": (None, None),
    }
    assert rows["initech"]["manual_requested_at"] == _iso(NOW - timedelta(minutes=10))
    assert rows["initech"]["cooldown_until"] == _iso(NOW + timedelta(hours=3))


@pytest.mark.asyncio
async def test_an_unscheduled_binding_carries_no_deadlines_and_zero_counters(api_client, seeded):
    hooli = next(row for row in (await _get(api_client))["bindings"] if row["company"] == "hooli")
    assert hooli == {
        "binding_id": seeded.bindings["hooli"], "company": "hooli", "provider": "greenhouse",
        "closure_capability": "authoritative", "scheduled": False, "discovery_enabled": False,
        **dict.fromkeys(_fields(contract.ScheduleBindingPayload)[6:19]),
        "last_new_count": 0, "consecutive_empty_discoveries": 0,
        "provider_state": "ready", "cooldown_until": None, "status": "unscheduled",
        # The scheduler's own rule: a Greenhouse company may be read on a timer.
        "waits_for_user": None,
    }


@pytest.mark.asyncio
async def test_an_anchored_schedule_serves_its_anchors_and_zone(api_client, seeded):
    meta = next(row for row in (await _get(api_client))["bindings"] if row["company"] == "meta")
    assert (meta["discovery_anchor_minute"], meta["reconcile_anchor_minute"], meta["schedule_timezone"]) == (
        8 * 60, 20 * 60, META_TIMEZONE,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("company", "mode", "minute", "zone", "deadline"),
    [
        # 20:00 in Stockholm is 18:00 UTC, still ahead of 14:00 local.
        ("acme", "reconcile", 20 * 60, "Europe/Stockholm", "2026-07-20T18:00:00Z"),
        # 08:00 in New York is exactly now: never an immediately overdue deadline, so tomorrow.
        ("acme", "discovery", 8 * 60, "America/New_York", "2026-07-21T12:00:00Z"),
        # a cooldown does not refuse a move; the queued manual reconcile stays queued.
        ("initech", "discovery", 60, "UTC", "2026-07-21T01:00:00Z"),
    ],
    ids=["reconcile_later_today", "discovery_at_now_is_tomorrow", "discovery_during_cooldown"],
)
async def test_a_move_persists_the_anchor_and_answers_the_schedule_the_next_read_serves(
    api_client, db_session, seeded, company, mode, minute, zone, deadline,
):
    before = {row["company"]: row for row in (await _get(api_client))["bindings"]}[company]
    response = await api_client.patch(
        f"/api/schedule/{seeded.bindings[company]}", json={"mode": mode, "local_minute": minute, "timezone": zone},
    )
    assert response.status_code == 200, response.text
    assert response.json() == await _get(api_client)

    after = {row["company"]: row for row in response.json()["bindings"]}[company]
    other = "reconcile" if mode == "discovery" else "discovery"
    assert (after[f"{mode}_anchor_minute"], after[f"next_{mode}_at"], after["schedule_timezone"]) == (minute, deadline, zone)
    unchanged = [f"{other}_anchor_minute", f"next_{other}_at", "manual_requested_at", "status"]
    assert {k: after[k] for k in unchanged} == {k: before[k] for k in unchanged}

    stored = (await db_session.execute(
        select(getattr(SyncScheduleState, f"{mode}_anchor_minute"), getattr(SyncScheduleState, f"next_{mode}_at"),
               SyncScheduleState.schedule_timezone).where(SyncScheduleState.binding_id == seeded.bindings[company])
    )).one()
    assert (stored[0], _iso(stored[1]), stored[2]) == (minute, deadline, zone)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("company", "body", "status", "detail"),
    [
        ("missing", {"mode": "reconcile"}, 404, "scheduled connector not found"),
        ("dormant", {"mode": "reconcile"}, 404, "scheduled connector not found"),
        ("wayne", {"mode": "reconcile"}, 404, "scheduled connector not found"),
        ("hooli", {"mode": "reconcile"}, 404, "schedule has not been seeded"),
        ("umbrella", {"mode": "discovery"}, 409, "lever scheduling is paused"),
        ("meta", {"mode": "discovery"}, 409, "meta scheduling is policy_denied"),
        ("globex", {"mode": "discovery"}, 409, "globex does not support discovery probes"),
        ("globex", {"mode": "reconcile"}, 409, "cancel the queued manual sync before changing its schedule"),
        ("acme", {"mode": "reconcile", "timezone": "Mars/Olympus"}, 422, "unknown timezone: Mars/Olympus"),
        ("acme", {"mode": "reconcile", "local_minute": 1440}, 422, None),
        ("acme", {"mode": "reconcile", "local_minute": -1}, 422, None),
        ("acme", {"mode": "sweep"}, 422, None),
        ("acme", {"mode": "reconcile", "timezone": ""}, 422, None),
    ],
    ids=[
        "unknown_binding", "disabled_company", "candidate_binding", "no_schedule_row",
        "provider_paused", "provider_denied", "discovery_unsupported", "manual_sync_queued",
        "unknown_zone", "minute_past_the_day", "negative_minute", "unknown_mode", "empty_zone",
    ],
)
async def test_a_refused_move_answers_why_and_writes_nothing(api_client, db_session, seeded, company, body, status, detail):
    before = await _table(db_session)
    response = await api_client.patch(
        f"/api/schedule/{seeded.bindings.get(company, 999_999)}",
        json={"local_minute": 60, "timezone": "UTC", **body},
    )
    assert response.status_code == status, response.text
    if detail is not None:
        assert said(response.json()) == {"detail": detail}
    assert await _table(db_session) == before


# --------------------------------------------------------------------------- #
# 3. Drift
# --------------------------------------------------------------------------- #


def _drifted(change):
    real = ops_router.schedule_payload

    def serializer(**kwargs):
        return change(real(**kwargs))

    return serializer


def _binding_key_added(payload):
    return {**payload, "bindings": [{**row, "next_dispatch_at": None} for row in payload["bindings"]]}


def _unknown_status(payload):
    return {**payload, "bindings": [{**row, "status": "stale"} for row in payload["bindings"]]}


def _provider_key_added(payload):
    return {**payload, "providers": [{**row, "weight": 1} for row in payload["providers"]]}


def _setting_dropped(payload):
    return {k: v for k, v in payload.items() if k != "tick_seconds"}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [_binding_key_added, _unknown_status, _provider_key_added, _setting_dropped],
                         ids=["binding_key_added", "unknown_status", "provider_key_added", "setting_dropped"])
@pytest.mark.parametrize("method", ["GET", "PATCH"])
async def test_a_serializer_that_drifts_fails_the_response(api_client, seeded, monkeypatch, change, method):
    monkeypatch.setattr(ops_router, "schedule_payload", _drifted(change))
    with pytest.raises(ResponseValidationError):
        if method == "GET":
            await api_client.get("/api/schedule")
        else:
            await api_client.patch(
                f"/api/schedule/{seeded.bindings['acme']}",
                json={"mode": "reconcile", "local_minute": 60, "timezone": "UTC"},
            )
