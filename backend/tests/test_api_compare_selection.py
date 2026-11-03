"""The compare selection over HTTP. Real Postgres, because the point is SQL.

The reason this table exists rather than a blob in the browser is referential
integrity: a selection id must not outlive its job and inflate the rail count.
That constraint is `ondelete="CASCADE"`, which a faked session
would answer by fiat. Same for the unique constraint and for replace-all
leaving no partial state behind.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from tracker.api.routers.jobs import (
    COMPARE_CAP,
    CompareSelectionPayload,
    get_compare_selection,
    put_compare_selection,
)
from tracker.db.models import CompareSelection, Job

pytestmark = pytest.mark.asyncio

NOW = datetime.now(UTC)


async def _job(session, title: str) -> Job:
    job = Job(
        company="google",
        title=title,
        url=f"https://example.test/google/{title}",
        level_band="L6",
        req_id=f"r-{title}",
        dedupe_key=f"k-{title}",
        status="open",
        first_seen=NOW - timedelta(days=5),
        last_seen=NOW,
        total_days_open=5,
        repost_count=0,
        in_scope=True,
    )
    session.add(job)
    await session.flush()
    return job


async def _jobs(session, count: int) -> list[Job]:
    return [await _job(session, f"Staff PM {n}") for n in range(count)]


async def test_selection_round_trips_in_the_order_it_was_picked(db_session):
    """The beacon docks level with the role selected LAST, so order is contract."""
    jobs = await _jobs(db_session, 3)
    picked = [jobs[2].id, jobs[0].id, jobs[1].id]

    stored = await put_compare_selection(CompareSelectionPayload(job_ids=picked), db_session)
    assert stored.job_ids == picked

    read_back = await get_compare_selection(db_session)
    assert read_back.job_ids == picked


async def test_empty_read_before_anything_is_selected(db_session):
    assert (await get_compare_selection(db_session)).job_ids == []


async def test_deleting_a_job_removes_it_from_the_selection(db_session):
    """The whole reason this is a table: the count cannot outlive the role.

    Held in a browser blob, the id would survive its job, the roster fetch would
    404, and the pill would say 3 while 2 rows rendered.
    """
    jobs = await _jobs(db_session, 3)
    await put_compare_selection(
        CompareSelectionPayload(job_ids=[j.id for j in jobs]), db_session
    )

    await db_session.delete(jobs[1])
    await db_session.commit()

    assert (await get_compare_selection(db_session)).job_ids == [jobs[0].id, jobs[2].id]


async def test_unknown_ids_are_dropped_not_refused(db_session):
    """A job that closed while the tab was open is not a client bug."""
    jobs = await _jobs(db_session, 2)
    ghost = jobs[1].id + 5000

    stored = await put_compare_selection(
        CompareSelectionPayload(job_ids=[jobs[0].id, ghost, jobs[1].id]), db_session
    )

    assert stored.job_ids == [jobs[0].id, jobs[1].id]
    assert (await get_compare_selection(db_session)).job_ids == [jobs[0].id, jobs[1].id]


async def test_the_cap_is_enforced_by_the_store_not_only_the_client(db_session):
    jobs = await _jobs(db_session, COMPARE_CAP + 3)

    stored = await put_compare_selection(
        CompareSelectionPayload(job_ids=[j.id for j in jobs]), db_session
    )

    assert stored.job_ids == [j.id for j in jobs[:COMPARE_CAP]]
    count = await db_session.scalar(select(func.count()).select_from(CompareSelection))
    assert count == COMPARE_CAP


async def test_a_selection_stored_under_a_larger_cap_is_clamped_on_read(db_session):
    """A stored selection can be larger than the cap.

    Written straight to the table so the case is a selection over the cap; a
    PUT could not produce it. The read is what a reload
    restores, so the clamp has to be there and not only on the write, or the
    reload can paint four columns on a three-column screen.
    """
    jobs = await _jobs(db_session, COMPARE_CAP + 1)
    for position, job in enumerate(jobs):
        db_session.add(CompareSelection(job_id=job.id, position=position))
    await db_session.flush()

    stored = await get_compare_selection(db_session)

    assert stored.job_ids == [j.id for j in jobs[:COMPARE_CAP]]


async def test_repeated_ids_collapse_keeping_the_first_position(db_session):
    """Order-preserving dedupe: the unique constraint would otherwise reject."""
    jobs = await _jobs(db_session, 2)

    stored = await put_compare_selection(
        CompareSelectionPayload(job_ids=[jobs[0].id, jobs[1].id, jobs[0].id]), db_session
    )

    assert stored.job_ids == [jobs[0].id, jobs[1].id]


async def test_replacing_leaves_nothing_of_the_previous_selection(db_session):
    jobs = await _jobs(db_session, 4)
    await put_compare_selection(
        CompareSelectionPayload(job_ids=[jobs[0].id, jobs[1].id]), db_session
    )

    stored = await put_compare_selection(
        CompareSelectionPayload(job_ids=[jobs[2].id, jobs[3].id]), db_session
    )

    assert stored.job_ids == [jobs[2].id, jobs[3].id]
    rows = (await db_session.scalars(select(CompareSelection.job_id))).all()
    assert sorted(rows) == sorted([jobs[2].id, jobs[3].id])


async def test_clearing_writes_an_empty_selection(db_session):
    jobs = await _jobs(db_session, 2)
    await put_compare_selection(
        CompareSelectionPayload(job_ids=[j.id for j in jobs]), db_session
    )

    stored = await put_compare_selection(CompareSelectionPayload(job_ids=[]), db_session)

    assert stored.job_ids == []
    count = await db_session.scalar(select(func.count()).select_from(CompareSelection))
    assert count == 0
