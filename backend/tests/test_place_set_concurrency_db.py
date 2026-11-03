"""Place-set writers and human decisions under concurrency.

`rebuild_place_sets` reads the human decisions (rejected members, decided
pairs), then writes; `review_place_set_member` and the lineage/twin verdict
commands each run in their own transaction. Unserialized, a decision committed
between the builder's reads and its writes is overwritten by the older
grouping: a split keeps stale size and places, a dissolved set comes back around
one member, an Undo is deleted, a set forms around a pair just decided. A split
during the builder's writes, and a twin verdict against a rebuild, can deadlock
into a 500.

Each test pauses a real builder (its own session, as the post pass) after its
reads, lets the decision run concurrently until it queues on the builder's
lock, then releases the builder. The rule
asserted is the outcome, whatever the order: the later human decision stands,
the stored sets equal what a fresh rebuild produces, and nothing fails.
Real Postgres; every read-back is a fresh session.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

import tracker.lineage.place_sets as ps
from tests.barriers import until_waiting
from tests.place_set_rows import pending_duplicate, place_set_job
from tracker.db.models import JobLineageLink, JobTwinLink
from tracker.lineage.detect import rebuild_lineage_projection
from tracker.lineage.place_sets import rebuild_place_sets, review_place_set_member
from tracker.lineage.review import decide_lineage_link, decide_twin_link

pytestmark = pytest.mark.asyncio


async def _snapshot(factory) -> tuple:
    async with factory() as session:
        sets = (
            await session.execute(
                text("SELECT size, places FROM job_place_set ORDER BY company, title, id")
            )
        ).all()
        members = (
            await session.execute(
                text(
                    "SELECT m.job_id, m.status, s.size FROM job_place_set_member m "
                    "LEFT JOIN job_place_set s ON s.id = m.set_id ORDER BY m.job_id"
                )
            )
        ).all()
    return [tuple(r) for r in sets], [tuple(r) for r in members]


async def _is_fresh(factory) -> None:
    """The stored sets are what a rebuild from the current decisions writes."""
    before = await _snapshot(factory)
    async with factory() as session:
        await rebuild_place_sets(session)
    assert await _snapshot(factory) == before


async def _race(db_session, monkeypatch, decide):
    """Pause a builder after its reads, run `decide` beside it, release the
    builder, and return (builder result, decision result), exceptions kept."""
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    gate, paused = asyncio.Event(), asyncio.Event()
    read_rejected = ps._rejected_ids
    async with factory() as builder_session:

        async def paused_read(session, ids):
            result = await read_rejected(session, ids)
            if session is builder_session and not paused.is_set():
                paused.set()
                await gate.wait()
            return result

        monkeypatch.setattr(ps, "_rejected_ids", paused_read)
        build = asyncio.create_task(rebuild_place_sets(builder_session))
        await asyncio.wait_for(paused.wait(), 10)
        decision = asyncio.create_task(decide(factory))
        # Unlocked, the decision commits while the builder is paused; locked,
        # it queues on the builder's lock.
        await until_waiting(db_session.bind, decision)
        queued = not decision.done()
        gate.set()
        results = await asyncio.wait_for(
            asyncio.gather(build, decision, return_exceptions=True), 30
        )
    assert queued, "the decision waits for the builder's lock instead of committing past its reads"
    return results


async def _three(db_session):
    a = await place_set_job(db_session, 1, "London")
    x = await place_set_job(db_session, 2, "Bristol")
    y = await place_set_job(db_session, 3, "Leeds")
    await db_session.commit()
    await rebuild_place_sets(db_session)
    return a, x, y


async def _review(factory, job_id, decision):
    async with factory() as session:
        return await review_place_set_member(session, job_id, decision)


async def test_a_split_during_a_rebuild_stands_and_the_set_is_current(db_session, monkeypatch):
    """Broken rule caught: the builder's older grouping kept the split
    member's places and size 3 on the set."""
    a, x, y = await _three(db_session)
    built, decided = await _race(
        db_session, monkeypatch, lambda f: _review(f, x.id, "different")
    )
    assert not isinstance(built, Exception), built
    assert not isinstance(decided, Exception), decided

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    sets, members = await _snapshot(factory)
    assert sets == [(2, ["Leeds, UK", "London, UK"])] or sets == [(2, ["London, UK", "Leeds, UK"])]
    assert (x.id, "rejected", None) in members or any(
        m[0] == x.id and m[1] == "rejected" for m in members
    )
    await _is_fresh(factory)


async def test_splitting_one_of_two_during_a_rebuild_leaves_no_set(db_session, monkeypatch):
    """Broken rule caught: the builder recreated the dissolved set around the
    one member left."""
    await place_set_job(db_session, 1, "London")
    x = await place_set_job(db_session, 2, "Bristol")
    await db_session.commit()
    await rebuild_place_sets(db_session)

    built, decided = await _race(
        db_session, monkeypatch, lambda f: _review(f, x.id, "different")
    )
    assert not isinstance(built, Exception), built
    assert not isinstance(decided, Exception), decided
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    sets, members = await _snapshot(factory)
    assert sets == []
    assert [m[:2] for m in members] == [(x.id, "rejected")]
    await _is_fresh(factory)


async def test_an_undo_during_a_rebuild_is_kept(db_session, monkeypatch):
    """Broken rule caught: the builder's stale-member DELETE removed the row
    the Undo put back, so the posting was neither a member nor split out."""
    a, x, y = await _three(db_session)
    await review_place_set_member(db_session, x.id, "different")

    built, decided = await _race(db_session, monkeypatch, lambda f: _review(f, x.id, "pending"))
    assert not isinstance(built, Exception), built
    assert not isinstance(decided, Exception), decided
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    sets, members = await _snapshot(factory)
    assert sets and sets[0][0] == 3
    assert (x.id, "auto", 3) in members
    await _is_fresh(factory)


async def test_a_verdict_during_a_rebuild_never_leaves_a_set_holding_a_decided_pair(
    db_session, monkeypatch
):
    """Broken rule caught: a "Related roles" verdict committed in the window,
    then the builder formed set {a, x} from its older read; the twin and the
    set both stood. Locked, either order is consistent: the verdict first
    keeps the pair out of any set, or the rebuild first withdraws the pending
    proposal and the verdict finds nothing to decide (404)."""
    a = await place_set_job(db_session, 1, "London")
    x = await place_set_job(db_session, 2, "Bristol")
    link = pending_duplicate(x, a)
    db_session.add(link)
    await db_session.commit()

    async def verdict(factory):
        async with factory() as session:
            result = await decide_lineage_link(session, link.id, "twin")
            await rebuild_lineage_projection(session)
            await session.commit()
            return result

    built, decided = await _race(db_session, monkeypatch, verdict)
    assert not isinstance(built, Exception), built
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as session:
        twins = (await session.execute(select(JobTwinLink.status))).scalars().all()
    sets, members = await _snapshot(factory)
    if isinstance(decided, Exception):
        assert type(decided).__name__ == "LinkNotFound", decided
        assert twins == []
    else:
        assert twins == ["confirmed"]
        assert sets == [] and members == []
    await _is_fresh(factory)


async def test_a_twin_verdict_and_a_rebuild_never_deadlock(db_session):
    """Broken rule caught (the twin-first lock order): a verdict that locks
    the twin row, then the lineage counterparts, against a rebuild that
    deletes pending lineage rows, then pending twin rows. Postgres aborts one."""
    a = await place_set_job(db_session, 1, "London")
    b = await place_set_job(db_session, 2, "Bristol")
    lo, hi = sorted((a.id, b.id))
    db_session.add_all(
        [
            pending_duplicate(b, a),
            JobTwinLink(
                job_a_id=lo, job_b_id=hi, method="content_overlap", confidence="suspected",
                status="pending", detector_version="twin/v1", evidence={},
            ),
        ]
    )
    await db_session.commit()
    twin_id = (await db_session.execute(select(JobTwinLink.id))).scalar_one()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    gate, paused = asyncio.Event(), asyncio.Event()

    async with factory() as verdict_session, factory() as pass_session:
        execute = verdict_session.execute

        async def paused_execute(stmt, *args, **kwargs):
            # Pause once the verdict holds the twin row, before it locks the
            # lineage counterpart (the inverted order).
            if "FROM job_lineage_link AS t" in str(stmt) and not gate.is_set():
                paused.set()
                await gate.wait()
            return await execute(stmt, *args, **kwargs)

        verdict_session.execute = paused_execute  # type: ignore[method-assign]

        async def verdict():
            await decide_twin_link(verdict_session, twin_id, "confirmed")
            await rebuild_lineage_projection(verdict_session)
            await verdict_session.commit()

        decided = asyncio.create_task(verdict())
        await asyncio.wait_for(paused.wait(), 10)
        rebuilt = asyncio.create_task(rebuild_place_sets(pass_session))
        await until_waiting(db_session.bind, rebuilt)
        queued = not rebuilt.done()
        gate.set()
        results = await asyncio.wait_for(
            asyncio.gather(decided, rebuilt, return_exceptions=True), 30
        )

    assert queued, "the rebuild waits for the verdict's lock"
    assert not any(isinstance(r, Exception) for r in results), results
    async with factory() as session:
        twins = (await session.execute(select(JobTwinLink.status))).scalars().all()
        links = (await session.execute(select(JobLineageLink.status))).scalars().all()
    assert twins == ["confirmed"]
    assert links == ["rejected"]  # the verdict's counterpart, never withdrawn
    await _is_fresh(factory)
