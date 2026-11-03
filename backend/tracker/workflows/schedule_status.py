"""What the schedule IS, apart from the dispatcher that changes it.

What the connector schedule is (`/api/schedule`), and whether the tree is
fresh and what is queued (`/api/status`), are projections of stored rows: given
a roster, its bindings, their schedule rows and provider pressure, they are pure
arithmetic over a clock, testable without an HTTP request. What to dispatch is
`scheduler.py`'s. Each fact both need has one home here, so the router and the
dispatcher cannot disagree about it:

- **The blocked-provider set** (`BLOCKED_PROVIDER_STATES`). A copy missing a
  state would read a paused provider as schedulable on one surface and not on
  another.
- **Which bindings the scheduler actually dispatches** (`stable_binding_where`).
  A router listing bindings the dispatcher will never touch is worse than an
  empty list, because it looks like work in progress.
- The stuck-run count (`stuck_running_count`), the predicate
  `reconcile_stale_runs` uses, read with the caller's Python clock.

Nothing here reads the clock or the settings: both arrive as parameters, because
the ops contract pins `routers/ops.py`'s `datetime` and its settings getter, and a
projection that fetched its own would answer from the real machine inside a
pinned test (`tests/test_schedule_status.py` reads this module's AST to keep it
that way). Nor does anything here
import `tracker.workflows.scheduler`: the dependency runs the other way, since
the dispatcher uses `stable_bindings` too.

What stays in the router: HTTP status mapping, the response envelopes, the
scan requests (`api/scan_requests.py`), and `_run_stopped_by`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.company_store import ScanTarget, get_active_targets
from tracker.config import Settings
from tracker.db.models import (
    DerivationState,
    ProviderPressureState,
    ScrapeRun,
    SourceBinding,
    SyncScheduleState,
)
from tracker.db.queries.runs import stale_run_where
from tracker.health import freshness
from tracker.source_policy import collection_access
from tracker.source_review import user_directed_source
from tracker.workflows.post_passes import POST_PASSES

#: A provider in one of these states holds every binding behind it: no deadline
#: is eligible, no manual request moves, and the binding is excluded from the
#: required roster rather than counted overdue. `scheduler.py` names the two
#: states individually (`POLICY_DENIED`, `PAUSED`) and this set must stay equal
#: to that pair: asserted in `tests/test_schedule_status.py`, not imported,
#: because the dispatcher imports THIS module.
BLOCKED_PROVIDER_STATES = frozenset({"policy_denied", "paused"})

#: How often the scan tick runs, reported by `/api/schedule` so the UI can say
#: when queued work will next move. The real cadence is the supervisor's `scan`
#: job (`tracker/supervisor/registry.py`), which this mirrors, asserted in
#: `tests/test_supervisor_due.py`; `scheduler.py` itself never reads it, which is
#: why it lives with the projection that reports it rather than with the tick.
SCHEDULER_TICK_SECONDS = 600


def effective_provider_state(
    provider_key: str, pressure: ProviderPressureState | None, *, settings: Settings
) -> str:
    """The provider state the DISPATCHER will act on, not the one last stored.

    `ProviderPressureState.state` is a reconciled cache: `scheduler._ensure_state`
    rewrites it from `collection_access` on every tick and on every `/api/sync`,
    so between a policy change and the next of those the row is stale. It is also
    absent entirely for a provider whose first tick has not run.

    Policy therefore OUTRANKS the row, in both directions of absence: a denied
    provider reads `policy_denied` whatever the row says or whether it exists at
    all. Both `/api/schedule` and `/api/status` apply this; if only one did,
    the same binding would be `policy_denied` on one surface and counted overdue --
    permanently, on a machine whose dispatcher is switched off -- on the other.
    """
    if collection_access(provider_key, settings=settings).denied:
        return "policy_denied"
    return pressure.state if pressure is not None else "ready"


#: `waits_for_user`'s answers, each also an `ExcludedBinding.reason` on the wire.
WALLED = "walled"
USER_DIRECTED = "user_directed"
#: A followed company whose careers page is gone from its address:
#: Coverage tells it, so the roster does not also call it stale.
BOARD_MISSING = "board_missing"
WAITS_FOR_USER = frozenset({WALLED, USER_DIRECTED})

#: `scheduler_status`'s `unread` reasons, each an `UnreadBinding.reason` on the
#: wire: no full read ever, or none inside the window.
NEVER_READ = "never_read"
READ_STALE = "read_stale"
UNREAD_REASONS = frozenset({NEVER_READ, READ_STALE})


def waits_for_user(
    company: str, target: ScanTarget, *, settings: Settings, manual_requested: bool
) -> str | None:
    """Why automatic work never collects this company, or None if it may.

    The ONE rule behind both `scheduler.collectable_now` (which drops the work)
    and `scheduler_status` (which drops the binding from the roster it calls
    fresh or overdue). Kept apart, the roster would count a company the
    dispatcher never scans on a timer as overdue, leave `last_complete_at`
    empty forever, and the top bar would read "No data yet" over a full Board.

    * `walled`: a walled company the user has not consented to; the collection
      gate refuses it whoever asks.
    * `user_directed`: a source collected only when the user asks,
      until this binding carries a manual request.
    """
    access = collection_access(
        target["adapter"], company=company, settings=settings, consent=target.get("consent")
    )
    if access.walled:
        return WALLED
    if user_directed_source(target["adapter"]) and not manual_requested:
        return USER_DIRECTED
    return None


def stable_binding_where(targets: Iterable[str]) -> tuple[ColumnElement[bool], ...]:
    """The bindings the dispatcher will actually consider, as WHERE criteria.

    `status == "stable"` is the binding state machine's own gate: a provisional
    or withdrawn binding is not dispatched, so a surface that lists it is
    describing work that will never happen.
    """
    return (
        SourceBinding.company_slug.in_(list(targets)),
        SourceBinding.status == "stable",
    )


async def stable_bindings(session: AsyncSession, targets: Iterable[str]) -> list[SourceBinding]:
    """Every stable binding of an active target, in one query."""
    return list(
        (await session.scalars(select(SourceBinding).where(*stable_binding_where(targets)))).all()
    )


async def stuck_running_count(session: AsyncSession, *, settings: Settings, now: datetime) -> int:
    """How many `running` rows are orphans rather than live progress.

    The predicate is `db/queries/runs.py::stale_run_where`, the same one
    `reconcile_stale_runs` flips rows with. Only the clock differs and
    that is the caller's answer: this surface reads the Python clock, because it
    reports beside `is_run_active`, which is handed the same `now`.
    """
    return (
        await session.scalar(
            select(func.count())
            .select_from(ScrapeRun)
            .where(
                stale_run_where(
                    now,
                    stale_minutes=settings.stale_run_minutes,
                    heartbeat_stale_seconds=settings.stale_run_heartbeat_seconds,
                )
            )
        )
    ) or 0


def eligible_schedule_at(
    deadline: datetime | None,
    *,
    provider_state: str,
    cooldown_until: datetime | None,
) -> datetime | None:
    if deadline is None or provider_state in BLOCKED_PROVIDER_STATES:
        return None
    if cooldown_until is not None:
        return max(deadline, cooldown_until)
    return deadline


def schedule_payload(
    *,
    bindings: Sequence[SourceBinding],
    states: Sequence[SyncScheduleState],
    pressure_rows: Sequence[ProviderPressureState],
    targets: Mapping[str, ScanTarget],
    settings: Settings,
    now: datetime,
) -> dict:
    """Everything `/api/schedule` answers: the envelope, the bindings, the providers.

    Persisted deadlines only — a dispatch time is never invented. The clock and
    the settings arrive as parameters; nothing here goes and asks.
    """
    state_by_binding = {row.binding_id: row for row in states}
    pressure_by_key = {row.pressure_key: row for row in pressure_rows}
    provider_counts: dict[str, int] = {}
    rows: list[dict] = []

    for binding in sorted(bindings, key=lambda item: item.company_slug):
        target = targets.get(binding.company_slug)
        state = state_by_binding.get(binding.id)
        provider_key = (
            state.provider_key if state is not None
            else target.get("adapter") if target else None
        )
        provider_key = provider_key or binding.connector_id
        provider_counts[provider_key] = provider_counts.get(provider_key, 0) + 1
        pressure = pressure_by_key.get(provider_key)
        provider_state = effective_provider_state(provider_key, pressure, settings=settings)
        cooldown_until = pressure.cooldown_until if pressure is not None else None

        if state is None:
            status_name = "unscheduled"
        elif provider_state in BLOCKED_PROVIDER_STATES:
            status_name = provider_state
        elif cooldown_until is not None and cooldown_until > now:
            status_name = "cooldown"
        elif state.manual_requested_at is not None:
            status_name = "manual"
        else:
            status_name = "scheduled"

        rows.append(
            {
                "binding_id": binding.id,
                "company": binding.company_slug,
                "provider": provider_key,
                "closure_capability": binding.closure_capability,
                "scheduled": state is not None,
                "discovery_enabled": bool(state and state.discovery_enabled),
                "discovery_cadence_seconds": (
                    state.discovery_cadence_seconds if state is not None else None
                ),
                "reconcile_cadence_seconds": (
                    state.reconcile_cadence_seconds if state is not None else None
                ),
                "last_discovery_at": state.last_discovery_at if state is not None else None,
                "last_reconcile_at": state.last_reconcile_at if state is not None else None,
                "next_discovery_at": state.next_discovery_at if state is not None else None,
                "next_reconcile_at": state.next_reconcile_at if state is not None else None,
                "discovery_anchor_minute": (
                    state.discovery_anchor_minute if state is not None else None
                ),
                "reconcile_anchor_minute": (
                    state.reconcile_anchor_minute if state is not None else None
                ),
                "schedule_timezone": (
                    state.schedule_timezone if state is not None else None
                ),
                "eligible_discovery_at": (
                    eligible_schedule_at(
                        state.next_discovery_at,
                        provider_state=provider_state,
                        cooldown_until=cooldown_until,
                    )
                    if state is not None and state.discovery_enabled
                    else None
                ),
                "eligible_reconcile_at": (
                    eligible_schedule_at(
                        state.next_reconcile_at,
                        provider_state=provider_state,
                        cooldown_until=cooldown_until,
                    )
                    if state is not None
                    else None
                ),
                "manual_requested_at": (
                    state.manual_requested_at if state is not None else None
                ),
                "last_outcome": state.last_outcome if state is not None else None,
                "last_new_count": state.last_new_count if state is not None else 0,
                "consecutive_empty_discoveries": (
                    state.consecutive_empty_discoveries if state is not None else 0
                ),
                "provider_state": provider_state,
                "cooldown_until": cooldown_until,
                "status": status_name,
                # The scheduler's own rule: the screen must not call a company
                # "Scheduled" when no timer takes it.
                "waits_for_user": waits_for_user(
                    binding.company_slug,
                    target,
                    settings=settings,
                    manual_requested=state is not None and state.manual_requested_at is not None,
                ) if target else None,
            }
        )

    provider_keys = sorted(provider_counts)
    providers: list[dict] = []
    for provider_key in provider_keys:
        pressure = pressure_by_key.get(provider_key)
        # Not `state`: that name is bound above to the SyncScheduleState row, and
        # this is the provider's string verdict.
        provider_verdict = effective_provider_state(provider_key, pressure, settings=settings)
        providers.append(
            {
                "provider": provider_key,
                "state": provider_verdict,
                "cooldown_until": pressure.cooldown_until if pressure is not None else None,
                "last_started_at": pressure.last_started_at if pressure is not None else None,
                "last_finished_at": pressure.last_finished_at if pressure is not None else None,
                "last_outcome": pressure.last_outcome if pressure is not None else None,
                "binding_count": provider_counts[provider_key],
            }
        )

    return {
        "generated_at": now,
        "enabled": settings.sync_scheduler_enabled,
        "tick_seconds": SCHEDULER_TICK_SECONDS,
        "max_parallel_providers": settings.sync_scheduler_max_providers,
        "authoritative_stale_hours": settings.sync_authoritative_stale_hours,
        "bindings": rows,
        "providers": providers,
    }


async def derivation_status(session: AsyncSession, settings: Settings, now: datetime) -> list[dict]:
    """Per-pass freshness for the derivation registry.

    One entry per POST_PASSES pass. Enabled passes are joined against
    `derivation_state`; a pass with no row (never run) or one older than the
    freshness window reports `stale=True`, so a pass registered but never run
    is visible rather than silent. Disabled passes
    report `enabled: false` and are never stale.
    """
    rows = {r.name: r for r in (await session.scalars(select(DerivationState))).all()}
    out: list[dict] = []
    for p in POST_PASSES:
        enabled = p.enabled(settings)
        row = rows.get(p.name)
        last_ok_at = row.last_ok_at if row else None
        if not enabled:
            out.append({"name": p.name, "enabled": False, "stale": False})
            continue
        age_hours, stale = freshness(last_ok_at, now, settings.freshness_max_hours)
        out.append(
            {
                "name": p.name,
                "enabled": True,
                "last_ok_at": last_ok_at,
                "last_run_at": row.last_run_at if row else None,
                "last_status": row.last_status if row else None,
                "age_hours": round(age_hours, 2) if age_hours is not None else None,
                "stale": stale,
            }
        )
    return out


def manual_block_reason(
    company: str,
    *,
    provider_key: str,
    provider_state: str,
    cooldown_until: datetime | None,
    now: datetime,
) -> dict | None:
    """Why this manually-requested binding cannot start yet, or None if it can.

    Only provider-level gates count. A binding whose own `next_reconcile_at` is
    in the future is NOT blocked: a manual request is what overrides its
    cadence, so reporting cadence as a block would call every queued binding
    blocked.

    `provider_state` is the EFFECTIVE state (`effective_provider_state`), not the
    stored row's: `provider.state` can answer "not blocked" for a provider the
    dispatcher will refuse on policy.
    """
    if provider_state in BLOCKED_PROVIDER_STATES:
        return {"company": company, "provider": provider_key,
                "reason": provider_state, "until": None}
    if cooldown_until is not None and cooldown_until > now:
        return {"company": company, "provider": provider_key,
                "reason": "backoff", "until": cooldown_until}
    return None


def blocks_by_provider(blocked: list[dict]) -> list[dict]:
    """One row per provider holding queued work back, with how many companies
    wait on it. The gate is the provider's (`manual_block_reason` reads nothing
    of the company), so every company behind one provider shares its reason
    and end, and a queue of every company is a handful of rows."""
    by_provider: dict[str, dict] = {}
    for row in blocked:
        held = by_provider.setdefault(row["provider"], {
            "provider": row["provider"], "reason": row["reason"], "until": row["until"], "companies": 0,
        })
        held["companies"] += 1
    return sorted(by_provider.values(), key=lambda row: row["provider"])


async def scheduler_status(
    session: AsyncSession,
    settings: Settings,
    now: datetime,
    *,
    full_reads: Mapping[int, datetime],
    gone: AbstractSet[int] = frozenset(),
) -> dict:
    """Per-binding authoritative freshness + provider-safe due-work state.

    `full_reads` is when each binding's board was last read in full, by
    binding id: a reconcile whose outcome is `ok`, `empty` or `lossy`. The
    caller passes the coverage report's own (`binding_attention.
    followed_bindings`), so the status age and that report read the
    same rows and cannot disagree. A full read counts what closure
    cannot use: the listing that validated its own binding and a
    board that lists all but a rounding error of its rows. Their
    postings are as new as the read; only the right to close is missing, and
    `overdue` keeps saying that.

    `gone` names the bindings whose careers page is gone from its address
    (`binding_attention.boards_gone`): excluded, reason
    `board_missing`, so one company that moved its roles does not hold the top
    bar at "Stale" until the user finds its new page or stops following it.
    """
    targets = await get_active_targets(session)
    if not targets:
        return {
            "enabled": settings.sync_scheduler_enabled,
            "seeded": False,
            "required": 0,
            "ever_read": 0,
            "fresh": 0,
            "overdue": [],
            "unread": [],
            "excluded": [],
            "last_complete_at": None,
            "oldest_scan_at": None,
            "next_due_at": None,
            "manual_queued": [],
            "manual_blocked": [],
            "providers": [],
        }
    bindings = await stable_bindings(session, targets)
    state_by_binding = {
        row.binding_id: row
        for row in (
            await session.scalars(
                select(SyncScheduleState).where(
                    SyncScheduleState.binding_id.in_([b.id for b in bindings])
                )
            )
        ).all()
    }
    pressure = list((await session.scalars(select(ProviderPressureState))).all())
    pressure_by_key = {row.pressure_key: row for row in pressure}
    cutoff = now - timedelta(hours=settings.sync_authoritative_stale_hours)
    overdue: list[dict] = []
    unread: list[dict] = []
    excluded: list[dict] = []
    authoritative: list[datetime] = []
    next_due: list[datetime] = []
    manual_queued: list[str] = []
    manual_blocked: list[dict] = []
    read: list[datetime] = []

    def note_read(binding: SourceBinding, state: SyncScheduleState | None) -> None:
        # The read clock: the newer of the binding's last full read
        # and its reconcile stamp, which predates `scrape_source_runs` for an
        # old binding and is seeded from its health row for a recreated one.
        stamps = [
            at
            for at in (
                state.last_reconcile_at if state is not None else None,
                full_reads.get(binding.id),
            )
            if at is not None
        ]
        read_at = max(stamps) if stamps else None
        if read_at is None:
            # Never read in full: the clock runs from the follow, as the
            # coverage report's does, so a company followed today
            # whose first read our page ceiling cut is not yet stale.
            if binding.created_at is not None and binding.created_at >= cutoff:
                return
            unread.append(
                {"company": binding.company_slug, "reason": NEVER_READ, "last_read_at": None}
            )
            return
        read.append(read_at)
        if read_at < cutoff:
            unread.append(
                {"company": binding.company_slug, "reason": READ_STALE, "last_read_at": read_at}
            )

    for binding in bindings:
        state = state_by_binding.get(binding.id)
        waiting = waits_for_user(
            binding.company_slug,
            targets[binding.company_slug],
            settings=settings,
            manual_requested=state is not None and state.manual_requested_at is not None,
        )
        if waiting is None and binding.id in gone:
            waiting = BOARD_MISSING
        if waiting is not None:
            excluded.append(
                {
                    "company": binding.company_slug,
                    "provider": state.provider_key if state else targets[binding.company_slug]["adapter"],
                    "reason": waiting,
                }
            )
            continue
        if state is None:
            overdue.append({"company": binding.company_slug, "reason": "not_scheduled"})
            note_read(binding, None)
            continue
        provider = pressure_by_key.get(state.provider_key)
        provider_state = effective_provider_state(
            state.provider_key, provider, settings=settings
        )
        cooldown_until = provider.cooldown_until if provider is not None else None
        if state.manual_requested_at is not None:
            manual_queued.append(binding.company_slug)
            # Queued is not the same as moving. A provider in backoff or paused
            # holds every binding behind it, and without naming that here the
            # request is indistinguishable from one about to run: a cooldown
            # would read as an active sync.
            blocked = manual_block_reason(
                binding.company_slug,
                provider_key=state.provider_key,
                provider_state=provider_state,
                cooldown_until=cooldown_until,
                now=now,
            )
            if blocked is not None:
                manual_blocked.append(blocked)
        if provider_state in BLOCKED_PROVIDER_STATES:
            excluded.append(
                {
                    "company": binding.company_slug,
                    "provider": state.provider_key,
                    "reason": provider_state,
                }
            )
            continue
        note_read(binding, state)
        eligible_reconcile = state.next_reconcile_at
        if cooldown_until is not None:
            eligible_reconcile = max(eligible_reconcile, cooldown_until)
        next_due.append(eligible_reconcile)
        if state.discovery_enabled:
            eligible_discovery = state.next_discovery_at
            if cooldown_until is not None:
                eligible_discovery = max(eligible_discovery, cooldown_until)
            next_due.append(eligible_discovery)
        if state.last_reconcile_at is None:
            overdue.append({"company": binding.company_slug, "reason": "never_reconciled"})
        elif state.last_reconcile_at < cutoff:
            overdue.append(
                {
                    "company": binding.company_slug,
                    "reason": "authoritative_stale",
                    "last_reconcile_at": state.last_reconcile_at,
                }
            )
        else:
            authoritative.append(state.last_reconcile_at)

    required = len(bindings) - len(excluded)
    return {
        "enabled": settings.sync_scheduler_enabled,
        "seeded": len(state_by_binding) == len(bindings),
        "required": required,
        # Required companies read in full at least once, however long ago:
        # with `required`, how far the first pass over the roster has got.
        # Unlike `unread`, it counts a company followed today that has not
        # been read yet as not read.
        "ever_read": len(read),
        "fresh": len(authoritative),
        "overdue": overdue,
        # Required companies whose board was not read in full inside the
        # window, or never: what makes `/api/status` stale. Not
        # `overdue`, which also names a board read in full last night that may
        # not close (`lossy`) or has not yet (its first read validated
        # its binding): one such company would hold the top bar at "Stale".
        "unread": unread,
        "excluded": excluded,
        # The oldest authoritative binding is when the whole required roster
        # was last known fresh. Missing/overdue bindings make the cycle partial.
        "last_complete_at": min(authoritative) if not overdue and authoritative else None,
        # The oldest scan any shown posting rests on: the oldest full read
        # among required companies. A company
        # never read in full has no full read to date, so it adds nothing here;
        # once its follow is older than the window it is named in `unread`.
        # None only when no required company was read.
        "oldest_scan_at": min(read) if read else None,
        "next_due_at": min(next_due) if next_due else None,
        "manual_queued": sorted(manual_queued),
        "manual_blocked": blocks_by_provider(manual_blocked),
        # Every provider a scheduled binding depends on, reported by its
        # EFFECTIVE state and kept to the ones that are not simply ready: the
        # question this list answers is "why is work not moving". Built from the
        # bindings rather than from the rows, because a policy-denied provider
        # whose first tick has not run has no row and is exactly such a reason.
        "providers": sorted(
            (
                {
                    "provider": key,
                    "state": effective_provider_state(
                        key, pressure_by_key.get(key), settings=settings
                    ),
                    "cooldown_until": (
                        pressure_by_key[key].cooldown_until if key in pressure_by_key else None
                    ),
                    "last_outcome": (
                        pressure_by_key[key].last_outcome if key in pressure_by_key else None
                    ),
                }
                for key in {
                    row.provider_key for row in state_by_binding.values()
                }
                if effective_provider_state(key, pressure_by_key.get(key), settings=settings)
                != "ready"
                or (key in pressure_by_key and pressure_by_key[key].cooldown_until is not None)
            ),
            key=lambda row: row["provider"],
        ),
    }

