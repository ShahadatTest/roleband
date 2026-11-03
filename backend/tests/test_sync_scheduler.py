"""Adaptive scheduler contracts: provider safety, authority, fairness, cadence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tracker.connectors.recipes.outcome import SourceOutcome
from tracker.db.models import SyncScheduleState
from tracker.provider_pacing import pacing_for
from tracker.workflows.collection_types import ScanMode, SourceCollection
from tracker.workflows.run_persistence import (
    discovery_should_persist,
    scan_emits_run_notifications,
    scan_may_close,
)
from tracker.workflows.scheduler import (
    BLOCKED,
    POLICY_DENIED,
    DueWork,
    PressureView,
    anchored_deadline,
    apply_manual_priority,
    choose_due_work,
    choose_manual_drain,
    clear_manual_priority,
    discovery_delay_seconds,
    move_schedule_deadline,
    next_local_occurrence,
    pressure_transition,
    reconciliation_is_authoritative,
    stable_offset_seconds,
)

NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)


def work(company: str, provider: str, mode: ScanMode, minutes_overdue: int) -> DueWork:
    return DueWork(
        binding_id=len(company),
        company_slug=company,
        provider_key=provider,
        mode=mode,
        due_at=NOW - timedelta(minutes=minutes_overdue),
    )


def complete_collection() -> SourceCollection:
    return SourceCollection(
        company="acme",
        enriched=[],
        seen_keys=set(),
        stats={"errors": []},
        drift=[],
        list_complete=True,
    )


def test_discovery_never_closes_even_when_the_tiny_board_completed():
    collection = complete_collection()
    assert scan_may_close(ScanMode.DISCOVERY, collection, max_list=None) is False
    assert scan_may_close(ScanMode.RECONCILE, collection, max_list=None) is True


def test_capped_reconciliation_still_cannot_close():
    assert scan_may_close(
        ScanMode.RECONCILE, complete_collection(), max_list=150
    ) is False


def test_complete_listing_does_not_advance_authority_while_health_withholds_closure():
    assert not reconciliation_is_authoritative(
        SourceOutcome.OK,
        {"list_complete": True, "closure_eligible": False},
    )


def test_discovery_persists_only_new_or_reopened_frontier_jobs():
    class Job:
        def __init__(self, status):
            self.status = status

    assert discovery_should_persist(None)
    assert discovery_should_persist(Job("closed"))
    assert not discovery_should_persist(Job("open"))


def test_discovery_emits_opportunity_events_without_per_probe_run_banners():
    assert not scan_emits_run_notifications(ScanMode.DISCOVERY)
    assert scan_emits_run_notifications(ScanMode.RECONCILE)
    assert reconciliation_is_authoritative(
        SourceOutcome.OK,
        {"list_complete": True, "closure_eligible": True},
    )


def test_selector_serves_every_provider_before_any_provider_twice():
    """Round-robin, not one binding per provider.

    One board per provider starves a roster where one family holds most of the
    boards. A provider may contribute up to its declared `max_boards_in_flight` (google's is 2, the
    whole population of that connector), but ORDER is the part that matters: the
    second google board must come after apple, never before it, or depth becomes
    monopoly the moment a family grows.
    """
    selected = choose_due_work(
        [
            work("google", "google", ScanMode.RECONCILE, 90),
            work("deepmind", "google", ScanMode.RECONCILE, 80),
            work("apple", "apple", ScanMode.RECONCILE, 70),
        ],
        {},
        now=NOW,
        max_providers=2,
    )
    assert [item.company_slug for item in selected] == ["google", "apple", "deepmind"]


def test_a_provider_never_exceeds_its_declared_depth():
    """The bound that keeps a deeper shard from becoming an unpaced one."""
    due = [work(f"gh{i}", "greenhouse", ScanMode.RECONCILE, 100 - i) for i in range(20)]

    selected = choose_due_work(due, {}, now=NOW, max_providers=1, max_bindings=50)

    assert len(selected) == pacing_for("greenhouse").max_boards_in_flight


def test_a_manual_sync_drains_every_queued_company_in_one_run():
    """A user's Sync is one run, not one shard per 600s tick, which would take
    hours over a large roster. Per-host lanes keep it polite,
    so no shard cap applies; pressure still gates, and automatic work that is
    merely due waits for the automatic shards."""
    specs = [(f"gh{i}", "greenhouse", ScanMode.RECONCILE, 100 - i) for i in range(30)] + [
        ("nvidia", "workday", ScanMode.RECONCILE, 50),
        ("google", "google", ScanMode.RECONCILE, 40),
        ("apple", "apple", ScanMode.DISCOVERY, 30),
        ("background", "ashby", ScanMode.RECONCILE, 200),
    ]
    due = [
        DueWork(index, company, provider, mode, NOW - timedelta(minutes=overdue))
        for index, (company, provider, mode, overdue) in enumerate(specs)
    ]

    selected = choose_manual_drain(
        due,
        {"google": PressureView(BLOCKED, NOW + timedelta(hours=1))},
        [item.binding_id for item in due if item.company_slug != "background"],
        now=NOW,
    )

    names = [item.company_slug for item in selected]
    assert set(names) == {f"gh{i}" for i in range(30)} | {"nvidia"}
    assert "google" not in names, "a provider in cooldown stays gated"
    assert "apple" not in names, "one run has one authority: a discovery probe waits"
    assert "background" not in names, "work nobody asked for keeps its small shard"
    assert len(selected) > pacing_for("greenhouse").max_boards_in_flight


def test_reconciliation_outranks_more_overdue_discovery():
    selected = choose_due_work(
        [
            work("apple", "apple", ScanMode.DISCOVERY, 500),
            work("openai", "ashby", ScanMode.RECONCILE, 1),
        ],
        {},
        now=NOW,
        max_providers=2,
    )
    # One invocation has one authority policy, so discovery waits for a later tick.
    assert [(item.company_slug, item.mode) for item in selected] == [
        ("openai", ScanMode.RECONCILE)
    ]


def test_provider_cooldown_and_policy_denial_are_hard_gates():
    selected = choose_due_work(
        [
            work("meta", "meta", ScanMode.RECONCILE, 100),
            work("google", "google", ScanMode.RECONCILE, 90),
            work("apple", "apple", ScanMode.RECONCILE, 80),
        ],
        {
            "meta": PressureView(POLICY_DENIED),
            "google": PressureView(BLOCKED, NOW + timedelta(hours=1)),
        },
        now=NOW,
        max_providers=3,
    )
    assert [item.company_slug for item in selected] == ["apple"]


def test_expired_cooldown_is_eligible():
    selected = choose_due_work(
        [work("google", "google", ScanMode.RECONCILE, 5)],
        {"google": PressureView(BLOCKED, NOW - timedelta(seconds=1))},
        now=NOW,
        max_providers=1,
    )
    assert [item.company_slug for item in selected] == ["google"]


def test_block_persists_across_runs_for_the_full_operator_cooldown():
    transition = pressure_transition(
        SourceOutcome.BLOCKED,
        now=NOW,
        consecutive_events=2,
        backoff_seconds=900,
        blocked_cooldown_seconds=86_400,
    )
    assert transition.state == BLOCKED
    assert transition.cooldown_until == NOW + timedelta(days=1)
    assert transition.consecutive_events == 3


def test_failures_back_off_exponentially_but_our_cap_does_not():
    first = pressure_transition(
        SourceOutcome.FAILED,
        now=NOW,
        consecutive_events=0,
        backoff_seconds=900,
        blocked_cooldown_seconds=86_400,
    )
    third = pressure_transition(
        SourceOutcome.DEGRADED,
        now=NOW,
        consecutive_events=2,
        backoff_seconds=900,
        blocked_cooldown_seconds=86_400,
    )
    bounded = pressure_transition(
        SourceOutcome.BOUNDED,
        now=NOW,
        consecutive_events=3,
        backoff_seconds=900,
        blocked_cooldown_seconds=86_400,
    )
    assert first.cooldown_until == NOW + timedelta(minutes=15)
    assert third.cooldown_until == NOW + timedelta(minutes=60)
    assert bounded.state == "ready"
    assert bounded.cooldown_until is None
    assert bounded.consecutive_events == 0


def test_empty_discovery_expands_cadence_only_after_repeated_evidence():
    base = 6 * 3600
    assert discovery_delay_seconds(base, consecutive_empty=2, jobs_new=0) == base
    assert discovery_delay_seconds(base, consecutive_empty=3, jobs_new=0) == 8 * 3600
    assert discovery_delay_seconds(base, consecutive_empty=7, jobs_new=0) == 12 * 3600
    assert discovery_delay_seconds(base, consecutive_empty=14, jobs_new=0) == 24 * 3600
    assert discovery_delay_seconds(base, consecutive_empty=20, jobs_new=1) == base


def test_schedule_spreading_is_stable_and_bounded():
    first = stable_offset_seconds("reconcile:42", 3600)
    assert first == stable_offset_seconds("reconcile:42", 3600)
    assert 0 <= first < 3600
    assert stable_offset_seconds("reconcile:42", 0) == 0


def test_direct_schedule_move_uses_the_next_local_wall_clock_occurrence():
    state = SyncScheduleState(
        binding_id=1,
        provider_key="google",
        next_discovery_at=NOW,
        next_reconcile_at=NOW,
    )

    deadline = move_schedule_deadline(
        state,
        mode=ScanMode.RECONCILE,
        minute_of_day=20 * 60,
        timezone="Europe/Stockholm",
        now=NOW,
    )

    assert deadline == datetime(2026, 7, 28, 18, tzinfo=UTC)
    assert state.next_reconcile_at == deadline
    assert state.reconcile_anchor_minute == 20 * 60
    assert state.schedule_timezone == "Europe/Stockholm"


def test_selected_time_that_already_passed_moves_to_tomorrow():
    after_local_target = datetime(2026, 7, 28, 19, tzinfo=UTC)

    assert next_local_occurrence(
        after_local_target,
        minute_of_day=20 * 60,
        timezone="Europe/Stockholm",
    ) == datetime(2026, 7, 29, 18, tzinfo=UTC)


def test_successful_runs_keep_the_user_selected_cadence_phase():
    finished = datetime(2026, 7, 28, 18, 7, tzinfo=UTC)

    assert anchored_deadline(
        finished,
        cadence_seconds=6 * 3600,
        minute_of_day=20 * 60,
        timezone="Europe/Stockholm",
    ) == datetime(2026, 7, 29, 0, tzinfo=UTC)
    assert anchored_deadline(
        finished,
        cadence_seconds=24 * 3600,
        minute_of_day=20 * 60,
        timezone="Europe/Stockholm",
    ) == datetime(2026, 7, 29, 18, tzinfo=UTC)


def test_a_finish_before_the_anchor_takes_the_next_slot_of_the_phase_not_the_anchor():
    """6 h anchored at 20:00 runs at 02:00, 08:00, 14:00 and 20:00 local: a
    finish at 02:07 is next due at 08:00, not twelve hours later at 20:00."""
    finished = datetime(2026, 7, 29, 0, 7, tzinfo=UTC)  # 02:07 in Stockholm

    assert anchored_deadline(
        finished,
        cadence_seconds=6 * 3600,
        minute_of_day=20 * 60,
        timezone="Europe/Stockholm",
    ) == datetime(2026, 7, 29, 6, tzinfo=UTC)
    # A daily cadence has one slot a day, so the anchor is the next one.
    assert anchored_deadline(
        finished,
        cadence_seconds=24 * 3600,
        minute_of_day=20 * 60,
        timezone="Europe/Stockholm",
    ) == datetime(2026, 7, 29, 18, tzinfo=UTC)


def test_direct_schedule_move_rejects_unknown_timezones():
    state = SyncScheduleState(
        binding_id=1,
        provider_key="google",
        next_discovery_at=NOW,
        next_reconcile_at=NOW,
    )

    with pytest.raises(ValueError, match="unknown timezone"):
        move_schedule_deadline(
            state,
            mode=ScanMode.RECONCILE,
            minute_of_day=20 * 60,
            timezone="Mars/Olympus",
            now=NOW,
        )


def test_manual_priority_cancel_restores_only_the_displaced_deadline():
    natural_due = NOW + timedelta(hours=9)
    state = SyncScheduleState(
        binding_id=1,
        provider_key="google",
        next_discovery_at=NOW + timedelta(hours=2),
        next_reconcile_at=natural_due,
    )

    apply_manual_priority(state, NOW)
    apply_manual_priority(state, NOW + timedelta(minutes=1))

    assert state.next_reconcile_at == NOW + timedelta(minutes=1)
    assert state.manual_previous_reconcile_at == natural_due

    clear_manual_priority(state)

    assert state.next_reconcile_at == natural_due
    assert state.manual_requested_at is None
    assert state.manual_previous_reconcile_at is None


@pytest.mark.asyncio
async def test_a_new_install_scans_every_company_it_follows_in_its_first_run(scratch_scope, monkeypatch):
    """A company never scanned is due now and joins one drain, rather than a
    new install's first scans spreading over hours of 8-per-tick shards. A
    user-directed source (Workday) still waits for a
    sync the user starts."""
    from tracker.config import get_settings
    from tracker.workflows import scheduler

    session_scope = scratch_scope
    monkeypatch.setattr(get_settings(), "sync_scheduler_max_bindings", 2)

    work = await scheduler.plan_due_work(NOW)

    async with session_scope() as session:
        targets = await scheduler.get_active_targets(session)
    providers = {item.provider_key for item in work}
    assert len(work) > 2, "the shard cap does not apply to a first scan"
    assert {item.company_slug for item in work} == {
        slug for slug, cfg in targets.items() if cfg["adapter"] != "workday"
    }
    assert "workday" not in providers
    assert all(item.mode is ScanMode.RECONCILE for item in work)


@pytest.mark.asyncio
async def test_a_company_the_run_deadline_deferred_stays_in_the_first_scan_drain(scratch_scope, monkeypatch):
    """The run's own deadline came before the company started. Recorded as
    `unattempted`, it must stay in the never-scanned drain rather than trickle
    through 8-per-tick shards. A company the policy refused is also `unattempted` and must still leave
    the drain, or it would take a place in every run forever."""
    from sqlalchemy import select

    from tracker.config import get_settings
    from tracker.workflows import scheduler
    from tracker.workflows.collection_types import deferred_collection

    session_scope = scratch_scope
    monkeypatch.setattr(get_settings(), "sync_scheduler_max_bindings", 2)

    first = await scheduler.plan_due_work(NOW)
    assert len(first) > 3
    deferred, refused = first[0], first[1]
    finished = NOW + timedelta(minutes=30)
    async with session_scope() as session:
        stats = {**deferred_collection(deferred.company_slug).stats, "outcome": "unattempted"}
        await scheduler.record_work_result(session, deferred, stats, finished, get_settings())
        refusal = {"outcome": "unattempted", "unattempted": True, "errors": [],
                   "policy_reason": "denied by the operator"}
        await scheduler.record_work_result(session, refused, refusal, finished, get_settings())

    later = await scheduler.plan_due_work(finished + timedelta(minutes=10))

    planned = {item.company_slug for item in later}
    assert deferred.company_slug in planned
    assert refused.company_slug not in planned
    assert len(later) > 2, "still the first-scan drain, not a shard"
    async with session_scope() as session:
        state = await session.scalar(
            select(SyncScheduleState).where(SyncScheduleState.binding_id == deferred.binding_id)
        )
    assert state.last_outcome is None


@pytest.mark.asyncio
@pytest.mark.parametrize("gone", [False, True])
async def test_a_provider_that_says_retry_after_is_not_asked_again_before_then(scratch_scope, gone):
    """A source received `Retry-After: 2 hours`. No binding on that provider is
    dispatched before then, across a restart (the cooldown is stored), and the
    pause is capped by the blocked cooldown. A board gone from its address
    (404) is that company's, never the provider's: no cooldown."""
    from tracker.config import get_settings
    from tracker.db.models import ProviderPressureState
    from tracker.workflows import scheduler

    session_scope = scratch_scope
    from sqlalchemy import update

    asked = (await scheduler.plan_due_work(NOW))[0]
    provider = asked.provider_key

    def dispatched(items) -> bool:
        return any(i.provider_key == provider for i in items)

    from tracker.workflows.collection_types import empty_stats

    finished = NOW + timedelta(minutes=1)
    asked_until = (finished + timedelta(hours=2)).isoformat()
    if gone:
        stats = {**empty_stats(), "errors": ["HTTPStatusError: 404 on the board root"], "board_missing": True,
                 "outcome": "failed", "retry_after_until": asked_until}
    else:
        stats = {**empty_stats(), "scanned": 3, "kept": 3, "outcome": "ok", "list_complete": True,
                 "closure_eligible": True, "retry_after_until": asked_until}
    async with session_scope() as session:
        await scheduler.record_work_result(session, asked, stats, finished, get_settings())

    async with session_scope() as session:
        cooldown = (await session.get(ProviderPressureState, provider)).cooldown_until
        # Due again at once: whatever on this provider is due must still wait.
        await session.execute(update(SyncScheduleState).where(SyncScheduleState.binding_id == asked.binding_id)
                              .values(next_reconcile_at=finished, next_discovery_at=finished))
    if gone:
        assert cooldown is None
        return
    assert cooldown == finished + timedelta(hours=2)
    later = await scheduler.plan_due_work(finished + timedelta(hours=1))
    assert not dispatched(later), "every binding on the provider waits out its pause"
    async with session_scope() as session:  # a new process reads the stored pause
        state = await session.get(ProviderPressureState, provider)
    view = scheduler.PressureView(state.state, state.cooldown_until)
    assert not view.eligible(finished + timedelta(hours=1)) and view.eligible(cooldown + timedelta(minutes=1))


@pytest.mark.asyncio
async def test_a_run_counts_one_pressure_event_per_provider_however_many_companies_failed(scratch_scope):
    """A run is one look at a provider, so the companies that failed there in
    it are one answer. Counted per company, a provider with a hundred companies
    would go from its first bad night straight to the blocked cooldown. The
    next run that fails there counts the next event, and a success in a run
    clears what came before it."""
    from dataclasses import replace

    from tracker.config import get_settings
    from tracker.db.models import ProviderPressureState
    from tracker.workflows import scheduler
    from tracker.workflows.collection_types import empty_stats

    settings = get_settings()
    first, *others = await scheduler.plan_due_work(NOW)
    provider = first.provider_key
    # Three of the run's companies read through one provider.
    work = [first, *(replace(item, provider_key=provider) for item in others[:2])]
    backoff = timedelta(seconds=settings.sync_provider_backoff_seconds)

    async def scan(started: datetime, outcomes: list[str]) -> tuple[int, datetime | None]:
        await scheduler._mark_started(work, started)
        for minute, (item, outcome) in enumerate(zip(work, outcomes, strict=True), start=1):
            stats = {**empty_stats(), "errors": ["ReadTimeout"] if outcome == "failed" else [], "outcome": outcome}
            async with scratch_scope() as session:
                await scheduler.record_work_result(session, item, stats, started + timedelta(minutes=minute), settings)
        async with scratch_scope() as session:
            state = await session.get(ProviderPressureState, provider)
            return state.consecutive_pressure_events, state.cooldown_until

    assert await scan(NOW, ["failed", "failed", "failed"]) == (1, NOW + timedelta(minutes=3) + backoff)
    later = NOW + timedelta(hours=1)
    assert await scan(later, ["failed", "failed", "failed"]) == (2, later + timedelta(minutes=3) + 2 * backoff)
    after = NOW + timedelta(hours=2)
    assert await scan(after, ["failed", "ok", "failed"]) == (1, after + timedelta(minutes=3) + backoff)


def test_a_retry_after_is_capped_by_the_blocked_cooldown_and_a_past_one_is_none():
    from tracker.workflows.scheduler import retry_after_cooldown

    far = {"retry_after_until": (NOW + timedelta(days=30)).isoformat()}
    assert retry_after_cooldown(far, NOW, 3600) == NOW + timedelta(seconds=3600)
    assert retry_after_cooldown({"retry_after_until": (NOW - timedelta(minutes=1)).isoformat()}, NOW, 3600) is None
    assert retry_after_cooldown({}, NOW, 3600) is None
