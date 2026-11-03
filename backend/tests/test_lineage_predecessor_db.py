"""One projected predecessor per job, over real Postgres.

The projection must not depend on link order: keeping the last inbound edge of
an unordered read lets a re-detection that changes no decision (it deletes and
re-inserts its machine row) move a role between `duplicate` and `repost`, and
makes a co-predecessor a `repost` of a role it is not. The lineage stack shows
each member's effective link, never a pending proposal to a posting outside
the lineage. The detector never proposes a second predecessor for a job a
person has already linked.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.lineage_rows import lineage_job, lineage_link, seed_rows
from tracker.config import get_settings
from tracker.db.models import Job, JobLineageLink
from tracker.lineage import detect
from tracker.lineage.detect import rebuild_lineage_projection
from tracker.lineage.score import Candidate, Verdict

pytestmark = pytest.mark.asyncio


async def _roles(db_session) -> dict[int, str | None]:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as session:
        rows = (await session.execute(select(Job.id, Job.lineage_role))).all()
    return {r.id: r.lineage_role for r in rows}


async def _rebuild(db_session) -> None:
    await rebuild_lineage_projection(db_session)
    await db_session.commit()


async def _reinsert(db_session, row_id: int) -> None:
    """What a re-detection does to its machine row: delete, insert again
    (a new physical slot, last in a sequential scan)."""
    await db_session.execute(
        text(
            "WITH gone AS (DELETE FROM job_lineage_link WHERE id = :id RETURNING *) "
            "INSERT INTO job_lineage_link (job_id, prior_job_id, relation, method, score, "
            "confidence, status, detector_version, evidence, created_at) "
            "SELECT job_id, prior_job_id, relation, method, score, confidence, status, "
            "detector_version, evidence, now() FROM gone"
        ),
        {"id": row_id},
    )
    await db_session.commit()


async def test_a_redetection_that_decides_nothing_moves_no_role(db_session):
    """A human duplicate verdict outranks a machine repost even when the
    machine row is read last."""
    x, y, j = await seed_rows(db_session, lineage_job("x", 0), lineage_job("y", 1), lineage_job("j", 5))
    (machine,) = await seed_rows(db_session, lineage_link(j, y, "repost"))
    await seed_rows(db_session, lineage_link(j, x, "duplicate", human=True))
    await _rebuild(db_session)
    first = await _roles(db_session)

    await _reinsert(db_session, machine.id)
    await _rebuild(db_session)

    assert await _roles(db_session) == first
    assert first[j.id] == "duplicate"
    # y is linked by nothing but j's unchosen edge: it stays its own opening.
    assert first[y.id] is None
    assert first[x.id] == "original"


async def test_the_stack_shows_the_link_the_projection_used(api_client, db_session):
    """A lineage member exposes its confirmed predecessor, never a pending
    proposal to a posting outside the lineage."""
    a, b, outside = await seed_rows(db_session, lineage_job("a", 0), lineage_job("b", 5), lineage_job("z", 3))
    (confirmed,) = await seed_rows(db_session, lineage_link(b, a, "repost", human=True))
    await seed_rows(db_session, lineage_link(b, outside, "duplicate", confidence="suspected"))
    await _rebuild(db_session)

    body = (await api_client.get(f"/api/jobs/{b.id}/lineage")).json()
    shown = {m["job"]["id"]: m["link"] for m in body["members"]}
    assert shown[b.id]["id"] == confirmed.id
    assert shown[b.id]["prior_job_id"] == a.id
    assert shown[a.id] is None


async def test_the_detector_proposes_no_second_predecessor(db_session, monkeypatch):
    """A job with a human-confirmed predecessor must not receive another
    predecessor proposal during detection."""
    x, y, j = await seed_rows(db_session, lineage_job("x", 0), lineage_job("y", 1), lineage_job("j", 5))
    await seed_rows(db_session, lineage_link(j, x, "repost", human=True))
    j.embedding = [0.0] * get_settings().embedding_dim
    await db_session.commit()

    async def candidates(_session, job, *, k, place_sets=None):
        cand = Candidate(
            job_id=job.id, prior_job_id=y.id, cosine=0.95, title_display_equal=True,
            title_equal=True, title_jaccard=1.0, title_grade_compatible=True,
            concurrent=False, gap_days=4, location_overlap=True, both_locations_empty=False,
            location_jaccard=1.0, same_family=True, same_level_band=True,
            prior_lineage_size=1, has_descriptions=True, band_relation="unknown",
        )
        return [detect.ScoredCandidate(
            candidate=cand, verdict=Verdict("suspected", "repost", 0.95, "embedding", ["close"]),
            prior_title=y.title, prior_closed_at=None,
        )]

    monkeypatch.setattr(detect, "fetch_candidates", candidates)
    summary = await detect.detect_lineage(db_session, [j.id])

    rows = (await db_session.execute(select(JobLineageLink.prior_job_id, JobLineageLink.status))).all()
    assert sorted(tuple(r) for r in rows) == [(x.id, "confirmed")]
    assert summary["links_written"] == 0
