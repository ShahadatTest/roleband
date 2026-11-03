"""Contract for the on-demand sync trigger, full and targeted.

The suite runs without a live DB, so these cover the pure decisions the endpoint
is built on: (1) `is_run_active` — the shared "a run is live right now" guard
used by both `/api/status` (the `running` badge) and `/api/sync` (the
already-running short-circuit); (2) that a trigger queues its companies and then
asks the supervisor for a scan, never starting a process itself (the requests
and the cancel are `test_api_scan_requests.py`'s, on a real database); and (3)
the targeted-sync contract — which company slugs may reach `--company`, and what the
picker at `/api/sync/targets` is allowed to say about each of them.
"""

import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import tracker.api.routers.ops as ops
import tracker.workflows.schedule_status as schedule_status
from tracker.db.models import (
    AppSetting,
    MachineAwakeSample,
    ProviderPressureState,
    SchedulePlanRun,
    ScrapeRun,
    SourceBinding,
    SyncScheduleState,
    TrackedCompany,
)
from tracker.health import RunScope, is_run_active
from tracker.workflows.retry_sources import reference_run

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")

NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)
STALE_MINUTES = 90


def test_fresh_running_marker_is_active():
    started = NOW - timedelta(minutes=5)
    assert is_run_active("running", started, NOW, STALE_MINUTES) is True


def test_stale_running_marker_is_not_active():
    # A "running" row older than the stale window is an orphan, not live progress
    # — so a new sync must not be blocked by it.
    started = NOW - timedelta(minutes=STALE_MINUTES + 1)
    assert is_run_active("running", started, NOW, STALE_MINUTES) is False


def test_finished_run_is_not_active():
    started = NOW - timedelta(minutes=5)
    assert is_run_active("ok", started, NOW, STALE_MINUTES) is False
    assert is_run_active("error", started, NOW, STALE_MINUTES) is False


def test_no_run_is_not_active():
    assert is_run_active(None, None, NOW, STALE_MINUTES) is False


HEARTBEAT_STALE_SECONDS = 180


def test_running_with_fresh_heartbeat_is_active():
    # A long-running but still-beating scrape is live even well past a few minutes.
    started = NOW - timedelta(minutes=30)
    beat = NOW - timedelta(seconds=20)
    assert (
        is_run_active(
            "running",
            started,
            NOW,
            STALE_MINUTES,
            heartbeat_at=beat,
            heartbeat_stale_seconds=HEARTBEAT_STALE_SECONDS,
        )
        is True
    )


def test_running_with_stale_heartbeat_is_dead_even_if_recently_started():
    # The whole point of heartbeats: a run that started only minutes ago but has
    # gone silent is a killed process, so a new sync must not stay blocked for the
    # full stale-minutes window.
    started = NOW - timedelta(minutes=5)
    beat = NOW - timedelta(seconds=HEARTBEAT_STALE_SECONDS + 30)
    assert (
        is_run_active(
            "running",
            started,
            NOW,
            STALE_MINUTES,
            heartbeat_at=beat,
            heartbeat_stale_seconds=HEARTBEAT_STALE_SECONDS,
        )
        is False
    )


def test_running_without_heartbeat_falls_back_to_started_at():
    # A run that died before emitting its first beat.
    fresh = NOW - timedelta(seconds=10)
    assert (
        is_run_active(
            "running",
            fresh,
            NOW,
            STALE_MINUTES,
            heartbeat_at=None,
            heartbeat_stale_seconds=HEARTBEAT_STALE_SECONDS,
        )
        is True
    )
    dead = NOW - timedelta(seconds=HEARTBEAT_STALE_SECONDS + 30)
    assert (
        is_run_active(
            "running",
            dead,
            NOW,
            STALE_MINUTES,
            heartbeat_at=None,
            heartbeat_stale_seconds=HEARTBEAT_STALE_SECONDS,
        )
        is False
    )


def test_a_fresh_heartbeat_keeps_a_long_run_alive():
    """Age is not evidence of death. A full collection outlasts any fixed
    wall-clock budget, and calling such a run dead starts a second one against
    a database the first is still writing, while the overlap guard here is the
    thing meant to prevent exactly that."""
    started = NOW - timedelta(minutes=STALE_MINUTES * 4)
    beat = NOW - timedelta(seconds=5)
    assert (
        is_run_active(
            "running",
            started,
            NOW,
            STALE_MINUTES,
            heartbeat_at=beat,
            heartbeat_stale_seconds=HEARTBEAT_STALE_SECONDS,
        )
        is True
    )


def test_a_long_run_that_stopped_beating_is_not_alive():
    """What ends a run is silence, and it ends one at any age."""
    started = NOW - timedelta(minutes=STALE_MINUTES * 4)
    beat = NOW - timedelta(seconds=HEARTBEAT_STALE_SECONDS + 1)
    assert (
        is_run_active(
            "running",
            started,
            NOW,
            STALE_MINUTES,
            heartbeat_at=beat,
            heartbeat_stale_seconds=HEARTBEAT_STALE_SECONDS,
        )
        is False
    )


def test_without_a_heartbeat_window_the_start_bound_still_answers():
    """A caller that reads no beat gets start-time-only semantics, which is
    what `stale_run_minutes` is still for."""
    old_start = NOW - timedelta(minutes=STALE_MINUTES + 1)
    assert is_run_active("running", old_start, NOW, STALE_MINUTES) is False
    young = NOW - timedelta(minutes=STALE_MINUTES - 1)
    assert is_run_active("running", young, NOW, STALE_MINUTES) is True


# --------------------------------------------------------------- targeted sync --


class _Scalars:
    def __init__(self, rows):
        self.rows = list(rows)

    def __iter__(self):
        return iter(self.rows)

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


class FakeSession:
    """Serves the roster read and the reference-run read off one fake.

    Dispatches on the entity a statement selects rather than on call order, so a
    test stays valid when the endpoint reorders its queries.
    """

    def __init__(self, *, companies=(), runs=(), followed=()):
        self.companies = list(companies)
        self.runs = list(runs)
        self.followed = list(followed)
        self.statements = []
        self.commits = 0

    async def commit(self):
        self.commits += 1

    async def scalars(self, stmt):
        self.statements.append(stmt)
        entity = stmt.column_descriptions[0]["entity"]
        if entity is TrackedCompany:
            return _Scalars(self.companies)
        if entity is ScrapeRun:
            return _Scalars(self.runs)
        if entity is ProviderPressureState:
            return _Scalars([])
        raise AssertionError(f"unexpected select of {entity}")

    async def scalar(self, stmt):
        self.statements.append(stmt)
        names = [d["name"] for d in stmt.column_descriptions]
        if names == ["per_source"]:
            # The reference run's blob; which run that is, SQL decides
            # (tests/test_reference_run_sql.py pins it to `reference_run`).
            reference = reference_run(self.runs)
            return reference.per_source if reference else None
        raise AssertionError(f"unexpected scalar of {names}")

    async def execute(self, stmt):
        self.statements.append(stmt)
        names = [d["name"] for d in stmt.column_descriptions]
        if names[:2] == ["id", "company_slug"]:
            # The coverage report behind each row's clock and `coverage`.
            return _Scalars(self.followed)
        raise AssertionError(f"unexpected execute of {names}")


class FakeScheduleSession:
    def __init__(self, *, binding, state, pressure):
        self.binding = binding
        self.state = state
        self.pressure = pressure
        self.company = company(
            binding.company_slug,
            adapter=state.provider_key,
        )
        self.commits = 0

    async def scalars(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        if entity is TrackedCompany:
            return _Scalars([self.company])
        if entity is SourceBinding:
            return _Scalars([self.binding])
        if entity is SyncScheduleState:
            return _Scalars([self.state])
        if entity is ProviderPressureState:
            return _Scalars([self.pressure] if self.pressure is not None else [])
        if entity in (SchedulePlanRun, MachineAwakeSample):
            return _Scalars([])  # the schedule plan's clock and samples: none yet
        raise AssertionError(f"unexpected select of {entity}")

    async def get(self, entity, key):
        if entity is AppSetting:
            return None  # the schedule plan's repeat: the default
        if entity is SourceBinding:
            return self.binding if key == self.binding.id else None
        if entity is ProviderPressureState:
            if self.pressure is not None and key == self.pressure.pressure_key:
                return self.pressure
            return None
        raise AssertionError(f"unexpected get of {entity}")

    async def commit(self):
        self.commits += 1


def company(slug, *, adapter="greenhouse", display=None):
    return TrackedCompany(
        slug=slug,
        display=display or slug.title(),
        adapter=adapter,
        status="active",
        enabled=True,
        visible=True,
        source="builtin",
    )


def schedule_settings(*, denied=frozenset()):
    return SimpleNamespace(
        sync_scheduler_enabled=True,
        sync_scheduler_max_providers=2,
        sync_authoritative_stale_hours=30,
        sync_policy_denied_providers=denied,
        sync_schedule_plan_enabled=True,
        schedule_plan_full_after_hours=20,
        schedule_plan_wake_gap_minutes=120,
    )


def full_run(per_source, run_id=7):
    return ScrapeRun(
        id=run_id,
        started_at=NOW,
        finished_at=NOW,
        status="partial",
        scope=RunScope.FULL,
        per_source=per_source,
    )


#: A clean source: no errors and the listing completed.
OK_STATS = {"scanned": 120, "kept": 8, "errors": [], "list_complete": True}
#: A source that produced nothing and errored — `failed`, and retry-eligible.
FAILED_STATS = {"scanned": 0, "kept": 0, "errors": ["HTTPError: 500"]}


def test_schedule_payload_uses_persisted_deadlines_and_provider_cooldown():
    binding = SourceBinding(
        id=1,
        company_slug="google",
        connector_id="google",
        status="stable",
        closure_capability="authoritative",
    )
    state = SyncScheduleState(
        binding_id=1,
        provider_key="google",
        discovery_enabled=True,
        discovery_cadence_seconds=21_600,
        reconcile_cadence_seconds=86_400,
        next_discovery_at=NOW + timedelta(hours=1),
        next_reconcile_at=NOW + timedelta(hours=8),
        last_new_count=2,
        consecutive_empty_discoveries=0,
    )
    pressure = ProviderPressureState(
        pressure_key="google",
        state="backoff",
        cooldown_until=NOW + timedelta(hours=3),
        last_outcome="degraded",
    )
    settings = SimpleNamespace(
        sync_scheduler_enabled=True,
        sync_scheduler_max_providers=2,
        sync_authoritative_stale_hours=30,
        sync_policy_denied_providers=frozenset({"meta"}),
    )

    out = schedule_status.schedule_payload(
        bindings=[binding],
        states=[state],
        pressure_rows=[pressure],
        targets={"google": {"adapter": "google"}},
        settings=settings,
        now=NOW,
    )

    row = out["bindings"][0]
    assert out["tick_seconds"] == 600
    assert row["next_discovery_at"] == NOW + timedelta(hours=1)
    assert row["eligible_discovery_at"] == NOW + timedelta(hours=3)
    assert row["eligible_reconcile_at"] == NOW + timedelta(hours=8)
    assert row["status"] == "cooldown"
    assert out["providers"][0]["binding_count"] == 1


def test_schedule_payload_exposes_denied_and_unscheduled_bindings_without_due_work():
    denied = SourceBinding(
        id=1,
        company_slug="meta",
        connector_id="meta",
        status="stable",
        closure_capability="authoritative",
    )
    unseeded = SourceBinding(
        id=2,
        company_slug="newco",
        connector_id="ashby",
        status="stable",
        closure_capability="none",
    )
    denied_state = SyncScheduleState(
        binding_id=1,
        provider_key="meta",
        discovery_enabled=False,
        discovery_cadence_seconds=21_600,
        reconcile_cadence_seconds=86_400,
        next_discovery_at=NOW,
        next_reconcile_at=NOW,
    )
    settings = SimpleNamespace(
        sync_scheduler_enabled=True,
        sync_scheduler_max_providers=2,
        sync_authoritative_stale_hours=30,
        sync_policy_denied_providers=frozenset({"meta"}),
    )

    out = schedule_status.schedule_payload(
        bindings=[denied, unseeded],
        states=[denied_state],
        pressure_rows=[],
        targets={"meta": {"adapter": "meta"}, "newco": {"adapter": "ashby"}},
        settings=settings,
        now=NOW,
    )
    by_company = {row["company"]: row for row in out["bindings"]}

    assert by_company["meta"]["status"] == "policy_denied"
    assert by_company["meta"]["eligible_reconcile_at"] is None
    assert by_company["newco"]["status"] == "unscheduled"
    assert by_company["newco"]["scheduled"] is False
    assert by_company["newco"]["eligible_discovery_at"] is None


def test_schedule_time_update_persists_anchor_and_returns_the_live_contract(monkeypatch):
    binding = SourceBinding(
        id=1,
        company_slug="google",
        connector_id="google",
        status="stable",
        closure_capability="authoritative",
    )
    state = SyncScheduleState(
        binding_id=1,
        provider_key="google",
        discovery_enabled=True,
        discovery_cadence_seconds=21_600,
        reconcile_cadence_seconds=86_400,
        next_discovery_at=NOW + timedelta(hours=1),
        next_reconcile_at=NOW + timedelta(hours=8),
    )
    pressure = ProviderPressureState(pressure_key="google", state="ready")
    session = FakeScheduleSession(binding=binding, state=state, pressure=pressure)
    monkeypatch.setattr(ops, "get_settings", schedule_settings)

    out = asyncio.run(
        ops.update_schedule_time(
            1,
            ops.ScheduleTimeUpdate(
                mode="reconcile",
                local_minute=20 * 60,
                timezone="Europe/Stockholm",
            ),
            session,
        )
    )

    assert session.commits == 1
    assert state.reconcile_anchor_minute == 20 * 60
    assert state.schedule_timezone == "Europe/Stockholm"
    assert out["bindings"][0]["reconcile_anchor_minute"] == 20 * 60


def test_schedule_time_update_cannot_bypass_policy_denial(monkeypatch):
    binding = SourceBinding(
        id=1,
        company_slug="meta",
        connector_id="meta",
        status="stable",
        closure_capability="authoritative",
    )
    state = SyncScheduleState(
        binding_id=1,
        provider_key="meta",
        discovery_enabled=False,
        next_discovery_at=NOW,
        next_reconcile_at=NOW,
    )
    pressure = ProviderPressureState(pressure_key="meta", state="policy_denied")
    session = FakeScheduleSession(binding=binding, state=state, pressure=pressure)
    monkeypatch.setattr(
        ops,
        "get_settings",
        lambda: schedule_settings(denied=frozenset({"meta"})),
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            ops.update_schedule_time(
                1,
                ops.ScheduleTimeUpdate(
                    mode="reconcile",
                    local_minute=20 * 60,
                    timezone="Europe/Stockholm",
                ),
                session,
            )
        )

    assert error.value.status_code == 409
    assert session.commits == 0


def call_sync(session, payload=None, spawned=None, monkeypatch=None):
    requested = payload.companies if payload else []

    async def queue(_session, companies, *, now):
        spawned.append(("queued", list(companies or [])))
        return list(companies or requested)

    async def ring(_session, *, requested_by):
        spawned.append(("rung", requested_by))

    monkeypatch.setattr(ops, "queue_manual_reconciliation", queue)
    monkeypatch.setattr(ops.scan_requests, "ring", ring)
    return asyncio.run(ops.sync(session, payload))


def test_sync_passes_the_requested_subset_to_the_scrape(monkeypatch):
    spawned = []
    session = FakeSession(companies=[company("anthropic"), company("meta")], runs=[])

    result = call_sync(
        session, ops.SyncPayload(companies=["anthropic"]), spawned, monkeypatch
    )

    assert spawned == [("queued", ["anthropic"]), ("rung", "sync")]
    assert result == {
        "status": "started",
        "companies": ["anthropic"],
        "queued": ["anthropic"],
    }


def test_sync_without_a_body_is_still_the_full_roster(monkeypatch):
    spawned = []
    session = FakeSession(companies=[company("anthropic")], runs=[])

    result = call_sync(session, None, spawned, monkeypatch)

    assert spawned == [
        ("queued", []),
        ("rung", "sync"),
    ], "no body must queue the whole roster"
    assert result["status"] == "started"


def test_sync_rejects_an_unknown_company(monkeypatch):
    # Silently dropping it would run a narrower scrape than the user asked for,
    # with nothing in the response to say so.
    spawned = []
    session = FakeSession(companies=[company("anthropic")], runs=[])

    with pytest.raises(HTTPException) as exc:
        call_sync(session, ops.SyncPayload(companies=["anthropic", "nope"]), spawned, monkeypatch)

    assert exc.value.status_code == 400
    assert "nope" in exc.value.detail["message"]
    assert spawned == [], "a rejected request must not have spawned anything"


def test_sync_rejects_a_tracked_company_with_no_connector(monkeypatch):
    # Tracked-but-connectorless is a recorded interest, not a scrapeable source:
    # `get_active_targets` drops it, so the run would never have covered it.
    spawned = []
    session = FakeSession(companies=[company("anthropic"), company("parked", adapter=None)])

    with pytest.raises(HTTPException) as exc:
        call_sync(session, ops.SyncPayload(companies=["parked"]), spawned, monkeypatch)

    assert exc.value.status_code == 400
    assert spawned == []


def test_sync_deduplicates_repeated_slugs(monkeypatch):
    # A company can sit in two sectors and be checked from either card.
    spawned = []
    session = FakeSession(companies=[company("anthropic"), company("apple")], runs=[])

    call_sync(
        session, ops.SyncPayload(companies=["anthropic", "apple", "anthropic"]), spawned, monkeypatch
    )

    assert spawned == [("queued", ["anthropic", "apple"]), ("rung", "sync")]


def test_sync_rejects_explicit_policy_denied_provider(monkeypatch):
    """The denied provider is synthetic: no real provider is denied, and this
    rejection must still work for the next one."""
    from tracker.config import get_settings

    spawned = []
    monkeypatch.setattr(
        get_settings(), "sync_policy_denied_providers", frozenset({"denied-ats"})
    )
    session = FakeSession(
        companies=[company("denied-co", adapter="denied-ats")], runs=[]
    )

    with pytest.raises(HTTPException) as exc:
        call_sync(
            session,
            ops.SyncPayload(companies=["denied-co"]),
            spawned,
            monkeypatch,
        )

    assert exc.value.status_code == 409
    assert "policy-denied" in exc.value.detail["message"]
    assert spawned == []


def _live_run() -> ScrapeRun:
    return ScrapeRun(
        id=9,
        started_at=datetime.now(UTC) - timedelta(minutes=2),
        heartbeat_at=datetime.now(UTC),
        status="running",
        scope=RunScope.FULL,
    )


def test_a_company_asked_for_while_a_run_is_live_is_queued_for_that_run(monkeypatch):
    """Scan now during a scan: no second run, and the request is kept, so the
    live run reads the company next (`run_pipeline(join_requests=True)`)."""
    spawned = []
    session = FakeSession(companies=[company("anthropic")], runs=[_live_run()])

    result = call_sync(session, ops.SyncPayload(companies=["anthropic"]), spawned, monkeypatch)

    assert (result["status"], result["companies"], result["queued"]) == ("already_running", [], ["anthropic"])
    assert spawned == [("queued", ["anthropic"]), ("rung", "sync")]


def test_asking_for_everyone_while_a_run_is_live_queues_nothing(monkeypatch):
    """The live run reads everyone already: queuing them all would read every
    company again as soon as it ends."""
    spawned = []
    session = FakeSession(companies=[company("anthropic")], runs=[_live_run()])

    result = call_sync(session, None, spawned, monkeypatch)

    assert (result["status"], result["queued"]) == ("already_running", [])
    assert spawned == []


def followed_row(binding_id, slug, *, attempted=None, full=None, cause=None, errors=(), adapter="greenhouse"):
    """One row of `followed_bindings`' statement, in its column order."""
    return (
        binding_id, slug, slug.title(), adapter, "adapter", None, NOW - timedelta(days=60),
        full, attempted, 0, cause, attempted if cause else None, 0, list(errors), [], None, None, None,
    )


def test_sync_targets_reports_freshness_coverage_and_retryability():
    now = datetime.now(UTC)
    session = FakeSession(
        companies=[company("google"), company("meta"), company("parked", adapter=None)],
        runs=[full_run({"google": OK_STATS, "meta": FAILED_STATS})],
        followed=[
            followed_row(1, "google", attempted=now - timedelta(hours=2), full=now - timedelta(hours=2)),
            followed_row(2, "meta", attempted=now - timedelta(hours=40), full=now - timedelta(days=5),
                         cause="failed", errors=["ReadError: "]),
        ],
    )

    out = asyncio.run(ops.sync_targets(session))
    by_slug = {c["slug"]: c for c in out["companies"]}

    assert "parked" not in by_slug, "the picker must not offer a company the run would drop"
    google, meta = by_slug["google"], by_slug["meta"]
    assert (google["last_outcome"], google["retryable"], google["stale"]) == ("ok", False, False)
    assert (google["last_full_scan_at"], google["coverage"]) == (now - timedelta(hours=2), None)
    assert (meta["last_outcome"], meta["retryable"], meta["stale"]) == ("failed", True, True)
    assert meta["last_sync_at"] == now - timedelta(hours=40), "the last attempt, not the last full scan"
    assert meta["last_full_scan_at"] == now - timedelta(days=5)
    assert meta["coverage"]["rings"] is True
    assert meta["coverage"]["title"] == "Couldn't scan Meta · 5 days"
    assert "health" not in meta


def test_sync_targets_says_nothing_about_a_company_the_reference_run_never_touched():
    # A company added after the last full run has no outcome — reporting one
    # would invent evidence, and `failed` is the wrong default for "never asked".
    session = FakeSession(
        companies=[company("google"), company("newco")],
        runs=[full_run({"google": OK_STATS})],
    )

    out = asyncio.run(ops.sync_targets(session))
    newco = next(c for c in out["companies"] if c["slug"] == "newco")

    assert newco["last_outcome"] is None
    assert newco["retryable"] is False
    assert newco["last_sync_at"] is None
    assert (newco["last_full_scan_at"], newco["automatic"], newco["coverage"]) == (None, False, None)


def test_sync_targets_ignores_a_newer_targeted_run():
    # A targeted run's per_source covers its own subset, so it cannot answer
    # "which sources still need work" for the companies it never contacted.
    targeted = ScrapeRun(
        id=9, started_at=NOW, finished_at=NOW, status="ok",
        scope=RunScope.TARGETED, per_source={"netflix": OK_STATS},
    )
    session = FakeSession(
        companies=[company("meta")],
        runs=[targeted, full_run({"meta": FAILED_STATS}, run_id=8)],
    )

    out = asyncio.run(ops.sync_targets(session))

    assert out["companies"][0]["retryable"] is True


def test_sync_targets_looks_past_a_full_run_that_observed_nothing():
    # A `full` run that died before collecting anything is no reference: taking
    # it would report every source as having no outcome while the real
    # evidence sits one run below it.
    crashed = ScrapeRun(
        id=39, started_at=NOW, finished_at=NOW, status="error",
        scope=RunScope.FULL, per_source={},
    )
    session = FakeSession(
        companies=[company("meta")],
        runs=[crashed, full_run({"meta": FAILED_STATS}, run_id=38)],
    )

    out = asyncio.run(ops.sync_targets(session))

    assert out["companies"][0]["last_outcome"] == "failed"
    assert out["companies"][0]["retryable"] is True


# -- queued is not running ----------------------------------------------------- #
#
# `/api/status.running` feeds the header's spinner, its elapsed clock and its
# "N found" readout. Were it `pipeline_running or manual_pending`, a manual
# request stalled behind a provider backoff would render as a live scrape, the
# clock ticking from `last_run_started_at` of a run that already finished, so a
# short run would display as "Syncing..." for over an hour. These pin the
# separation of queued from running.


def _queued_state(provider_key="ashby", **kwargs):
    return SyncScheduleState(
        binding_id=1,
        provider_key=provider_key,
        discovery_enabled=False,
        next_discovery_at=NOW,
        next_reconcile_at=kwargs.pop("next_reconcile_at", NOW),
        manual_requested_at=kwargs.pop("manual_requested_at", NOW - timedelta(minutes=5)),
    )


def _block(company: str, pressure: ProviderPressureState, now=NOW):
    """`manual_block_reason` over a pressure row, the way `scheduler_status` calls
    it: the EFFECTIVE provider state, not the row's own."""
    return schedule_status.manual_block_reason(
        company,
        provider_key=pressure.pressure_key,
        provider_state=schedule_status.effective_provider_state(
            pressure.pressure_key, pressure, settings=schedule_settings()
        ),
        cooldown_until=pressure.cooldown_until,
        now=now,
    )


def test_a_provider_in_backoff_blocks_its_queued_binding():
    pressure = ProviderPressureState(
        pressure_key="ashby", state="backoff", cooldown_until=NOW + timedelta(hours=4)
    )

    blocked = _block("mistral", pressure)

    assert blocked == {
        "company": "mistral",
        "provider": "ashby",
        "reason": "backoff",
        "until": NOW + timedelta(hours=4),
    }


def test_an_expired_cooldown_is_not_a_block():
    """The cooldown timestamp outlives the backoff. Reading the column without
    comparing it to now would report a binding blocked forever."""
    pressure = ProviderPressureState(
        pressure_key="ashby", state="backoff", cooldown_until=NOW - timedelta(minutes=1)
    )

    assert _block("mistral", pressure) is None


@pytest.mark.parametrize("state", ["policy_denied", "paused"])
def test_a_denied_or_paused_provider_blocks_with_no_end_time(state):
    pressure = ProviderPressureState(pressure_key="meta", state=state, cooldown_until=None)

    blocked = _block("meta", pressure)

    assert blocked == {"company": "meta", "provider": "meta", "reason": state, "until": None}


def test_a_future_cadence_cannot_reach_the_block_decision_at_all():
    """A manual request is precisely what overrides cadence. Counting
    `next_reconcile_at` as a block would mark every queued binding blocked and
    make the readout meaningless.

    This is structural rather than behavioural: the function is handed the
    provider's state and cooldown and nothing else, so the schedule row (the
    only thing carrying a cadence) cannot be consulted. Asserted on the
    signature, because a test that passes a state and checks the answer would
    keep passing if the parameter came back unused."""
    given = set(inspect.signature(schedule_status.manual_block_reason).parameters)

    assert given == {"company", "provider_key", "provider_state", "cooldown_until", "now"}
    pressure = ProviderPressureState(pressure_key="ashby", state="ready", cooldown_until=None)
    assert _block("mistral", pressure) is None


def test_a_ready_provider_does_not_block():
    pressure = ProviderPressureState(pressure_key="ashby", state="ready", cooldown_until=None)

    assert _block("lovable", pressure) is None


def _scheduler_for(state, pressure, monkeypatch, slug="mistral"):
    binding = SourceBinding(
        id=1,
        company_slug=slug,
        connector_id="ashby",
        status="stable",
        closure_capability="authoritative",
    )
    session = FakeScheduleSession(binding=binding, state=state, pressure=pressure)
    monkeypatch.setattr(ops, "get_settings", schedule_settings)
    # No scan runs on these rosters: the read clock is the schedule row's own
    # reconcile stamp.
    return asyncio.run(
        schedule_status.scheduler_status(session, schedule_settings(), NOW, full_reads={})
    )


def test_scheduler_status_reports_queued_work_and_why_it_is_stuck(monkeypatch):
    pressure = ProviderPressureState(
        pressure_key="ashby", state="backoff", cooldown_until=NOW + timedelta(hours=4)
    )

    scheduler = _scheduler_for(_queued_state(), pressure, monkeypatch)

    assert scheduler["manual_queued"] == ["mistral"]
    assert [row["reason"] for row in scheduler["manual_blocked"]] == ["backoff"]
    assert scheduler["manual_blocked"][0]["until"] == NOW + timedelta(hours=4)


def test_a_company_scanned_only_when_the_user_asks_is_never_overdue(monkeypatch):
    """The dispatcher never scans a user-directed source on a timer, so a
    roster that required it fresh would be stale for good: one Workday company
    would leave `last_complete_at` empty and the top bar would read "No data
    yet" over a full Board. It is excluded, the same rule `collectable_now`
    drops its work by."""
    state = _queued_state(
        "workday", manual_requested_at=None, next_reconcile_at=NOW - timedelta(days=6)
    )
    state.last_reconcile_at = NOW - timedelta(days=6)

    scheduler = _scheduler_for(state, None, monkeypatch, slug="nvidia")

    assert scheduler["excluded"] == [
        {"company": "nvidia", "provider": "workday", "reason": "user_directed"}
    ]
    assert (scheduler["required"], scheduler["overdue"]) == (0, [])


def test_a_user_directed_company_the_user_asked_for_is_on_the_roster(monkeypatch):
    """The Sync button is the user asking: from then on the company is work
    the dispatcher will do, so the roster counts it and says it is queued."""
    state = _queued_state("workday")
    state.last_reconcile_at = NOW - timedelta(days=6)

    scheduler = _scheduler_for(state, None, monkeypatch, slug="nvidia")

    assert scheduler["excluded"] == []
    assert scheduler["manual_queued"] == ["nvidia"]
    assert [row["reason"] for row in scheduler["overdue"]] == ["authoritative_stale"]


def test_a_roster_with_a_company_behind_still_dates_its_oldest_scan(monkeypatch):
    """`last_complete_at` is empty while any company is behind; `oldest_scan_at`
    still answers how old the shown postings are, so the badge has an age to
    print instead of "No data yet"."""
    state = _queued_state(manual_requested_at=None)
    state.last_reconcile_at = NOW - timedelta(hours=40)

    scheduler = _scheduler_for(state, None, monkeypatch)

    assert [row["reason"] for row in scheduler["overdue"]] == ["authoritative_stale"]
    assert (scheduler["last_complete_at"], scheduler["oldest_scan_at"]) == (
        None, NOW - timedelta(hours=40),
    )


def _first_pass_for(*, followed_at, read_at, monkeypatch):
    binding = SourceBinding(
        id=1,
        company_slug="mistral",
        connector_id="ashby",
        status="stable",
        closure_capability="authoritative",
        created_at=followed_at,
    )
    state = _queued_state(manual_requested_at=None)
    state.last_reconcile_at = read_at
    session = FakeScheduleSession(binding=binding, state=state, pressure=None)
    monkeypatch.setattr(ops, "get_settings", schedule_settings)
    return asyncio.run(
        schedule_status.scheduler_status(session, schedule_settings(), NOW, full_reads={})
    )


def test_a_company_followed_today_and_not_yet_read_is_not_counted_as_read(monkeypatch):
    """The first scan's progress is `ever_read` of `required`. `unread` leaves
    out a company followed inside the stale window, so `required` less
    `unread` would call the whole roster read before the first scan read
    anything."""
    scheduler = _first_pass_for(followed_at=NOW - timedelta(minutes=2), read_at=None, monkeypatch=monkeypatch)

    assert scheduler["unread"] == [], "a fresh follow is not yet unread"
    assert (scheduler["ever_read"], scheduler["required"]) == (0, 1)


def test_a_company_read_once_counts_as_read_however_old_the_read(monkeypatch):
    fresh = _first_pass_for(followed_at=NOW - timedelta(minutes=10), read_at=NOW - timedelta(minutes=1),
                            monkeypatch=monkeypatch)
    old = _first_pass_for(followed_at=NOW - timedelta(days=9), read_at=NOW - timedelta(days=4),
                          monkeypatch=monkeypatch)

    assert (fresh["ever_read"], fresh["required"]) == (1, 1)
    assert (old["ever_read"], old["required"]) == (1, 1), "a stale read is still a read: the first pass is over"
    assert [row["reason"] for row in old["unread"]] == ["read_stale"]


def test_queued_work_on_a_ready_provider_is_queued_but_not_blocked(monkeypatch):
    pressure = ProviderPressureState(pressure_key="ashby", state="ready", cooldown_until=None)

    scheduler = _scheduler_for(_queued_state(), pressure, monkeypatch)

    assert scheduler["manual_queued"] == ["mistral"]
    assert scheduler["manual_blocked"] == [], "a queue that is moving is not blocked"


def test_a_second_sync_still_queues_the_companies_it_asked_for(monkeypatch):
    """A scan already asked for must not become not queueing.

    The running scan's next tick reads the queue, so a second targeted sync's
    companies still have to reach it, queued before the request is rung. The
    second request joins the first (`job_store.ring` coalesces it), so no
    second scan starts.
    """

    spawned = []
    session = FakeSession(companies=[company("anthropic"), company("stripe")], runs=[])

    result = call_sync(session, ops.SyncPayload(companies=["anthropic"]), spawned, monkeypatch)

    assert spawned == [("queued", ["anthropic"]), ("rung", "sync")], "the queue is written before the ring"
    assert session.commits == 1
    assert result == {"status": "started", "companies": ["anthropic"], "queued": ["anthropic"]}


def test_sync_refuses_a_walled_company_the_user_has_not_consented_to(monkeypatch):
    """Google is walled (robots disallows its paginated listing). A
    followed Google with no consent is refused by name, never queued; the same
    row carrying a consent goes through."""
    from tracker.source_review import SOURCE_REVIEWS

    spawned = []
    google = company("google", adapter="google")
    session = FakeSession(companies=[google], runs=[])
    with pytest.raises(HTTPException) as refused:
        call_sync(session, ops.SyncPayload(companies=["google"]), spawned, monkeypatch)
    assert refused.value.status_code == 409 and refused.value.detail["params"]["companies"] == ["google"]
    assert spawned == []

    google.consent_fingerprint = SOURCE_REVIEWS["google"].wall_fingerprint
    result = call_sync(session, ops.SyncPayload(companies=["google"]), spawned, monkeypatch)
    assert result["queued"] == ["google"]

