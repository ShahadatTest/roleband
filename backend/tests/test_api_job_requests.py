"""The API's requests for the directory sweep and the corpus re-embed.

On real Postgres. The re-embed stop is half of "stop and go back": it answers
"stopped" only once nothing of ours is live, so the tier is never restored under
a live encoder, and "error" when the run outlives its deadline.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tracker.api import job_requests
from tracker.db import job_store
from tracker.db.models import JobRequest

pytestmark = pytest.mark.asyncio


async def _queued(session, job: str) -> list[JobRequest]:
    session.expire_all()
    return list(
        await session.scalars(
            select(JobRequest).where(JobRequest.job == job, JobRequest.state == job_store.QUEUED)
        )
    )


async def test_directory_requests_coalesce_while_one_is_queued(db_session):
    await job_requests.ring_directory(db_session, requested_by="follow")
    await job_requests.ring_directory(db_session, requested_by="settings")
    await db_session.commit()
    assert len(await _queued(db_session, "directory")) == 1


async def test_a_re_embed_is_asked_for_once_and_committed(db_session):
    assert await job_requests.ring_reembed(db_session, requested_by="tier_switch")
    assert not await job_requests.ring_reembed(db_session, requested_by="tier_switch")
    factory = async_sessionmaker(db_session.bind)
    async with factory() as elsewhere:
        assert len(await _queued(elsewhere, "reembed")) == 1, "the supervisor sees it: it was committed"


async def test_stopping_a_queued_re_embed_cancels_it_and_reports_stopped(db_session):
    await job_requests.ring_reembed(db_session, requested_by="tier_switch")
    assert await job_requests.stop_reembed(db_session, wait_seconds=0) == ("stopped", None)
    assert await _queued(db_session, "reembed") == []


async def test_stopping_nothing_of_ours_reports_not_running(db_session):
    assert await job_requests.stop_reembed(db_session, wait_seconds=0) == ("not_running", None)


async def _live_reembed(db_session, group: int):
    await job_requests.ring_reembed(db_session, requested_by="tier_switch")
    _request, run = await job_store.claim(db_session, "reembed")
    await job_store.mark_running(db_session, run.id, pid=group, pgid=group, proc_started_at=None)
    await db_session.commit()
    return run


async def test_a_live_re_embed_is_stopped_before_the_stop_says_so(db_session):
    run = await _live_reembed(db_session, 5100)
    run_id = run.id
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def supervisor_stops_it() -> None:
        await asyncio.sleep(0.2)
        async with factory() as session:
            await job_store.finish_run(session, run_id, state=job_store.RUN_CANCELLED, exit_code=-15)
            await session.commit()

    stopper = asyncio.create_task(supervisor_stops_it())
    outcome = await job_requests.stop_reembed(db_session, wait_seconds=10)
    await stopper
    assert outcome == ("stopped", 5100)
    await db_session.refresh(run)
    assert run.cancel_reason == "tier_stop"


async def test_a_re_embed_still_live_at_the_deadline_is_an_error_so_the_tier_stays(db_session):
    await _live_reembed(db_session, 5200)
    assert await job_requests.stop_reembed(db_session, wait_seconds=0.2) == ("error", 5200)
