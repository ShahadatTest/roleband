"""The neighbour table is refreshed at the cost of what changed.

A full rebuild recomputes every posting's neighbours on every run, which on a
real corpus is hours of queries for a table that barely moves. The refresh
recomputes only the sources whose answer can have changed, and the contract is
that it lands on exactly the table a full rebuild writes. Real Postgres and
pgvector ranking.
"""

from __future__ import annotations

import math
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from tests.factories import T0, make_job
from tracker.config import get_settings
from tracker.db.models import Job, JobSimilarity
from tracker.semantic import similarity
from tracker.semantic.similarity import FULL_EVERY, refresh_similarity

pytestmark = pytest.mark.asyncio

K = 2


def _at(degrees: float) -> list[float]:
    """A unit vector at an angle in the first plane: cosine falls with the angle
    between two postings, so the nearest neighbours are the nearest angles."""
    vec = [0.0] * get_settings().embedding_dim
    vec[0], vec[1] = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return vec


def _posting(key: str, company: str, degrees: float, **over) -> Job:
    over.setdefault("embedded_at", T0)
    return make_job(key, company=company, dedupe_key=f"{company}:{key}", embedding=_at(degrees), **over)


async def _table(db_session) -> set[tuple[int, str, int, int]]:
    rows = (await db_session.execute(select(JobSimilarity))).scalars().all()
    return {(r.job_id, r.scope, r.rank, r.neighbor_job_id) for r in rows}


async def _refresh(db_session, *, at, full=False) -> int:
    written = await refresh_similarity(db_session, k=K, full=full, now=at)
    await db_session.commit()
    return written


async def _corpus(db_session) -> dict[str, Job]:
    # Distinct angles everywhere, so no two distances tie.
    jobs = {
        "a1": _posting("a1", "apple", 0), "a2": _posting("a2", "apple", 7), "a3": _posting("a3", "apple", 19),
        "g1": _posting("g1", "google", 3), "g2": _posting("g2", "google", 11), "g3": _posting("g3", "google", 31),
        "m1": _posting("m1", "meta", 5), "m2": _posting("m2", "meta", 23), "m3": _posting("m3", "meta", 61),
    }
    db_session.add_all(jobs.values())
    await db_session.commit()
    await _refresh(db_session, at=T0 + timedelta(minutes=1))
    return jobs


async def test_a_refresh_after_real_changes_is_the_table_a_full_rebuild_writes(db_session):
    jobs = await _corpus(db_session)
    later = T0 + timedelta(hours=1)
    # A new posting, one that closed, one re-embedded, one that left scope.
    db_session.add(_posting("n1", "openai", 9, embedded_at=later))
    await db_session.execute(update(Job).where(Job.id == jobs["g2"].id).values(status="closed"))
    await db_session.execute(
        update(Job).where(Job.id == jobs["m2"].id).values(embedding=_at(2), embedded_at=later)
    )
    await db_session.execute(update(Job).where(Job.id == jobs["a3"].id).values(in_scope=False))
    await db_session.commit()

    await _refresh(db_session, at=later + timedelta(minutes=1))
    refreshed = await _table(db_session)
    await _refresh(db_session, at=later + timedelta(minutes=2), full=True)
    assert refreshed == await _table(db_session)


async def test_nothing_changed_means_nothing_is_recomputed(db_session, monkeypatch):
    await _corpus(db_session)
    before = {r.id for r in (await db_session.execute(select(JobSimilarity))).scalars()}
    asked: list[int] = []
    live = similarity._live_neighbors

    async def counting(session, job_id, *args, **kwargs):
        asked.append(job_id)
        return await live(session, job_id, *args, **kwargs)

    monkeypatch.setattr(similarity, "_live_neighbors", counting)
    assert await _refresh(db_session, at=T0 + timedelta(hours=1)) == 0
    assert asked == []
    assert {r.id for r in (await db_session.execute(select(JobSimilarity))).scalars()} == before


async def test_an_arrival_joins_a_source_it_does_not_list_itself(db_session):
    """Nearest neighbours are not symmetric. A lone posting far from a tight
    group keeps two of the group; a new posting at the group's edge is nearer
    to it than its second, yet the lone one is not among the newcomer's own
    two. Reading displacement from the newcomer's list would miss it."""
    group = [_posting(f"c{i}", f"co{i}", angle) for i, angle in enumerate((0, 2, 4, 6))]
    lone = _posting("lone", "solo", 60)
    db_session.add_all([*group, lone])
    await db_session.commit()
    await _refresh(db_session, at=T0 + timedelta(minutes=1))

    later = T0 + timedelta(hours=1)
    edge = _posting("edge", "newco", 10, embedded_at=later)
    db_session.add(edge)
    await db_session.commit()
    await _refresh(db_session, at=later + timedelta(minutes=1))

    lone_cross = (await db_session.execute(
        select(JobSimilarity.neighbor_job_id).where(JobSimilarity.job_id == lone.id, JobSimilarity.scope == "cross")
        .order_by(JobSimilarity.rank)
    )).scalars().all()
    edge_cross = (await db_session.execute(
        select(JobSimilarity.neighbor_job_id).where(JobSimilarity.job_id == edge.id, JobSimilarity.scope == "cross")
    )).scalars().all()
    assert lone.id not in edge_cross, "the fixture must be asymmetric to prove anything"
    assert lone_cross[0] == edge.id


async def test_a_full_rebuild_still_runs_once_the_last_is_old_enough(db_session, monkeypatch):
    await _corpus(db_session)
    asked: list[int] = []
    live = similarity._live_neighbors

    async def counting(session, job_id, *args, **kwargs):
        asked.append(job_id)
        return await live(session, job_id, *args, **kwargs)

    monkeypatch.setattr(similarity, "_live_neighbors", counting)
    await _refresh(db_session, at=T0 + FULL_EVERY - timedelta(minutes=1))
    assert asked == []
    await _refresh(db_session, at=T0 + FULL_EVERY + timedelta(minutes=2))
    assert len(set(asked)) == 9, "every source, as the reopened posting no row records needs"


async def test_a_posting_re_embedded_next_to_a_source_joins_its_neighbours(db_session):
    """The only change is one posting's new text: its vector moves next to a
    source that did not list it and has no other reason to be recomputed."""
    jobs = await _corpus(db_session)
    a1_cross = select(JobSimilarity.neighbor_job_id).where(
        JobSimilarity.job_id == jobs["a1"].id, JobSimilarity.scope == "cross"
    ).order_by(JobSimilarity.rank)
    assert jobs["m3"].id not in (await db_session.execute(a1_cross)).scalars().all()

    later = T0 + timedelta(hours=1)
    await db_session.execute(
        update(Job).where(Job.id == jobs["m3"].id).values(embedding=_at(1), embedded_at=later)
    )
    await db_session.commit()
    await _refresh(db_session, at=later + timedelta(minutes=1))
    assert (await db_session.execute(a1_cross)).scalars().all()[0] == jobs["m3"].id
    refreshed = await _table(db_session)
    await _refresh(db_session, at=later + timedelta(minutes=2), full=True)
    assert refreshed == await _table(db_session)
