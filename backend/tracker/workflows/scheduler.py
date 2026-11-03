"""Provider-aware due-work scheduler.

One short invocation:

1. reconcile built-ins/bindings + seed missing schedule/provider rows;
2. select overdue work, round-robin across providers, up to each provider's
   declared `provider_pacing.max_boards_in_flight`;
3. run one small pipeline shard (<= `sync_scheduler_max_bindings`);
4. persist next due times + cross-run provider cooldown.

A provider's boards are queue depth, not parallelism: `collect_sources` drains
one backend's companies serially behind the pacer they all share, so a deeper
shard retires more of the roster without raising anyone's request rate.

Discovery is capped, no-hydrate, and `ScanMode.DISCOVERY`; the pipeline itself
refuses closure and activation in that mode. Reconciliation is the existing
complete source path. The process holds `data/daily.lock`, so scheduler,
manual, `tracker.daily` and targeted retry runs stay one writer.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select

from tracker.company_store import (
    ScanTarget,
    ensure_builtins,
    ensure_catalog_connectors,
    ensure_source_bindings,
    get_active_targets,
)
from tracker.config import Settings, get_settings
from tracker.connectors.recipes.outcome import SourceOutcome, board_missing
from tracker.db.binding import get_active_binding
from tracker.db.models import (
    ProviderPressureState,
    ScrapeSourceRun,
    SourceBinding,
    SyncScheduleState,
)
from tracker.db.repo import close_runs_left_running
from tracker.db.session import session_scope
from tracker.health import RunScope
from tracker.notifications.pursuit_due import generate_pursuit_due_notifications
from tracker.platform import power as host_power
from tracker.platform.locks import (
    AlreadyRunning,
    release_dedicated_advisory_lock,
    run_lock,
    take_dedicated_advisory_lock,
)
from tracker.platform.paths import DATA_DIR, PACING_DIR
from tracker.platform.ratelimit import enable_shared_pacing
from tracker.platform.util import describe_exception
from tracker.plugins.reestimate import reestimate_when_idle
from tracker.provider_pacing import pacing_for
from tracker.settings_store import SCHEDULE_REPEAT_CHOICES, get_schedule_plan_settings
from tracker.source_policy import collection_access
from tracker.source_review import user_directed_source
from tracker.usage_stats.flush import flush_if_due
from tracker.usage_stats.recorder import record_exception
from tracker.workflows import schedule_plan
from tracker.workflows.collection_types import ScanMode
from tracker.workflows.launcher_status import ScanSchedule
from tracker.workflows.pipeline import run_pipeline
from tracker.workflows.retention import retention_when_idle
from tracker.workflows.schedule_status import stable_bindings, waits_for_user

logger = logging.getLogger(__name__)


READY = "ready"
BACKOFF = "backoff"
BLOCKED = "blocked"
PAUSED = "paused"
POLICY_DENIED = "policy_denied"


@dataclass(frozen=True)
class DueWork:
    binding_id: int
    company_slug: str
    provider_key: str
    mode: ScanMode
    due_at: datetime


@dataclass(frozen=True)
class PressureView:
    state: str = READY
    cooldown_until: datetime | None = None

    def eligible(self, now: datetime) -> bool:
        if self.state in {PAUSED, POLICY_DENIED}:
            return False
        return self.cooldown_until is None or self.cooldown_until <= now


@dataclass(frozen=True)
class PressureTransition:
    state: str
    cooldown_until: datetime | None
    consecutive_events: int


def stable_offset_seconds(key: str, window_seconds: int) -> int:
    """Stable schedule spreading without Python's randomized `hash()`."""
    if window_seconds <= 0:
        return 0
    digest = hashlib.blake2b(key.encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % window_seconds


def choose_due_work(
    due: list[DueWork],
    pressure: dict[str, PressureView],
    *,
    now: datetime,
    max_providers: int,
    max_bindings: int | None = None,
) -> list[DueWork]:
    """Oldest reconciliation first, then round-robin across providers.

    Reconciliation outranks discovery because it is the closure/freshness
    contract. Within a mode, oldest deadline wins. Provider cooldown/policy is
    a hard gate, never a score a high-yield source may override.

    **Several bindings per provider.** One binding per provider per tick
    starves a roster whose companies sit mostly on one shared job site: its
    tenants would share a few slots a day while `collect_sources`, built for
    exactly this, sat idle. It admits backends concurrently and drains each
    backend's companies SERIALLY behind one shared pacer, and a queue of length
    1 never reaches the machinery that makes many boards safe.

    A provider contributes up to `pacing_for(provider).max_boards_in_flight`.
    That is queue DEPTH, not parallelism: the boards still drain one at a time
    behind the shared pacer, so a deeper shard retires more of the roster
    without raising the provider's request rate. `RateLimiterPool` is what makes
    that a structural property rather than an intention.

    **Round-robin, so depth cannot become monopoly.** Filling greedily in due
    order would let one provider with fifty overdue tenants take every slot, and
    a provider is exactly the thing we must not concentrate load on. Each pass
    offers every eligible provider ONE binding, oldest-due first, before any
    provider gets a second, so the shard spreads across APIs by construction
    and a big family widens the shard rather than owning it.
    """
    ordered = sorted(
        due,
        key=lambda item: (
            0 if item.mode is ScanMode.RECONCILE else 1,
            item.due_at,
            item.company_slug,
        ),
    )
    # One pipeline invocation has one authority/hydration policy, so the shard's
    # mode is decided by its oldest eligible item and the rest must match it.
    selected_mode: ScanMode | None = None
    queues: dict[str, list[DueWork]] = {}
    provider_order: list[str] = []
    for item in ordered:
        if not pressure.get(item.provider_key, PressureView()).eligible(now):
            continue
        if selected_mode is None:
            selected_mode = item.mode
        elif item.mode is not selected_mode:
            continue
        if item.provider_key not in queues:
            queues[item.provider_key] = []
            provider_order.append(item.provider_key)
        queues[item.provider_key].append(item)

    # Providers are offered slots in oldest-due order, which is what keeps the
    # rotation self-correcting: a family whose tenants are falling behind
    # carries older deadlines and is served first on the next tick.
    provider_order = provider_order[:max_providers]
    allowance = {
        key: max(1, pacing_for(key).max_boards_in_flight) for key in provider_order
    }
    ceiling = max_bindings if max_bindings is not None else sum(allowance.values())

    selected: list[DueWork] = []
    round_index = 0
    while len(selected) < ceiling:
        progressed = False
        for key in provider_order:
            if round_index >= allowance[key] or round_index >= len(queues[key]):
                continue
            selected.append(queues[key][round_index])
            progressed = True
            if len(selected) >= ceiling:
                break
        if not progressed:
            break
        round_index += 1
    return selected


def choose_manual_drain(
    due: list[DueWork],
    pressure: dict[str, PressureView],
    manual_ids: Collection[int],
    *,
    now: datetime,
) -> list[DueWork]:
    """Every queued manual (or never-scanned) reconciliation, as ONE run.

    A user's Sync (and Follow all) drained one shard per tick would spend most
    of its time waiting for the next tick. One run over all of them is safe for
    the reason a deep shard is:
    `collect_sources` gives each host one lane at its own pace, so the run's
    width is hosts in flight, never requests per host. Provider pressure stays
    a hard gate. Automatic work keeps its small shards.
    """
    queued = set(manual_ids)
    return sorted(
        (
            item
            for item in due
            if item.binding_id in queued
            and item.mode is ScanMode.RECONCILE
            and pressure.get(item.provider_key, PressureView()).eligible(now)
        ),
        key=lambda item: (item.due_at, item.company_slug),
    )


def discovery_delay_seconds(
    base_seconds: int, *, consecutive_empty: int, jobs_new: int
) -> int:
    """Conservative cadence expansion; new jobs return to the configured base."""
    if jobs_new > 0 or consecutive_empty < 3:
        return base_seconds
    if consecutive_empty < 7:
        return max(base_seconds, 8 * 3600)
    if consecutive_empty < 14:
        return max(base_seconds, 12 * 3600)
    return max(base_seconds, 24 * 3600)


def _schedule_zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"unknown timezone: {timezone}") from error


def next_local_occurrence(
    now: datetime,
    *,
    minute_of_day: int,
    timezone: str,
) -> datetime:
    """Next selected wall-clock time, never an immediately overdue deadline."""
    if not 0 <= minute_of_day < 24 * 60:
        raise ValueError("minute_of_day must be between 0 and 1439")
    zone = _schedule_zone(timezone)
    local_now = now.astimezone(zone)
    target = local_now.replace(
        hour=minute_of_day // 60,
        minute=minute_of_day % 60,
        second=0,
        microsecond=0,
    )
    if target <= local_now:
        target += timedelta(days=1)
    return target.astimezone(UTC)


def anchored_deadline(
    after: datetime,
    *,
    cadence_seconds: int,
    minute_of_day: int | None,
    timezone: str | None,
) -> datetime:
    """Next cadence slot on a user-selected local-time phase."""
    if minute_of_day is None or timezone is None:
        return after + timedelta(seconds=cadence_seconds)
    if cadence_seconds <= 0:
        raise ValueError("cadence_seconds must be positive")
    zone = _schedule_zone(timezone)
    local_after = after.astimezone(zone)
    anchor = local_after.replace(
        hour=minute_of_day // 60,
        minute=minute_of_day % 60,
        second=0,
        microsecond=0,
    )
    elapsed = (local_after - anchor).total_seconds()
    # Floor division runs backwards for a finish before today's anchor, so the
    # phase repeats through the whole day: 6 h slots anchored at 20:00 include
    # 02:00, 08:00 and 14:00, not only the anchor itself.
    steps = math.floor(elapsed / cadence_seconds) + 1
    candidate = anchor + timedelta(seconds=steps * cadence_seconds)
    return candidate.astimezone(UTC)


def move_schedule_deadline(
    schedule: SyncScheduleState,
    *,
    mode: ScanMode,
    minute_of_day: int,
    timezone: str,
    now: datetime,
) -> datetime:
    """Persist one direct-manipulation anchor and its next natural deadline."""
    deadline = next_local_occurrence(
        now,
        minute_of_day=minute_of_day,
        timezone=timezone,
    )
    schedule.schedule_timezone = timezone
    if mode is ScanMode.DISCOVERY:
        schedule.discovery_anchor_minute = minute_of_day
        schedule.next_discovery_at = deadline
    else:
        schedule.reconcile_anchor_minute = minute_of_day
        schedule.next_reconcile_at = deadline
    return deadline


#: The outcomes that count a pressure event against the provider.
PRESSURE_OUTCOMES = frozenset({SourceOutcome.BLOCKED, SourceOutcome.DEGRADED, SourceOutcome.FAILED})


def counted_this_run(provider: ProviderPressureState) -> bool:
    """The provider's last outcome was recorded by the run in progress (since
    `_mark_started` stamped it) and counted an event nothing has reset since."""
    started, finished = provider.last_started_at, provider.last_finished_at
    return (
        started is not None
        and finished is not None
        and finished >= started
        and provider.consecutive_pressure_events > 0
        and provider.last_outcome in {outcome.value for outcome in PRESSURE_OUTCOMES}
    )


def pressure_transition(
    outcome: SourceOutcome,
    *,
    now: datetime,
    consecutive_events: int,
    backoff_seconds: int,
    blocked_cooldown_seconds: int,
) -> PressureTransition:
    """Cross-run provider response; our bounds/caps are not provider pressure."""
    if outcome is SourceOutcome.UNATTEMPTED:
        return PressureTransition(READY, None, consecutive_events)
    if outcome is SourceOutcome.BLOCKED:
        return PressureTransition(
            BLOCKED,
            now + timedelta(seconds=blocked_cooldown_seconds),
            consecutive_events + 1,
        )
    if outcome in {SourceOutcome.DEGRADED, SourceOutcome.FAILED}:
        events = consecutive_events + 1
        delay = min(blocked_cooldown_seconds, backoff_seconds * (2 ** (events - 1)))
        return PressureTransition(BACKOFF, now + timedelta(seconds=delay), events)
    return PressureTransition(READY, None, 0)


def retry_after_cooldown(stats: dict, now: datetime, cap_seconds: int) -> datetime | None:
    """The moment a provider asked us to stay away until (`Retry-After`, the
    latest one a source received), capped at `cap_seconds` from `now`: a
    provider names a pause, never an unbounded one. None when it asked none or
    the moment has passed."""
    raw = stats.get("retry_after_until")
    if not raw:
        return None
    until = min(datetime.fromisoformat(raw), now + timedelta(seconds=cap_seconds))
    return until if until > now else None


def apply_manual_priority(schedule: SyncScheduleState, now: datetime) -> None:
    """Queue once; repeated clicks must not overwrite the natural deadline."""
    if schedule.manual_requested_at is None:
        schedule.manual_previous_reconcile_at = schedule.next_reconcile_at
    schedule.manual_requested_at = now
    schedule.next_reconcile_at = now


def clear_manual_priority(schedule: SyncScheduleState) -> None:
    """Restore only the deadline displaced by a manual request."""
    if schedule.manual_previous_reconcile_at is not None:
        schedule.next_reconcile_at = schedule.manual_previous_reconcile_at
    schedule.manual_requested_at = None
    schedule.manual_previous_reconcile_at = None


def reconciliation_is_authoritative(outcome: SourceOutcome, stats: dict) -> bool:
    """A natural list stop is insufficient while binding authority is withheld."""
    return (
        outcome is SourceOutcome.OK
        and bool(stats.get("list_complete"))
        and bool(stats.get("closure_eligible"))
    )


def reconciliation_read_the_board(outcome: SourceOutcome, stats: dict) -> bool:
    """A reconcile that read the whole board, whether or not it may close.

    The authoritative reconcile, and a board proven empty: it
    answered everything it was asked, so asking again in 900 s only asks the
    same question. Rechecked at the reconcile cadence, and fresh on the
    schedule's own clock, since the roster's freshness is about reading. Its
    postings still cannot close: the attention report says so, per company,
    which the roster's freshness never could.

    And the clean, complete listing that validated its own binding.
    That run never closes on the evidence it supplies, but the
    binding may close from the next read on. Sent to the failure branch, every
    newly followed company would be re-read 900 s later to learn nothing.
    """
    return (
        reconciliation_is_authoritative(outcome, stats)
        or outcome is SourceOutcome.EMPTY
        or (
            outcome is SourceOutcome.OK
            and bool(stats.get("list_complete"))
            and stats.get("binding_activated") is True
        )
    )


async def _ensure_state(
    session, now: datetime, settings, *, commit: bool = True
) -> tuple[dict[str, ScanTarget], dict[int, SourceBinding]]:
    """Seed what a tick plans from: built-ins, catalog connectors, bindings,
    schedule rows and provider state. With `commit` false the seeding is only
    flushed, so a dry run plans from it and its caller rolls it back."""
    await ensure_builtins(session)
    await ensure_catalog_connectors(session)
    await ensure_source_bindings(session)
    targets = await get_active_targets(session)
    if not targets:
        return targets, {}

    bindings = await stable_bindings(session, targets)
    by_binding = {row.binding_id: row for row in (
        await session.scalars(
            select(SyncScheduleState).where(
                SyncScheduleState.binding_id.in_([b.id for b in bindings])
            )
        )
    ).all()}
    # A binding with no schedule row yet follows its last full read, taken from
    # its runs. Read only for the bindings that need it, which on a settled
    # roster is none.
    unscheduled = [b.id for b in bindings if b.id not in by_binding]
    last_read: dict[int, datetime] = {}
    if unscheduled:
        last_read = {
            binding_id: finished
            for binding_id, finished in (
                await session.execute(
                    select(ScrapeSourceRun.binding_id, func.max(ScrapeSourceRun.finished_at))
                    .where(
                        ScrapeSourceRun.binding_id.in_(unscheduled),
                        ScrapeSourceRun.scan_mode == ScanMode.RECONCILE.value,
                        ScrapeSourceRun.outcome.in_(
                            (SourceOutcome.OK.value, SourceOutcome.EMPTY.value)
                        ),
                    )
                    .group_by(ScrapeSourceRun.binding_id)
                )
            ).all()
        }

    for binding in bindings:
        provider = targets[binding.company_slug]["adapter"]
        state = by_binding.get(binding.id)
        if state is None:
            last_authoritative = last_read.get(binding.id)
            # Existing bindings follow their last full read. A new
            # binding with none is due NOW: it is a company the user just
            # followed (or a new install's), and its first scan joins one drain
            # run. Per-host lanes already make a startup burst impossible, so
            # nothing is spread out to delay a new user's first scan.
            next_reconcile = (
                last_authoritative
                + timedelta(seconds=settings.sync_reconcile_cadence_seconds)
                if last_authoritative is not None
                else now
            )
            state = SyncScheduleState(
                binding_id=binding.id,
                provider_key=provider,
                discovery_enabled=provider in settings.sync_discovery_adapters,
                discovery_cadence_seconds=settings.sync_discovery_cadence_seconds,
                reconcile_cadence_seconds=settings.sync_reconcile_cadence_seconds,
                last_reconcile_at=last_authoritative,
                next_discovery_at=now
                + timedelta(
                    seconds=stable_offset_seconds(
                        f"discovery:{binding.id}",
                        min(3600, settings.sync_discovery_cadence_seconds),
                    )
                ),
                next_reconcile_at=next_reconcile,
            )
            session.add(state)
            by_binding[binding.id] = state
        else:
            state.provider_key = provider
            state.discovery_enabled = provider in settings.sync_discovery_adapters
            state.discovery_cadence_seconds = settings.sync_discovery_cadence_seconds
            state.reconcile_cadence_seconds = settings.sync_reconcile_cadence_seconds

        pressure = await session.get(ProviderPressureState, provider)
        denied = collection_access(provider, settings=settings).denied
        if pressure is None:
            session.add(
                ProviderPressureState(
                    pressure_key=provider,
                    state=POLICY_DENIED if denied else READY,
                    evidence={"reason": "provider policy denies scheduled collection"}
                    if denied
                    else {},
                )
            )
        elif denied:
            pressure.state = POLICY_DENIED
            pressure.cooldown_until = None
            pressure.evidence = {
                "reason": "provider policy denies scheduled collection"
            }
        elif pressure.state == POLICY_DENIED:
            # Policy configuration is the authority for this terminal state.
            # Removing a provider from the deny set must make it schedulable
            # again without a hand-edited DB row.
            pressure.state = READY
            pressure.cooldown_until = None
            pressure.evidence = {}

    if commit:
        await session.commit()
    else:
        await session.flush()
    return targets, {b.id: b for b in bindings}


def collectable_now(
    due: list[DueWork],
    targets: Mapping[str, ScanTarget],
    settings: Settings,
    manual_binding_ids: Collection[int] = (),
) -> list[DueWork]:
    """Drop work the collection gate would refuse, or that only a user may start.

    Two drops, both about work the dispatcher must not choose for itself:

    * **Consent**: a walled company the user has not consented to is
      not due work: the gate refuses it anyway, and leaving it in makes it
      PERMANENTLY overdue, selected every tick and taking a dispatch slot from a
      source that can actually be scanned.
    * **Direction**: a `user_directed` source is collected only
      when the user asks. Consent says "you may"; it does not say "now". So its
      work is admitted ONLY when this binding carries a manual request
      (`SyncScheduleState.manual_requested_at`), which is what the Sync button
      writes. Without that the deadline passing means nothing: the source waits,
      however overdue, rather than being scanned on a timer.

    Both drops are `schedule_status.waits_for_user`, the rule `/api/status`
    also reads, so a company never scanned on a timer is never counted overdue.

    An operator-denied provider is deliberately NOT dropped here: that is a
    provider-level terminal state the pressure table reports, and hiding it from
    the plan would hide it from the screen.
    """
    manual = set(manual_binding_ids)
    keep: list[DueWork] = []
    for item in due:
        if waits_for_user(
            item.company_slug,
            targets[item.company_slug],
            settings=settings,
            manual_requested=item.binding_id in manual,
        ) is None:
            keep.append(item)
    return keep


@dataclass(frozen=True)
class TickPlan:
    """What one tick dispatches, and which run of the schedule plan it is.

    `plan_kind` is `full`/`quick` for a planned run, `continue` for the
    companies the current full read has not read yet, `manual` for a drain of
    user-queued or never-scanned companies, None for a shard of pinned work.
    `roster` is the automatic roster a planned or manual run is measured
    against, so a Scan now of everyone moves the plan's clock and a scan of
    three companies does not."""

    work: list[DueWork]
    plan_kind: str | None = None
    roster: int = 0
    #: The user asked planned scans to wait for mains power.
    wait_for_mains: bool = False


def _pinned(row: SyncScheduleState, mode: ScanMode) -> bool:
    """A deadline the user set on the clock, which the plan leaves alone."""
    if mode is ScanMode.RECONCILE:
        return row.reconcile_anchor_minute is not None
    return row.discovery_anchor_minute is not None


async def plan_due_work(now: datetime | None = None) -> list[DueWork]:
    """Seed/read schedule state and return one provider-safe shard."""
    return (await plan_tick(now)).work


async def plan_tick(now: datetime | None = None, *, dry_run: bool = False) -> TickPlan:
    """Seed/read schedule state and decide this tick's work.

    In order: a drain of user-queued and never-scanned companies;
    then, with the schedule plan on, the companies the current full read has
    not read yet, a planned full read or quick check of the whole automatic
    roster when the plan says so, else a shard of pinned deadlines only; with
    it off, a shard of whatever is due.

    A dry run plans from the same seeding and then rolls it back: it writes
    nothing, so a rehearsal from a branch leaves the database it reaches as it
    found it."""
    settings = get_settings()
    if not settings.sync_scheduler_enabled:
        return TickPlan([])
    now = now or datetime.now(UTC)
    async with session_scope() as session:
        try:
            return await _plan(session, now, settings, seed=not dry_run)
        finally:
            if dry_run:
                await session.rollback()


async def _plan(session, now: datetime, settings: Settings, *, seed: bool) -> TickPlan:
    """`plan_tick` on its session; `seed` false leaves the seeding unsaved."""
    targets, bindings = await _ensure_state(session, now, settings, commit=seed)
    if not bindings:
        return TickPlan([])
    rows = list(
        (
            await session.scalars(
                select(SyncScheduleState).where(
                    SyncScheduleState.binding_id.in_(bindings)
                )
            )
        ).all()
    )
    pressure_rows = {
        row.pressure_key: PressureView(row.state, row.cooldown_until)
        for row in (
            await session.scalars(select(ProviderPressureState))
        ).all()
    }
    rows_by_id = {row.binding_id: row for row in rows}

    due: list[DueWork] = []
    for row in rows:
        binding = bindings[row.binding_id]
        if row.next_reconcile_at <= now:
            due.append(
                DueWork(
                    row.binding_id,
                    binding.company_slug,
                    row.provider_key,
                    ScanMode.RECONCILE,
                    row.next_reconcile_at,
                )
            )
        elif row.discovery_enabled and row.next_discovery_at <= now:
            due.append(
                DueWork(
                    row.binding_id,
                    binding.company_slug,
                    row.provider_key,
                    ScanMode.DISCOVERY,
                    row.next_discovery_at,
                )
            )
    # Ensure no stale target survived a binding race.
    due = [item for item in due if item.company_slug in targets]
    manual_ids = [row.binding_id for row in rows if row.manual_requested_at is not None]
    due = collectable_now(due, targets, settings, manual_ids)
    # A company never scanned at all joins the drain like a manual one: its
    # first scan is what a user who just followed it is waiting for.
    # `collectable_now` has already kept a user-directed source out
    # unless the user started the sync.
    never_scanned = [row.binding_id for row in rows if row.last_outcome is None]
    roster = planned_roster(rows, bindings, targets, pressure_rows, settings, now=now)
    drain = choose_manual_drain(due, pressure_rows, [*manual_ids, *never_scanned], now=now)
    if drain:
        return TickPlan(drain, schedule_plan.MANUAL, len(roster))
    if not settings.sync_schedule_plan_enabled:
        return TickPlan(choose_due_work(
            due,
            pressure_rows,
            now=now,
            max_providers=settings.sync_scheduler_max_providers,
            max_bindings=settings.sync_scheduler_max_bindings,
        ))

    context = await schedule_plan.load_context(session, now=now)
    choices = await get_schedule_plan_settings(session)
    rules, _usual = schedule_plan.context_rules(context, now=now, choices=choices, settings=settings)
    began = schedule_plan.continuation_start(context.runs, now=now, rules=rules)
    if began is not None and roster:
        read = await schedule_plan.read_since(session, began)
        rest = [item for item in roster if item.binding_id not in read]
        if rest:
            return TickPlan(rest, schedule_plan.CONTINUE, len(roster), choices.mains_only)
    kind = schedule_plan.decide(context, now=now, choices=choices, settings=settings)
    if kind == schedule_plan.FULL and roster:
        return TickPlan(roster, kind, len(roster), choices.mains_only)
    if kind == schedule_plan.QUICK:
        quick = [
            DueWork(item.binding_id, item.company_slug, item.provider_key,
                    ScanMode.DISCOVERY, item.due_at)
            for item in roster
            if rows_by_id[item.binding_id].discovery_enabled
        ]
        if quick:
            return TickPlan(quick, kind, len(roster), choices.mains_only)
    # A pause holds every automatic scan, a company's own time included;
    # days of the week are the plan's, and a time a user set is not.
    if choices.paused_until is not None and now < choices.paused_until:
        return TickPlan([])
    pinned = [item for item in due if _pinned(rows_by_id[item.binding_id], item.mode)]
    return TickPlan(choose_due_work(
        pinned,
        pressure_rows,
        now=now,
        max_providers=settings.sync_scheduler_max_providers,
        max_bindings=settings.sync_scheduler_max_bindings,
    ))


async def scan_schedule(
    session, *, now: datetime, settings: Settings, next_due_at: datetime | None
) -> ScanSchedule:
    """When scans start on their own, by the switches `plan_tick` and `_plan` read.

    With the plan off, each company keeps its own deadline and `next_due_at` (the
    scheduler status's earliest) is the next. With it on, the next scan is the plan's
    next run, the one the Schedule page lists first, after any pause; a time a person
    set for one company is listed apart there, and is not the plan's next scan."""
    if not settings.sync_scheduler_enabled:
        return {"scheduling": "off", "paused_until": None, "next_scan_at": None}
    if not settings.sync_schedule_plan_enabled:
        return {"scheduling": "timers", "paused_until": None, "next_scan_at": next_due_at}
    rules, upcoming = schedule_plan.plan_upcoming(
        await schedule_plan.load_context(session, now=now),
        now=now,
        choices=await get_schedule_plan_settings(session),
        settings=settings,
    )
    return {
        "scheduling": "plan",
        "paused_until": rules.paused_until if rules.paused(now) else None,
        "next_scan_at": next((run.at for run in upcoming if not run.running), None),
    }


async def plan_view(
    session,
    *,
    now: datetime,
    settings: Settings,
    zone: ZoneInfo,
    targets: Mapping[str, ScanTarget],
    bindings: Sequence[SourceBinding],
    states: Sequence[SyncScheduleState],
    pressure_rows: Sequence[ProviderPressureState],
    on_battery: bool,
) -> dict:
    """`/api/schedule`'s `plan`, from the same roster and rules a tick uses.

    Takes the rows the route already read, so the plan costs only its own two
    tables and one setting; the clock and settings arrive as parameters (the
    ops contract pins both). `on_battery` is the route's reading of the power
    source, for "waiting for mains power"."""
    by_id = {binding.id: binding for binding in bindings}
    rows = [row for row in states if row.binding_id in by_id]
    pressure = {
        row.pressure_key: PressureView(row.state, row.cooldown_until) for row in pressure_rows
    }
    roster = planned_roster(rows, by_id, targets, pressure, settings, now=now)
    discovery = {row.binding_id for row in rows if row.discovery_enabled}
    pinned = sum(
        1 for row in rows
        if row.reconcile_anchor_minute is not None or row.discovery_anchor_minute is not None
    )
    return schedule_plan.plan_payload(
        await schedule_plan.load_context(session, now=now),
        now=now,
        choices=await get_schedule_plan_settings(session),
        repeat_choices=SCHEDULE_REPEAT_CHOICES,
        settings=settings,
        zone=zone,
        roster=len(roster),
        quick_roster=sum(1 for item in roster if item.binding_id in discovery),
        pinned=pinned,
        on_battery=on_battery,
    )


def planned_roster(
    rows: list[SyncScheduleState],
    bindings: Mapping[int, SourceBinding],
    targets: Mapping[str, ScanTarget],
    pressure: Mapping[str, PressureView],
    settings: Settings,
    *,
    now: datetime,
) -> list[DueWork]:
    """Every company a planned full read takes: the automatic roster.

    The same gates as any automatic work: a company only the user starts
    or a walled one without consent is left out (`collectable_now`
    with no manual request), and so is a provider that is paused, denied or
    cooling down. Oldest full read first, and a company never read is the
    oldest of all: it is the one its person is waiting for."""
    items = [
        DueWork(
            row.binding_id,
            bindings[row.binding_id].company_slug,
            row.provider_key,
            ScanMode.RECONCILE,
            row.last_reconcile_at or now,
        )
        for row in rows
        if bindings[row.binding_id].company_slug in targets
    ]
    items = collectable_now(items, targets, settings)
    last_read = {row.binding_id: row.last_reconcile_at for row in rows}
    return sorted(
        (item for item in items
         if pressure.get(item.provider_key, PressureView()).eligible(now)),
        key=lambda item: (last_read[item.binding_id] is not None, item.due_at, item.company_slug),
    )


async def queue_manual_reconciliation(
    session,
    companies: list[str] | None,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Make selected bindings due now; dispatcher still enforces pressure.

    Empty/None = current roster. The API validates explicit slugs before this
    call. Committed before the scheduler process starts so the first tick cannot
    race an uncommitted queue update.
    """
    settings = get_settings()
    now = now or datetime.now(UTC)
    targets, bindings = await _ensure_state(session, now, settings)
    requested = set(companies or targets)
    pressure = {
        row.pressure_key: row.state
        for row in (await session.scalars(select(ProviderPressureState))).all()
    }
    binding_ids = [
        binding.id
        for binding in bindings.values()
        if binding.company_slug in requested
        and pressure.get(targets[binding.company_slug]["adapter"], READY)
        not in {PAUSED, POLICY_DENIED}
    ]
    if not binding_ids:
        return []
    rows = list(
        (
            await session.scalars(
                select(SyncScheduleState).where(
                    SyncScheduleState.binding_id.in_(binding_ids)
                )
            )
    ).all()
    )
    for row in rows:
        apply_manual_priority(row, now)
    await session.commit()
    by_id = {binding.id: binding.company_slug for binding in bindings.values()}
    return sorted(by_id[row.binding_id] for row in rows)


async def queue_promoted_reconciliation(session, companies: list[str]) -> list[str]:
    """Make companies a scope save promoted postings from due now.

    Not the user's Sync: a user-directed source is collected only
    when the user asks, and a manual request is exactly what lets
    `collectable_now` collect one, so those are left out here. The rest are
    queued like a manual request, so the next tick fetches the promoted rows'
    descriptions, pay and derivations. Commits, as `queue_manual_reconciliation`
    does: call it after the save's own commit.
    """
    targets = await get_active_targets(session)
    chosen = [
        slug for slug in companies
        if slug in targets and not user_directed_source(targets[slug]["adapter"])
    ]
    return await queue_manual_reconciliation(session, chosen) if chosen else []


async def cancel_manual_reconciliation(session) -> list[str]:
    """Remove manual priority while preserving each scheduler deadline."""
    rows = list(
        (
            await session.scalars(
                select(SyncScheduleState).where(
                    SyncScheduleState.manual_requested_at.is_not(None)
                )
            )
        ).all()
    )
    if not rows:
        return []
    binding_ids = [row.binding_id for row in rows]
    bindings = {
        row.id: row.company_slug
        for row in (
            await session.scalars(
                select(SourceBinding).where(SourceBinding.id.in_(binding_ids))
            )
        ).all()
    }
    for row in rows:
        clear_manual_priority(row)
    await session.commit()
    return sorted(bindings[row.binding_id] for row in rows if row.binding_id in bindings)


async def _mark_started(work: list[DueWork], now: datetime) -> None:
    async with session_scope() as session:
        for provider in {item.provider_key for item in work}:
            row = await session.get(ProviderPressureState, provider)
            if row is not None:
                row.last_started_at = now


async def _record_result(
    work: list[DueWork], summary: dict, finished_at: datetime, settings
) -> None:
    by_company = {item.company_slug: item for item in work}
    async with session_scope() as session:
        for company, item in by_company.items():
            stats = (summary.get("per_source") or {}).get(company)
            if stats is None:
                continue
            await record_work_result(session, item, stats, finished_at, settings)


async def record_work_result(
    session, item: DueWork, stats: dict, finished_at: datetime, settings
) -> None:
    """One binding's next deadlines and its provider's pressure, from its outcome.

    Commits nothing. Called by the run's writer inside the commit that finishes
    the company, so a sync stopped midway keeps every company it
    already finished.
    """
    if stats.get("deferred_reason"):
        # A network with no job site answering came before this company
        # started: nothing was asked, so nothing about it
        # is known. Its schedule stays as it was, still due and still in the
        # first-scan or manual drain. Recorded as `unattempted`, a never-scanned
        # company would leave the drain and wait for the small shards.
        # A policy refusal is `unattempted` too and does record: it is the
        # answer for that company until the policy changes.
        return
    company = item.company_slug
    outcome = SourceOutcome(stats["outcome"])
    schedule = (
        await session.scalars(
            select(SyncScheduleState).where(
                SyncScheduleState.binding_id == item.binding_id
            ).with_for_update()
        )
    ).one()
    schedule.last_outcome = outcome.value
    schedule.last_new_count = int(stats.get("new") or 0)
    gone = board_missing(stats)

    if item.mode is ScanMode.DISCOVERY:
        schedule.last_discovery_at = finished_at
        if schedule.last_new_count:
            schedule.consecutive_empty_discoveries = 0
        else:
            schedule.consecutive_empty_discoveries += 1
        delay = discovery_delay_seconds(
            schedule.discovery_cadence_seconds,
            consecutive_empty=schedule.consecutive_empty_discoveries,
            jobs_new=schedule.last_new_count,
        )
        schedule.next_discovery_at = anchored_deadline(
            finished_at,
            cadence_seconds=delay,
            minute_of_day=schedule.discovery_anchor_minute,
            timezone=schedule.schedule_timezone,
        )
    elif reconciliation_read_the_board(outcome, stats):
        schedule.last_reconcile_at = finished_at
        schedule.next_reconcile_at = anchored_deadline(
            finished_at,
            cadence_seconds=schedule.reconcile_cadence_seconds,
            minute_of_day=schedule.reconcile_anchor_minute,
            timezone=schedule.schedule_timezone,
        )
        # A complete reconciliation also covers discovery.
        schedule.last_discovery_at = finished_at
        schedule.next_discovery_at = min(
            schedule.next_reconcile_at,
            anchored_deadline(
                finished_at,
                cadence_seconds=schedule.discovery_cadence_seconds,
                minute_of_day=schedule.discovery_anchor_minute,
                timezone=schedule.schedule_timezone,
            ),
        )
    elif outcome is SourceOutcome.LOSSY or gone:
        # Read the board minus a rounding error of rows. The
        # loss is the board's own and is the same an hour later, so a 900 s
        # retry would re-read the whole board to learn nothing. Next at the
        # reconcile cadence; freshness is NOT stamped, because its postings
        # still cannot close and the roster should keep saying so. A board gone
        # from its address answers the same 404 an hour later too.
        schedule.next_reconcile_at = anchored_deadline(
            finished_at,
            cadence_seconds=schedule.reconcile_cadence_seconds,
            minute_of_day=schedule.reconcile_anchor_minute,
            timezone=schedule.schedule_timezone,
        )
    else:
        # Keep authoritative freshness unchanged; retry later, after
        # the provider transition below decides the pressure window.
        schedule.next_reconcile_at = finished_at + timedelta(
            seconds=settings.sync_provider_backoff_seconds
        )
    if item.mode is ScanMode.RECONCILE:
        schedule.manual_requested_at = None
        schedule.manual_previous_reconcile_at = None

    if gone:
        # The company's board is gone, not the provider pushing back: backing
        # off for it would hold every company on that provider back for one
        # dead board. The provider's state is left as the others made it.
        return
    provider = await session.get(ProviderPressureState, item.provider_key)
    if provider is None or provider.state == POLICY_DENIED:
        return
    events = provider.consecutive_pressure_events
    if outcome in PRESSURE_OUTCOMES and counted_this_run(provider):
        # A run is one look at the provider, however many of its companies it
        # reads: the event this run already counted is the one this outcome
        # would count, so it renews the state and cooldown without counting.
        events -= 1
    transition = pressure_transition(
        outcome,
        now=finished_at,
        consecutive_events=events,
        backoff_seconds=settings.sync_provider_backoff_seconds,
        blocked_cooldown_seconds=settings.sync_provider_blocked_cooldown_seconds,
    )
    cooldown = transition.cooldown_until
    asked = retry_after_cooldown(stats, finished_at, settings.sync_provider_blocked_cooldown_seconds)
    if asked is not None and (cooldown is None or asked > cooldown):
        cooldown = asked
    provider.state = transition.state
    provider.cooldown_until = cooldown
    provider.consecutive_pressure_events = transition.consecutive_events
    provider.last_outcome = outcome.value
    provider.last_finished_at = finished_at
    provider.evidence = {
        "company": company,
        "scan_mode": item.mode.value,
        "errors": list(stats.get("errors") or [])[:5],
    }
    if cooldown and schedule.next_reconcile_at < cooldown:
        schedule.next_reconcile_at = cooldown
    if cooldown and schedule.next_discovery_at < cooldown:
        schedule.next_discovery_at = cooldown


async def _record_dispatch_failure(work: list[DueWork], finished_at: datetime, settings) -> None:
    """Retry later the work a failed run did not record.

    The failure is the run's own: a job site's answer is each company's
    outcome, recorded inside the run. Counted as pressure, one crash would put
    every provider it held on its longest cooldown for an error no job site
    made. The work is due again after the usual retry delay instead.
    """
    retry_at = finished_at + timedelta(seconds=settings.sync_provider_backoff_seconds)
    async with session_scope() as session:
        for item in work:
            schedule = (
                await session.scalars(
                    select(SyncScheduleState).where(
                        SyncScheduleState.binding_id == item.binding_id
                    ).with_for_update()
                )
            ).one_or_none()
            if schedule is None:
                continue
            if item.mode is ScanMode.RECONCILE:
                schedule.next_reconcile_at = retry_at
            else:
                schedule.next_discovery_at = retry_at


async def reminders_when_idle() -> int:
    """The idle tick's reminder reconcile in its own session."""
    async with session_scope() as session:
        return await generate_pursuit_due_notifications(session)


async def close_runs_left_open(now: datetime) -> None:
    """Close what a scan whose process ended before it did left open, before
    a tick plans.

    A run holds the run lock from before it opens its row to its end, so with
    the lock held here no run is live and every ``running`` row is left over,
    however recent its heartbeat; each is closed as a stopped run. `tick`
    holds ``daily.lock``, under which `run_once` opens and finishes plan runs,
    so a plan run without a finish is a stopped tick's: left open, the plan
    would wait for it as a run in progress. With the lock held elsewhere a run
    is live, and nothing is closed.
    """
    settings = get_settings()
    async with session_scope() as session:
        lock = await take_dedicated_advisory_lock(session.bind, settings.advisory_lock_key)
        if lock is None:
            return
        try:
            runs = await close_runs_left_running(session)
            plans = await schedule_plan.close_unfinished_runs(session, now=now)
            await session.commit()
        finally:
            await release_dedicated_advisory_lock(lock, settings.advisory_lock_key)
    if runs or plans:
        logger.info("closed %s scan run(s) and %s plan run(s) a stopped process left open", runs, plans)


async def run_once(*, dry_run: bool = False) -> dict:
    settings = get_settings()
    now = datetime.now(UTC)
    if not dry_run:
        try:
            await close_runs_left_open(now)
        except Exception:  # noqa: BLE001 - housekeeping never fails a tick
            logger.warning("could not close what a stopped scan left open", exc_info=True)
    tick = await plan_tick(now, dry_run=dry_run)
    work = tick.work
    plan = [
        {
            "binding_id": item.binding_id,
            "company": item.company_slug,
            "provider": item.provider_key,
            "mode": item.mode.value,
            "due_at": item.due_at,
        }
        for item in work
    ]
    if dry_run:
        return {"ran": False, "work": plan, "plan_kind": tick.plan_kind, "reason": "dry_run"}
    # A tick in a maintenance wake (lid shut) would read for seconds, freeze,
    # and read again a quarter of an hour later: every read crossing a sleep,
    # none able to close a posting, the run lock held for hours. Nobody sees a
    # result until the lid opens, and the first tick in a full wake reads then.
    # Battery is no reason to wait: these are the user's companies.
    power = host_power.read_power()
    waiting = power.wait_reason(mains=tick.wait_for_mains)
    if waiting is not None:
        return {"ran": False, "work": plan, "plan_kind": tick.plan_kind, "reason": waiting}
    if not work:
        # No run means no post pass: without this a user who stopped following
        # every company would never have their postings removed.
        # Housekeeping, never the tick's outcome: a failure is logged and the
        # next idle tick (or run) removes what is due.
        try:
            retention = await retention_when_idle(now)
            removal: dict = {"removed": retention.removed, "more": retention.more}
        except Exception as error:  # noqa: BLE001 - retention never fails a tick
            logger.warning("idle retention failed", exc_info=True)
            removal = {"error": describe_exception(error)[:500]}
        # Follow-ups that fell due since the last write or run ring now, not at
        # the next scan, which may be hours away or never. DB-only,
        # and the tick already waited out a maintenance wake above.
        try:
            reminders: dict = {"owed": await reminders_when_idle()}
        except Exception as error:  # noqa: BLE001 - reminders never fail a tick
            logger.warning("idle reminder reconcile failed", exc_info=True)
            reminders = {"error": describe_exception(error)[:500]}
        # A reference switch with no scan due (a plugin enabled or refreshed, an
        # atlas edition) moves the stored estimates now, not at the next scan.
        # Per-batch lock; a no-op when nothing moved.
        try:
            moved = await reestimate_when_idle()
            reference: dict = {"applied": moved.applied, "written": moved.written, "skipped": moved.skipped}
        except Exception as error:  # noqa: BLE001 - the re-estimate never fails a tick
            logger.warning("idle re-estimate failed", exc_info=True)
            reference = {"error": describe_exception(error)[:500]}
        return {
            "ran": False, "work": plan, "reason": "nothing due",
            "retention": removal, "reminders": reminders, "reference": reference,
        }

    mode = work[0].mode
    await _mark_started(work, now)
    plan_run_id = await _start_plan_run(tick, now)
    by_company = {item.company_slug: item for item in work}
    recorded: set[str] = set()

    async def record(session, company: str, stats: dict) -> None:
        # In the commit that finishes the company. A company asked for during
        # the run joined it (`join_requests`) and is recorded like the rest.
        item = by_company.get(company) or await _joined_work(session, company, now)
        if item is None:
            return
        await record_work_result(session, item, stats, datetime.now(UTC), settings)
        recorded.add(company)

    try:
        summary = await run_pipeline(
            companies=[item.company_slug for item in work],
            max_list=None,
            hydrate=mode is ScanMode.RECONCILE,
            run_scope=RunScope.TARGETED,
            scan_mode=mode,
            on_source_recorded=record,
            join_requests=True,
        )
    except Exception:
        await _record_dispatch_failure(
            [item for item in work if item.company_slug not in recorded],
            datetime.now(UTC),
            settings,
        )
        await _finish_plan_run(plan_run_id, schedule_plan.FAILED)
        raise
    skipped = summary.get("status") == "skipped"
    if not skipped:
        await _record_result(
            [item for item in work if item.company_slug not in recorded],
            summary,
            datetime.now(UTC),
            settings,
        )
    await _finish_plan_run(plan_run_id, "skipped" if skipped else "ok")
    return {
        "ran": not skipped, "work": plan, "plan_kind": tick.plan_kind, "summary": summary,
    }


async def _joined_work(session, company: str, now: datetime) -> DueWork | None:
    """The reconcile work of a company that joined a run when asked for."""
    binding = await get_active_binding(session, company)
    if binding is None:
        return None
    row = await session.scalar(select(SyncScheduleState).where(SyncScheduleState.binding_id == binding.id))
    if row is None:
        return None
    return DueWork(row.binding_id, company, row.provider_key, ScanMode.RECONCILE, now)


async def _start_plan_run(tick: TickPlan, now: datetime) -> int | None:
    """Open the plan's record of this run, or None for a pinned shard."""
    if tick.plan_kind is None:
        return None
    async with session_scope() as session:
        return await schedule_plan.start_run(
            session, kind=tick.plan_kind, now=now,
            companies=len(tick.work), roster=tick.roster,
        )


async def _finish_plan_run(run_id: int | None, outcome: str) -> None:
    if run_id is None:
        return
    async with session_scope() as session:
        await schedule_plan.finish_run(session, run_id, now=datetime.now(UTC), outcome=outcome)


async def note_awake() -> None:
    """This tick's sample of the machine being on, for the plan's usual hours.

    Taken before the run lock, so ticks during a long run still count, and
    never allowed to fail a tick."""
    try:
        async with session_scope() as session:
            await schedule_plan.note_awake(session, now=datetime.now(UTC))
    except Exception:  # noqa: BLE001 - a sample never fails a tick
        logger.warning("could not record the machine awake", exc_info=True)


def main(after_lock: Sequence[AfterLock] = ()) -> None:
    """Run a manual tick, then any supplied steps after the scan lock is released."""
    enable_shared_pacing(PACING_DIR)
    parser = argparse.ArgumentParser(description="Run one adaptive sync scheduler tick")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    result = asyncio.run(tick(dry_run=args.dry_run, after_lock=after_lock))
    print(json.dumps(result, indent=2, default=str))


#: A step the tick runs after `daily.lock` is released: (result key, step).
AfterLock = tuple[str, Callable[[], Awaitable[dict]]]


async def tick(
    *,
    dry_run: bool,
    after_lock: Sequence[AfterLock] = (),
    sample_awake: bool = True,
    send_usage: bool = True,
) -> dict:
    """One scheduler tick: the awake sample, the run under the lock, then the
    usage-sharing send. The supervisor takes the sample and runs the send on
    their own schedules (neither waits for the preflight), and turns both off here.

    ONE event loop for all three. The database engine pools its connections,
    and a connection belongs to the loop that opened it: a sample taken in its
    own `asyncio.run` would leave a pooled connection the tick's loop then
    reuses, and every tick would fail with "attached to a different loop".
    The sample still comes before the lock, so ticks during a long run
    count. The send comes after the lock is released: it makes a network call,
    and a manual sync waiting for `daily.lock` must not wait on it."""
    if not dry_run and sample_awake:
        await note_awake()
    try:
        with run_lock(DATA_DIR / "daily.lock"):
            result = await run_once(dry_run=dry_run)
    except AlreadyRunning:
        result = {"ran": False, "reason": "run in progress", "work": []}
    except Exception as error:
        await usage_crash(error)
        raise
    if not dry_run:
        for name, step in after_lock:
            result[name] = await step()
        if send_usage:
            result["usage"] = await usage_when_due()
    return result


async def usage_when_due() -> dict:
    """The daily usage-sharing send (docs/architecture.md): logged, never
    fails a tick. It waits out a maintenance wake itself."""
    try:
        return await flush_if_due(scope=session_scope, power=host_power.read_power)
    except Exception as error:  # noqa: BLE001 - usage sharing never fails a tick
        logger.warning("usage sharing send failed", exc_info=True)
        return {"error": describe_exception(error)[:200]}


async def usage_crash(error: BaseException) -> None:
    """Record a tick's crash for crash reports, unless the pipeline already did
    (`record_run_failure` marks what it recorded). Never raises."""
    if getattr(error, "_usage_recorded", False):
        return
    try:
        async with session_scope() as session:
            if await record_exception(session, error, source="scheduler", now=datetime.now(UTC)):
                await session.commit()
    except Exception:  # noqa: BLE001 - a crash report never hides the crash
        logger.warning("could not record the tick's crash for crash reports", exc_info=True)


if __name__ == "__main__":
    main()
