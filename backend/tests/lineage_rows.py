"""Postings, proposals and links for the lineage and twin tests over real
Postgres, and the route call their verdicts go through.

Every read-back helper opens a fresh session, so nothing is read from a
handler's own identity map.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tracker.db.models import Job, JobLineageLink, JobTwinLink
from tracker.schema import dedupe_key_for

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def lineage_job(key: str, days: int, company: str = "google") -> Job:
    """A staff product manager posting at `company`, first seen `days` after
    `T0` and last seen three days later."""
    first_seen = T0 + timedelta(days=days)
    return Job(
        company=company,
        req_id=key,
        dedupe_key=dedupe_key_for(company, key),
        title="Staff Product Manager, Inference",
        url=f"https://careers.example.test/{company}/{key}",
        first_seen=first_seen,
        last_seen=first_seen + timedelta(days=3),
        status="open",
        level_band="staff",
    )


async def seed_rows(db_session: AsyncSession, *rows) -> list:
    """Add and commit `rows`, and return them in order."""
    db_session.add_all(rows)
    await db_session.commit()
    return list(rows)


async def seed_pair(db_session):
    """Two postings of one company, the second listed later."""
    older, newer = await seed_rows(db_session, lineage_job("a", 0), lineage_job("b", 10))
    return older, newer


def duplicate_proposal(older: Job, newer: Job, **over) -> JobLineageLink:
    """The detector's pending proposal that `newer` duplicates `older`."""
    row = dict(
        job_id=newer.id,
        prior_job_id=older.id,
        relation="duplicate",
        method="embedding",
        confidence="suspected",
        status="pending",
        detector_version="lineage/test",
        evidence={"reasons": ["close pair"]},
    )
    row.update(over)
    return JobLineageLink(**row)


def twin_proposal(older: Job, newer: Job, **over) -> JobTwinLink:
    """The detector's pending proposal that the two are twins, lower id first."""
    a, b = sorted((older.id, newer.id))
    row = dict(
        job_a_id=a,
        job_b_id=b,
        method="content_overlap",
        confidence="suspected",
        status="pending",
        detector_version="twins/test",
        evidence={"reasons": ["shared text"]},
    )
    row.update(over)
    return JobTwinLink(**row)


def lineage_link(job: Job, prior: Job, relation: str, *, human: bool = False, **over) -> JobLineageLink:
    """A link from `job` to `prior`: the detector's pending one, or with
    `human` a person's confirmed one, reviewed thirty days after `T0`."""
    row = dict(
        job_id=job.id, prior_job_id=prior.id, relation=relation, method="embedding",
        confidence="auto", status="confirmed" if human else "pending",
        detector_version="lineage/test", score=0.97, evidence={},
        reviewed_at=T0 + timedelta(days=30) if human else None,
    )
    row.update(over)
    return JobLineageLink(**row)


def fresh_sessions(db_session):
    """A session factory on the scratch database, for read-backs that must
    not see the writer's identity map."""
    return async_sessionmaker(db_session.bind, expire_on_commit=False)


async def review_link(api_client, kind: str, link_id: int, verdict: str, expected: int = 200) -> dict:
    """Post a verdict on a duplicate or twin link through the real route."""
    path = f"/api/lineage/links/{link_id}/review" if kind == "duplicate" else f"/api/twins/links/{link_id}/review"
    response = await api_client.post(path, json={"verdict": verdict})
    assert response.status_code == expected, response.text
    return response.json()
