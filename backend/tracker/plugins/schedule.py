"""How often a plugin's jobs run, and when next (pure).

The user picks one schedule per plugin in Settings > Plugins; None keeps each
job's manifest schedule. `manual` never starts itself, and a paused plugin
starts nothing on its own while it stays on and answers. `next_start` is the
one answer to "when does this job run next": `runtime.due_jobs` starts what it
says is due, `status` shows it. No process is touched here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from tracker.plugins.registry import InstallRecord
from tracker.plugins.store import PASS_OUTCOMES

#: A job whose last attempt did not go through (`store.PASS_OUTCOMES`) is tried again after this.
RETRY_AFTER = timedelta(hours=6)
#: A pass in progress continues this long after its last run ended.
CONTINUE_AFTER = timedelta(minutes=30)
#: A scheduled job is due this long after its last whole pass started.
INTERVALS: dict[str, timedelta] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}
SCHEDULES: tuple[str, ...] = ("manual", *INTERVALS)


def job_schedule(record: InstallRecord, job: Mapping[str, Any]) -> str:
    """The schedule a job runs on: the user's choice, else its manifest's."""
    chosen = record.schedule if record.schedule in SCHEDULES else None
    return chosen or str(job.get("schedule") or "manual")


@dataclass(frozen=True)
class RunRecord:
    """What the schedule needs from one `plugin_run` row."""

    plugin_id: str
    job: str
    outcome: str
    started_at: datetime
    ended_at: datetime | None = None
    #: A clean or partial run whose pass is not through (`end.more`).
    continues: bool = False
    #: The pass's position and length as the run last reported them
    #: (`ctx.progress`; `ctx.resume` counts from the start of the pass).
    progress_done: int | None = None
    progress_total: int | None = None


@dataclass(frozen=True)
class NextStart:
    """When a job next starts on its own, and why."""

    #: None = as soon as the gates allow (it has never run).
    at: datetime | None
    #: never_clean | continues | daily | weekly | monthly
    reason: str


def _through(run: RunRecord) -> bool:
    """The run finished a pass: it went through the job (`PASS_OUTCOMES`, a
    `partial` one too) and did not say `more`."""
    return run.outcome in PASS_OUTCOMES and not run.continues


def _continuing(run: RunRecord) -> bool:
    """The run went through its part of a pass and said `more`."""
    return run.outcome in PASS_OUTCOMES and run.continues


def next_start(record: InstallRecord, job: Mapping[str, Any], runs: Sequence[RunRecord]) -> NextStart | None:
    """When `job` of `record` next starts by itself; None when it never does
    (manual, paused, not runnable). Pure; `runtime.due_jobs` starts what is
    due and `status` shows the same answer.

    - A run that went through its part (`clean`, or `partial`: some of it was
      refused) and said `more` is a pass in progress: the next run
      continues it `CONTINUE_AFTER` its end, not a schedule interval later.
    - A run that did not go through (`error`, `bounded`, `stopped`) is tried
      again `RETRY_AFTER` its start; within
      a pass in progress that is the whole wait, after a whole pass it is also no
      earlier than the schedule would have it.
    - Otherwise the schedule counts from the START of the last whole pass: the
      first run after the pass before it, so a pass spread over many runs is
      repeated every interval, not every interval after its last chunk.
    """
    interval = INTERVALS.get(job_schedule(record, job))
    if interval is None or record.paused or not record.runnable:
        return None
    name = str(job.get("name"))
    mine = sorted((r for r in runs if r.plugin_id == record.plugin_id and r.job == name), key=lambda r: r.started_at)
    if not mine:
        return NextStart(None, "never_clean")
    last = mine[-1]
    if _continuing(last):
        return NextStart((last.ended_at or last.started_at) + CONTINUE_AFTER, "continues")
    wholes = [r for r in mine if _through(r)]
    schedule = job_schedule(record, job)
    if last.outcome not in PASS_OUTCOMES:
        retry = last.started_at + RETRY_AFTER
        since = [r for r in mine if not wholes or r.started_at > wholes[-1].started_at]
        if any(_continuing(r) for r in since):
            return NextStart(retry, "continues")
        if not wholes:
            return NextStart(retry, "never_clean")
        return NextStart(max(retry, _pass_start(mine, wholes[-1]) + interval), schedule)
    return NextStart(_pass_start(mine, last) + interval, schedule)


@dataclass(frozen=True)
class ReadingLeft:
    """How far a job's pass under way has to go, at the pace its own runs kept."""

    #: Units (for a company job, companies) the pass has still to go through.
    units: int
    #: Seconds one unit took, over the job's last `PACE_RUNS` runs that moved.
    seconds_per_unit: float
    #: About how long until the pass is through: the reading, plus the wait
    #: `CONTINUE_AFTER` between the runs the job's budget splits it into.
    seconds: float


#: How many recent runs that moved a pass the pace is measured over.
PACE_RUNS = 5


def reading_left(job: Mapping[str, Any], runs: Sequence[RunRecord]) -> ReadingLeft | None:
    """What is left of `job`'s pass under way, measured, never declared.

    A run's `progress_done` is the pass's position, so a run's own work is what
    it moved since the run before it, and a pass that finished (clean, no
    `more`) puts the next one back at zero. A running run's position counts,
    its unfinished time does not. None when there is nothing to say: no pass
    under way, a job that never counted its units, or no run that moved one."""
    name = str(job.get("name"))
    mine = sorted((r for r in runs if r.job == name), key=lambda r: r.started_at)
    paced: list[tuple[float, int]] = []
    at = 0
    position: tuple[int, int] | None = None
    for run in mine:
        if run.progress_done is not None:
            moved = run.progress_done - at if run.progress_done >= at else run.progress_done
            if run.ended_at is not None and moved > 0:
                paced.append(((run.ended_at - run.started_at).total_seconds(), moved))
            at = run.progress_done
            position = (run.progress_done, run.progress_total) if run.progress_total else None
        if _through(run):
            at, position = 0, None
    if position is None or not paced:
        return None
    units = position[1] - position[0]
    if units <= 0:
        return None
    took, moved = map(sum, zip(*paced[-PACE_RUNS:], strict=True))
    pace = took / moved
    reading = units * pace
    budget = float(job.get("budget_seconds") or 0)
    waits = max(math.ceil(reading / budget) - 1, 0) if budget > 0 else 0
    return ReadingLeft(units, pace, reading + waits * CONTINUE_AFTER.total_seconds())


def _pass_start(mine: Sequence[RunRecord], whole: RunRecord) -> datetime:
    """When the pass that `whole` completed began: the first run after the whole
    pass before it."""
    before = [r for r in mine if r.started_at < whole.started_at and _through(r)]
    after = [r for r in mine if not before or r.started_at > before[-1].started_at]
    return after[0].started_at if after else whole.started_at
