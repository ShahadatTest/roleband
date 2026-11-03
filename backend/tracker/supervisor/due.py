"""Whether a job starts now, and if not, why not and until when.

A pure function of the job's registry entry, what is known about its key (its
last run, its queued requests) and the state of the world (power, the preflight
gate, the schema). No processes, no database, no clock of its own: the tests
replay any moment.

Schedules are decided on wall-clock time, so a machine that slept through a
start time sees it as due at its first look after waking.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from enum import StrEnum

from tracker.supervisor.registry import (
    AtDeadline,
    Daily,
    Every,
    JobSpec,
    OnChange,
    OnRequest,
    Power,
)

#: A daily slot without catch-up still runs this long after its time.
DAILY_GRACE = timedelta(hours=1)


class Gate(StrEnum):
    PASSED = "passed"
    RUNNING = "running"
    FAILED = "failed"
    #: No verdict for the current code yet; the preflight job is about to give one.
    UNKNOWN = "unknown"


# Reason codes. The dashboard words them; a parameter (who holds a lock, until
# when) travels in its own field, never inside the code.
SCHEMA_PENDING = "schema_pending"
DEPENDENCIES_PENDING = "dependencies_pending"
PREFLIGHT_RUNNING = "preflight_running"
PREFLIGHT_FAILED = "preflight_failed"
WAITING_FOR_WAKE = "waiting_for_wake"
WAITING_FOR_MAINS = "waiting_for_mains"

IDLE = "idle"
WAITING = "waiting"
RUNNING = "running"


@dataclass(frozen=True)
class Facts:
    """What is known about one job key at one moment."""

    now: datetime
    #: A run of this key is starting or running.
    live: bool = False
    last_started_at: datetime | None = None
    last_ended_at: datetime | None = None
    #: Queued requests of this key, and the trigger the oldest one asks to be
    #: judged by ("schedule" when a scheduled evaluation rang it).
    queued: int = 0
    requested_for: str | None = None
    #: `OnChange`: since when the watched fingerprint has differed from the
    #: accepted one; None when they agree.
    changed_since: datetime | None = None
    #: `AtDeadline`: when the job asked to run next.
    deadline: datetime | None = None


@dataclass(frozen=True)
class World:
    dark_wake: bool
    on_battery: bool
    gate: Gate
    #: The database is at the code's schema revision.
    schema_ready: bool
    #: The zone daily schedules are read in.
    zone: tzinfo
    #: What the checkout needs installed is installed (or unknown, which does
    #: not hold anything).
    dependencies_ready: bool = True


@dataclass(frozen=True)
class Decision:
    start: bool
    #: What starts it: "request", "schedule" or "change"; None when nothing is due.
    trigger: str | None
    state: str
    reason: str | None = None
    #: When the schedule next falls due, whatever is blocking now.
    next_at: datetime | None = None


def decide(job: JobSpec, facts: Facts, world: World) -> Decision:
    next_at = scheduled_next(job, facts, world.zone)
    if facts.live:
        return Decision(False, None, RUNNING, next_at=next_at)
    trigger = _wanted(job, facts, next_at)
    if trigger is None:
        return Decision(False, None, IDLE, next_at=next_at)
    reason = _blocker(job, facts, world, trigger)
    if reason is not None:
        return Decision(False, trigger, WAITING, reason=reason, next_at=next_at)
    return Decision(True, trigger, RUNNING, next_at=next_at)


def _wanted(job: JobSpec, facts: Facts, next_at: datetime | None) -> str | None:
    if facts.queued:
        return "request"
    if next_at is None or facts.now < next_at:
        return None
    return "change" if isinstance(job.schedule, OnChange) else "schedule"


def _blocker(job: JobSpec, facts: Facts, world: World, trigger: str) -> str | None:
    if job.uses_database and not world.schema_ready:
        return SCHEMA_PENDING
    if job.uses_database and not world.dependencies_ready:
        return DEPENDENCIES_PENDING
    if job.gated and world.gate is not Gate.PASSED:
        return PREFLIGHT_FAILED if world.gate is Gate.FAILED else PREFLIGHT_RUNNING
    if job.power is Power.NONE:
        return None
    if world.dark_wake:
        return WAITING_FOR_WAKE
    if world.on_battery and _needs_mains(job, facts, trigger):
        return WAITING_FOR_MAINS
    return None


def _needs_mains(job: JobSpec, facts: Facts, trigger: str) -> bool:
    if job.power is Power.MAINS:
        return True
    if job.power is Power.BY_TRIGGER:
        scheduled = facts.requested_for if trigger == "request" else trigger
        return scheduled == "schedule"
    return False


def scheduled_next(job: JobSpec, facts: Facts, zone: tzinfo) -> datetime | None:
    """When the job's own schedule next falls due; None for a job that runs only
    when asked, or that has nothing to wait for."""
    schedule = job.schedule
    if isinstance(schedule, Every):
        return _every_next(schedule, facts)
    if isinstance(schedule, Daily):
        return _daily_next(schedule, facts, zone)
    if isinstance(schedule, OnChange):
        if facts.changed_since is None:
            return None
        return facts.changed_since + timedelta(seconds=schedule.settle_seconds)
    if isinstance(schedule, AtDeadline):
        return facts.deadline
    assert isinstance(schedule, OnRequest)
    return None


def _every_next(schedule: Every, facts: Facts) -> datetime:
    started = facts.last_started_at
    if started is None:
        return facts.now
    period = schedule.seconds
    ran_for = 0.0
    if facts.last_ended_at is not None and facts.last_ended_at > started:
        ran_for = (facts.last_ended_at - started).total_seconds()
    # The starts that fell inside the run are missed: the next one is the first
    # period boundary, counted from the last start, at or after the run ended.
    periods = max(1, math.ceil(ran_for / period))
    return started + timedelta(seconds=period * periods)


def _daily_next(schedule: Daily, facts: Facts, zone: tzinfo) -> datetime:
    local_now = facts.now.astimezone(zone)
    slot = _slot_on(local_now.date(), schedule, zone)
    if slot > facts.now:
        slot = _slot_on(local_now.date() - timedelta(days=1), schedule, zone)
    # `slot` is the latest slot at or before now.
    done = facts.last_started_at is not None and facts.last_started_at >= slot
    too_late = not schedule.catch_up and facts.now - slot > DAILY_GRACE
    if done or too_late:
        return _slot_on(slot.astimezone(zone).date() + timedelta(days=1), schedule, zone)
    return slot


def _slot_on(day: date, schedule: Daily, zone: tzinfo) -> datetime:
    return datetime.combine(day, schedule.at, tzinfo=zone)
