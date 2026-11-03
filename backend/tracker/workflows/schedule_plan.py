"""The schedule plan: every company read on one clock.

A timer per company, restarted from whenever it was last read, stops being a
schedule at a few hundred companies: reads bunch into waves that take hours to
clear, and the dial's marks become side effects of when reads happened to
finish. The plan is one clock the user can read:

* **A full read when the computer comes on.** A tick that finds the machine
  awake after `schedule_plan_wake_gap_minutes` off starts a full read of every
  company at once (the Scan now path, one run, a lane per host). Also when the
  last full read of the whole roster is `schedule_plan_full_after_hours` old,
  so a machine that never sleeps still gets one a day.
* **A quick check on each repeat** (`settings_store` repeat, default 6h) while
  the computer is on: every company's discovery probe in one run.
* **Missed runs are not replayed.** A machine asleep through three repeats runs
  once when it wakes.
* **A full read is finished, not started over.** While the newest full read is
  the current one, the companies it has not read yet (a quit, a crash or an
  update stopped it, or a lane lost the network) are read by a continuation.

A company the user pinned to a time keeps it (the dispatcher still serves
pinned deadlines in shards). Nothing here asks the user when the computer is
on: every scheduler tick in a full wake leaves a `machine_awake_samples` row,
seeded once from `pmset -g log`, and `usual_hours` learns the pattern.

The pure half (stretches, usual hours, the decision, the projection) takes the
clock and the rows as arguments; the DB half reads and writes the two tables.
This module imports neither the dispatcher nor the router: `scheduler.py` and
`schedule_status.py` both import it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from statistics import median
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import Settings
from tracker.db.models import MachineAwakeSample, SchedulePlanRun, ScrapeSourceRun
from tracker.platform import power as host_power
from tracker.platform.local_zone import local_zone
from tracker.settings_store import SchedulePlanSettings

FULL = "full"
QUICK = "quick"
MANUAL = "manual"
#: The companies the current full read has not read yet.
CONTINUE = "continue"

#: A run's process ended before the run did (`close_unfinished_runs`).
INTERRUPTED = "interrupted"
FAILED = "failed"

#: A sample stands for this much time after it: the scheduler ticks every 10 min.
SAMPLE_SPAN = timedelta(minutes=10)
#: Two samples at most this far apart are one stretch of being on. Wider than a
#: tick so one late or skipped tick does not split a working day in two.
SAMPLE_JOIN_GAP = timedelta(minutes=25)
#: A run that failed is retried this soon, not a whole repeat later; so are the
#: companies a finished full read left unread.
FAILED_RETRY = timedelta(minutes=30)
#: A user scan moves the plan's clock only if it read nearly everyone.
ROSTER_SHARE = 0.9

#: Learning the usual hours.
BUCKET_MINUTES = 15
LEARN_WINDOW_DAYS = 28
HALF_LIFE_DAYS = 7.0
#: Whole days observed before the pattern is shown as known.
NEEDED_DAYS = 5
#: A quarter hour is "usually on" when the machine was on in it on at least
#: this (recency-weighted) share of the days observed.
ON_SHARE = 0.5
#: Off gaps this short inside a day are bridged; on runs this short are noise.
MERGE_GAP_BUCKETS = 2
MIN_RUN_BUCKETS = 2

#: Run lengths before there is a measured one, and how many to take a median of.
FULL_ESTIMATE = timedelta(minutes=45)
QUICK_ESTIMATE = timedelta(minutes=15)
DURATION_SAMPLE = 5


# --------------------------------------------------------------------------- pure


@dataclass(frozen=True)
class PlanRunView:
    kind: str
    started_at: datetime
    finished_at: datetime | None
    companies: int
    roster: int
    outcome: str | None

    @property
    def covers_roster(self) -> bool:
        """Read (nearly) every company: a planned run always means to; a user
        scan does only when it was the whole list, not a handful."""
        if self.kind != MANUAL:
            return True
        return self.roster > 0 and self.companies >= math.ceil(ROSTER_SHARE * self.roster)

    @property
    def is_full(self) -> bool:
        return self.kind == FULL or (self.kind == MANUAL and self.covers_roster)


def awake_stretches(samples: Iterable[datetime]) -> list[tuple[datetime, datetime]]:
    """Samples joined into stretches of being on, each ending a span after its last sample."""
    stretches: list[tuple[datetime, datetime]] = []
    for seen in sorted(samples):
        if stretches and seen - (stretches[-1][1] - SAMPLE_SPAN) <= SAMPLE_JOIN_GAP:
            stretches[-1] = (stretches[-1][0], seen + SAMPLE_SPAN)
        else:
            stretches.append((seen, seen + SAMPLE_SPAN))
    return stretches


def turned_on_at(
    stretches: Sequence[tuple[datetime, datetime]], *, now: datetime, gap: timedelta
) -> datetime | None:
    """When the computer was last turned on, if it is on now.

    The start of the stretch that reaches `now`, when the machine was seen off
    for at least `gap` before it. None when the machine is not seen on now, has
    been on without such a break, or has no history before this stretch (it may
    have been on all along; a first run is full anyway)."""
    if len(stretches) < 2:
        return None
    start, end = stretches[-1]
    if end + SAMPLE_JOIN_GAP < now:
        return None
    if start - stretches[-2][1] < gap:
        return None
    return start


@dataclass(frozen=True)
class UsualHours:
    """When the computer is usually on, learned from samples, in one zone."""

    timezone: str
    #: Whole local days the samples cover (at most `LEARN_WINDOW_DAYS`).
    observed_days: int
    #: Usually-on windows as (start, end) minutes of the local day, per day class.
    #: None = no day of that class observed yet.
    weekdays: tuple[tuple[int, int], ...] | None
    weekends: tuple[tuple[int, int], ...] | None

    @property
    def learning(self) -> bool:
        return self.observed_days < NEEDED_DAYS

    def windows_on(self, day: date) -> tuple[tuple[int, int], ...] | None:
        """The windows for a date, or None while learning or for an unseen class."""
        if self.learning:
            return None
        return self.weekends if day.weekday() >= 5 else self.weekdays


def _bucket_on(stretches: Sequence[tuple[datetime, datetime]], start: datetime, end: datetime) -> bool:
    """On for at least half the bucket."""
    covered = timedelta()
    for s, e in stretches:
        if e <= start or s >= end:
            continue
        covered += min(e, end) - max(s, start)
    return covered * 2 >= end - start


def _windows(on: Sequence[bool]) -> tuple[tuple[int, int], ...]:
    """Bucket flags to (start, end) minute windows, small gaps bridged, noise dropped."""
    flags = list(on)
    # Bridge short off gaps between two on runs.
    index = 0
    while index < len(flags):
        if not flags[index]:
            gap_end = index
            while gap_end < len(flags) and not flags[gap_end]:
                gap_end += 1
            if 0 < index and gap_end < len(flags) and gap_end - index <= MERGE_GAP_BUCKETS:
                for fill in range(index, gap_end):
                    flags[fill] = True
            index = gap_end
        else:
            index += 1
    windows: list[tuple[int, int]] = []
    index = 0
    while index < len(flags):
        if flags[index]:
            run_end = index
            while run_end < len(flags) and flags[run_end]:
                run_end += 1
            if run_end - index >= MIN_RUN_BUCKETS:
                windows.append((index * BUCKET_MINUTES, run_end * BUCKET_MINUTES))
            index = run_end
        else:
            index += 1
    return tuple(windows)


def usual_hours(
    stretches: Sequence[tuple[datetime, datetime]], *, now: datetime, zone: ZoneInfo
) -> UsualHours:
    """Learn the usual on-hours from whole local days, weekdays and weekends apart.

    Only whole days count: the first day sampling began is partial (nothing is
    known before its first sample) and today is not over. A day with no
    samples after sampling began is a real day off. Recent days weigh more
    (half-life `HALF_LIFE_DAYS`), so a new routine shows within days."""
    name = getattr(zone, "key", str(zone))
    if not stretches:
        return UsualHours(name, 0, None, None)
    first_day = stretches[0][0].astimezone(zone).date() + timedelta(days=1)
    today = now.astimezone(zone).date()
    first_day = max(first_day, today - timedelta(days=LEARN_WINDOW_DAYS))
    days = [first_day + timedelta(days=n) for n in range((today - first_day).days)]
    if not days:
        return UsualHours(name, 0, None, None)

    per_day = 24 * 60 // BUCKET_MINUTES
    sums = {False: [0.0] * per_day, True: [0.0] * per_day}
    weights = {False: 0.0, True: 0.0}
    for day in days:
        weekend = day.weekday() >= 5
        weight = 0.5 ** ((today - day).days / HALF_LIFE_DAYS)
        weights[weekend] += weight
        midnight = datetime.combine(day, time(), tzinfo=zone)
        day_stretches = [
            (s, e) for s, e in stretches
            if e > midnight and s < midnight + timedelta(days=1, hours=2)
        ]
        for bucket in range(per_day):
            # Aware arithmetic in one zone is wall-clock: a DST day is still 96
            # local quarter hours, and comparisons convert to UTC.
            start = midnight + timedelta(minutes=bucket * BUCKET_MINUTES)
            if day_stretches and _bucket_on(
                day_stretches, start, start + timedelta(minutes=BUCKET_MINUTES)
            ):
                sums[weekend][bucket] += weight

    def windows_for(weekend: bool) -> tuple[tuple[int, int], ...] | None:
        if weights[weekend] == 0:
            return None
        return _windows([value / weights[weekend] >= ON_SHARE for value in sums[weekend]])

    return UsualHours(name, len(days), windows_for(False), windows_for(True))


def _effective_runs(runs: Sequence[PlanRunView]) -> list[PlanRunView]:
    """Runs that hold the clock, newest first: not skipped, and (for a user
    scan) one that read the whole roster. A run without a finish is in
    progress however long it has run: one whose process ended is closed as
    interrupted by the next tick (`close_unfinished_runs`), never judged by
    its age."""
    kept = [
        run for run in runs
        if run.outcome != "skipped" and run.covers_roster
    ]
    return sorted(kept, key=lambda run: run.started_at, reverse=True)


def last_full_at(runs: Sequence[PlanRunView], now: datetime) -> datetime | None:
    """When the newest full read of the whole roster began. One that stopped
    before its end counts too: what it left is continued, not read again from
    the start."""
    for run in _effective_runs(runs):
        if run.is_full:
            return run.started_at
    return None


def continuation_start(runs: Sequence[PlanRunView], *, now: datetime, rules: PlanRules) -> datetime | None:
    """When the full read whose unread companies a tick may read now began, or None.

    The newest full read is continued while it is the current one (it began
    less than `daily_full_after` ago); whether any company is left is the
    caller's to read. After an interrupted run the next tick continues; after
    one that finished or failed, `FAILED_RETRY` later, so a network that stays
    down is asked again every half hour, not on every tick. Nothing while
    paused, on a day off, or while a run is in progress."""
    if rules.paused(now) or not rules.scan_day(now):
        return None
    effective = _effective_runs(runs)
    if not effective or any(run.finished_at is None for run in effective):
        return None
    full = next((run for run in effective if run.is_full), None)
    if full is None or now - full.started_at >= rules.daily_full_after:
        return None
    last = effective[0]
    if last.outcome != INTERRUPTED and last.finished_at is not None and now < last.finished_at + FAILED_RETRY:
        return None
    return full.started_at


#: A ready-by full scan starts this much earlier than its measured length, so
#: a scheduler tick (every 10 min) that lands just after the start still
#: finishes it in time.
READY_MARGIN = timedelta(minutes=10)
#: How long after its start a missed ready-by scan is still worth starting as
#: that day's ready-by scan. Later, the wake rule or the repeat takes over.
READY_GRACE = timedelta(hours=3)
#: With a ready-by time the daily full scan follows it, so the 20 h rule only
#: backstops a day the ready-by scan did not happen.
READY_FULL_AFTER = timedelta(hours=30)


@dataclass(frozen=True)
class PlanRules:
    """Everything the plan's decision and its projection read besides the runs.

    `ready_by`: per weekday (Monday = 0), the local minute the daily full scan
    should be finished by, or None. `days`: the weekdays planned scans run on.
    `paused_until`: no planned scan before it. `full_seconds`: how long a full
    scan takes, measured or the built-in guess."""

    repeat: timedelta
    full_after: timedelta
    zone: ZoneInfo
    days: frozenset[int] = frozenset(range(7))
    paused_until: datetime | None = None
    ready_by: tuple[int | None, ...] = (None,) * 7
    full_seconds: int = int(FULL_ESTIMATE.total_seconds())
    #: Quick scans at fixed clock times: this local minute plus whole repeats
    #: (set by dragging one on the dial). None = a repeat after the last scan.
    repeat_anchor: int | None = None

    def _slots(self, around: datetime) -> list[datetime]:
        """The anchored slots on the days around `around`, in order."""
        if self.repeat_anchor is None:
            return []
        step = max(1, int(self.repeat.total_seconds() // 60))
        minutes = sorted({(self.repeat_anchor + k * step) % (24 * 60) for k in range(24 * 60 // step + 1)})
        local = around.astimezone(self.zone).date()
        return [
            (datetime.combine(local + timedelta(days=offset), time(), tzinfo=self.zone)
             + timedelta(minutes=minute)).astimezone(UTC)
            for offset in (-1, 0, 1, 2)
            for minute in minutes
        ]

    def latest_slot(self, at: datetime) -> datetime | None:
        past = [slot for slot in self._slots(at) if slot <= at]
        return past[-1] if past else None

    def next_slot(self, after: datetime) -> datetime | None:
        ahead = [slot for slot in self._slots(after) if slot >= after]
        return ahead[0] if ahead else None

    def paused(self, at: datetime) -> bool:
        return self.paused_until is not None and at < self.paused_until

    def scan_day(self, at: datetime) -> bool:
        return at.astimezone(self.zone).weekday() in self.days

    @property
    def daily_full_after(self) -> timedelta:
        if any(minute is not None for minute in self.ready_by):
            return max(self.full_after, READY_FULL_AFTER)
        return self.full_after

    def ready_start(self, day: date) -> datetime | None:
        """When that day's ready-by full scan starts, or None: no ready-by time
        that day, or not a scan day."""
        minute = self.ready_by[day.weekday()]
        if minute is None or day.weekday() not in self.days:
            return None
        finish = datetime.combine(day, time(), tzinfo=self.zone) + timedelta(minutes=minute)
        return (finish - timedelta(seconds=self.full_seconds) - READY_MARGIN).astimezone(UTC)

    def ready_served(self, full: datetime | None, start: datetime) -> bool:
        """Whether the full read that began at `full` is the one the ready-by
        start `start` asks for: it began since, or within one full read's
        length before, so it was still reading at the start. Another full read
        then would only queue behind it and read every company twice in a row."""
        return full is not None and full >= start - timedelta(seconds=self.full_seconds)

    def next_ready_start(self, after: datetime) -> datetime | None:
        """The first ready-by start at or after `after`, outside a pause."""
        local = after.astimezone(self.zone).date()
        for offset in range(-1, 8):
            start = self.ready_start(local + timedelta(days=offset))
            if start is not None and start >= after and not self.paused(start):
                return start
        return None

    def next_allowed(self, at: datetime) -> datetime:
        """`at`, or the first moment after it that is outside a pause and on a
        scan day (a day off resumes at the next scan day's midnight)."""
        if self.paused_until is not None and at < self.paused_until:
            at = self.paused_until
        for _ in range(8):
            if self.scan_day(at):
                return at
            local = at.astimezone(self.zone)
            midnight = datetime.combine(local.date() + timedelta(days=1), time(), tzinfo=self.zone)
            at = midnight.astimezone(UTC)
        return at


def rules_for(
    *,
    repeat: timedelta,
    full_after: timedelta,
    zone: ZoneInfo,
    usual: UsualHours | None = None,
    ready_by_minute: int | None = None,
    days: Iterable[int] = range(7),
    paused_until: datetime | None = None,
    full_seconds: int = int(FULL_ESTIMATE.total_seconds()),
    repeat_anchor_minute: int | None = None,
) -> PlanRules:
    """The rules from the user's choices. Without a ready-by time of their own,
    each day's ready-by is the usual start the plan learned for that kind of day:
    the first usually-on window, when it does not start
    at midnight (a machine on all day has no start to be ready by)."""
    def usual_start(weekend: bool) -> int | None:
        if usual is None or usual.learning:
            return None
        windows = usual.weekends if weekend else usual.weekdays
        if not windows or windows[0][0] == 0:
            return None
        return windows[0][0]

    ready = tuple(
        ready_by_minute if ready_by_minute is not None else usual_start(day >= 5)
        for day in range(7)
    )
    return PlanRules(
        repeat=repeat,
        full_after=full_after,
        zone=zone,
        days=frozenset(days),
        paused_until=paused_until,
        ready_by=ready,
        full_seconds=full_seconds,
        repeat_anchor=repeat_anchor_minute,
    )


def plan_decision(
    runs: Sequence[PlanRunView],
    *,
    now: datetime,
    rules: PlanRules,
    turned_on: datetime | None,
) -> str | None:
    """`full`, `quick`, or None: whether the plan runs now, and how deep.

    * Paused, or not a scan day: nothing.
    * A run still in progress: wait for it.
    * The computer was turned on after the last run: a full read, now.
    * Today's ready-by start has come and no full read began since, or was
      still under way at it (`PlanRules.ready_served`): a full read.
    * Otherwise due once a repeat has passed since the last run started (a
      failed or interrupted one is retried after `FAILED_RETRY`); full when
      the last full read is `daily_full_after` old, quick otherwise.
    """
    if rules.paused(now) or not rules.scan_day(now):
        return None
    effective = _effective_runs(runs)
    if any(run.finished_at is None for run in effective):
        return None
    last = effective[0] if effective else None
    if last is None:
        return FULL
    if turned_on is not None and turned_on > last.started_at:
        return FULL
    full = last_full_at(runs, now)
    start = rules.ready_start(now.astimezone(rules.zone).date())
    if start is not None and start <= now < start + READY_GRACE and not rules.ready_served(full, start):
        return FULL
    if last.outcome in (FAILED, INTERRUPTED):
        if now < last.started_at + min(rules.repeat, FAILED_RETRY):
            return None
    elif rules.repeat_anchor is not None:
        # Anchored: the newest slot counts, unless a scan began within half a
        # repeat before it (a wake scan at 08:50 makes the 09:00 one redundant).
        slot = rules.latest_slot(now)
        if slot is None or slot - last.started_at < rules.repeat / 2:
            return None
    elif now < last.started_at + rules.repeat:
        return None
    if full is None or now - full >= rules.daily_full_after:
        return FULL
    return QUICK


@dataclass(frozen=True)
class UpcomingRun:
    at: datetime
    kind: str
    seconds: int
    #: The length is a guess until a run of this kind has been measured.
    estimated: bool
    #: Placed at the start of the usual on-hours because the computer is
    #: usually off at the repeat time: it runs when the computer is turned on.
    on_wake: bool = False
    running: bool = False
    #: The day's full scan, started so it is finished by the ready-by time.
    ready_by: bool = False


def run_durations(runs: Sequence[PlanRunView]) -> dict[str, tuple[int, bool]]:
    """Median length of the last few finished runs of each kind, with whether
    it is the built-in estimate. A whole-roster user scan is a full read."""
    measured: dict[str, list[float]] = {FULL: [], QUICK: []}
    for run in sorted(runs, key=lambda item: item.started_at, reverse=True):
        if run.finished_at is None or run.outcome != "ok" or not run.covers_roster or run.kind == CONTINUE:
            continue
        kind = FULL if run.is_full else QUICK
        if len(measured[kind]) < DURATION_SAMPLE:
            measured[kind].append((run.finished_at - run.started_at).total_seconds())
    fallback = {FULL: FULL_ESTIMATE, QUICK: QUICK_ESTIMATE}
    return {
        kind: (int(median(values)), False) if values
        else (int(fallback[kind].total_seconds()), True)
        for kind, values in measured.items()
    }


def _next_on(at: datetime, usual: UsualHours, zone: ZoneInfo) -> tuple[datetime, bool]:
    """`at`, or the start of the next usually-on window when the computer is
    usually off then. Unknown hours never move a run."""
    local = at.astimezone(zone)
    for offset in range(8):
        day = local.date() + timedelta(days=offset)
        windows = usual.windows_on(day)
        if windows is None:
            return at, False
        for start, end in windows:
            window_start = datetime.combine(day, time(), tzinfo=zone) + timedelta(minutes=start)
            window_end = datetime.combine(day, time(), tzinfo=zone) + timedelta(minutes=end)
            if offset == 0 and window_start <= local < window_end:
                return at, False
            if window_start > local:
                return window_start.astimezone(UTC), True
    return at, False


def project_upcoming(
    runs: Sequence[PlanRunView],
    *,
    now: datetime,
    rules: PlanRules,
    turned_on: datetime | None,
    usual: UsualHours,
    on_now: bool,
    horizon: timedelta = timedelta(hours=24),
) -> list[UpcomingRun]:
    """The plan's runs over the next `horizon`, as the dial draws them.

    The same rules as `plan_decision`, walked forward: a run in progress first,
    then each repeat. Pause and days off move a run to the first allowed
    moment; a repeat that falls when the computer is usually off is drawn at
    the start of the next usual on-hours, as a full read, because that is when
    and how it will run; a day's ready-by full scan takes the place of the
    repeat it comes before. A run due now stays now while the computer is on
    (the next tick starts it), whatever the usual hours say."""
    durations = run_durations(runs)
    effective = _effective_runs(runs)
    upcoming: list[UpcomingRun] = []
    full = last_full_at(runs, now)
    zone = rules.zone

    running = next((run for run in effective if run.finished_at is None), None)
    if running is not None:
        kind = FULL if running.is_full or running.kind == CONTINUE else QUICK
        seconds, estimated = durations[kind]
        upcoming.append(UpcomingRun(running.started_at, kind, seconds, estimated, running=True))
        if running.is_full:
            full = running.started_at
        at = _after(running.started_at, rules)
    else:
        decision = plan_decision(runs, now=now, rules=rules, turned_on=turned_on)
        if decision is not None or not effective:
            at = now
        else:
            last = effective[0]
            if last.outcome in (FAILED, INTERRUPTED):
                at = last.started_at + min(rules.repeat, FAILED_RETRY)
            else:
                at = _after(last.started_at, rules)

    end = now + horizon
    while at < end:
        due_now = at <= now and running is None and not upcoming
        if due_now and on_now and not rules.paused(now) and rules.scan_day(now):
            at, on_wake = now, False
        else:
            at = rules.next_allowed(max(at, now))
            moved, on_wake = _next_on(at, usual, zone)
            at = rules.next_allowed(moved)
        ready = rules.next_ready_start(max(now, upcoming[-1].at if upcoming else now))
        ready_by = False
        if ready is not None and ready <= at and not rules.ready_served(full, ready):
            at, on_wake, ready_by = max(ready, now), False, True
        if at >= end:
            break
        if due_now and not on_wake and not ready_by:
            kind = plan_decision(runs, now=now, rules=rules, turned_on=turned_on) or QUICK
        elif ready_by or on_wake or full is None or at - full >= rules.daily_full_after:
            kind = FULL
        else:
            kind = QUICK
        seconds, estimated = durations[kind]
        upcoming.append(UpcomingRun(
            max(at, now), kind, seconds, estimated, on_wake=on_wake, ready_by=ready_by,
        ))
        if kind == FULL:
            full = max(at, now)
        at = _after(max(at, now), rules)
    return upcoming


def _after(started: datetime, rules: PlanRules) -> datetime:
    """When the repeat after a scan that began at `started` falls: a repeat
    later, or with fixed clock times the first slot at least half a repeat on."""
    if rules.repeat_anchor is None:
        return started + rules.repeat
    return rules.next_slot(started + rules.repeat / 2) or started + rules.repeat


# ----------------------------------------------------------------------- database


def _view(row: SchedulePlanRun) -> PlanRunView:
    return PlanRunView(
        kind=row.kind,
        started_at=row.started_at,
        finished_at=row.finished_at,
        companies=row.companies,
        roster=row.roster,
        outcome=row.outcome,
    )


#: Enough runs to hold the newest full read and several measured run lengths:
#: a day of 2-hour repeats is 12.
RECENT_RUNS = 50


async def recent_runs(session: AsyncSession, *, now: datetime) -> list[PlanRunView]:
    """The newest runs, newest first: one statement, whatever the history."""
    rows = (
        await session.scalars(
            select(SchedulePlanRun)
            .where(SchedulePlanRun.started_at <= now)
            .order_by(SchedulePlanRun.started_at.desc())
            .limit(RECENT_RUNS)
        )
    ).all()
    return [_view(row) for row in rows]


async def recent_samples(session: AsyncSession, *, now: datetime) -> list[datetime]:
    since = now - timedelta(days=LEARN_WINDOW_DAYS + 2)
    return list(
        (
            await session.scalars(
                select(MachineAwakeSample.seen_at)
                .where(MachineAwakeSample.seen_at >= since)
                .order_by(MachineAwakeSample.seen_at)
            )
        ).all()
    )


async def start_run(session: AsyncSession, *, kind: str, now: datetime, companies: int, roster: int) -> int:
    row = SchedulePlanRun(kind=kind, started_at=now, companies=companies, roster=roster)
    session.add(row)
    await session.flush()
    return row.id


async def finish_run(session: AsyncSession, run_id: int, *, now: datetime, outcome: str) -> None:
    row = await session.get(SchedulePlanRun, run_id)
    if row is not None:
        row.finished_at = now
        row.outcome = outcome


async def close_unfinished_runs(session: AsyncSession, *, now: datetime) -> int:
    """Finish as interrupted every run left without a finish, so a full read
    is continued at once and any other run retried after `FAILED_RETRY`,
    rather than waited for as one in progress. Only for a caller that knows
    no run is in progress. Returns runs closed."""
    result = await session.execute(
        update(SchedulePlanRun)
        .where(SchedulePlanRun.finished_at.is_(None))
        .values(finished_at=now, outcome=INTERRUPTED)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def read_since(session: AsyncSession, since: datetime) -> set[int]:
    """Bindings with a full read since `since`, whatever it found: a site's
    failure is its answer, and only a company its lane never started
    (`deferred_reason`) is still unread."""
    return set(
        (
            await session.scalars(
                select(ScrapeSourceRun.binding_id)
                .where(
                    ScrapeSourceRun.finished_at >= since,
                    ScrapeSourceRun.scan_mode == "reconcile",
                    ~ScrapeSourceRun.stats.has_key("deferred_reason"),
                )
                .distinct()
            )
        ).all()
    )


async def _insert_samples(session: AsyncSession, moments: Iterable[datetime], source: str) -> int:
    values = [{"seen_at": moment, "source": source} for moment in moments]
    if not values:
        return 0
    for start in range(0, len(values), 1000):
        stmt = insert(MachineAwakeSample).values(values[start:start + 1000])
        await session.execute(stmt.on_conflict_do_nothing(index_elements=["seen_at"]))
    return len(values)


def samples_from_intervals(intervals: Iterable[tuple[datetime, datetime]]) -> list[datetime]:
    """One sample per tick span inside each full-wake interval, so a seeded
    week looks like a week of ticks."""
    moments: list[datetime] = []
    for start, end in intervals:
        at = start.astimezone(UTC)
        while at < end:
            moments.append(at)
            at += SAMPLE_SPAN
    return moments


async def has_samples(session: AsyncSession) -> bool:
    return bool(await session.scalar(select(MachineAwakeSample.seen_at).limit(1)))


async def note_awake(
    session: AsyncSession,
    *,
    now: datetime,
    read_power: Callable[[], host_power.Power] = host_power.read_power,
    read_log: Callable[[], str | None] = host_power.read_wake_log,
) -> bool:
    """Record that the machine is properly awake now. True if it was recorded.

    A dark wake is not "on". The first sample ever also seeds the past week from
    `pmset -g log`, so a new install knows the usual hours in days, not weeks."""
    if read_power().dark_wake:
        return False
    if not await has_samples(session):
        intervals = host_power.full_wake_intervals(read_log(), now)
        await _insert_samples(session, samples_from_intervals(intervals), "pmset")
    await _insert_samples(session, [now], "tick")
    return True


@dataclass
class PlanContext:
    """What one decision reads, loaded once."""

    runs: list[PlanRunView]
    stretches: list[tuple[datetime, datetime]] = field(default_factory=list)


async def load_context(session: AsyncSession, *, now: datetime) -> PlanContext:
    return PlanContext(
        runs=await recent_runs(session, now=now),
        stretches=awake_stretches(await recent_samples(session, now=now)),
    )


#: Where "until tomorrow" ends while the usual hours are still being learned.
TOMORROW_FALLBACK_MINUTE = 8 * 60


def tomorrow_start(stretches: Sequence[tuple[datetime, datetime]], *, now: datetime, zone: ZoneInfo) -> datetime:
    """When "pause until tomorrow" ends: tomorrow's usual start, or 08:00 local
    while the hours are learning or tomorrow starts at midnight (on all day)."""
    tomorrow = now.astimezone(zone).date() + timedelta(days=1)
    windows = usual_hours(stretches, now=now, zone=zone).windows_on(tomorrow)
    minute = windows[0][0] if windows and windows[0][0] > 0 else TOMORROW_FALLBACK_MINUTE
    return (datetime.combine(tomorrow, time(), tzinfo=zone) + timedelta(minutes=minute)).astimezone(UTC)


def plan_zone(choices: SchedulePlanSettings) -> ZoneInfo:
    """The zone the user chose times and days in, else this machine's."""
    if choices.timezone:
        try:
            return ZoneInfo(choices.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return local_zone()


def context_rules(
    context: PlanContext, *, now: datetime, choices: SchedulePlanSettings, settings: Settings
) -> tuple[PlanRules, UsualHours]:
    """The rules a tick and the screen both use, with the usual hours behind them."""
    zone = plan_zone(choices)
    usual = usual_hours(context.stretches, now=now, zone=zone)
    rules = rules_for(
        repeat=timedelta(hours=choices.repeat_hours),
        full_after=timedelta(hours=settings.schedule_plan_full_after_hours),
        zone=zone,
        usual=usual,
        ready_by_minute=choices.ready_by_minute,
        days=choices.days,
        paused_until=choices.paused_until,
        full_seconds=run_durations(context.runs)[FULL][0],
        repeat_anchor_minute=choices.repeat_anchor_minute,
    )
    return rules, usual


def _turned_on(context: PlanContext, *, now: datetime, settings: Settings) -> datetime | None:
    return turned_on_at(
        context.stretches, now=now, gap=timedelta(minutes=settings.schedule_plan_wake_gap_minutes)
    )


def decide(
    context: PlanContext, *, now: datetime, choices: SchedulePlanSettings, settings: Settings
) -> str | None:
    rules, _usual = context_rules(context, now=now, choices=choices, settings=settings)
    return plan_decision(
        context.runs, now=now, rules=rules, turned_on=_turned_on(context, now=now, settings=settings)
    )


def plan_upcoming(
    context: PlanContext, *, now: datetime, choices: SchedulePlanSettings, settings: Settings,
) -> tuple[PlanRules, list[UpcomingRun]]:
    """The plan's rules and its runs over the next day, as `plan_payload` serves them."""
    rules, rules_usual = context_rules(context, now=now, choices=choices, settings=settings)
    on_now = bool(context.stretches and context.stretches[-1][1] + SAMPLE_JOIN_GAP >= now)
    return rules, project_upcoming(
        context.runs,
        now=now,
        rules=rules,
        turned_on=_turned_on(context, now=now, settings=settings),
        usual=rules_usual,
        on_now=on_now,
    )


def plan_payload(
    context: PlanContext,
    *,
    now: datetime,
    choices: SchedulePlanSettings,
    repeat_choices: Sequence[int],
    settings: Settings,
    zone: ZoneInfo,
    roster: int,
    quick_roster: int,
    pinned: int,
    on_battery: bool,
) -> dict:
    """`/api/schedule`'s `plan`: what the plan is, what it learned, what comes next.

    `zone` is the zone the screen asked in, for the usual hours it shows; the
    rules run in the zone the choices were made in (`plan_zone`)."""
    rules, upcoming = plan_upcoming(context, now=now, choices=choices, settings=settings)
    usual = usual_hours(context.stretches, now=now, zone=zone)
    on_now = bool(context.stretches and context.stretches[-1][1] + SAMPLE_JOIN_GAP >= now)
    effective = _effective_runs(context.runs)
    last = effective[0] if effective else None
    today = now.astimezone(zone).date()
    rules_today = now.astimezone(rules.zone).date()
    ready_today = rules.ready_by[rules_today.weekday()]
    if rules.paused(now):
        waiting = "paused"
    elif not rules.scan_day(now):
        waiting = "day_off"
    elif choices.mains_only and on_battery:
        waiting = "mains"
    else:
        waiting = None

    def windows(value: tuple[tuple[int, int], ...] | None) -> list[dict] | None:
        if value is None:
            return None
        return [{"start_minute": start, "end_minute": end} for start, end in value]

    return {
        "enabled": settings.sync_schedule_plan_enabled,
        "repeat_hours": choices.repeat_hours,
        "repeat_anchor_minute": choices.repeat_anchor_minute,
        "repeat_choices": list(repeat_choices),
        "full_after_hours": settings.schedule_plan_full_after_hours,
        "roster": roster,
        "quick_roster": quick_roster,
        "pinned": pinned,
        "ready_by_minute": choices.ready_by_minute,
        "ready_by_today": None if ready_today is None else {
            "minute": ready_today,
            "source": "set" if choices.ready_by_minute is not None else "usual",
        },
        "days": list(choices.days),
        "paused_until": rules.paused_until if rules.paused(now) else None,
        "mains_only": choices.mains_only,
        "waiting": waiting,
        "last_run": None if last is None else {
            # A continuation reads the rest of a full read's roster.
            "kind": FULL if last.is_full or last.kind == CONTINUE else QUICK,
            "manual": last.kind == MANUAL,
            "started_at": last.started_at,
            "finished_at": last.finished_at,
            "companies": last.companies,
            "outcome": last.outcome,
        },
        "last_full_at": last_full_at(context.runs, now),
        "upcoming": [
            {
                "at": run.at,
                "kind": run.kind,
                "seconds": run.seconds,
                "estimated": run.estimated,
                "on_wake": run.on_wake,
                "running": run.running,
                "ready_by": run.ready_by,
            }
            for run in upcoming
        ],
        "usual": {
            "timezone": usual.timezone,
            "observed_days": usual.observed_days,
            "needed_days": NEEDED_DAYS,
            "learning": usual.learning,
            "today": windows(usual.windows_on(today)),
            "weekdays": windows(usual.weekdays) if not usual.learning else None,
            "weekends": windows(usual.weekends) if not usual.learning else None,
            "on_now": on_now,
        },
    }
