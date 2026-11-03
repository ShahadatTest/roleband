"""Realistic rows for the operational contract.

The ops handlers read the clock and the settings themselves, so
`pin_ops_environment` freezes both: `datetime.now` in `routers/ops.py` answers
`NOW`, the freshness windows and pass toggles are the shipped defaults whatever
`.env` says, every scan request the routes ring is recorded as well as stored,
and a cancel does not wait for a supervisor the test does not run. Two runs of the same request
therefore return the same bytes.

Three rosters, each a real scheduler state rather than a fixture shape:

| roster | what `/api/status` sees |
|---|---|
| `fresh` | every scheduled binding reconciled inside the window; umbrella's provider paused, so excluded; nothing queued |
| `mixed` | acme fresh, globex never reconciled and queued, initech stale and queued behind an ashby backoff, umbrella queued behind a pause |
| `unscheduled` | `mixed` plus hooli, a stable binding with no schedule row, so the roster is not seeded and freshness falls back to the last full run |

In every roster: piedpiper is tracked with an adapter but has no binding yet,
and dormant is disabled, so no route may mention it. The runs are a stuck
`running` row from five days ago, a full `partial` run whose `per_source` holds
an ok, a failed and a bounded source, and a targeted retry after it; `live_run`
adds a running scrape with a fresh heartbeat. The live run and the stuck row both
record process group `LIVE_GROUP`: a group number is reused once its process is
gone, so only liveness tells the run a cancel stopped from a dead one's leftover.
`per_source` starts from the pipeline's own `empty_stats()` and carries every key
a persisted source stores.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.db.models import (
    DerivationState,
    ProviderPressureState,
    ScrapeRun,
    ScrapeSourceRun,
    SourceBinding,
    SyncScheduleState,
    TrackedCompany,
)
from tracker.semantic import provision
from tracker.workflows.collection_types import empty_stats

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

#: The process group the live scrape records at open (`os.getpgrp()` in the pipeline).
LIVE_GROUP = 48_213

Roster = Literal["fresh", "mixed", "unscheduled"]

#: The shipped defaults every expectation in the contract is computed from.
PINNED_SETTINGS = {
    "freshness_max_hours": 26,
    "sync_authoritative_stale_hours": 30,
    "stale_run_minutes": 90,
    "stale_run_heartbeat_seconds": 180,
    "sync_scheduler_enabled": True,
    "sync_policy_denied_providers": frozenset({"meta"}),
    # No environment price key: the `prices` pass runs and skips itself.
    "tiingo_api_key": None,
    "lineage_enabled": True,
    "twin_enabled": True,
    "intelligence_extract_in_pipeline": True,
    "relevance_review_in_pipeline": True,
}


def pin_ops_environment(monkeypatch, tmp_path) -> list[str]:
    """Freeze the ops clock and settings; return the list each scan request
    appends its producer to. The request is still written."""
    import tracker.api.routers.ops as ops
    import tracker.workflows.scheduler as scheduler
    from tracker.api import scan_requests

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is not None else NOW.replace(tzinfo=None)

    settings = get_settings().model_copy(update=PINNED_SETTINGS)
    monkeypatch.setattr(ops, "datetime", _Clock)
    monkeypatch.setattr(ops, "get_settings", lambda: settings)
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    # The matching model as installed and idle: status reads the weights on
    # disk, and a test must neither depend on this machine's nor write a tier.
    monkeypatch.setattr(provision, "resolve_tier", lambda: "int8")
    monkeypatch.setattr(provision, "provision_state", lambda _spec, tier: provision.ProvisionState("ready", tier, 1, 1))
    spawned: list[str] = []
    real_ring = scan_requests.ring

    async def ring(session, *, requested_by):
        spawned.append(requested_by)
        await real_ring(session, requested_by=requested_by)

    monkeypatch.setattr(scan_requests, "ring", ring)
    monkeypatch.setattr(scan_requests, "STOP_WAIT_SECONDS", 0)
    return spawned


@dataclass(frozen=True)
class SeededOps:
    stuck_run: int
    full_run: int
    targeted_run: int
    live_run: int | None
    bindings: dict[str, int]


def _company(slug: str, display: str, adapter: str, *, enabled: bool = True) -> TrackedCompany:
    return TrackedCompany(
        slug=slug, display=display, adapter=adapter, board_token=slug, board_region=None,
        careers_url=f"https://careers.example.test/{slug}", status="active", enabled=enabled,
        visible=True, source="catalog", role_catalog_status="ready",
        role_catalog_scanned_at=NOW, role_catalog_error=None, created_at=NOW,
    )


def _query(items: int, stop_reason: str) -> dict:
    return {
        "ceiling": 50, "declared_total": items, "items": items, "page_size": 100,
        "pages_used": max(1, -(-items // 100)), "query_key": "all", "stop_reason": stop_reason,
    }


def _source(binding: int, **final) -> dict:
    """One persisted source record: the scan-open keys, then what the scan and
    persistence stages add, in the order the pipeline adds them."""
    stats = empty_stats()
    scan = {k: final.pop(k) for k in list(final) if k in stats}
    stats.update(scan)
    stats.update(
        {
            "duration_seconds": final.pop("duration_seconds"),
            "records_dropped": 0,
            "listing_invalidated": final.pop("listing_invalidated", False),
            "queries": final.pop("queries"),
            "closure_scope": (
                f"binding {binding} stable/authoritative; 0 owned, {stats['kept']} unmigrated"
                if final["outcome"] == "ok"
                else "listing not authoritative (capped/incomplete/errors)"
            ),
            "closure_eligible": final["outcome"] == "ok",
            "drift": [],
            "list_complete": final["outcome"] == "ok",
            "outcome": final.pop("outcome"),
        }
    )
    assert not final, final
    return stats


def _binding(slug: str, adapter: str) -> SourceBinding:
    return SourceBinding(
        company_slug=slug, connector_kind="adapter", connector_id=adapter, status="stable",
        closure_capability="authoritative", created_at=NOW - timedelta(days=30),
        activated_at=NOW - timedelta(days=30),
    )


def _schedule(
    binding: int, provider: str, *, last_reconcile: datetime | None, next_reconcile: datetime,
    discovery: bool, manual: datetime | None = None,
) -> SyncScheduleState:
    return SyncScheduleState(
        binding_id=binding, provider_key=provider, discovery_enabled=discovery,
        discovery_cadence_seconds=21_600, reconcile_cadence_seconds=86_400,
        last_discovery_at=NOW - timedelta(hours=2) if discovery else None,
        last_reconcile_at=last_reconcile,
        next_discovery_at=NOW + timedelta(hours=4),
        next_reconcile_at=manual if manual is not None else next_reconcile,
        manual_requested_at=manual,
        manual_previous_reconcile_at=next_reconcile if manual is not None else None,
        last_outcome="ok" if last_reconcile is not None else None,
        last_new_count=2, consecutive_empty_discoveries=0,
    )


async def seed_ops_contract(session: AsyncSession, *, roster: Roster, live_run: bool = False) -> SeededOps:
    mixed = roster in ("mixed", "unscheduled")
    companies = [
        _company("acme", "Acme", "greenhouse"),
        _company("globex", "Globex", "greenhouse"),
        _company("umbrella", "Umbrella", "lever"),
        _company("piedpiper", "Pied Piper", "ashby"),
        _company("dormant", "Dormant", "greenhouse", enabled=False),
    ]
    if mixed:
        companies.append(_company("initech", "Initech", "ashby"))
    if roster == "unscheduled":
        companies.append(_company("hooli", "Hooli", "greenhouse"))
    session.add_all(companies)
    await session.flush()

    adapters = {c.slug: c.adapter for c in companies if c.slug != "piedpiper"}
    bindings = {slug: _binding(slug, adapter) for slug, adapter in adapters.items()}
    session.add_all(bindings.values())
    await session.flush()
    ids = {slug: b.id for slug, b in bindings.items()}

    queued_at = NOW - timedelta(minutes=10)
    schedules = [
        _schedule(ids["acme"], "greenhouse", last_reconcile=NOW - timedelta(hours=2),
                  next_reconcile=NOW + timedelta(hours=22), discovery=True),
        _schedule(ids["dormant"], "greenhouse", last_reconcile=None,
                  next_reconcile=NOW + timedelta(hours=1), discovery=False),
    ]
    if mixed:
        schedules += [
            _schedule(ids["globex"], "greenhouse", last_reconcile=None,
                      next_reconcile=NOW + timedelta(hours=1), discovery=False, manual=queued_at),
            _schedule(ids["initech"], "ashby", last_reconcile=NOW - timedelta(hours=40),
                      next_reconcile=NOW - timedelta(hours=16), discovery=True, manual=queued_at),
            _schedule(ids["umbrella"], "lever", last_reconcile=NOW - timedelta(hours=80),
                      next_reconcile=NOW - timedelta(hours=56), discovery=False, manual=queued_at),
        ]
    else:
        schedules += [
            _schedule(ids["globex"], "greenhouse", last_reconcile=NOW - timedelta(hours=5),
                      next_reconcile=NOW + timedelta(hours=19), discovery=False),
            _schedule(ids["umbrella"], "lever", last_reconcile=NOW - timedelta(hours=80),
                      next_reconcile=NOW - timedelta(hours=56), discovery=False),
        ]
    session.add_all(schedules)

    pressure = [
        ProviderPressureState(pressure_key="greenhouse", state="ready", cooldown_until=None,
                              last_started_at=NOW - timedelta(hours=2), last_finished_at=NOW - timedelta(hours=2),
                              consecutive_pressure_events=0, last_outcome="ok", evidence={}),
        ProviderPressureState(pressure_key="lever", state="paused", cooldown_until=None,
                              last_started_at=NOW - timedelta(days=4), last_finished_at=NOW - timedelta(days=4),
                              consecutive_pressure_events=0, last_outcome=None, evidence={}),
    ]
    if mixed:
        pressure.append(
            ProviderPressureState(pressure_key="ashby", state="backoff", cooldown_until=NOW + timedelta(hours=3),
                                  last_started_at=NOW - timedelta(hours=1), last_finished_at=NOW - timedelta(hours=1),
                                  consecutive_pressure_events=2, last_outcome="blocked", evidence={"status": 429})
        )
    session.add_all(pressure)

    session.add_all(
        [
            DerivationState(name="lineage", last_run_at=NOW - timedelta(hours=3),
                            last_ok_at=NOW - timedelta(hours=3), last_status="ok", detail={}),
            DerivationState(name="twins", last_run_at=NOW - timedelta(hours=1),
                            last_ok_at=NOW - timedelta(hours=50), last_status="error",
                            detail={"error": "RuntimeError"}),
        ]
    )

    stuck = ScrapeRun(started_at=NOW - timedelta(days=5), heartbeat_at=None, status="running", scope="full",
                      process_group=LIVE_GROUP, jobs_seen=0, jobs_new=0, jobs_closed=0, per_source={},
                      drift_alerts=[], notes=None)
    full = ScrapeRun(
        started_at=NOW - timedelta(hours=7), finished_at=NOW - timedelta(hours=6),
        heartbeat_at=NOW - timedelta(hours=6), status="partial", scope="full",
        jobs_seen=1204, jobs_new=12, jobs_closed=4,
        per_source={
            "acme": _source(ids["acme"], scanned=412, kept=40, new=3, closed=1, duration_seconds=38.4,
                            queries=[_query(412, "exhausted")], outcome="ok"),
            "globex": _source(ids["globex"], errors=["HTTPStatusError: 503 on page 1"], duration_seconds=12.0,
                              listing_invalidated=True, queries=[], outcome="failed"),
            "piedpiper": _source(0, scanned=200, kept=9, bounded=True, duration_seconds=900.0,
                                 queries=[_query(200, "budget")], outcome="bounded"),
        },
        drift_alerts=[{"source": "globex", "status": 503, "message": "listing page returned 503"}],
        notes="87 demand slices",
    )
    targeted = ScrapeRun(
        started_at=NOW - timedelta(hours=2), finished_at=NOW - timedelta(hours=1, minutes=55),
        heartbeat_at=NOW - timedelta(hours=1, minutes=55), status="ok", scope="targeted",
        jobs_seen=38, jobs_new=1, jobs_closed=0,
        per_source={
            "globex": _source(ids["globex"], scanned=38, kept=5, new=1, duration_seconds=6.1,
                              queries=[_query(38, "exhausted")], outcome="ok"),
        },
        drift_alerts=[], notes="0 demand slices",
    )
    session.add_all([stuck, full, targeted])
    await session.flush()
    # The reconciles each company's coverage and freshness are read from.
    # Hosted on the runs above: a source run's own times are what
    # the report reads.
    reads = [
        ("acme", stuck, "ok", NOW - timedelta(hours=2), [], 412),
        ("globex", stuck, "ok", NOW - timedelta(days=3), [], 38),
        ("globex", full, "failed", NOW - timedelta(hours=30), ["HTTPStatusError: 503 on page 1"], 0),
    ]
    if mixed:
        reads += [
            ("initech", stuck, "ok", NOW - timedelta(days=4), [], 90),
            ("initech", full, "degraded", NOW - timedelta(hours=40), [], 60),
        ]
    if roster == "unscheduled":
        reads.append(("hooli", targeted, "ok", NOW - timedelta(hours=1), [], 20))
    session.add_all([
        ScrapeSourceRun(
            run_id=run.id, binding_id=ids[slug], company_slug=slug, provider_key=adapters[slug],
            scan_mode="reconcile", outcome=outcome, started_at=at, finished_at=at,
            scanned=scanned, errors=errors, drift=[],
        )
        for slug, run, outcome, at, errors, scanned in reads
    ])
    await session.flush()
    live = None
    if live_run:
        live = ScrapeRun(started_at=NOW - timedelta(minutes=10), heartbeat_at=NOW - timedelta(seconds=30),
                         status="running", scope="full", process_group=LIVE_GROUP, jobs_seen=311, jobs_new=2,
                         jobs_closed=0, per_source={}, drift_alerts=[], notes=None)
        session.add(live)
        await session.flush()
    await session.commit()
    return SeededOps(
        stuck_run=stuck.id, full_run=full.id, targeted_run=targeted.id,
        live_run=live.id if live is not None else None, bindings=ids,
    )
