"""The API asks the supervisor for scans and stops only the one Sync asked for.

On real Postgres: the requests are the store's rows, and the cancel is the
supervisor's `cancel_requested_at`. No process exists in these tests; the
supervisor's side is `test_supervisor_dispatch.py`'s.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tracker.api import scan_requests
from tracker.db import job_store
from tracker.db.models import JobRequest, JobRun

pytestmark = pytest.mark.asyncio


async def _queued(session) -> list[tuple[str, str]]:
    session.expire_all()
    rows = await session.scalars(
        select(JobRequest).where(JobRequest.state == job_store.QUEUED).order_by(JobRequest.id)
    )
    return [(row.job, row.requested_by) for row in rows]


async def _running(session, *, requested_by: str, group: int) -> JobRun:
    await scan_requests.ring(session, requested_by=requested_by)
    _request, run = await job_store.claim(session, "scan")
    await job_store.mark_running(session, run.id, pid=group, pgid=group, proc_started_at=None)
    await session.commit()
    return run


async def test_repeated_syncs_ask_for_one_scan_and_a_first_scan_asks_for_its_own(db_session):
    for _ in range(3):
        await scan_requests.ring(db_session, requested_by=scan_requests.SYNC)
    await scan_requests.ring(db_session, requested_by=scan_requests.FIRST_SCAN)
    await db_session.commit()
    assert await _queued(db_session) == [("scan", "sync"), ("scan", "first_scan")]


async def test_the_header_stop_shows_while_sync_s_scan_is_queued_or_running_and_not_after(db_session):
    assert not await scan_requests.manual_sync_pending(db_session)
    await scan_requests.ring(db_session, requested_by=scan_requests.SYNC)
    await db_session.commit()
    assert await scan_requests.manual_sync_pending(db_session), "queued, waiting for its gate: still Sync's"

    _request, run = await job_store.claim(db_session, "scan")
    await db_session.commit()
    assert await scan_requests.manual_sync_pending(db_session), "starting: the startup gap is covered"

    await job_store.finish_run(db_session, run.id, state=job_store.EXITED, exit_code=0)
    await db_session.commit()
    assert not await scan_requests.manual_sync_pending(db_session)


async def test_a_first_scan_alone_does_not_show_the_header_stop(db_session):
    await _running(db_session, requested_by=scan_requests.FIRST_SCAN, group=4100)
    assert not await scan_requests.manual_sync_pending(db_session)


async def test_cancel_asks_the_supervisor_to_stop_sync_s_scan_and_names_its_group(db_session):
    run = await _running(db_session, requested_by=scan_requests.SYNC, group=4200)
    status, stopped = await scan_requests.stop_manual_scan(db_session, wait_seconds=0)
    assert (status, stopped.id, stopped.pgid) == ("cancelled", run.id, 4200)
    await db_session.refresh(run)
    assert run.cancel_reason == "sync_cancel"
    assert run.cancel_requested_at is not None


async def test_cancel_never_stops_a_first_scan_or_a_scheduled_tick(db_session):
    first = await _running(db_session, requested_by=scan_requests.FIRST_SCAN, group=4300)
    assert await scan_requests.stop_manual_scan(db_session, wait_seconds=0) == ("not_running", None)
    await db_session.refresh(first)
    assert first.cancel_requested_at is None

    await job_store.finish_run(db_session, first.id, state=job_store.EXITED, exit_code=0)
    scheduled = await job_store.open_run(db_session, "scan", "scan", trigger="schedule")
    await db_session.commit()
    assert await scan_requests.stop_manual_scan(db_session, wait_seconds=0) == ("not_running", None)
    await db_session.refresh(scheduled)
    assert scheduled.cancel_requested_at is None


async def test_cancel_drops_sync_s_queued_request_and_keeps_a_first_scan_s(db_session):
    await scan_requests.ring(db_session, requested_by=scan_requests.SYNC)
    await scan_requests.ring(db_session, requested_by=scan_requests.FIRST_SCAN)
    await db_session.commit()
    assert await scan_requests.stop_manual_scan(db_session, wait_seconds=0) == ("not_running", None)
    assert await _queued(db_session) == [("scan", "first_scan")]


async def test_cancel_answers_as_soon_as_the_supervisor_has_stopped_the_scan(db_session):
    run = await _running(db_session, requested_by=scan_requests.SYNC, group=4400)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def supervisor_stops_it() -> None:
        await asyncio.sleep(0.2)
        async with factory() as session:
            await job_store.finish_run(session, run.id, state=job_store.RUN_CANCELLED, exit_code=-15)
            await session.commit()

    stopper = asyncio.create_task(supervisor_stops_it())
    loop = asyncio.get_running_loop()
    began = loop.time()
    status, stopped = await scan_requests.stop_manual_scan(db_session, wait_seconds=10)
    await stopper
    assert status == "cancelled"
    assert stopped.state == job_store.RUN_CANCELLED
    assert loop.time() - began < 5, "it waited for the stop, not for its whole allowance"
