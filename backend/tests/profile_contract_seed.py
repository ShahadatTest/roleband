"""Realistic rows for the pursuit contract.

Every timestamp the reads return is fixed at `NOW` or counted back from it. A
pursuit write stamps `created_at`/`updated_at` in Postgres, so tests read those
as timestamps, never as values.

| rows | what they exercise |
|---|---|
| jobs `applied`, `interviewing`, `rejected` | three pursuits across priorities; the rejected role is closed |
| job `saved` | saved, not pursued: a pursuit write creates its first pursuit |
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_job
from tracker.db.models import Favorite, Job, Pursuit, PursuitEvent

NOW = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)


@dataclass(frozen=True)
class SeededProfile:
    jobs: dict[str, int]
    pursuits: dict[str, int]


def _role(key: str, company: str, title: str, **over) -> Job:
    return make_job(f"{company}-{key}", company=company, dedupe_key=f"{company}:{key}", title=title,
                first_seen=NOW - timedelta(days=30), last_seen=NOW, **over)


async def seed_profile(session: AsyncSession) -> SeededProfile:
    jobs = {
        "applied": _role("applied", "google", "Staff Product Manager, Cloud AI"),
        "interviewing": _role("interviewing", "openai", "Product Lead, Developer Platform"),
        "rejected": _role("rejected", "anthropic", "Staff Product Manager, Claude Apps", status="closed",
                          closed_at=NOW - timedelta(days=4)),
        "saved": _role("saved", "google", "Group Product Manager, Workspace"),
    }
    session.add_all(jobs.values())
    await session.flush()
    j = {key: row.id for key, row in jobs.items()}

    pursuits = {
        "applied": Pursuit(job_id=j["applied"], stage="applied", priority=1, notes="Referred by a former colleague.",
                           next_action="Prepare the product sense interview", next_action_due=NOW + timedelta(days=3),
                           created_at=NOW - timedelta(days=6), updated_at=NOW - timedelta(days=1)),
        "interviewing": Pursuit(job_id=j["interviewing"], stage="interviewing", priority=2,
                                created_at=NOW - timedelta(days=9), updated_at=NOW - timedelta(days=2)),
        "rejected": Pursuit(job_id=j["rejected"], stage="rejected", priority=2,
                            created_at=NOW - timedelta(days=20), updated_at=NOW - timedelta(days=5)),
    }
    session.add_all(pursuits.values())
    await session.flush()
    p = {key: row.id for key, row in pursuits.items()}

    def event(pursuit: str, from_stage: str | None, to_stage: str, days_ago: int) -> PursuitEvent:
        return PursuitEvent(pursuit_id=p[pursuit], actor="user", event_type="created" if from_stage is None else "updated",
                            from_stage=from_stage, to_stage=to_stage, detail={"changed": ["stage"]},
                            created_at=NOW - timedelta(days=days_ago))

    def saved(job: str, at: datetime) -> Favorite:
        return Favorite(job_id=j[job], created_at=at)

    minutes = timedelta(minutes=5)
    session.add_all([
        event("applied", None, "saved", 6), event("applied", "saved", "applied", 1),
        event("interviewing", None, "applied", 9), event("interviewing", "applied", "interviewing", 2),
        event("rejected", None, "saved", 20), event("rejected", "interviewing", "rejected", 5),
        saved("applied", NOW - timedelta(days=6) + minutes), saved("interviewing", NOW - timedelta(days=9) + minutes),
        saved("rejected", NOW - timedelta(days=20) + minutes), saved("saved", NOW - timedelta(hours=3)),
    ])

    await session.commit()
    return SeededProfile(jobs=j, pursuits=p)
