"""Pure health/freshness helpers shared by the API status endpoint and watchdog.

Kept free of DB/IO so the decision logic is unit-testable in isolation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum


class RunScope(StrEnum):
    """What a run *covered* — orthogonal to `status`, which is how it went.

    Freshness is a claim about the whole roster, so only a run that attempted
    the whole roster may advance it. A `targeted` run re-attempts a chosen
    subset (the sources a previous run failed on); it can legitimately be `ok`
    while most companies were never contacted, and counting that as a refresh
    would mark them fresh and switch off the catch-up meant to reach them.
    """

    FULL = "full"
    TARGETED = "targeted"


#: Terminal run statuses that count as a successful data refresh — the ones that
#: advance `last_success_at` and therefore clear staleness.
#:
#: `partial` belongs here; without it, one throttled source makes every run
#: terminal-`error`, so `last_success_at` never advances, `stale` stays true
#: forever, and `should_catch_up` kicks another run into the same wall every
#: hour. A run where most sources delivered *did* refresh the data; the
#: degraded source surfaces through its own outcome rather than through global
#: staleness.
#:
#: `error` is deliberately excluded: it means "no source
#: produced usable data", and a total failure (network down, DB unreachable)
#: *should* keep the watchdog retrying.
REFRESHED_STATUSES = ("ok", "partial")


def freshness(
    last_success_at: datetime | None,
    now: datetime,
    max_hours: float,
) -> tuple[float | None, bool]:
    """Return (age_in_hours, is_stale) for the last successful run.

    No prior success (``None``) counts as stale. Age is ``None`` in that case.
    """
    if last_success_at is None:
        return None, True
    age_hours = (now - last_success_at).total_seconds() / 3600.0
    return age_hours, age_hours > max_hours


def is_run_active(
    status: str | None,
    started_at: datetime | None,
    now: datetime,
    stale_minutes: float,
    *,
    heartbeat_at: datetime | None = None,
    heartbeat_stale_seconds: float | None = None,
) -> bool:
    """Whether a scrape run is live *right now* (in-progress, not orphaned).

    A ``running`` marker is live only while it keeps beating: the last beat
    (``heartbeat_at``, or ``started_at`` for a run that has not beaten yet)
    must be within ``heartbeat_stale_seconds``. A
    killed process stops beating, so this clears the ``running`` state in
    minutes.

    ``stale_minutes`` is the answer only for a caller that passes no heartbeat
    args, which gets start-time-only semantics. Applied beside a beat it would
    call a run dead for lasting a long time, which a full collection does.
    ``queries/runs.stale_run_where`` states the whole rule; this judges a row
    already in hand and the two must agree row for row.

    Shared by the API status badge and the ``/api/sync`` overlap guard so both
    agree on "active".
    """
    if status != "running" or started_at is None:
        return False
    if heartbeat_stale_seconds is not None:
        last_beat = heartbeat_at or started_at
        return last_beat >= now - timedelta(seconds=heartbeat_stale_seconds)
    return started_at >= now - timedelta(minutes=stale_minutes)


def should_catch_up(status: dict) -> bool:
    """Decide whether the watchdog should trigger a catch-up scrape.

    True only when data is stale AND nothing is already running — so a catch-up
    can never pile onto a scheduled or in-flight run.
    """
    if not status.get("stale"):
        return False
    if status.get("last_run_status") == "running":
        return False
    if status.get("stuck_running"):
        return False
    return True


def stale_derivations(status: dict) -> list[str]:
    """Names of derived tables whose producing pass is stale.

    A derived table can rot while the scrape itself is healthy — a pass that
    never ran, or is failing. The watchdog notifies on this; the next scrape
    rebuilds it, so no separate remediation is triggered here.
    """
    names = status.get("derivations_stale") or []
    return [n for n in names if isinstance(n, str)]
