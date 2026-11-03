"""Cached and live neighbours answer to one contract.

The live query offers only open, in-scope neighbours. A cache read by source id
and scope alone, where any cached row suppresses the live fallback, would still
serve a neighbour that closed or left scope after the rebuild, and after a
re-embed would keep presenting the old neighbour at its old score. Real
Postgres and pgvector ranking; the real route function.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tests.factories import make_job
from tracker.api.routers.jobs import similar_jobs
from tracker.company_store import OffBoardSlugs
from tracker.config import get_settings
from tracker.db.models import JobSimilarity
from tracker.semantic import similarity
from tracker.semantic.similarity import refresh_similarity

pytestmark = pytest.mark.asyncio


def _unit(*weights: float) -> list[float]:
    vec = [0.0] * get_settings().embedding_dim
    for axis, weight in enumerate(weights):
        vec[axis] = weight
    norm = sum(w * w for w in vec) ** 0.5
    return [w / norm for w in vec]


async def _corpus(db_session):
    """An origin and three cross-company neighbours, nearest first."""
    origin = make_job("origin", embedding=_unit(1, 0))
    near = make_job("near", company="apple", dedupe_key="apple:near", embedding=_unit(1, 0.1))
    mid = make_job("mid", company="meta", dedupe_key="meta:mid", embedding=_unit(1, 0.3))
    far = make_job("far", company="openai", dedupe_key="openai:far", embedding=_unit(1, 0.6))
    db_session.add_all([origin, near, mid, far])
    await db_session.commit()
    await refresh_similarity(db_session, full=True)
    await db_session.commit()
    return origin, near, mid, far


async def _similar(db_session, origin, *, limit: int, hidden=()) -> list[int]:
    body = await similar_jobs(origin.id, db_session, OffBoardSlugs(hidden), scope="cross", limit=limit)
    return [item["id"] for item in body["items"]]


async def test_the_control_serves_the_nearest_from_the_cache(db_session, monkeypatch):
    origin, near, mid, _far = await _corpus(db_session)
    live_reads: list[int] = []
    real = similarity._live_neighbors

    async def counted(*args, **kwargs):
        live_reads.append(1)
        return await real(*args, **kwargs)

    monkeypatch.setattr(similarity, "_live_neighbors", counted)
    assert await _similar(db_session, origin, limit=2) == [near.id, mid.id]
    assert live_reads == [], "a valid cache needs no ANN read"


async def test_a_neighbour_that_closed_or_left_scope_takes_no_slot(db_session):
    origin, near, mid, far = await _corpus(db_session)
    near.status, near.closed_at = "closed", datetime.now(UTC)
    mid.in_scope = False
    await db_session.commit()
    assert await _similar(db_session, origin, limit=2) == [far.id]


async def test_a_hidden_companys_neighbour_takes_no_slot(db_session):
    origin, near, mid, far = await _corpus(db_session)
    assert await _similar(db_session, origin, limit=2, hidden=["apple"]) == [mid.id, far.id]


@pytest.mark.parametrize("moved", ["origin", "neighbour"])
async def test_a_re_embedded_posting_is_not_served_its_old_neighbours(db_session, moved):
    origin, near, mid, far = await _corpus(db_session)
    if moved == "origin":
        origin.embedding = _unit(1, 0.6)  # now nearest to `far`
        expected_first = far.id
    else:
        near.embedding = _unit(0, 1)  # moved away: near nothing
        expected_first = mid.id
    await db_session.commit()
    first, *_ = await _similar(db_session, origin, limit=3)
    assert first == expected_first


async def test_no_stale_score_is_presented_as_current(db_session):
    origin, near, *_ = await _corpus(db_session)
    near.embedding = _unit(0, 1)
    await db_session.commit()
    body = await similar_jobs(origin.id, db_session, OffBoardSlugs(), scope="cross", limit=3)
    scores = {item["id"]: item["score"] for item in body["items"]}
    assert scores.get(near.id, 0.0) < 0.5  # its cached 0.995 is gone with its vector
    stored = dict((await db_session.execute(
        select(JobSimilarity.neighbor_job_id, JobSimilarity.score).where(JobSimilarity.job_id == origin.id)
    )).all())
    assert stored[near.id] > 0.99, "the control: the cache still holds the old score"
