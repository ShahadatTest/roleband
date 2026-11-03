"""The supervisor's store: run-now requests, supervised runs, and what each job is doing.

The one writer of `job_requests`, `job_runs` and `job_status`. Every function works
inside the caller's transaction and commits nothing, so a producer commits its domain
change and its request together, and the supervisor commits a claim before it spawns
the process the claim names.

Delivery is at least once. A request whose run was lost is queued again, so every job
must find nothing left to do when it replays work that already happened; the work
itself lives in the job's domain queue, never here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import JobRequest, JobRun, JobStatus

#: The channel a request or a cancel is announced on; the supervisor listens to it
#: and also polls, so a missed notification only delays a start.
CHANNEL = "roleband_jobs"

QUEUED = "queued"
CLAIMED = "claimed"
DONE = "done"
CANCELLED = "cancelled"
FAILED = "failed"

STARTING = "starting"
RUNNING = "running"
EXITED = "exited"
TIMED_OUT = "timed_out"
RUN_CANCELLED = "cancelled"
LOST = "lost"
SPAWN_FAILED = "spawn_failed"

LIVE = (STARTING, RUNNING)
#: Run ends that say nothing about the work: the process never started, or it went
#: away unobserved. Their request is queued again.
UNOBSERVED = (LOST, SPAWN_FAILED)

#: A request is tried this many times before it is marked failed.
MAX_ATTEMPTS = 3

#: Result kinds that record a run which did no work; retention keeps fewer of them,
#: so a ten-minute tick that finds nothing due cannot crowd out the runs that did.
NO_OP_KINDS = ("nothing_due", "waiting", "busy")

#: The `job_status` key of the supervisor's own heartbeat row.
SUPERVISOR_KEY = "supervisor"


def instance_key(job: str, argument: str | None = None) -> str:
    """One instance of a job: the job's name, or `<job>:<argument>` for a job that
    runs once per argument (a plugin run per plugin)."""
    return job if argument is None else f"{job}:{argument}"


def coalesce_key(key: str, args: Mapping[str, Any]) -> str:
    """Requests with equal keys and equal arguments are one queued request."""
    if not args:
        return key
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    return f"{key}#{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"


async def _notify(session: AsyncSession, payload: str) -> None:
    # Delivered at commit, so a listener never wakes for a request it cannot see.
    await session.execute(text("SELECT pg_notify(:channel, :payload)"), {"channel": CHANNEL, "payload": payload})


async def ring(
    session: AsyncSession,
    job: str,
    *,
    requested_by: str,
    argument: str | None = None,
    args: Mapping[str, Any] | None = None,
) -> JobRequest:
    """Ask for `job` to run now, coalescing with an equal request still queued.

    Returns the queued request, new or existing."""
    key = instance_key(job, argument)
    values = dict(args or {})
    merged = coalesce_key(key, values)
    queued_only = text("state = 'queued'")
    # Two tries: the queued row this insert collided with can be claimed before the
    # read below sees it, and then a fresh insert succeeds.
    for _ in range(2):
        new_id = await session.scalar(
            insert(JobRequest)
            .values(job=job, key=key, args=values, coalesce_key=merged, requested_by=requested_by)
            .on_conflict_do_nothing(index_elements=["coalesce_key"], index_where=queued_only)
            .returning(JobRequest.id)
        )
        if new_id is None:
            row = await session.scalar(
                select(JobRequest).where(JobRequest.coalesce_key == merged, JobRequest.state == QUEUED)
            )
        else:
            row = await session.get(JobRequest, new_id)
        if row is not None:
            await _notify(session, key)
            return row
    raise RuntimeError(f"could not queue a request for {key}")


async def open_run(
    session: AsyncSession,
    job: str,
    key: str,
    *,
    trigger: str,
    request_id: int | None = None,
    code_version: str | None = None,
) -> JobRun | None:
    """Open the live run of `key`, or None when one is already live.

    The unique live-run index decides, not a read: two supervisors racing for one
    key cannot both open a run."""
    run_id = await session.scalar(
        insert(JobRun)
        .values(job=job, key=key, trigger=trigger, request_id=request_id, code_version=code_version)
        .on_conflict_do_nothing(
            index_elements=["key"], index_where=text("state IN ('starting', 'running')")
        )
        .returning(JobRun.id)
    )
    return None if run_id is None else await session.get(JobRun, run_id)


async def claim(
    session: AsyncSession, key: str, *, code_version: str | None = None
) -> tuple[JobRequest, JobRun] | None:
    """Claim the oldest queued request of `key` and open its run.

    None when nothing is queued, when another claimer holds the request (`SKIP
    LOCKED`), or when `key` already has a live run; the request then stays queued."""
    request = await session.scalar(
        select(JobRequest)
        .where(JobRequest.key == key, JobRequest.state == QUEUED)
        .order_by(JobRequest.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if request is None:
        return None
    run = await open_run(
        session, request.job, key, trigger="request", request_id=request.id, code_version=code_version
    )
    if run is None:
        return None
    request.state = CLAIMED
    request.claimed_at = func.now()
    request.attempts = request.attempts + 1
    await session.flush()
    await session.refresh(request)
    return request, run


async def mark_running(
    session: AsyncSession,
    run_id: int,
    *,
    pid: int,
    pgid: int,
    proc_started_at: datetime | None,
    log_path: str | None = None,
    log_offset: int | None = None,
) -> None:
    """Record the process a claimed run became."""
    await session.execute(
        update(JobRun)
        .where(JobRun.id == run_id, JobRun.state == STARTING)
        .values(
            state=RUNNING, pid=pid, pgid=pgid, proc_started_at=proc_started_at,
            log_path=log_path, log_offset=log_offset,
        )
    )


async def mark_log_rotated(session: AsyncSession, log_path: str) -> int:
    """Every run whose output began in `log_path` before it was rotated: its
    offset now points into whatever is written next, so the run says so."""
    done = await session.execute(
        update(JobRun)
        .where(JobRun.log_path == log_path, JobRun.log_rotated.is_(False))
        .values(log_rotated=True)
    )
    return int(getattr(done, "rowcount", 0) or 0)


async def last_ended(session: AsyncSession, key: str) -> JobRun | None:
    """The most recently started run of `key` that has ended."""
    return await session.scalar(
        select(JobRun)
        .where(JobRun.key == key, JobRun.state.not_in(LIVE))
        .order_by(JobRun.started_at.desc(), JobRun.id.desc())
        .limit(1)
    )


async def finish_run(
    session: AsyncSession,
    run_id: int,
    *,
    state: str,
    exit_code: int | None = None,
    result: Mapping[str, Any] | None = None,
) -> JobRun | None:
    """End a live run and settle its request.

    A run that exited, whatever its exit code, completes its request: the run says
    what happened. A cancelled run cancels it. A run that never started or went
    away unobserved queues it again, unless it has used its attempts."""
    if state in LIVE:
        raise ValueError(f"{state} is not an end")
    run = await session.get(JobRun, run_id, with_for_update=True)
    if run is None or run.state not in LIVE:
        return run
    run.state = state
    run.ended_at = func.now()
    run.exit_code = exit_code
    run.result = dict(result) if result is not None else None
    if run.request_id is not None:
        request = await session.get(JobRequest, run.request_id, with_for_update=True)
        if request is not None and request.state == CLAIMED:
            await _settle(session, request, state)
    await session.flush()
    await session.refresh(run)
    return run


async def _settle(session: AsyncSession, request: JobRequest, run_state: str) -> None:
    if run_state in UNOBSERVED and request.attempts < MAX_ATTEMPTS:
        twin = await session.scalar(
            select(JobRequest.id).where(
                JobRequest.coalesce_key == request.coalesce_key, JobRequest.state == QUEUED
            )
        )
        if twin is None:
            request.state = QUEUED
            request.claimed_at = None
            await _notify(session, request.key)
            return
        request.note = f"merged into request {twin}"
        request.state = DONE
    elif run_state in UNOBSERVED:
        request.state = FAILED
        request.note = f"no run started after {request.attempts} attempts"
    elif run_state == RUN_CANCELLED:
        request.state = CANCELLED
    else:
        request.state = DONE
    request.ended_at = func.now()


async def request_cancel(session: AsyncSession, run_id: int, *, reason: str) -> bool:
    """Ask the supervisor to stop a live run. False when the run is not live."""
    done = await session.execute(
        update(JobRun)
        .where(JobRun.id == run_id, JobRun.state.in_(LIVE), JobRun.cancel_requested_at.is_(None))
        .values(cancel_requested_at=func.now(), cancel_reason=reason)
        .returning(JobRun.key)
    )
    key = done.scalar_one_or_none()
    if key is None:
        return False
    await _notify(session, key)
    return True


async def cancel_queued(
    session: AsyncSession,
    *,
    key: str | None = None,
    job: str | None = None,
    requested_by: str | None = None,
) -> list[int]:
    """Cancel queued requests by key, job and producer; the ids cancelled."""
    if key is None and job is None:
        raise ValueError("name a key or a job")
    statement = update(JobRequest).where(JobRequest.state == QUEUED)
    if key is not None:
        statement = statement.where(JobRequest.key == key)
    if job is not None:
        statement = statement.where(JobRequest.job == job)
    if requested_by is not None:
        statement = statement.where(JobRequest.requested_by == requested_by)
    done = await session.execute(
        statement.values(state=CANCELLED, ended_at=func.now()).returning(JobRequest.id)
    )
    return sorted(done.scalars())


async def report_progress(session: AsyncSession, run_id: int, **progress: Any) -> None:
    """A running child's own account of how far it is: done, total, note, pending, until."""
    await session.execute(
        update(JobRun).where(JobRun.id == run_id, JobRun.state == RUNNING).values(progress=progress)
    )


async def live_runs(session: AsyncSession) -> list[JobRun]:
    return list(await session.scalars(select(JobRun).where(JobRun.state.in_(LIVE)).order_by(JobRun.id)))


async def latest_runs(session: AsyncSession) -> dict[str, JobRun]:
    """The most recently started run of every key."""
    rows = await session.scalars(
        select(JobRun)
        .distinct(JobRun.key)
        .order_by(JobRun.key, JobRun.started_at.desc(), JobRun.id.desc())
    )
    return {row.key: row for row in rows}


@dataclass(frozen=True)
class Queue:
    """The queued requests of one key."""

    key: str
    job: str
    count: int
    oldest: datetime


async def queues(session: AsyncSession) -> dict[str, Queue]:
    rows = await session.execute(
        select(JobRequest.key, func.min(JobRequest.job), func.count(), func.min(JobRequest.requested_at))
        .where(JobRequest.state == QUEUED)
        .group_by(JobRequest.key)
    )
    return {key: Queue(key, job, count, oldest) for key, job, count, oldest in rows}


async def oldest_triggers(session: AsyncSession) -> dict[str, str | None]:
    """The `trigger` argument of each key's oldest queued request: a plugin run a
    scheduled evaluation asked for waits for mains, one the user asked for does not."""
    rows = await session.execute(
        select(JobRequest.key, JobRequest.args["trigger"].astext)
        .distinct(JobRequest.key)
        .where(JobRequest.state == QUEUED)
        .order_by(JobRequest.key, JobRequest.id)
    )
    return {key: trigger for key, trigger in rows}


@dataclass(frozen=True)
class Status:
    """One job key's published state."""

    key: str
    job: str
    state: str
    since: datetime
    reason: str | None = None
    next_at: datetime | None = None
    run_id: int | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)


async def publish(session: AsyncSession, statuses: Iterable[Status]) -> None:
    """Upsert each key's state. `since` moves only when the state or reason does.

    A row that would come out the same is not rewritten, so its `updated_at`
    says when it last changed. The supervisor's own row is always written: its
    `updated_at` is the heartbeat `status_view` reads."""
    for status in statuses:
        values = {
            "key": status.key, "job": status.job, "state": status.state, "reason": status.reason,
            "since": status.since, "next_at": status.next_at, "run_id": status.run_id,
            "detail": dict(status.detail),
        }
        statement = insert(JobStatus).values(**values)
        excluded = statement.excluded
        changed = (JobStatus.state != excluded.state) | JobStatus.reason.is_distinct_from(excluded.reason)
        differs = (
            changed
            | (JobStatus.job != excluded.job)
            | JobStatus.next_at.is_distinct_from(excluded.next_at)
            | JobStatus.run_id.is_distinct_from(excluded.run_id)
            | JobStatus.detail.is_distinct_from(excluded.detail)
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "job": excluded.job,
                    "state": excluded.state,
                    "reason": excluded.reason,
                    "since": case((changed, excluded.since), else_=JobStatus.since),
                    "next_at": excluded.next_at,
                    "run_id": excluded.run_id,
                    "detail": excluded.detail,
                    "updated_at": func.now(),
                },
                where=None if status.key == SUPERVISOR_KEY else differs,
            )
        )


#: The supervisor's state, and every job's reason, while it is in maintenance.
MAINTENANCE = "maintenance"


async def publish_paused(session: AsyncSession, now: datetime, *, detail: Mapping[str, Any]) -> None:
    """Every job disabled for maintenance, and the supervisor's own row saying so."""
    await session.execute(
        update(JobStatus)
        .where(JobStatus.key != SUPERVISOR_KEY)
        .values(state="disabled", reason=MAINTENANCE, since=now, run_id=None, updated_at=func.now())
    )
    await publish(
        session, [Status(key=SUPERVISOR_KEY, job="supervisor", state=MAINTENANCE, since=now, detail=detail)]
    )


#: The supervisor's own row older than this means it is not supervising.
SUPERVISOR_STALE_AFTER = timedelta(seconds=90)
#: A last run that came to one of these says why a job is idle.
_TELLING_KINDS = ("waiting", "refused", "busy")


async def status_view(session: AsyncSession, now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(jobs, supervisor) for `/api/status`, in one query.

    A supervisor whose row is older than `SUPERVISOR_STALE_AFTER` is `stale`,
    and then every job says `supervisor_stale` with the requests it has queued:
    the work waits, and the screen says so."""
    rows = (
        await session.execute(
            select(JobStatus, JobRun.progress)
            .outerjoin(JobRun, JobRun.id == JobStatus.run_id)
            .order_by(JobStatus.key)
        )
    ).all()
    supervisor: dict[str, Any] = {"state": "absent", "since": None}
    jobs: list[dict[str, Any]] = []
    for status, progress in rows:
        if status.key == SUPERVISOR_KEY:
            stale = status.updated_at is not None and now - status.updated_at > SUPERVISOR_STALE_AFTER
            state = "stale" if stale else ("maintenance" if status.state == MAINTENANCE else "running")
            supervisor = {"state": state, "since": status.updated_at if stale else status.since,
                          "reason": status.reason}
            continue
        detail: dict[str, Any] = status.detail if isinstance(status.detail, dict) else {}
        reason = status.reason
        last: dict[str, Any] = detail["last"] if isinstance(detail.get("last"), dict) else {}
        if reason is None and status.state == "idle" and last.get("kind") in _TELLING_KINDS:
            reason = last.get("reason")
        waiting = detail.get("waiting") if isinstance(detail.get("waiting"), dict) else None
        done = progress.get("done") if isinstance(progress, dict) else None
        total = progress.get("total") if isinstance(progress, dict) else None
        jobs.append({
            "key": status.key, "job": status.job, "state": status.state, "reason": reason,
            "since": status.since, "next_at": status.next_at, "run_id": status.run_id,
            "progress": {"done": done, "total": total} if done is not None else None,
            "waiting": {"count": int(waiting.get("count") or 0), "until": _at(waiting.get("until"))}
            if waiting else None,
            "queued": int(detail.get("queued") or 0),
        })
    if supervisor["state"] == "stale":
        # The published counts stopped with the supervisor; the requests did not.
        queued: dict[str, int] = {
            key: count
            for key, count in (await session.execute(
                select(JobRequest.key, func.count()).where(JobRequest.state == QUEUED).group_by(JobRequest.key)
            )).all()
        }
        for job in jobs:
            job["reason"] = "supervisor_stale"
            job["queued"] = int(queued.get(job["key"], 0))
    return jobs, supervisor


def _at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


async def statuses(session: AsyncSession) -> list[JobStatus]:
    return list(await session.scalars(select(JobStatus).order_by(JobStatus.key)))


@dataclass(frozen=True)
class Pruned:
    runs: int
    requests: int


async def prune(
    session: AsyncSession,
    now: datetime | None = None,
    *,
    keep_runs: int = 500,
    keep_no_op_runs: int = 50,
    request_days: int = 30,
) -> Pruned:
    """Retention: the latest runs of each job, more of those that did work, and
    requests for a while after they ended. Live runs and queued requests stay."""
    now = now or datetime.now(UTC)
    runs = await session.execute(
        text(
            """
            DELETE FROM job_runs WHERE id IN (
              SELECT id FROM (
                SELECT id, no_op, row_number() OVER (
                  PARTITION BY job, no_op ORDER BY started_at DESC, id DESC
                ) AS rank
                FROM (
                  SELECT id, job, started_at,
                         coalesce(result->>'kind' = ANY(:no_op_kinds), false) AS no_op
                  FROM job_runs WHERE state NOT IN ('starting', 'running')
                ) ended
              ) ranked
              WHERE (no_op AND rank > :keep_no_op) OR (NOT no_op AND rank > :keep)
            )
            """
        ),
        {"no_op_kinds": list(NO_OP_KINDS), "keep_no_op": keep_no_op_runs, "keep": keep_runs},
    )
    requests = await session.execute(
        delete(JobRequest).where(
            JobRequest.state.in_((DONE, CANCELLED, FAILED)),
            JobRequest.ended_at < now - timedelta(days=request_days),
        )
    )
    return Pruned(
        runs=int(getattr(runs, "rowcount", 0) or 0),
        requests=int(getattr(requests, "rowcount", 0) or 0),
    )
