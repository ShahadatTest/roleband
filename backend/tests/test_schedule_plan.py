"""The schedule plan: one clock for every company.

What the plan promises, each held here against a plausible wrong version:

* A full read when the computer comes on, a quick check each repeat while it is
  on, missed repeats never replayed, a full read at least daily on a machine
  that never sleeps.
* A Scan now of everyone moves the clock; a scan of a few companies does not.
* The usual on-hours are learned from ticks (seeded from `pmset -g log`), never
  asked; a dark wake is not "on"; whole days only; recent days weigh more.
* The dispatcher reads the whole automatic roster in one run, leaves Workday to
  the user, and otherwise serves only deadlines the user pinned.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, update

from tracker.db.models import MachineAwakeSample, SchedulePlanRun, SyncScheduleState
from tracker.platform.power import Power, full_wake_intervals
from tracker.workflows import schedule_plan as plan
from tracker.workflows.collection_types import ScanMode
from tracker.workflows.schedule_plan import (
    CONTINUE,
    FAILED_RETRY,
    FULL,
    INTERRUPTED,
    MANUAL,
    QUICK,
    PlanRunView,
    UsualHours,
    awake_stretches,
    plan_decision,
    project_upcoming,
    run_durations,
    turned_on_at,
    usual_hours,
)

# The API cases reach the ops router, which can start or signal a process, so
# no test here may.
pytestmark = pytest.mark.usefixtures("no_escape")

STOCKHOLM = ZoneInfo("Europe/Stockholm")
#: A Wednesday, 10:00 in Stockholm.
NOW = datetime(2026, 10, 7, 10, 0, tzinfo=STOCKHOLM).astimezone(UTC)
REPEAT = timedelta(hours=6)
FULL_AFTER = timedelta(hours=20)


def run(kind: str, started_hours_ago: float, minutes: float | None = 40, *,
        outcome: str | None = "ok", companies: int = 1000, roster: int = 1000) -> PlanRunView:
    started = NOW - timedelta(hours=started_hours_ago)
    finished = None if minutes is None else started + timedelta(minutes=minutes)
    return PlanRunView(kind, started, finished, companies, roster,
                       outcome if minutes is not None else None)


RULES = plan.rules_for(repeat=REPEAT, full_after=FULL_AFTER, zone=STOCKHOLM)


def decide(runs, *, turned_on=None, now=NOW, rules=RULES):
    return plan_decision(runs, now=now, rules=rules, turned_on=turned_on)


# ------------------------------------------------------------------ the wake log


PMSET_LOG = """\
2026-09-28 19:51:07 +0200 Start               \tpowerd process is started
2026-09-28 21:52:47 +0200 Assertions          \tPID 432(runningboardd) Released PreventUserIdleSystemSleep
2026-09-29 06:25:25 +0200 Sleep               \tEntering Sleep state due to 'Software Sleep pid=431'
2026-09-29 06:25:26 +0200 Wake Requests       \t[process=dasd request=SleepService deltaSecs=988]
2026-09-29 06:25:44 +0200 DarkWake            \tDarkWake from Deep Idle [CDNP] : due to smc.sysState.Wake
2026-09-29 06:26:02 +0200 Sleep               \tEntering Sleep state due to 'Maintenance Sleep'
2026-09-29 16:31:20 +0200 DarkWake            \tDarkWake from Deep Idle [CDNP] : due to HID Activity
2026-09-29 16:31:26 +0200 Wake                \tDarkWake to FullWake from Deep Idle [CDNVA] : due to HID Activity
2026-09-29 18:00:00 +0200 Sleep               \tEntering Sleep state due to 'Clamshell Sleep'
2026-09-30 08:00:00 +0200 Wake                \tWake from Normal Sleep [CDNVA] : due to UserActivity
"""


def test_the_wake_log_yields_full_wakes_only_and_an_open_one_runs_to_now():
    now = datetime(2026, 9, 30, 9, 30, tzinfo=STOCKHOLM)
    intervals = full_wake_intervals(PMSET_LOG, now)

    def at(text: str) -> datetime:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S %z")

    assert intervals == [
        (at("2026-09-28 19:51:07 +0200"), at("2026-09-29 06:25:25 +0200")),
        # The dark wake at 06:25 and the one at 16:31:20 are maintenance, not use.
        (at("2026-09-29 16:31:26 +0200"), at("2026-09-29 18:00:00 +0200")),
        (at("2026-09-30 08:00:00 +0200"), now),
    ]


def test_wake_requests_are_not_wakes_and_no_log_is_no_history():
    only_requests = "2026-09-29 06:25:26 +0200 Wake Requests       \t[process=dasd]\n"
    assert full_wake_intervals(only_requests, NOW) == []
    assert full_wake_intervals(None, NOW) == []


# ---------------------------------------------------------------- awake stretches


def test_samples_a_tick_or_a_late_tick_apart_are_one_stretch_and_a_break_is_two():
    t0 = NOW - timedelta(hours=5)
    samples = [t0, t0 + timedelta(minutes=10), t0 + timedelta(minutes=32),  # 22 min: one late tick
               t0 + timedelta(hours=3)]  # a break
    assert awake_stretches(samples) == [
        (t0, t0 + timedelta(minutes=42)),
        (t0 + timedelta(hours=3), t0 + timedelta(hours=3, minutes=10)),
    ]


def test_turned_on_is_the_start_of_today_after_a_night_off_and_none_when_never_off():
    night = [NOW - timedelta(hours=26) + timedelta(minutes=10 * n) for n in range(30)]
    morning = [NOW - timedelta(minutes=40) + timedelta(minutes=10 * n) for n in range(5)]
    stretches = awake_stretches(night + morning)
    assert turned_on_at(stretches, now=NOW, gap=timedelta(hours=2)) == NOW - timedelta(minutes=40)

    always = awake_stretches([NOW - timedelta(minutes=10 * n) for n in range(200)])
    assert turned_on_at(always, now=NOW, gap=timedelta(hours=2)) is None

    lunch = awake_stretches(
        [NOW - timedelta(hours=3) + timedelta(minutes=10 * n) for n in range(8)]
        + [NOW - timedelta(minutes=30) + timedelta(minutes=10 * n) for n in range(4)]
    )
    assert turned_on_at(lunch, now=NOW, gap=timedelta(hours=2)) is None, "a short break is not turning on"
    assert turned_on_at(stretches, now=NOW + timedelta(hours=2), gap=timedelta(hours=2)) is None, (
        "not seen on now"
    )


# -------------------------------------------------------------------- usual hours


def days_on(first: date, count: int, start: time, end: time, *, weekdays_only: bool = True):
    samples: list[datetime] = []
    for n in range(count):
        day = first + timedelta(days=n)
        if weekdays_only and day.weekday() >= 5:
            continue
        at = datetime.combine(day, start, tzinfo=STOCKHOLM)
        stop = datetime.combine(day, end, tzinfo=STOCKHOLM)
        while at < stop:
            samples.append(at.astimezone(UTC))
            at += timedelta(minutes=10)
    return samples


def test_a_working_week_learns_weekday_hours_and_weekends_off():
    # Mon 21 Sep .. Tue 6 Oct, on 09:00-17:30 on weekdays, never at weekends.
    samples = days_on(date(2026, 9, 21), 16, time(9), time(17, 30))
    usual = usual_hours(awake_stretches(samples), now=NOW, zone=STOCKHOLM)
    assert not usual.learning
    assert usual.weekdays == ((9 * 60, 17 * 60 + 30),)
    assert usual.weekends == (), "weekends were observed, and off"
    assert usual.windows_on(date(2026, 10, 7)) == ((540, 1050),)
    assert usual.windows_on(date(2026, 10, 10)) == ()


def test_fewer_than_five_whole_days_is_still_learning_and_the_partial_days_do_not_count():
    # Sampling began Sat 3 Oct at 14:00; today (Wed 7th) is not over.
    samples = days_on(date(2026, 10, 3), 5, time(14), time(18), weekdays_only=False)
    usual = usual_hours(awake_stretches(samples), now=NOW, zone=STOCKHOLM)
    assert usual.observed_days == 3, "Sun, Mon, Tue: not Sat (began mid-day) nor today"
    assert usual.learning
    assert usual.windows_on(date(2026, 10, 7)) is None


def test_a_new_routine_replaces_the_old_one_within_a_week():
    old = days_on(date(2026, 9, 14), 14, time(8), time(12))  # two weeks of mornings
    new = days_on(date(2026, 9, 28), 9, time(14), time(20))  # then afternoons
    usual = usual_hours(awake_stretches(old + new), now=NOW, zone=STOCKHOLM)
    assert usual.weekdays == ((14 * 60, 20 * 60),)


def test_scattered_use_learns_no_window():
    samples: list[datetime] = []
    for n in range(14):
        day = date(2026, 9, 22) + timedelta(days=n)
        hour = 6 + (n * 5) % 15  # a different hour each day
        samples += days_on(day, 1, time(hour), time(hour + 1), weekdays_only=False)
    usual = usual_hours(awake_stretches(samples), now=NOW, zone=STOCKHOLM)
    assert not usual.learning
    assert usual.weekdays == () and usual.weekends == ()


# ------------------------------------------------------------------ the decision


def test_the_first_run_ever_is_a_full_read():
    assert decide([]) == FULL


def test_nothing_runs_before_the_repeat_and_a_quick_check_runs_after_it():
    assert decide([run(FULL, 2)]) is None
    assert decide([run(FULL, 10), run(QUICK, 5.9)]) is None
    assert decide([run(FULL, 10), run(QUICK, 6)]) == QUICK


def test_a_day_old_full_read_makes_the_repeat_a_full_read():
    assert decide([run(FULL, 21), run(QUICK, 7)]) == FULL


def test_turning_the_computer_on_starts_a_full_read_at_once():
    last = run(QUICK, 3)  # repeat not yet due
    assert decide([run(FULL, 9), last], turned_on=NOW - timedelta(minutes=5)) == FULL
    assert decide([run(FULL, 9), last], turned_on=NOW - timedelta(hours=4)) is None, (
        "turned on before the last run: that run was the wake's"
    )


def test_a_machine_asleep_through_three_repeats_runs_once():
    assert decide([run(FULL, 20)], turned_on=NOW - timedelta(minutes=2)) == FULL
    assert decide([run(FULL, 20), run(FULL, 0.1, None)], turned_on=NOW - timedelta(minutes=2)) is None


def test_a_run_in_progress_waits_however_long_it_has_run():
    assert decide([run(FULL, 30), run(FULL, 1, None)]) is None
    assert decide([run(FULL, 30), run(FULL, 9, None)]) is None, "a slow scan is long, not dead"


def test_a_failed_run_is_retried_in_half_an_hour_and_a_skipped_one_never_happened():
    assert decide([run(FULL, 10), run(QUICK, 0.4, outcome="failed")]) is None
    assert decide([run(FULL, 10), run(QUICK, 0.5, outcome="failed")]) == QUICK
    assert decide([run(FULL, 3), run(QUICK, 0.1, outcome="skipped")]) is None
    assert decide([run(FULL, 7), run(QUICK, 0.1, outcome="skipped")]) == QUICK


def test_an_interrupted_full_read_is_continued_at_once_while_it_is_the_current_one():
    def start(runs, *, now=NOW, rules=RULES):
        return plan.continuation_start(runs, now=now, rules=rules)

    stopped = run(FULL, 1, 20, outcome=INTERRUPTED)
    assert start([stopped]) == stopped.started_at
    assert start([run(FULL, 21, 20, outcome=INTERRUPTED)]) is None, "a day-old full read is read again"
    assert start([run(FULL, 1, None)]) is None, "a run in progress continues itself"
    paused = plan.rules_for(repeat=REPEAT, full_after=FULL_AFTER, zone=STOCKHOLM,
                            paused_until=NOW + timedelta(hours=1))
    assert start([stopped], rules=paused) is None


def test_what_a_finished_or_failed_full_read_left_is_asked_again_in_half_an_hour():
    finished = run(FULL, 1, 40)  # finished 20 minutes ago
    assert plan.continuation_start([finished], now=NOW, rules=RULES) is None
    assert plan.continuation_start([finished], now=NOW + timedelta(minutes=10), rules=RULES) == (
        finished.started_at
    )
    failed = run(FULL, 2, 30, outcome="failed")
    after_continuation = run(CONTINUE, 0.2, 5)
    assert plan.continuation_start([failed, after_continuation], now=NOW, rules=RULES) is None
    assert plan.continuation_start(
        [failed, after_continuation], now=NOW + FAILED_RETRY, rules=RULES
    ) == failed.started_at, "a continuation never moves the start it continues"


def test_a_stopped_full_read_still_holds_the_daily_clock():
    stopped = run(FULL, 3, 20, outcome=INTERRUPTED)
    assert plan.last_full_at([run(FULL, 25), stopped], NOW) == stopped.started_at
    assert decide([stopped, run(CONTINUE, 2.5, 30)]) is None, "no full read starts over it"
    assert decide([run(FULL, 21), run(QUICK, 0.4, outcome=INTERRUPTED)]) is None
    assert decide([run(FULL, 21), run(QUICK, 0.5, outcome=INTERRUPTED)]) == FULL


def test_a_running_continuation_is_drawn_as_the_full_read_and_never_measured():
    upcoming = project_upcoming([run(FULL, 2, 20, outcome=INTERRUPTED), run(CONTINUE, 0.5, None)],
                                now=NOW, rules=RULES, turned_on=None, usual=OFFICE, on_now=True)
    assert upcoming[0].running and upcoming[0].kind == FULL
    assert run_durations([run(CONTINUE, 2, 3)])[FULL][1] is True, "a piece of a full read is no full read"


def test_a_scan_now_of_everyone_is_a_full_read_and_of_three_companies_is_nothing():
    everyone = run(MANUAL, 1, companies=950, roster=1000)
    three = run(MANUAL, 1, companies=3, roster=1000)
    assert decide([everyone]) is None
    assert decide([run(FULL, 21), everyone, run(QUICK, 7)]) is None
    assert decide([run(FULL, 21), three, run(QUICK, 7)]) == FULL
    assert plan.last_full_at([run(FULL, 30), everyone], NOW) == everyone.started_at


# ---------------------------------------------------------------- the projection

OFFICE = UsualHours("Europe/Stockholm", 14, ((9 * 60, 18 * 60),), ())


def test_the_day_projects_repeats_in_the_on_hours_and_tomorrow_starts_full_on_wake():
    runs = [run(FULL, 1, 40)]  # 09:00 today
    upcoming = project_upcoming(runs, now=NOW, rules=RULES, turned_on=None,
                                usual=OFFICE, on_now=True)
    local = [(item.at.astimezone(STOCKHOLM).strftime("%a %H:%M"), item.kind, item.on_wake)
             for item in upcoming]
    # 15:00 quick; 21:00 falls after hours, so it runs Thursday when the computer comes on.
    assert local == [("Wed 15:00", QUICK, False), ("Thu 09:00", FULL, True)]


def test_a_saturday_off_moves_the_next_run_to_monday():
    friday = datetime(2026, 10, 9, 16, 0, tzinfo=STOCKHOLM).astimezone(UTC)
    runs = [PlanRunView(QUICK, friday - timedelta(hours=1), friday - timedelta(minutes=45), 900, 1000, "ok"),
            PlanRunView(FULL, friday - timedelta(hours=7), friday - timedelta(hours=6), 1000, 1000, "ok")]
    upcoming = project_upcoming(runs, now=friday, rules=RULES, turned_on=None,
                                usual=OFFICE, on_now=True,
                                horizon=timedelta(days=4))
    assert [(item.at.astimezone(STOCKHOLM).strftime("%a %H:%M"), item.kind) for item in upcoming][:1] == [
        ("Mon 09:00", FULL)
    ]


def test_a_run_due_now_stays_now_while_on_and_a_running_one_comes_first():
    due = project_upcoming([run(FULL, 21), run(QUICK, 7)], now=NOW, rules=RULES, turned_on=None,
                                usual=OFFICE,
                           on_now=True)
    assert (due[0].at, due[0].kind) == (NOW, FULL)

    running = project_upcoming([run(FULL, 30), run(QUICK, 0.2, None)], now=NOW, rules=RULES, turned_on=None,
                                usual=OFFICE,
                               on_now=True)
    assert running[0].running and running[0].kind == QUICK
    assert running[0].at == NOW - timedelta(hours=0.2)


def test_unknown_hours_never_move_a_run():
    learning = UsualHours("Europe/Stockholm", 2, None, None)
    upcoming = project_upcoming([run(FULL, 1)], now=NOW, rules=RULES, turned_on=None,
                                usual=learning, on_now=True)
    assert [item.at for item in upcoming] == [NOW + timedelta(hours=5), NOW + timedelta(hours=11),
                                              NOW + timedelta(hours=17), NOW + timedelta(hours=23)]
    assert [item.kind for item in upcoming] == [QUICK, QUICK, QUICK, FULL]


def test_run_lengths_are_measured_medians_and_a_guess_until_measured():
    runs = [run(FULL, 30, 38), run(FULL, 50, 44), run(FULL, 70, 41), run(QUICK, 6, 9),
            run(QUICK, 12, 300, outcome="failed"), run(MANUAL, 8, 3, companies=3)]
    durations = run_durations(runs)
    assert durations[FULL] == (41 * 60, False)
    assert durations[QUICK] == (9 * 60, False)
    assert run_durations([])[QUICK] == (int(plan.QUICK_ESTIMATE.total_seconds()), True)


# --------------------------------------------------------------- the dispatcher


async def _everyone_read(scratch_scope, at: datetime) -> None:
    """Seed the schedule rows (a tick does), then mark every company read at `at`."""
    from tracker.workflows import scheduler

    await scheduler.plan_tick(at)
    async with scratch_scope() as session:
        await session.execute(update(SyncScheduleState).values(
            last_outcome="ok", last_reconcile_at=at, last_discovery_at=at,
            next_reconcile_at=at + timedelta(hours=24), next_discovery_at=at + timedelta(hours=6),
        ))


async def _recorded_reads(scratch_scope, at: datetime, work, *, deferred=()) -> None:
    """The per-company rows a scan run writes for `work`, finished at `at`:
    a company in `deferred` is one its lane never started."""
    from tracker.db.models import ScrapeRun, ScrapeSourceRun

    async with scratch_scope() as session:
        scan = ScrapeRun(started_at=at, status="ok")
        session.add(scan)
        await session.flush()
        for item in work:
            stats = {"deferred_reason": "no job site accepted a connection"} if item.company_slug in deferred else {}
            session.add(ScrapeSourceRun(
                run_id=scan.id, binding_id=item.binding_id, company_slug=item.company_slug,
                provider_key=item.provider_key, scan_mode="reconcile",
                outcome="unattempted" if stats else "ok", started_at=at, finished_at=at, stats=stats,
            ))


async def _seeded_counts(scratch_scope) -> dict[str, int]:
    from sqlalchemy import func

    from tracker.db.models import ProviderPressureState, SourceBinding, TrackedCompany

    async with scratch_scope() as session:
        return {
            model.__name__: await session.scalar(select(func.count()).select_from(model))
            for model in (TrackedCompany, SourceBinding, SyncScheduleState, ProviderPressureState)
        }


@pytest.mark.asyncio
async def test_a_dry_run_plans_from_the_seeding_and_writes_none_of_it(scratch_scope):
    """A rehearsal from a branch with another catalog or cadence must leave the
    database it reaches as it found it, and still say what a real tick would do."""
    from tracker.workflows import scheduler

    empty = await _seeded_counts(scratch_scope)
    dry = await scheduler.run_once(dry_run=True)
    assert dry["reason"] == "dry_run"
    assert dry["work"], "a dry run plans from the built-ins it would seed"
    assert await _seeded_counts(scratch_scope) == empty

    real = await scheduler.plan_tick()
    assert [item.company_slug for item in real.work] == [item["company"] for item in dry["work"]]
    seeded = await _seeded_counts(scratch_scope)
    assert seeded["SourceBinding"] > empty["SourceBinding"] and seeded["SyncScheduleState"] > 0


@pytest.mark.asyncio
async def test_the_plan_reads_the_whole_roster_once_then_only_pinned_work_until_the_repeat(scratch_scope):
    from tracker.workflows import scheduler

    first = await scheduler.plan_tick(NOW - timedelta(days=2))
    assert first.plan_kind == MANUAL, "a never-scanned roster is still the first-scan drain"
    await _everyone_read(scratch_scope, NOW - timedelta(days=2))

    tick = await scheduler.plan_tick(NOW)
    async with scratch_scope() as session:
        targets = await scheduler.get_active_targets(session)
    assert tick.plan_kind == FULL
    assert {item.company_slug for item in tick.work} == {
        slug for slug, cfg in targets.items() if cfg["adapter"] != "workday"
    }, "the whole automatic roster in one run, Workday left to the user"
    assert all(item.mode is ScanMode.RECONCILE for item in tick.work)
    assert tick.roster == len(tick.work)

    async with scratch_scope() as session:
        run_id = await plan.start_run(session, kind=FULL, now=NOW, companies=len(tick.work),
                                      roster=tick.roster)
    await _recorded_reads(scratch_scope, NOW + timedelta(minutes=20), tick.work)
    async with scratch_scope() as session:
        await plan.finish_run(session, run_id, now=NOW + timedelta(minutes=40), outcome="ok")

    # Every per-company deadline is overdue by now: the plan, not the timers, decides.
    later = await scheduler.plan_tick(NOW + timedelta(hours=3))
    assert (later.plan_kind, later.work) == (None, [])

    repeat = await scheduler.plan_tick(NOW + timedelta(hours=6))
    assert repeat.plan_kind == QUICK
    async with scratch_scope() as session:
        discovery = set((await session.scalars(
            select(SyncScheduleState.binding_id).where(SyncScheduleState.discovery_enabled)
        )).all())
    assert {item.binding_id for item in repeat.work} <= discovery
    assert all(item.mode is ScanMode.DISCOVERY for item in repeat.work)


@pytest.mark.asyncio
async def test_a_pinned_deadline_is_still_served_between_plan_runs(scratch_scope):
    from tracker.workflows import scheduler

    await _everyone_read(scratch_scope, NOW - timedelta(hours=1))
    async with scratch_scope() as session:
        await plan.start_run(session, kind=FULL, now=NOW - timedelta(hours=1), companies=9, roster=9)
        await session.execute(update(SchedulePlanRun).values(
            finished_at=NOW - timedelta(minutes=20), outcome="ok"))
        pinned = await session.scalar(select(SyncScheduleState).limit(1))
        pinned.reconcile_anchor_minute = 9 * 60
        pinned.schedule_timezone = "Europe/Stockholm"
        pinned.next_reconcile_at = NOW - timedelta(minutes=5)
        pinned_id = pinned.binding_id
        other = await session.scalar(
            select(SyncScheduleState).where(SyncScheduleState.binding_id != pinned_id).limit(1))
        other.next_reconcile_at = NOW - timedelta(minutes=5)

    tick = await scheduler.plan_tick(NOW)
    assert tick.plan_kind is None
    assert [item.binding_id for item in tick.work] == [pinned_id], "only the pinned one"


@pytest.mark.asyncio
async def test_with_the_plan_off_the_timers_and_their_shards_come_back(scratch_scope, monkeypatch):
    from tracker.config import get_settings
    from tracker.workflows import scheduler

    monkeypatch.setattr(get_settings(), "sync_schedule_plan_enabled", False)
    monkeypatch.setattr(get_settings(), "sync_scheduler_max_bindings", 2)
    await _everyone_read(scratch_scope, NOW - timedelta(days=2))

    tick = await scheduler.plan_tick(NOW)
    assert tick.plan_kind is None
    assert 0 < len(tick.work) <= 2


# ---------------------------------------------------------------- awake samples


@pytest.mark.asyncio
async def test_a_dark_wake_is_not_recorded_and_the_first_sample_seeds_the_week(db_session):
    dark = await plan.note_awake(db_session, now=NOW, read_power=lambda: Power(True, False),
                                 read_log=lambda: PMSET_LOG)
    assert dark is False
    assert (await db_session.scalars(select(MachineAwakeSample))).all() == []

    now = datetime(2026, 9, 30, 9, 30, tzinfo=STOCKHOLM).astimezone(UTC)
    assert await plan.note_awake(db_session, now=now, read_power=lambda: Power(False, True),
                                 read_log=lambda: PMSET_LOG)
    rows = (await db_session.scalars(select(MachineAwakeSample))).all()
    sources = {row.source for row in rows}
    assert sources == {"pmset", "tick"}
    seeded = [row.seen_at for row in rows if row.source == "pmset"]
    # 19:51 to 06:25 + 16:31 to 18:00 + 08:00 to 09:30, a sample per ten minutes.
    assert len(seeded) == 64 + 9 + 9

    def never():
        raise AssertionError("the log is read once, when there is no history")

    assert await plan.note_awake(db_session, now=now + timedelta(minutes=10),
                                 read_power=lambda: Power(False, False), read_log=never)


# ----------------------------------------------------------------------- the API


@pytest.mark.asyncio
async def test_a_continuation_is_served_as_the_full_read_it_continues(api_client, db_session, no_escape):
    await plan.start_run(db_session, kind=CONTINUE, now=datetime.now(UTC), companies=3, roster=40)
    await db_session.commit()

    last = (await api_client.get("/api/schedule")).json()["plan"]["last_run"]

    assert (last["kind"], last["manual"], last["companies"]) == (FULL, False, 3)


@pytest.mark.asyncio
async def test_the_schedule_serves_the_plan_and_a_repeat_change_is_stored(api_client, db_session, no_escape):
    response = await api_client.get("/api/schedule", params={"tz": "Europe/Stockholm"})
    assert response.status_code == 200
    body = response.json()["plan"]
    assert body["enabled"] is True
    assert (body["repeat_hours"], body["repeat_choices"]) == (6, [2, 3, 6, 12])
    assert body["usual"]["timezone"] == "Europe/Stockholm"
    assert body["usual"]["learning"] is True
    assert body["upcoming"][0]["kind"] == FULL, "nothing has run: a full read is due"

    changed = await api_client.put("/api/schedule/plan", json={"repeat_hours": 3},
                                   params={"tz": "Europe/Stockholm"})
    assert changed.status_code == 200
    assert changed.json()["plan"]["repeat_hours"] == 3
    assert (await api_client.get("/api/schedule")).json()["plan"]["repeat_hours"] == 3


@pytest.mark.asyncio
async def test_a_repeat_off_the_menu_or_an_unknown_zone_is_refused(api_client, no_escape):
    assert (await api_client.put("/api/schedule/plan", json={"repeat_hours": 5})).status_code == 422
    assert (await api_client.get("/api/schedule", params={"tz": "Mars/Olympus"})).status_code == 422
    assert (await api_client.get("/api/schedule")).json()["plan"]["repeat_hours"] == 6


# ------------------------------------------------------------------ the tick


def test_a_tick_samples_and_runs_in_one_event_loop(monkeypatch, tmp_path):
    """The engine's pooled connections belong to the loop that opened them, so
    the awake sample and the run must share one. Two `asyncio.run` calls in
    `main()` would break every tick ("attached to a different loop")."""
    import asyncio
    import contextlib
    import sys

    from tracker.workflows import scheduler

    loops: dict[str, object] = {}

    async def sampled():
        loops["sample"] = asyncio.get_running_loop()

    async def ran(*, dry_run):
        loops["run"] = asyncio.get_running_loop()
        return {"ran": False, "work": [], "reason": "nothing due"}

    monkeypatch.setattr(scheduler, "note_awake", sampled)
    monkeypatch.setattr(scheduler, "run_once", ran)
    async def plugins():
        loops["plugins"] = asyncio.get_running_loop()
        return {"started": [], "waiting": None}

    monkeypatch.setattr(scheduler, "run_lock", lambda _path: contextlib.nullcontext())
    monkeypatch.setattr(scheduler, "enable_shared_pacing", lambda _path: None)
    monkeypatch.setattr(sys, "argv", ["tracker.scheduler"])

    scheduler.main(after_lock=[("plugins", plugins)])

    assert set(loops) == {"sample", "run", "plugins"}
    assert loops["plugins"] is loops["run"]
    assert loops["sample"] is loops["run"]


# ------------------------------------------------------------- the user's choices


def test_a_pause_holds_every_planned_scan_until_it_ends():
    paused = plan.rules_for(repeat=REPEAT, full_after=FULL_AFTER, zone=STOCKHOLM,
                            paused_until=NOW + timedelta(hours=1))
    assert decide([], rules=paused) is None, "not even the first full read"
    assert decide([run(FULL, 30)], rules=paused, turned_on=NOW - timedelta(minutes=2)) is None
    assert decide([run(FULL, 30)], rules=paused, now=NOW + timedelta(hours=1)) == FULL


def test_a_day_off_runs_nothing_and_the_next_scan_day_starts_with_a_full_read():
    # NOW is a Wednesday (2); a plan for Monday, Tuesday and Thursday.
    days = plan.rules_for(repeat=REPEAT, full_after=FULL_AFTER, zone=STOCKHOLM, days=[0, 1, 3])
    assert decide([run(FULL, 30)], rules=days) is None
    assert decide([run(FULL, 30)], rules=days, turned_on=NOW - timedelta(minutes=5)) is None
    upcoming = project_upcoming([run(FULL, 3)], now=NOW, rules=days, turned_on=None,
                                usual=OFFICE, on_now=True)
    first = upcoming[0]
    assert first.at.astimezone(STOCKHOLM).strftime("%a %H:%M") == "Thu 09:00"
    assert first.kind == FULL


def test_ready_by_starts_the_daily_full_read_so_it_is_done_in_time():
    # Done by 09:00, a full read measured at 40 min: start 08:10 (with the margin).
    ready = plan.rules_for(repeat=REPEAT, full_after=FULL_AFTER, zone=STOCKHOLM,
                           ready_by_minute=9 * 60, full_seconds=40 * 60)
    eight = datetime(2026, 10, 7, 8, 10, tzinfo=STOCKHOLM).astimezone(UTC)
    runs = [run(FULL, 14), run(QUICK, 5)]  # yesterday 20:00's full; 05:00's quick, next due 11:00
    assert decide(runs, rules=ready, now=eight - timedelta(minutes=1)) is None
    assert decide(runs, rules=ready, now=eight) == FULL
    done = runs + [PlanRunView(FULL, eight, eight + timedelta(minutes=40), 1000, 1000, "ok")]
    assert decide(done, rules=ready, now=eight + timedelta(hours=1)) is None, "once a day"


def test_a_full_read_still_reading_at_the_ready_by_start_is_that_days_full_read():
    """A Scan now over every company began 20 min before the 08:10 start and
    finished at 08:30. Starting the ready-by read when it ends would read every
    company twice in a row, and the second hour of reading is the one a
    background pass beside it can push past the run's bound."""
    from tracker.workflows.schedule_plan import MANUAL

    ready = plan.rules_for(repeat=REPEAT, full_after=FULL_AFTER, zone=STOCKHOLM,
                           ready_by_minute=9 * 60, full_seconds=40 * 60)
    start = datetime(2026, 10, 7, 8, 10, tzinfo=STOCKHOLM).astimezone(UTC)
    after = start + timedelta(minutes=30)
    yesterday = [run(FULL, 14)]

    def scan_now(began: datetime) -> PlanRunView:
        return PlanRunView(MANUAL, began, began + timedelta(minutes=40), 1000, 1000, "ok")

    overlapping = [*yesterday, scan_now(start - timedelta(minutes=20))]
    assert decide(overlapping, rules=ready, now=after) is None
    upcoming = project_upcoming(overlapping, now=after, rules=ready, turned_on=None,
                                usual=OFFICE, on_now=True)
    assert not any(item.ready_by and item.at < start + timedelta(hours=12) for item in upcoming)
    # The negative control: one that ended long before the start is not today's read.
    early = [*yesterday, scan_now(start - timedelta(hours=2))]
    assert decide(early, rules=ready, now=after) == FULL


def test_with_ready_by_the_20h_rule_no_longer_adds_a_second_daily_full_read():
    ready = plan.rules_for(repeat=timedelta(hours=2), full_after=FULL_AFTER, zone=STOCKHOLM,
                           ready_by_minute=9 * 60, full_seconds=40 * 60)
    # 05:00: the last full read was 21 h ago, but today's ready-by full is at 08:10.
    five = datetime(2026, 10, 7, 5, 0, tzinfo=STOCKHOLM).astimezone(UTC)
    runs = [PlanRunView(FULL, five - timedelta(hours=21), five - timedelta(hours=20), 1000, 1000, "ok"),
            PlanRunView(QUICK, five - timedelta(hours=2), five - timedelta(hours=2) + timedelta(minutes=9),
                        900, 1000, "ok")]
    assert decide(runs, rules=ready, now=five) == QUICK
    plain = plan.rules_for(repeat=timedelta(hours=2), full_after=FULL_AFTER, zone=STOCKHOLM)
    assert decide(runs, rules=plain, now=five) == FULL, "the negative control: without ready-by it is full"


def test_without_a_time_of_your_own_ready_by_is_the_usual_start_and_all_day_has_none():
    usual = UsualHours("Europe/Stockholm", 14, ((8 * 60 + 30, 18 * 60),), ((10 * 60, 16 * 60),))
    rules = plan.rules_for(repeat=REPEAT, full_after=FULL_AFTER, zone=STOCKHOLM, usual=usual)
    assert rules.ready_by == (510, 510, 510, 510, 510, 600, 600)
    own = plan.rules_for(repeat=REPEAT, full_after=FULL_AFTER, zone=STOCKHOLM, usual=usual,
                         ready_by_minute=7 * 60)
    assert set(own.ready_by) == {420}
    always = UsualHours("Europe/Stockholm", 14, ((0, 1440),), ((0, 1440),))
    assert plan.rules_for(repeat=REPEAT, full_after=FULL_AFTER, zone=STOCKHOLM,
                          usual=always).ready_by == (None,) * 7
    learning = UsualHours("Europe/Stockholm", 2, None, None)
    assert plan.rules_for(repeat=REPEAT, full_after=FULL_AFTER, zone=STOCKHOLM,
                          usual=learning).ready_by == (None,) * 7


def test_the_projection_places_tomorrows_ready_by_full_read_before_its_repeat():
    ready = plan.rules_for(repeat=REPEAT, full_after=FULL_AFTER, zone=STOCKHOLM,
                           ready_by_minute=9 * 60, full_seconds=40 * 60)
    upcoming = project_upcoming([run(FULL, 1, 40)], now=NOW, rules=ready, turned_on=None,
                                usual=UsualHours("Europe/Stockholm", 14, ((0, 1440),), ((0, 1440),)),
                                on_now=True)
    local = [(item.at.astimezone(STOCKHOLM).strftime("%a %H:%M"), item.kind, item.ready_by)
             for item in upcoming]
    assert local == [("Wed 15:00", QUICK, False), ("Wed 21:00", QUICK, False),
                     ("Thu 03:00", QUICK, False), ("Thu 08:10", FULL, True)]


def test_a_pause_moves_the_projection_to_where_it_ends():
    paused = plan.rules_for(repeat=REPEAT, full_after=FULL_AFTER, zone=STOCKHOLM,
                            paused_until=NOW + timedelta(hours=8))
    upcoming = project_upcoming([run(FULL, 21), run(QUICK, 7)], now=NOW, rules=paused,
                                turned_on=None, usual=UsualHours("Europe/Stockholm", 2, None, None),
                                on_now=True)
    assert upcoming[0].at == NOW + timedelta(hours=8)


def test_the_machines_zone_is_read_from_its_localtime_link():
    from tracker.platform.local_zone import zone_name_from_link

    assert zone_name_from_link("/var/db/timezone/zoneinfo/Europe/Stockholm") == "Europe/Stockholm"
    assert zone_name_from_link("/usr/share/zoneinfo/America/New_York") == "America/New_York"
    assert zone_name_from_link("/etc/somewhere") is None
    assert zone_name_from_link(None) is None


@pytest.mark.asyncio
async def test_a_paused_plan_holds_pinned_work_too(scratch_scope):
    from tracker.settings_store import SchedulePlanSettings, set_schedule_plan_settings
    from tracker.workflows import scheduler

    await _everyone_read(scratch_scope, NOW - timedelta(hours=1))
    async with scratch_scope() as session:
        pinned = await session.scalar(select(SyncScheduleState).limit(1))
        pinned.reconcile_anchor_minute = 9 * 60
        pinned.next_reconcile_at = NOW - timedelta(minutes=5)
        await set_schedule_plan_settings(
            session, SchedulePlanSettings(paused_until=NOW + timedelta(hours=1)))

    assert (await scheduler.plan_tick(NOW)).work == []
    later = await scheduler.plan_tick(NOW + timedelta(hours=1, minutes=1))
    assert later.plan_kind == FULL, "the pause over, the plan's first full read"


@pytest.mark.asyncio
async def test_mains_only_holds_a_planned_run_on_battery(monkeypatch):
    from tracker.platform.power import WAITING_FOR_MAINS
    from tracker.workflows import scheduler
    from tracker.workflows.scheduler import DueWork

    item = DueWork(1, "acme", "greenhouse", ScanMode.RECONCILE, NOW)
    started: list = []

    async def planned(_now, **_):
        return scheduler.TickPlan([item], FULL, 1, wait_for_mains=True)

    async def mark(work, _now):
        started.extend(work)

    async def nothing_left_open(_now):
        return None

    monkeypatch.setattr(scheduler, "close_runs_left_open", nothing_left_open)
    monkeypatch.setattr(scheduler, "plan_tick", planned)
    monkeypatch.setattr(scheduler, "_mark_started", mark)
    monkeypatch.setattr(scheduler.host_power, "read_power", lambda: Power(False, True))
    result = await scheduler.run_once()
    assert (result["ran"], result["reason"]) == (False, WAITING_FOR_MAINS)
    assert started == []


#: A Saturday, 10:00 in Stockholm: outside a Monday-to-Friday plan.
SATURDAY = datetime(2026, 10, 10, 10, 0, tzinfo=STOCKHOLM).astimezone(UTC)


def _pin_ops_clock(monkeypatch, at: datetime) -> None:
    """`datetime.now` in the ops router answers `at`, so a plan's days are
    read against a known weekday rather than the day the suite runs."""
    import tracker.api.routers.ops as ops

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at if tz is not None else at.replace(tzinfo=None)

    monkeypatch.setattr(ops, "datetime", _Clock)


@pytest.mark.asyncio
@pytest.mark.parametrize(("at", "waiting_after_resume"), [(NOW, None), (SATURDAY, "day_off")],
                         ids=["weekday", "saturday"])
async def test_plan_choices_change_one_key_at_a_time_and_ready_by_null_clears(
        api_client, no_escape, monkeypatch, at, waiting_after_resume):
    _pin_ops_clock(monkeypatch, at)
    tz = {"tz": "Europe/Stockholm"}
    body = (await api_client.put("/api/schedule/plan", json={"ready_by_minute": 510}, params=tz)).json()
    plan_body = body["plan"]
    assert plan_body["ready_by_minute"] == 510
    assert plan_body["ready_by_today"] == {"minute": 510, "source": "set"}
    assert plan_body["repeat_hours"] == 6, "untouched"

    body = (await api_client.put("/api/schedule/plan", json={"days": [0, 1, 2, 3, 4], "mains_only": True},
                                 params=tz)).json()["plan"]
    assert (body["days"], body["mains_only"], body["ready_by_minute"]) == ([0, 1, 2, 3, 4], True, 510)

    body = (await api_client.put("/api/schedule/plan", json={"ready_by_minute": None}, params=tz)).json()["plan"]
    assert body["ready_by_minute"] is None

    paused = (await api_client.put("/api/schedule/plan", json={"pause": "3h"}, params=tz)).json()["plan"]
    assert paused["waiting"] == "paused" and paused["paused_until"] is not None
    tomorrow = (await api_client.put("/api/schedule/plan", json={"pause": "tomorrow"}, params=tz)).json()["plan"]
    until = datetime.fromisoformat(tomorrow["paused_until"].replace("Z", "+00:00")).astimezone(STOCKHOLM)
    assert until.strftime("%H:%M") == "08:00", "while learning, tomorrow starts at 08:00"
    resumed = (await api_client.put("/api/schedule/plan", json={"pause": "resume"}, params=tz)).json()["plan"]
    # Resumed, nothing is paused; a Saturday is still outside Monday to Friday.
    assert (resumed["waiting"], resumed["paused_until"]) == (waiting_after_resume, None)


@pytest.mark.asyncio
async def test_no_days_or_an_unknown_pause_is_refused(api_client, no_escape):
    assert (await api_client.put("/api/schedule/plan", json={"days": []})).status_code == 422
    assert (await api_client.put("/api/schedule/plan", json={"days": [7]})).status_code == 422
    assert (await api_client.put("/api/schedule/plan", json={"pause": "forever"})).status_code == 422
    assert (await api_client.put("/api/schedule/plan", json={"color": "red"})).status_code == 422


@pytest.mark.asyncio
async def test_two_overlapping_saves_of_different_choices_both_survive(api_client, db_session):
    """Each save sends only the choice it changes, and the plan is one row. A
    save of another choice that starts while the first is still open waits for
    it and builds on what it committed, so it never writes the first choice
    back as it was (two tabs, or two controls on one screen)."""
    import asyncio

    from tests.barriers import until_waiting
    from tracker.settings_store import update_schedule_plan_settings

    await update_schedule_plan_settings(db_session, repeat_hours=3)
    second = asyncio.create_task(api_client.put("/api/schedule/plan", json={"mains_only": True}))
    try:
        await until_waiting(db_session.bind, second)
        assert not second.done(), "the second save waits for the open one"
        await db_session.commit()
        response = await second
    finally:
        second.cancel()

    assert response.status_code == 200, response.text
    answered = response.json()["plan"]
    assert (answered["repeat_hours"], answered["mains_only"]) == (3, True)
    stored = (await api_client.get("/api/schedule")).json()["plan"]
    assert (stored["repeat_hours"], stored["mains_only"]) == (3, True), "both choices are kept"


@pytest.mark.asyncio
async def test_a_workday_company_says_it_waits_for_you(api_client, db_session, no_escape):
    """No timer takes Workday companies, so the screen must not call them
    "Scheduled": the binding carries the scheduler's own reason."""
    from tests.ops_contract_seed import _binding, _company

    db_session.add_all([_company("acme-wd", "Acme", "workday"), _company("beta-gh", "Beta", "greenhouse")])
    await db_session.flush()
    db_session.add_all([_binding("acme-wd", "workday"), _binding("beta-gh", "greenhouse")])
    await db_session.commit()

    body = (await api_client.get("/api/schedule")).json()
    by_company = {row["company"]: row for row in body["bindings"]}
    assert by_company["acme-wd"]["waits_for_user"] == "user_directed"
    assert by_company["beta-gh"]["waits_for_user"] is None


# --------------------------------------------- quick scans at fixed clock times


ANCHORED = plan.rules_for(repeat=REPEAT, full_after=FULL_AFTER, zone=STOCKHOLM, repeat_anchor_minute=9 * 60)


def at_local(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 7, hour, minute, tzinfo=STOCKHOLM).astimezone(UTC)


def test_dragging_a_quick_scan_puts_every_repeat_on_its_clock_time():
    # Slots 03:00, 09:00, 15:00, 21:00. Last quick scan 05:00, full 20:00 yesterday.
    runs = [PlanRunView(FULL, at_local(20) - timedelta(days=1), at_local(20, 40) - timedelta(days=1), 1000, 1000, "ok"),
            PlanRunView(QUICK, at_local(5), at_local(5, 10), 900, 1000, "ok")]
    assert decide(runs, rules=ANCHORED, now=at_local(8, 59)) is None
    assert decide(runs, rules=ANCHORED, now=at_local(9)) == QUICK
    plain = plan.rules_for(repeat=REPEAT, full_after=FULL_AFTER, zone=STOCKHOLM)
    assert decide(runs, rules=plain, now=at_local(9)) is None, "the control: unanchored waits until 11:00"


def test_a_scan_just_before_a_slot_makes_that_slot_redundant():
    wake = [PlanRunView(FULL, at_local(8, 50), at_local(9, 30), 1000, 1000, "ok")]
    assert decide(wake, rules=ANCHORED, now=at_local(9, 5)) is None
    assert decide(wake, rules=ANCHORED, now=at_local(11, 55)) is None, "never off the slot"
    assert decide(wake, rules=ANCHORED, now=at_local(15)) == QUICK


def test_the_projection_walks_the_clock_times():
    runs = [PlanRunView(FULL, at_local(8, 50), at_local(9, 30), 1000, 1000, "ok")]
    upcoming = project_upcoming(runs, now=at_local(10), rules=ANCHORED, turned_on=None,
                                usual=UsualHours("Europe/Stockholm", 2, None, None), on_now=True)
    assert [item.at.astimezone(STOCKHOLM).strftime("%H:%M") for item in upcoming] == [
        "15:00", "21:00", "03:00", "09:00",
    ]


@pytest.mark.asyncio
async def test_a_clock_time_for_the_quick_scans_is_saved_and_null_returns_to_repeats(api_client):
    tz = {"tz": "Europe/Stockholm"}
    body = (await api_client.put("/api/schedule/plan", json={"repeat_anchor_minute": 540}, params=tz)).json()
    assert body["plan"]["repeat_anchor_minute"] == 540
    body = (await api_client.put("/api/schedule/plan", json={"repeat_hours": 3}, params=tz)).json()
    assert (body["plan"]["repeat_anchor_minute"], body["plan"]["repeat_hours"]) == (540, 3)
    body = (await api_client.put("/api/schedule/plan", json={"repeat_anchor_minute": None}, params=tz)).json()
    assert body["plan"]["repeat_anchor_minute"] is None


@pytest.mark.asyncio
async def test_an_interrupted_full_read_continues_with_exactly_the_companies_it_did_not_read(scratch_scope):
    """A quit half way through a full read: the next tick reads the companies
    it never reached and the one its lane deferred, not the whole roster, and
    once they are read the plan goes back to its repeat."""
    from tracker.workflows import scheduler

    await _everyone_read(scratch_scope, NOW - timedelta(days=2))
    full = await scheduler.plan_tick(NOW)
    assert full.plan_kind == FULL and len(full.work) > 4
    async with scratch_scope() as session:
        await plan.start_run(session, kind=FULL, now=NOW, companies=len(full.work), roster=full.roster)
    half = full.work[: len(full.work) // 2]
    deferred = half[0].company_slug
    await _recorded_reads(scratch_scope, NOW + timedelta(minutes=10), half, deferred={deferred})
    async with scratch_scope() as session:
        assert await plan.close_unfinished_runs(session, now=NOW + timedelta(minutes=30)) == 1

    rest = await scheduler.plan_tick(NOW + timedelta(minutes=40))

    assert rest.plan_kind == CONTINUE
    assert {item.company_slug for item in rest.work} == (
        {item.company_slug for item in full.work[len(half):]} | {deferred}
    )
    assert rest.roster == full.roster
    async with scratch_scope() as session:
        run_id = await plan.start_run(session, kind=CONTINUE, now=NOW + timedelta(minutes=40),
                                      companies=len(rest.work), roster=rest.roster)
    await _recorded_reads(scratch_scope, NOW + timedelta(minutes=60), rest.work)
    async with scratch_scope() as session:
        await plan.finish_run(session, run_id, now=NOW + timedelta(minutes=61), outcome="ok")

    later = await scheduler.plan_tick(NOW + timedelta(hours=3))
    assert (later.plan_kind, later.work) == (None, []), "finished: no second full read, no more continuing"


@pytest.mark.asyncio
async def test_a_company_never_read_leads_the_full_read(scratch_scope):
    """A company whose reads never got through has no last read: it is the
    oldest of all, not the newest."""
    from tracker.workflows import scheduler

    await _everyone_read(scratch_scope, NOW - timedelta(days=2))
    async with scratch_scope() as session:
        row = (await session.scalars(
            select(SyncScheduleState).order_by(SyncScheduleState.binding_id.desc()).limit(1)
        )).one()
        row.last_reconcile_at = None
        row.last_outcome = "failed"
        unread = row.binding_id

    tick = await scheduler.plan_tick(NOW)

    assert tick.plan_kind == FULL
    assert tick.work[0].binding_id == unread
