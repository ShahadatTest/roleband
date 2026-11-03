"""The lineage projection writes only what a link changed, over real Postgres.

The projection is rebuilt after every full run and inside every verdict
request. Rewriting every member each time is a non-HOT update through every
`jobs` index (the lineage columns are indexed) and re-mints the id of every
lineage. A row's `xmin` names the transaction that last wrote it, so a row the
rebuild left alone keeps it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import event, select, text

from tests.lineage_rows import fresh_sessions, lineage_job, lineage_link, review_link, seed_rows
from tracker.db.models import Job, JobLineage
from tracker.lineage.detect import rebuild_lineage_projection

pytestmark = pytest.mark.asyncio

_WRITE = re.compile(r"\s*(INSERT|UPDATE|DELETE)\b", re.IGNORECASE)


async def _jobs(db_session) -> dict[int, tuple]:
    """Each job's lineage columns and the transaction that last wrote its row."""
    async with fresh_sessions(db_session)() as session:
        rows = (
            await session.execute(
                text("SELECT id, lineage_id, lineage_seq, lineage_role, xmin::text AS writer FROM jobs")
            )
        ).all()
    return {r.id: (r.lineage_id, r.lineage_seq, r.lineage_role, r.writer) for r in rows}


async def _lineages(db_session) -> dict[int, tuple]:
    """Each lineage row by its root: id, size, updated_at, last writer."""
    async with fresh_sessions(db_session)() as session:
        rows = (
            await session.execute(
                text("SELECT id, root_job_id, size, updated_at, xmin::text AS writer FROM job_lineage")
            )
        ).all()
    return {r.root_job_id: (r.id, r.size, r.updated_at, r.writer) for r in rows}


@contextmanager
def _writes(db_session) -> Iterator[list[str]]:
    """Every INSERT, UPDATE or DELETE the engine sends while open."""
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if _WRITE.match(statement):
            seen.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


async def _rebuild(db_session) -> None:
    await rebuild_lineage_projection(db_session)
    await db_session.commit()


async def _two_lineages(db_session):
    """Lineage A (a1, a2), lineage B (b1, b2), and a posting in none."""
    a1, a2, b1, b2, alone = await seed_rows(
        db_session, lineage_job("a1", 0), lineage_job("a2", 5), lineage_job("b1", 1), lineage_job("b2", 6), lineage_job("alone", 2)
    )
    _, b_link = await seed_rows(db_session, lineage_link(a2, a1, "repost"), lineage_link(b2, b1, "repost"))
    await _rebuild(db_session)
    return (a1, a2, b1, b2, alone), b_link


def _changed(before: dict, after: dict, *keys: int) -> dict:
    return {key: (before[key], after[key]) for key in keys if before[key] != after[key]}


async def test_a_rebuild_with_no_link_change_writes_nothing(db_session):
    (a1, a2, b1, b2, alone), _ = await _two_lineages(db_session)
    jobs, lineages = await _jobs(db_session), await _lineages(db_session)
    assert set(lineages) == {a1.id, b1.id}
    assert jobs[a2.id][:3] == (lineages[a1.id][0], 2, "repost")
    assert jobs[alone.id][:3] == (None, None, None)

    with _writes(db_session) as writes:
        await _rebuild(db_session)

    assert writes == []
    assert await _jobs(db_session) == jobs
    assert await _lineages(db_session) == lineages


async def test_a_verdict_rewrites_only_its_own_lineage(api_client, db_session):
    (a1, a2, b1, b2, alone), _ = await _two_lineages(db_session)
    (b3,) = await seed_rows(db_session, lineage_job("b3", 9))
    (proposal,) = await seed_rows(db_session, lineage_link(b3, b2, "duplicate", confidence="suspected"))
    await _rebuild(db_session)
    jobs, lineages = await _jobs(db_session), await _lineages(db_session)
    assert jobs[b3.id][:3] == (None, None, None)

    await review_link(api_client, "duplicate", proposal.id, "confirmed")

    after_jobs, after_lineages = await _jobs(db_session), await _lineages(db_session)
    assert _changed(jobs, after_jobs, a1.id, a2.id, b1.id, b2.id, alone.id) == {}
    b_id = lineages[b1.id][0]
    assert after_jobs[b3.id][:3] == (b_id, 3, "duplicate")
    assert after_lineages[a1.id] == lineages[a1.id]
    assert after_lineages[b1.id][:2] == (b_id, 3)
    assert after_lineages[b1.id][2] > lineages[b1.id][2]


async def test_a_lineage_that_dissolves_clears_exactly_its_members(api_client, db_session):
    (a1, a2, b1, b2, alone), b_link = await _two_lineages(db_session)
    jobs, lineages = await _jobs(db_session), await _lineages(db_session)

    await review_link(api_client, "duplicate", b_link.id, "rejected")

    after = await _jobs(db_session)
    assert after[b1.id][:3] == after[b2.id][:3] == (None, None, None)
    assert _changed(jobs, after, a1.id, a2.id, alone.id) == {}
    assert await _lineages(db_session) == {a1.id: lineages[a1.id]}


async def test_two_lineages_that_join_keep_the_older_roots_row(db_session):
    (a1, a2, b1, b2, alone), _ = await _two_lineages(db_session)
    jobs, lineages = await _jobs(db_session), await _lineages(db_session)

    await seed_rows(db_session, lineage_link(b1, a1, "duplicate", human=True))
    await _rebuild(db_session)

    after, after_lineages = await _jobs(db_session), await _lineages(db_session)
    a_id = lineages[a1.id][0]
    assert list(after_lineages) == [a1.id]
    assert after_lineages[a1.id][:2] == (a_id, 4)
    assert [after[j.id][:3] for j in (a1, b1, a2, b2)] == [
        (a_id, 1, "original"), (a_id, 2, "duplicate"), (a_id, 3, "repost"), (a_id, 4, "repost"),
    ]
    assert _changed(jobs, after, a1.id, alone.id) == {}


async def test_a_new_earlier_root_takes_a_new_row_and_the_old_one_goes(db_session):
    (a1, a2, b1, b2, alone), _ = await _two_lineages(db_session)
    (z,) = await seed_rows(db_session, lineage_job("z", -3))
    await seed_rows(db_session, lineage_link(a1, z, "repost", human=True))
    await _rebuild(db_session)

    after, lineages = await _jobs(db_session), await _lineages(db_session)
    assert set(lineages) == {z.id, b1.id}
    z_id = lineages[z.id][0]
    assert [after[j.id][:3] for j in (z, a1, a2)] == [
        (z_id, 1, "original"), (z_id, 2, "repost"), (z_id, 3, "repost"),
    ]


async def test_a_session_holding_lineage_rows_compares_against_the_table(api_client, db_session):
    """The test's session rebuilds B at three members and keeps the rows it
    loaded; a verdict in another session takes B back to two; the link is
    restored and the test's session rebuilds again. Its copy of B still says
    three, the table says two: comparing against the copy would leave two."""
    (a1, a2, b1, b2, alone), _ = await _two_lineages(db_session)
    (b3,) = await seed_rows(db_session, lineage_job("b3", 9))
    (link,) = await seed_rows(db_session, lineage_link(b3, b2, "duplicate", human=True))
    await _rebuild(db_session)
    held = (await db_session.scalars(select(JobLineage))).all()
    assert {row.root_job_id: row.size for row in held} == {a1.id: 2, b1.id: 3}

    assert (await api_client.delete(f"/api/lineage/links/{link.id}")).status_code == 200
    assert (await _lineages(db_session))[b1.id][1] == 2

    await db_session.execute(
        text("UPDATE job_lineage_link SET status = 'confirmed' WHERE id = :id"), {"id": link.id}
    )
    await _rebuild(db_session)

    lineages = await _lineages(db_session)
    assert lineages[b1.id][1] == 3
    assert (await _jobs(db_session))[b3.id][:3] == (lineages[b1.id][0], 3, "duplicate")


async def test_the_rebuilding_sessions_own_jobs_take_the_new_projection(db_session):
    """A later pass in the same session (the twin detector) reads
    `lineage_id` off the `Job` objects that session already loaded."""
    a1, a2 = await seed_rows(db_session, lineage_job("a1", 0), lineage_job("a2", 5))
    (link,) = await seed_rows(db_session, lineage_link(a2, a1, "repost"))
    held = (await db_session.scalars(select(Job).execution_options(populate_existing=True))).all()
    assert {(j.lineage_id, j.lineage_role) for j in held} == {(None, None)}

    await _rebuild(db_session)
    (lineage_id, _, _, _), = (await _lineages(db_session)).values()
    assert (a1.lineage_id, a1.lineage_role, a2.lineage_id, a2.lineage_seq, a2.lineage_role) == (
        lineage_id, "original", lineage_id, 2, "repost",
    )

    await db_session.execute(
        text("UPDATE job_lineage_link SET status = 'rejected' WHERE id = :id"), {"id": link.id}
    )
    await _rebuild(db_session)
    assert (a2.lineage_id, a2.lineage_seq, a2.lineage_role, a2.lineage_first_seen) == (None, None, None, None)
