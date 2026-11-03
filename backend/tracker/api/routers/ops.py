"""Operational surface: health, freshness/supervision status, manual sync, runs."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, literal_column, or_, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from tracker import __version__
from tracker.api import job_requests, scan_requests
from tracker.api.deps import SessionDep
from tracker.api.errors import ErrorCode, api_error
from tracker.api.schemas.ops import (
    HealthResponse,
    LauncherHealthResponse,
    ReleaseNotesResponse,
    RunListResponse,
    SchedulePayload,
    SchedulePlanUpdate,
    ScheduleTimeUpdate,
    SyncCancelResponse,
    SyncResponse,
    SyncTargetsResponse,
    SystemStatusResponse,
)
from tracker.company_store import get_active_targets, off_board_company_slugs
from tracker.config import Settings, get_settings
from tracker.connectors.recipes.outcome import (
    STOPPED_BY_USER_NOTE,
    SourceOutcome,
    cancelled_run_status,
    classify_source_outcome,
)
from tracker.db import job_store
from tracker.db.models import (
    Notification,
    ProviderPressureState,
    ScrapeRun,
    SourceBinding,
    SyncScheduleState,
    TrackedCompany,
)
from tracker.db.queries.binding_attention import (
    FollowedBinding,
    binding_attention,
    boards_gone,
    followed_bindings,
)
from tracker.db.queries.jobs import run_new_roles_stmt
from tracker.db.queries.runs import committed_per_source, committed_per_source_expr
from tracker.health import REFRESHED_STATUSES, RunScope, freshness, is_run_active
from tracker.notifications import classify_coverage, generate_sync_result_notification
from tracker.notifications.coverage import coverage_report
from tracker.notifications.coverage import rings as coverage_rings
from tracker.platform import preparation
from tracker.platform.launcher import installation_identity
from tracker.platform.paths import DATA_DIR, PACKAGED, REPO_ROOT
from tracker.platform.power import read_power
from tracker.platform.releases import release_notes
from tracker.plugins import runtime as plugin_runtime
from tracker.plugins import status as plugin_status
from tracker.semantic import matching
from tracker.semantic.embed import model_warming
from tracker.settings_store import SCHEDULE_PLAN_KEY, update_schedule_plan_settings
from tracker.source_policy import collection_access, scanned_automatically
from tracker.workflows import schedule_plan
from tracker.workflows.collection_types import ScanMode
from tracker.workflows.launcher_status import (
    ScanSchedule,
    in_flight_slugs,
    project_scan,
    project_status,
)
from tracker.workflows.retry_sources import reference_per_source_stmt, retry_candidates
from tracker.workflows.schedule_status import (
    BLOCKED_PROVIDER_STATES,
    derivation_status,
    schedule_payload,
    scheduler_status,
    stable_bindings,
    stuck_running_count,
)
from tracker.workflows.scheduler import (
    cancel_manual_reconciliation,
    move_schedule_deadline,
    plan_view,
    queue_manual_reconciliation,
    scan_schedule,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/release-notes", response_model=ReleaseNotesResponse)
async def installed_release_notes() -> dict:
    settings = get_settings()
    try:
        identity = installation_identity(REPO_ROOT, api_host=settings.api_host, api_port=settings.api_port, version=__version__)
    except ValueError:
        identity = None
    return {"launcher": identity, "version": __version__, "notes": await asyncio.to_thread(release_notes, __version__)}

#: Upper bound on a targeted sync's company list. Not a policy limit — the whole
#: roster is always allowed via the plain full sync — just a bound on how much
#: unvalidated list a request may make us walk.
_MAX_SYNC_COMPANIES = 500

#: How far back to look for a run that can serve as the outcome reference. Same
#: window `plan_retry` reads, for the same reason: a crashed or targeted run at
#: the head must not hide the last run that actually observed the sources.
_REFERENCE_RUN_WINDOW = 20
#: A run's two summaries, left unloaded by a read that only asks whether a
#: run is live: a finished run's `per_source` holds every company's counts and
#: errors, the largest value the run table stores.
_RUN_SUMMARY_DEFERRED = (
    defer(ScrapeRun.per_source, raiseload=True),
    defer(ScrapeRun.drift_alerts, raiseload=True),
)


_LIVE_PROGRESS = Notification.meta["progress"]
#: What the scan picture reads of a live scan's progress: its counts and the
#: companies it is reading now. The carrier also lists every company the scan
#: has touched, which grows with the roster while status is polled every few
#: seconds. Strict mode keeps the picture's reading of a malformed carrier: a
#: `companies` that is not a list holds no rows, and a row that is not an
#: object is skipped.
_SCAN_PICTURE_PROGRESS = case(
    (func.jsonb_typeof(_LIVE_PROGRESS) == "object", func.jsonb_build_object(
        *(part for key in ("phase", "percent", "companies_total", "opportunities_pending", "opportunities_recorded")
          for part in (key, _LIVE_PROGRESS[key])),
        "companies", func.jsonb_path_query_array(
            _LIVE_PROGRESS, literal_column("""'strict $.companies[*] ? (@.state == "scraping")'::jsonpath"""),
            literal_column("'{}'::jsonb"), true(),
        ),
    )),
)


class SyncPayload(BaseModel):
    """Optional company subset for a targeted sync.

    Omitted or empty = the full roster, which is what the header's plain
    "Sync" sends.
    """

    companies: list[str] = Field(default_factory=list, max_length=_MAX_SYNC_COMPANIES)


@router.get("/api/health", response_model=HealthResponse)
async def health(session: SessionDep) -> dict:
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/api/launcher-health", response_model=LauncherHealthResponse)
async def launcher_health() -> dict:
    settings = get_settings()
    identity = installation_identity(
        REPO_ROOT, api_host=settings.api_host, api_port=settings.api_port, version=__version__,
    )
    return preparation.payload(DATA_DIR, identity, packaged=PACKAGED)


def _schedule_zone(tz: str | None) -> ZoneInfo:
    """The zone the plan's usual hours are told in; the dashboard sends its own."""
    if not tz:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise api_error(422, ErrorCode.INVALID_INPUT, f"unknown timezone: {tz}") from error


@router.get("/api/schedule", response_model=SchedulePayload)
async def schedule(
    session: SessionDep,
    tz: Annotated[str | None, Query(max_length=64)] = None,
) -> dict:
    """Persisted connector deadlines, provider pressure and the schedule plan
    for Settings. `tz` is the zone the plan's usual hours are given in."""
    settings = get_settings()
    now = datetime.now(UTC)
    zone = _schedule_zone(tz)
    targets = await get_active_targets(session)
    bindings = await stable_bindings(session, targets)
    binding_ids = [binding.id for binding in bindings]
    states = (
        list(
            (
                await session.scalars(
                    select(SyncScheduleState).where(
                        SyncScheduleState.binding_id.in_(binding_ids)
                    )
                )
            ).all()
        )
        if binding_ids
        else []
    )
    pressure_rows = list((await session.scalars(select(ProviderPressureState))).all())
    return {
        **schedule_payload(
            bindings=bindings,
            states=states,
            pressure_rows=pressure_rows,
            targets=targets,
            settings=settings,
            now=now,
        ),
        "plan": await plan_view(
            session,
            now=now,
            settings=settings,
            zone=zone,
            targets=targets,
            bindings=bindings,
            states=states,
            pressure_rows=pressure_rows,
            # pmset blocks; off the loop, as the directory status reads it.
            on_battery=(await asyncio.to_thread(read_power)).on_battery,
        ),
    }


#: How long each short pause lasts.
_PAUSES = {"1h": timedelta(hours=1), "3h": timedelta(hours=3)}


@router.put("/api/schedule/plan", response_model=SchedulePayload)
async def update_schedule_plan(
    payload: SchedulePlanUpdate,
    session: SessionDep,
    tz: Annotated[str | None, Query(max_length=64)] = None,
) -> dict:
    """Change the schedule plan's choices; only the keys sent change.

    The zone the screen sent is stored with them, so a ready-by time and the
    days mean the wall clock the user chose them on."""
    zone = _schedule_zone(tz)
    now = datetime.now(UTC)
    sent = payload.model_fields_set
    changes: dict = {}
    if payload.repeat_hours is not None:
        changes["repeat_hours"] = payload.repeat_hours
    if "ready_by_minute" in sent:
        changes["ready_by_minute"] = payload.ready_by_minute
    if "repeat_anchor_minute" in sent:
        changes["repeat_anchor_minute"] = payload.repeat_anchor_minute
    if payload.days is not None:
        changes["days"] = tuple(sorted(set(payload.days)))
    if payload.mains_only is not None:
        changes["mains_only"] = payload.mains_only
    if payload.pause == "resume":
        changes["paused_until"] = None
    elif payload.pause == "tomorrow":
        context = await schedule_plan.load_context(session, now=now)
        changes["paused_until"] = schedule_plan.tomorrow_start(context.stretches, now=now, zone=zone)
    elif payload.pause is not None:
        changes["paused_until"] = now + _PAUSES[payload.pause]
    if tz:
        changes["timezone"] = zone.key
    await update_schedule_plan_settings(session, **changes)
    await session.commit()
    return await schedule(session, tz=zone.key)


@router.patch("/api/schedule/{binding_id}", response_model=SchedulePayload)
async def update_schedule_time(
    binding_id: int,
    payload: ScheduleTimeUpdate,
    session: SessionDep,
    tz: Annotated[str | None, Query(max_length=64)] = None,
) -> dict:
    """Move one binding deadline while preserving dispatcher safety gates."""
    settings = get_settings()
    now = datetime.now(UTC)
    targets = await get_active_targets(session)
    binding = await session.get(SourceBinding, binding_id)
    if (
        binding is None
        or binding.company_slug not in targets
        or binding.status != "stable"
    ):
        raise api_error(404, ErrorCode.SCHEDULE_NOT_FOUND, "scheduled connector not found")
    state = (
        await session.scalars(
            select(SyncScheduleState).where(
                SyncScheduleState.binding_id == binding_id
            ).with_for_update()
        )
    ).first()
    if state is None:
        raise api_error(404, ErrorCode.SCHEDULE_NOT_FOUND, "schedule has not been seeded")
    provider = await session.get(ProviderPressureState, state.provider_key)
    provider_state = provider.state if provider is not None else "ready"
    if collection_access(state.provider_key, settings=settings).denied:
        provider_state = "policy_denied"
    if provider_state in BLOCKED_PROVIDER_STATES:
        raise api_error(409, ErrorCode.SCHEDULING_UNAVAILABLE, f"{state.provider_key} scheduling is {provider_state}")
    mode = ScanMode(payload.mode)
    if mode is ScanMode.DISCOVERY and not state.discovery_enabled:
        raise api_error(409, ErrorCode.DISCOVERY_UNSUPPORTED, f"{binding.company_slug} does not support discovery probes", company=binding.company_slug)
    if mode is ScanMode.RECONCILE and state.manual_requested_at is not None:
        raise api_error(409, ErrorCode.MANUAL_SCAN_QUEUED, "cancel the queued manual sync before changing its schedule")
    try:
        move_schedule_deadline(
            state,
            mode=mode,
            minute_of_day=payload.local_minute,
            timezone=payload.timezone,
            now=now,
        )
    except ValueError as error:
        raise api_error(422, ErrorCode.SCHEDULE_REFUSED, str(error)) from error
    await session.commit()
    return await schedule(session, tz=tz)


# The scan-bound part of a status read: which followed boards were read when, the
# scheduler's summary of them, when the next scan starts, and how many companies the
# last finished scan read and how many of its roles the New board lists. On a
# populated database it is most of the read, and the app and the dashboard each poll
# status every few seconds while work runs. It is reused for a short while within
# one process. Everything a person changes in the schedule or the followed companies
# is in the key, so a Sync request, a provider pause, a schedule pause or choice, a
# follow, a board or consent change, or a settings change shows on the next read, as
# does a scan that finishes. What a scan writes while it runs, and a role marked Not
# for me or a scope save, may lag by at most the reuse window.
SCAN_BOUND_REUSE_SECONDS = 30.0
_reuse_clock = time.monotonic
_SCAN_BOUND_KEY = text(
    "SELECT"
    " (SELECT md5(coalesce(string_agg(row(binding_id, provider_key, discovery_enabled, manual_requested_at,"
    " discovery_anchor_minute, reconcile_anchor_minute, schedule_timezone)::text, '|' ORDER BY binding_id), ''))"
    " FROM sync_schedule_state),"
    " (SELECT md5(coalesce(string_agg(row(pressure_key, state, cooldown_until)::text, '|' ORDER BY pressure_key),"
    " '')) FROM provider_pressure_state),"
    " (SELECT md5(coalesce(string_agg(row(id, company_slug, status, connector_kind, connector_id, retired_at)::text,"
    " '|' ORDER BY id), '')) FROM source_bindings),"
    " (SELECT md5(coalesce(string_agg(row(slug, status, enabled, visible, adapter, board_token, board_region,"
    " careers_url, consented_at, consent_fingerprint)::text, '|' ORDER BY slug), '')) FROM tracked_company),"
    " (SELECT md5(value::text) FROM app_settings WHERE key = :plan_key),"
    " (SELECT row(id, finished_at, outcome)::text FROM schedule_plan_runs ORDER BY id DESC LIMIT 1)"
).bindparams(plan_key=SCHEDULE_PLAN_KEY)


@dataclass(frozen=True)
class _ScanBound:
    key: tuple
    read_at: float
    followed: list[FollowedBinding]
    scheduler: dict
    schedule: ScanSchedule
    new_roles: int | None
    last_companies: int | None


_scan_bound: _ScanBound | None = None


def forget_scan_bound() -> None:
    global _scan_bound
    _scan_bound = None


async def _scan_bound_reads(
    session: AsyncSession, settings: Settings, now: datetime, last_finished: int | None
) -> _ScanBound:
    """`last_finished` is the newest finished scan run's id, whose companies and new roles are counted."""
    global _scan_bound
    key = (settings.model_dump_json(), last_finished, *(await session.execute(_SCAN_BOUND_KEY)).one())
    reused = _scan_bound
    if reused is not None and reused.key == key and _reuse_clock() - reused.read_at < SCAN_BOUND_REUSE_SECONDS:
        return reused
    # Followed companies and what their runs say: one query, read
    # once, for the coverage report and for when each board was last read in
    # full, which dates the status.
    followed = await followed_bindings(session, automatic=scanned_automatically)
    scheduler = await scheduler_status(
        session,
        settings,
        now,
        full_reads={
            row.binding_id: row.last_full_scan_at
            for row in followed
            if row.last_full_scan_at is not None
        },
        gone=boards_gone(followed),
    )
    schedule = await scan_schedule(session, now=now, settings=settings, next_due_at=scheduler["next_due_at"])
    new_roles = (
        await session.scalar(run_new_roles_stmt(last_finished, await off_board_company_slugs(session)))
        if last_finished is not None else None
    )
    # Counted where it is stored: `per_source` holds every company's counts and
    # errors, the largest value the run table stores, and only its size is shown.
    last_companies = await session.scalar(
        select(func.count()).select_from(ScrapeRun)
        .join(func.jsonb_object_keys(ScrapeRun.per_source).table_valued("key").lateral(), true())
        .where(ScrapeRun.id == last_finished, func.jsonb_typeof(ScrapeRun.per_source) == "object")
    ) if last_finished is not None else None
    _scan_bound = _ScanBound(key, _reuse_clock(), followed, scheduler, schedule, new_roles, last_companies)
    return _scan_bound


@router.get("/api/status", response_model=SystemStatusResponse)
async def status(session: SessionDep) -> dict:
    """Freshness + supervision surface for the watchdog and dashboard badge."""
    settings = get_settings()
    now = datetime.now(UTC)

    try:
        await session.execute(text("SELECT 1"))
        db_state = "ok"
    except Exception:  # noqa: BLE001
        db_state = "error"

    # `REFRESHED_STATUSES` includes `partial`: most sources
    # returned data, so the tree is NOT stale. See the constant for why
    # excluding it would keep the scraper in a self-sustaining hourly loop.
    #
    # `scope == "full"` is the second half of that judgement. A targeted retry
    # covers only the sources that failed, so its success is evidence about
    # those and nothing else; counting it here would mark every untouched
    # company fresh and switch off the catch-up that would have re-scraped them.
    last_ok_finished_at = (
        await session.scalars(
            select(ScrapeRun.finished_at)
            .where(
                ScrapeRun.status.in_(REFRESHED_STATUSES),
                ScrapeRun.scope == RunScope.FULL,
            )
            .order_by(ScrapeRun.id.desc())
            .limit(1)
        )
    ).first()
    # The newest scan that read anything, in any scope: what the header calls
    # the last scan. Freshness (`last_success_at`, `stale`) stays the
    # judgement above and below, so one company that cannot be read shows as
    # behind beside a recent scan instead of ageing the whole badge.
    last_scan_at = (
        await session.scalars(
            select(ScrapeRun.finished_at)
            .where(ScrapeRun.status.in_(REFRESHED_STATUSES), ScrapeRun.finished_at.is_not(None))
            .order_by(ScrapeRun.id.desc())
            .limit(1)
        )
    ).first()
    latest_id = select(ScrapeRun.id).order_by(ScrapeRun.id.desc()).limit(1).correlate(None).scalar_subquery()
    finished_id = (select(ScrapeRun.id).where(ScrapeRun.finished_at.is_not(None))
                   .order_by(ScrapeRun.id.desc()).limit(1).correlate(None).scalar_subquery())
    recent = list(await session.scalars(
        select(ScrapeRun).where(or_(ScrapeRun.id == latest_id, ScrapeRun.id == finished_id))
        .order_by(ScrapeRun.id.desc())
        .options(*_RUN_SUMMARY_DEFERRED)
    ))
    last_run = recent[0] if recent else None
    last_finished = next((run for run in recent if run.finished_at is not None), None)
    stuck_running = await stuck_running_count(session, settings=settings, now=now)

    bound = await _scan_bound_reads(session, settings, now, last_finished.id if last_finished else None)
    followed, scheduler = bound.followed, bound.scheduler
    if scheduler["seeded"]:
        # The age of the oldest scan the shown postings rest on, stale while any
        # company's board was not read in full inside the window. Not
        # `last_complete_at`, which is empty whenever ONE company is behind (an
        # empty age reads "No data yet" over a full Board), and not the oldest
        # AUTHORITATIVE reconcile: a board read in full but `lossy` would stay
        # stale forever and keep the watchdog restarting the dispatcher.
        # Closure stays in `overdue`.
        last_success_at = scheduler["oldest_scan_at"]
        stale = bool(scheduler["unread"])
        age_hours = (
            (now - last_success_at).total_seconds() / 3600.0
            if last_success_at is not None
            else None
        )
    else:
        last_success_at = last_ok_finished_at
        age_hours, stale = freshness(last_success_at, now, settings.freshness_max_hours)

    derivations = await derivation_status(session, settings, now)

    pipeline_running = is_run_active(
        last_run.status if last_run else None,
        last_run.started_at if last_run else None,
        now,
        settings.stale_run_minutes,
        heartbeat_at=last_run.heartbeat_at if last_run else None,
        heartbeat_stale_seconds=settings.stale_run_heartbeat_seconds,
    )
    jobs, supervisor = await job_store.status_view(session, now)
    # Two questions about requests, one statement: Sync's scan, and a re-embed.
    manual_sync_running, reembed_requested = (
        await session.execute(
            select(scan_requests.manual_sync_clause(), job_requests.pending_clause(job_requests.REEMBED))
        )
    ).one()
    # `running` is "a pipeline is executing right now", and nothing else.
    # Queued work reports as itself, never merged into it: the dashboard pairs
    # `running` with `last_run_started_at` and ticks an elapsed clock, so a
    # manual sync queued behind a provider backoff would read as a live scrape
    # that is not happening.
    model_status, reembed_executing = await matching.activity_facts(session)
    body = {
        "db": db_state,
        "preparation": preparation.snapshot(DATA_DIR) if PACKAGED else None,
        "last_success_at": last_success_at,
        "last_success_age_hours": round(age_hours, 2) if age_hours is not None else None,
        "last_scan_at": last_scan_at,
        "last_scan_age_hours": (
            round((now - last_scan_at).total_seconds() / 3600.0, 2) if last_scan_at is not None else None
        ),
        "last_run_status": last_run.status if last_run else None,
        "last_run_started_at": last_run.started_at if last_run else None,
        "last_run_finished_at": last_run.finished_at if last_run else None,
        "last_run_new": last_run.jobs_new if last_run else None,
        "last_run_seen": last_run.jobs_seen if last_run else None,
        "running": pipeline_running,
        "manual_sync_running": manual_sync_running,
        "manual_queued": scheduler["manual_queued"],
        "manual_blocked": scheduler["manual_blocked"],
        "stuck_running": stuck_running,
        "stale": stale,
        "freshness_max_hours": settings.freshness_max_hours,
        "derivations": derivations,
        "derivations_stale": [d["name"] for d in derivations if d["stale"]],
        # The queue is answered once, at the top: the dashboard polls this
        # every few seconds while it waits.
        "scheduler": {
            key: value for key, value in scheduler.items()
            if key not in ("manual_queued", "manual_blocked")
        },
        # Followed companies without a full scan in days, and empty boards.
        # One query; a report, never a state change.
        "bindings_attention": binding_attention(
            followed, now, stale_after=timedelta(days=settings.coverage_stale_after_days)
        ),
        # A matching-model download or re-embed runs for minutes and is
        # watched from Settings; the shell says one is running anywhere else.
        "matching_switch": matching.phase_of(model_status, reembed_running=reembed_requested or reembed_executing),
        **await plugin_status.status_block(session),
        "jobs": jobs,
        "supervisor": supervisor,
    }
    try:
        identity = installation_identity(
            REPO_ROOT, api_host=settings.api_host, api_port=settings.api_port, version=__version__,
        )
    except ValueError:
        body["launcher"] = None
    else:
        model = "unused" if not settings.search_semantic_enabled else "ready" if model_status == "ready" else (
            "preparing" if model_warming() or reembed_executing else "missing"
        )
        attention = body["bindings_attention"]
        projection = project_status(
            {**body, "last_scan_at": last_finished.finished_at if last_finished else None,
             "last_scan_outcome": last_finished.status if last_finished else None,
             "coverage_attention": attention["outage"] or any(
                coverage_rings(item, outage=attention["outage"]) for item in attention["items"]
            )}, now=now, model=model, reembed_executing=reembed_executing,
        )
        progress = None
        if pipeline_running and last_run is not None and last_run.finished_at is None:
            progress = (await session.scalars(
                select(_SCAN_PICTURE_PROGRESS).where(
                    Notification.source_type == "run", Notification.source_id == last_run.id,
                    Notification.category == "sync_started",
                ).limit(1)
            )).first()
        slugs = in_flight_slugs(progress)
        names = dict((await session.execute(
            select(TrackedCompany.slug, TrackedCompany.display).where(TrackedCompany.slug.in_(slugs))
        )).all()) if slugs else {}
        scan = project_scan(
            progress=progress, names=names, stopped_note=STOPPED_BY_USER_NOTE,
            last_finished={"companies": bound.last_companies, "new_roles": bound.new_roles,
                           "jobs_seen": last_finished.jobs_seen, "notes": last_finished.notes}
            if last_finished else None,
            schedule=bound.schedule, now=now,
        )
        body["launcher"] = {**identity, "status": projection, "scan": scan}
    return body


@router.post("/api/sync", response_model=SyncResponse)
async def sync(session: SessionDep, payload: SyncPayload | None = None) -> dict:
    """Queue provider-safe authoritative reconciliation.

    Empty selection queues the roster; subset queues those bindings. One
    dispatcher pass starts immediately, then the ten-minute agent drains the
    remainder. Same-provider bindings never share a shard, and persisted
    policy/cooldown gates apply to manual work exactly as scheduled work.

    A live run is never joined by a second dispatcher. Companies asked for by
    name are queued anyway, and the live run reads them next
    (`run_pipeline(join_requests=True)`); asking for everyone queues nothing,
    since the live run reads them already. Queue state is committed before
    the process starts.
    """
    settings = get_settings()
    now = datetime.now(UTC)

    # De-duplicated, order-preserving: the picker can hand us the same slug twice
    # (a company sits in two sectors), and a repeated `--company` argument would
    # make the run's target count disagree with its roster.
    requested = list(dict.fromkeys(payload.companies)) if payload else []
    if requested:
        scrapeable = await get_active_targets(session)
        unknown = [slug for slug in requested if slug not in scrapeable]
        if unknown:
            # 400 rather than a silent drop: the pipeline intersects its target
            # list with the roster, so an unknown slug would otherwise produce a
            # narrower run than the user asked for, with nothing to say so.
            raise api_error(400, ErrorCode.INVALID_INPUT, f"not a scrapeable tracked company: {', '.join(sorted(unknown))}")
        providers = {scrapeable[slug]["adapter"] for slug in requested}
        pressure = {
            row.pressure_key: row.state
            for row in (
                await session.scalars(
                    select(ProviderPressureState).where(
                        ProviderPressureState.pressure_key.in_(providers)
                    )
                )
            ).all()
        }
        unavailable = [
            slug
            for slug in requested
            if collection_access(
                scrapeable[slug]["adapter"], company=slug, settings=settings,
                consent=scrapeable[slug].get("consent"),
            ).denied
            or pressure.get(scrapeable[slug]["adapter"]) in BLOCKED_PROVIDER_STATES
        ]
        if unavailable:
            raise api_error(409, ErrorCode.SCHEDULING_UNAVAILABLE, "scheduled collection is paused or policy-denied: "
                    + ", ".join(sorted(unavailable)), companies=sorted(unavailable))

    last_run = (
        await session.scalars(
            select(ScrapeRun).order_by(ScrapeRun.id.desc()).limit(1).options(*_RUN_SUMMARY_DEFERRED)
        )
    ).first()
    if last_run is not None and is_run_active(
        last_run.status,
        last_run.started_at,
        now,
        settings.stale_run_minutes,
        heartbeat_at=last_run.heartbeat_at,
        heartbeat_stale_seconds=settings.stale_run_heartbeat_seconds,
    ):
        queued: list[str] = []
        if requested:
            queued = await queue_manual_reconciliation(session, requested, now=now)
            # If the live run ends before it takes them, the next scan starts.
            await scan_requests.ring(session, requested_by=scan_requests.SYNC)
            await session.commit()
        return {
            "status": "already_running",
            "run_id": last_run.id,
            "started_at": last_run.started_at,
            "companies": [],
            "queued": queued,
        }

    queued = await queue_manual_reconciliation(session, requested or None, now=now)
    # The queue says what to scan; the request says "now". Requests from Sync
    # coalesce while queued, so a second click asks for nothing new, and the
    # supervisor never runs two scans at once. The queue is committed first: a
    # request lost before its commit costs only the wait for the next tick.
    await scan_requests.ring(session, requested_by=scan_requests.SYNC)
    await session.commit()
    # Sync also starts the due plugin work: work the user
    # starts skips the mains gate, never the maintenance-wake gate. Detached; a
    # failure to start it never fails the sync the user asked for.
    await _start_plugin_work(session)
    # Echoed so the header can label the run it just started ("Syncing 3
    # companies") without waiting for the first progress heartbeat.
    return {"status": "started", "companies": requested, "queued": queued}


async def _start_plugin_work(session) -> None:
    try:
        await plugin_runtime.plugins_when_due(session, trigger="sync", power=read_power)
    except Exception:  # noqa: BLE001 - plugin work never fails a sync
        logger.warning("sync: starting plugin work failed", exc_info=True)


def _coverage(item: dict) -> dict:
    """One company's `coverage`: the report's facts, the Coverage notification's
    ring decision and its words. The row on Settings > Companies reads these
    rather than deciding or wording anything itself, so the bell and the row
    say one thing. `rings` ignores the outage collapse: during an
    outage the bell rings once for every stale company, and each row is still
    one of them."""
    said = classify_coverage(item)
    return {
        **{key: item[key] for key in ("cause", "held_open", "days_since_full_scan")},
        "rings": coverage_rings(item),
        "title": said.title,
        "body": said.body,
        "say": said.meta["say"],
    }


@router.get("/api/sync/targets", response_model=SyncTargetsResponse)
async def sync_targets(session: SessionDep) -> dict:
    """The companies a targeted sync may cover, with what ranking them needs.

    The roster is `get_active_targets` and nothing else — exactly the set
    `run_pipeline` would accept — so the picker can never offer a company the
    run would silently drop. A tracked company with no connector is absent here
    on purpose: it is a recorded interest, not a scrapeable source, and the
    Companies board is where that distinction is already explained.

    A pure read, like `/api/companies/discovery`: no `ensure_builtins()` upsert
    (startup and every mutating company route already reconcile built-ins), so
    opening the picker can never queue behind a running scrape's row locks.

    Per company:
      * `last_sync_at` / `age_hours` / `stale` — the newest reconcile attempted,
        from the runs: "when did we last go and look", not "when did
        we last succeed"; a source we attempted and failed is not fresh, and
        its outcome below is what says so.
      * `last_full_scan_at` — the newest reconcile that read the whole board:
        the coverage clock ("Scanned 3 hours ago").
      * `automatic` — scanned without the user asking (not a user-directed source).
      * `last_outcome` / `retryable` — read off the newest **full** run. A
        targeted run's `per_source` covers only its own subset, so it cannot
        answer "which sources still need work" for anyone else.
    """
    settings = get_settings()
    now = datetime.now(UTC)

    targets = await get_active_targets(session)
    if not targets:
        return {"companies": [], "freshness_max_hours": settings.freshness_max_hours}

    # The coverage report, keyed by company: one statement, the same report
    # `/api/status` serves and the bell rings from. It covers the
    # followed companies' active bindings, which is this roster.
    items, _outage = await coverage_report(session, now)
    report = {item["company"]: item for item in items}

    # `reference_run`'s rule picks it, in SQL so only the chosen run's blob is
    # read: the picker's "failed last run" and the set the scheduler retries
    # must be chosen from the same run.
    per_source = await session.scalar(reference_per_source_stmt(_REFERENCE_RUN_WINDOW)) or {}
    # `retry_candidates` is the same eligibility the automated retry uses, so the
    # "failed last run" set in the UI and the one the scheduler works on are one
    # judgement, not two that can drift apart.
    retryable = set(retry_candidates(per_source))

    companies = []
    for slug, target in sorted(targets.items()):
        item = report.get(slug)
        last_sync_at = item["last_attempted_at"] if item else None
        age_hours, stale = freshness(last_sync_at, now, settings.freshness_max_hours)
        # Derived, never read off the stored key: `retryable` below comes from
        # the same derivation, and a company the reference run never touched
        # (added since) must report no outcome rather than an invented one.
        stats = per_source.get(slug)
        outcome = classify_source_outcome(stats).value if stats is not None else None
        companies.append(
            {
                "slug": slug,
                "display": target["display"],
                "adapter": target["adapter"],
                "last_sync_at": last_sync_at,
                "age_hours": round(age_hours, 2) if age_hours is not None else None,
                # A company never yet attempted has no age to be stale against;
                # `freshness` reports it stale, which is the honest answer for a
                # picker whose job is to surface what needs a run.
                "stale": stale,
                "last_full_scan_at": item["last_full_scan_at"] if item else None,
                "automatic": bool(item["automatic"]) if item else False,
                "last_outcome": outcome,
                "retryable": slug in retryable,
                # Only where the bell rings: a user-directed source is scanned
                # when its user asks, and its row shows when instead.
                "coverage": _coverage(item) if item and coverage_rings(item) else None,
            }
        )
    return {"companies": companies, "freshness_max_hours": settings.freshness_max_hours}


async def _run_stopped_by(session, process_group: int) -> ScrapeRun | None:
    """The live run executing in the process group a cancel just signalled.

    Live by the rule `/api/status` applies. A group number is reused once its
    process is gone, so a silent `running` row recorded under the same number
    belongs to a dead process: it stays the stale-run reconciler's case.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    candidates = (
        await session.scalars(
            select(ScrapeRun)
            .where(ScrapeRun.status == "running", ScrapeRun.process_group == process_group)
            .order_by(ScrapeRun.id.desc())
        )
    ).all()
    return next(
        (
            run
            for run in candidates
            if is_run_active(
                run.status,
                run.started_at,
                now,
                settings.stale_run_minutes,
                heartbeat_at=run.heartbeat_at,
                heartbeat_stale_seconds=settings.stale_run_heartbeat_seconds,
            )
        ),
        None,
    )


@router.post("/api/sync/cancel", response_model=SyncCancelResponse)
async def cancel_sync(session: SessionDep) -> dict:
    """Stop a manual sync and remove its remaining queue priority.

    The header control stops only a scan Sync asked for: a scheduled tick or a
    first scan is not its to stop. Pending manual bindings have their prior
    scheduler deadlines restored; naturally overdue work stays overdue.

    It ends only the run it stopped: the live run recorded under the process
    group of the scan it asked the supervisor to stop. Dequeuing stops no
    process, so on its own it ends no run, and a live run in another group is
    not this route's to end.
    """
    status, stopped = await scan_requests.stop_manual_scan(session)
    pid = stopped.pgid if stopped is not None else None
    dequeued = await cancel_manual_reconciliation(session)
    if status != "cancelled" and not dequeued:
        return {"status": status, "pid": pid, "dequeued": []}

    run = await _run_stopped_by(session, pid) if status == "cancelled" and pid is not None else None
    if run is not None:
        # The sources it already committed stay recorded, so the status is
        # their projection, capped at partial; and a stopped run
        # covered less than it set out to, so it claims no full refresh.
        # A run writes `per_source` at its terminal record; a stopped one
        # reports the sources it committed.
        run.per_source = await committed_per_source(session, run.id)
        run.status = cancelled_run_status(
            SourceOutcome(stats["outcome"])
            for stats in run.per_source.values()
            if isinstance(stats, dict) and stats.get("outcome")
        )
        run.scope = RunScope.TARGETED
        run.finished_at = datetime.now(UTC)
        run.notes = STOPPED_BY_USER_NOTE
        await session.flush()
        await generate_sync_result_notification(session, run)
        await session.commit()
    return {
        "status": "cancelled",
        "pid": pid,
        "run_id": run.id if run is not None else None,
        "dequeued": dequeued,
    }


@router.get("/api/runs", response_model=RunListResponse)
async def runs(session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 10) -> dict:
    # A run still running has written no `per_source` yet: it shows what it committed.
    shown = case(
        (ScrapeRun.status == "running", committed_per_source_expr(ScrapeRun.id)), else_=ScrapeRun.per_source,
    ).label("shown_per_source")
    rows = (
        await session.execute(
            select(ScrapeRun, shown)
            .order_by(ScrapeRun.id.desc())
            .limit(limit)
            .options(defer(ScrapeRun.per_source, raiseload=True))
        )
    ).all()
    return {
        "items": [
            {
                "id": r.id,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "status": r.status,
                "jobs_seen": r.jobs_seen,
                "jobs_new": r.jobs_new,
                "jobs_closed": r.jobs_closed,
                "per_source": per_source,
                "drift_alerts": r.drift_alerts,
                "notes": r.notes,
            }
            for r, per_source in rows
        ]
    }
