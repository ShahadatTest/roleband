"""How the API asks for a scan and stops the one the user asked for.

A scan is a request to the supervisor (`tracker.db.job_store`), never a process
the API starts. What to scan stays in the scheduler's own queue
(`SyncScheduleState.manual_requested_at`); the request only says "look now".

Sync's requests carry `manual`, so they never merge with a first scan's: the
header's Cancel stops what Sync asked for and nothing else, as it always has.
"""

from __future__ import annotations

import asyncio
import time

from sqlalchemy import ColumnElement, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db import job_store
from tracker.db.models import JobRequest, JobRun

SCAN = "scan"
#: The header's Sync, the only scan its Cancel stops.
SYNC = "sync"
#: A company the user just followed.
FIRST_SCAN = "first_scan"

#: A cancel waits this long for the supervisor to stop the run before it
#: answers; the stop itself goes on regardless.
STOP_WAIT_SECONDS = 5.0


async def ring(session: AsyncSession, *, requested_by: str) -> None:
    """Ask for a scan now, in the caller's transaction."""
    args = {"manual": True} if requested_by == SYNC else {}
    await job_store.ring(session, SCAN, requested_by=requested_by, args=args)


def _manual_live():
    return (
        select(JobRun)
        .join(JobRequest, JobRequest.id == JobRun.request_id)
        .where(
            JobRun.key == SCAN,
            JobRun.state.in_(job_store.LIVE),
            JobRequest.requested_by == SYNC,
        )
    )


async def manual_scan_run(session: AsyncSession) -> JobRun | None:
    """The live scan Sync started, if any."""
    return await session.scalar(_manual_live().order_by(JobRun.id.desc()).limit(1))


def manual_sync_clause() -> ColumnElement[bool]:
    """Sync asked for a scan that has not ended: queued, waiting for its gate, or
    running. The header's Stop shows exactly while this holds. A clause, so the
    status read asks it in the same statement as its other questions."""
    queued = exists().where(
        JobRequest.key == SCAN, JobRequest.state == job_store.QUEUED, JobRequest.requested_by == SYNC
    )
    return queued | exists(_manual_live().with_only_columns(JobRun.id))


async def manual_sync_pending(session: AsyncSession) -> bool:
    return bool(await session.scalar(select(manual_sync_clause())))


async def stop_manual_scan(
    session: AsyncSession, *, wait_seconds: float | None = None, poll_seconds: float = 0.1
) -> tuple[str, JobRun | None]:
    """Cancel Sync's queued requests and stop its live scan.

    Commits, because the supervisor acts only on a committed cancel. Returns
    ("cancelled", run) for a live run it asked to stop, else ("not_running", None).
    """
    await job_store.cancel_queued(session, key=SCAN, requested_by=SYNC)
    run = await manual_scan_run(session)
    if run is None:
        await session.commit()
        return "not_running", None
    await job_store.request_cancel(session, run.id, reason="sync_cancel")
    await session.commit()
    deadline = time.monotonic() + (STOP_WAIT_SECONDS if wait_seconds is None else wait_seconds)
    while time.monotonic() < deadline:
        await session.refresh(run)
        if run.state not in job_store.LIVE:
            break
        await asyncio.sleep(poll_seconds)
    return "cancelled", run
