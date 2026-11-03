"""Postings and proposals for the place-set tests over real Postgres: one
AECOM role, its description and its embedding, listed in several cities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tracker.config import get_settings
from tracker.db.models import Job, JobLineageLink
from tracker.schema import dedupe_key_for

NOW = datetime.now(UTC)
TITLE = "Project Director - Controls Analytics"
BODY = (
    "AECOM is seeking a Project Director to lead controls analytics across our "
    "infrastructure portfolio. You will own schedule and cost performance, build "
    "the reporting the programme board reads, and grow a team of analysts. "
) * 6


def unit_vector(seed: int = 0) -> list[float]:
    """An embedding with one dimension set: equal seeds are identical."""
    dim = get_settings().embedding_dim
    vec = [0.0] * dim
    vec[seed % dim] = 1.0
    return vec


async def place_set_job(
    session,
    n: int,
    city: str,
    *,
    title: str = TITLE,
    body: str = BODY,
    status: str = "open",
    company: str = "aecom",
) -> Job:
    """Posting `n` of the role in `city`, first seen two days ago, flushed so
    it has its id."""
    req_id = f"7440001274{n:05d}"
    job = Job(
        company=company,
        title=title,
        url=f"https://jobs.example.test/{company}/{n}",
        req_id=req_id,
        dedupe_key=dedupe_key_for(company, req_id),
        level_band="director_plus",
        family="data_science",
        locations=[f"{city}, United Kingdom"],
        location_cities=[f"{city}, UK"],
        description_text=body,
        status=status,
        first_seen=NOW - timedelta(days=2, minutes=-n),
        last_seen=NOW,
        closed_at=NOW - timedelta(days=1) if status == "closed" else None,
        total_days_open=2,
        repost_count=0,
        in_scope=True,
        embedding=unit_vector(),
    )
    session.add(job)
    await session.flush()
    return job


def pending_duplicate(newer: Job, earlier: Job, **over) -> JobLineageLink:
    """The detector's pending proposal that `newer` duplicates `earlier`, the
    shape it writes while the earlier one is still open."""
    fields = dict(
        job_id=newer.id,
        prior_job_id=earlier.id,
        relation="duplicate",
        method="title+embedding",
        score=1.0,
        confidence="suspected",
        status="pending",
        detector_version="lineage/v4",
        evidence={"reasons": ["prior still open (duplicate listing)"]},
    )
    fields.update(over)
    return JobLineageLink(**fields)
