"""The header's New count and the New lens: roles listed in the last two days,
on the open board. A company's first read reads a board that was already
listing, so nothing it finds is new by our sighting alone, and New never counts
a role the open board leaves out, so New is always part of Open."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from tests.factories import make_job
from tracker.db.models import Job, JobLifecycleEvent, ScrapeRun


async def _run(session, started_at: datetime) -> ScrapeRun:
    run = ScrapeRun(status="ok", started_at=started_at, per_source={}, drift_alerts=[])
    session.add(run)
    await session.flush()
    return run


async def _opened(session, run: ScrapeRun, req_id: str, *, at: datetime, arrival: str, **over) -> Job:
    job = make_job(req_id, first_seen=at, last_seen=at, arrival=arrival, **over)
    session.add(job)
    await session.flush()
    session.add(JobLifecycleEvent(job_id=job.id, run_id=run.id, event_type="opened", created_at=at))
    return job


async def _counts(client) -> tuple[int, int, set[int], set[int]]:
    stats = (await client.get("/api/stats")).json()
    lens = (await client.get("/api/jobs", params={"limit": 100, "new_today_only": "true"})).json()
    board = (await client.get("/api/jobs", params={"limit": 100})).json()
    assert lens["total"] == stats["new_today"] and board["total"] == stats["open_total"]
    return (stats["open_total"], stats["new_today"],
            {item["id"] for item in board["items"]}, {item["id"] for item in lens["items"]})


@pytest.mark.asyncio
async def test_a_fresh_install_first_scan_finds_nothing_new(api_client, db_session):
    now = datetime.now(UTC)
    first = await _run(db_session, now)
    await _opened(db_session, first, "r1", at=now, arrival="first_read")
    await _opened(db_session, first, "r2", at=now, arrival="first_read")
    await _opened(db_session, first, "outside", at=now, arrival="first_read", in_scope=False)
    await db_session.commit()

    open_total, new_today, _, _ = await _counts(api_client)
    assert (open_total, new_today) == (2, 0)


@pytest.mark.asyncio
async def test_new_counts_only_roles_on_the_open_board(api_client, db_session):
    now = datetime.now(UTC)
    first = await _run(db_session, now - timedelta(days=2))
    await _opened(db_session, first, "listed", at=now - timedelta(days=2), arrival="first_read")
    later = await _run(db_session, now)
    fresh = await _opened(db_session, later, "fresh", at=now, arrival="new")
    outside = await _opened(db_session, later, "outside", at=now, arrival="new", in_scope=False)
    await db_session.commit()

    open_total, new_today, board, lens = await _counts(api_client)
    assert (open_total, new_today) == (2, 1)
    assert lens == {fresh.id} and lens <= board and outside.id not in board | lens

    # A scope save that drops the role takes it off New with the board.
    await db_session.execute(update(Job).where(Job.id == fresh.id).values(in_scope=False))
    await db_session.commit()
    open_total, new_today, board, lens = await _counts(api_client)
    assert (open_total, new_today, lens) == (1, 0, set())
