"""Twins matched automatically over real Postgres: the detector
writes them `auto`, every reader that shows a twin shows them, the review
queue asks only about the rest, and a person's "Different roles" ends one."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tracker.config import get_settings
from tracker.db.models import Job, JobTwinLink
from tracker.lineage.twins import detect_twins

pytestmark = pytest.mark.asyncio

NOW = datetime.now(UTC)
COMMON = (
    "Lead the payments platform team. You will set the roadmap with product, grow a team of "
    "eight engineers, and own reliability for card issuing and settlement across regions. "
) * 5


def _vector() -> list[float]:
    vec = [0.0] * get_settings().embedding_dim
    vec[0] = 1.0
    return vec


async def _job(session, n: int, *, title: str = "Engineering Manager, Payments",
               department: str | None = "Engineering", extra: str = "") -> Job:
    job = Job(
        company="stripe", title=title, url=f"https://jobs.example.test/stripe/{n}",
        req_id=f"9{n:05d}", dedupe_key=f"stripe:{n}", level_band="staff",
        family="engineering_management", locations=["Dublin, Ireland"],
        location_cities=["Dublin, IE"], department=department,
        description_text=COMMON + extra, status="open",
        first_seen=NOW - timedelta(days=3, minutes=-n), last_seen=NOW, total_days_open=3,
        repost_count=0, in_scope=True, embedding=_vector(),
    )
    session.add(job)
    await session.flush()
    return job


async def _link(session) -> JobTwinLink:
    return (await session.execute(select(JobTwinLink))).scalar_one()


async def test_identical_titles_in_one_department_are_shown_as_twins_at_once(api_client, db_session):
    left = await _job(db_session, 1, extra="You will partner with the risk team on fraud models.")
    right = await _job(db_session, 2, extra="You will partner with the treasury team on liquidity.")
    await db_session.commit()

    summary = await detect_twins(db_session, [right.id])

    assert (summary["auto"], summary["suspected"]) == (1, 0)
    link = await _link(db_session)
    assert (link.confidence, link.status) == ("auto", "pending")

    # Every reader that shows a twin shows it.
    row = (await api_client.get(f"/api/jobs/{left.id}")).json()
    assert row["twin_count"] == 1
    twins = (await api_client.get(f"/api/jobs/{left.id}/twins")).json()
    assert [(m["job"]["id"], m["job"]["twin_count"]) for m in twins["members"]] == [(left.id, 1), (right.id, 1)]
    # The queue asks only about proposals; the checking lens lists it.
    assert (await api_client.get("/api/twins/review")).json()["total"] == 0
    assert (await api_client.get("/api/twins/review?confidence=auto")).json()["total"] == 1
    stats = (await api_client.get("/api/stats")).json()
    assert stats["review_pending"] == 0

    # "Different roles" on it ends it everywhere, and the detector keeps it so.
    response = await api_client.post(f"/api/twins/links/{link.id}/review", json={"verdict": "rejected"})
    assert response.status_code == 200, response.text
    assert (await api_client.get(f"/api/jobs/{left.id}")).json()["twin_count"] == 0
    after = (await api_client.get(f"/api/jobs/{left.id}/twins")).json()["members"]
    assert [(m["job"]["id"], m["job"]["twin_count"]) for m in after] == [(left.id, 0)]
    await detect_twins(db_session, [right.id])
    db_session.expire_all()
    assert (await _link(db_session)).status == "rejected"


async def test_a_near_title_or_a_missing_department_stays_in_the_queue(api_client, db_session):
    await _job(db_session, 1, extra="You will partner with the risk team on fraud models.")
    right = await _job(db_session, 2, department=None,
                       extra="You will partner with the treasury team on liquidity.")
    await db_session.commit()

    summary = await detect_twins(db_session, [right.id])

    assert (summary["auto"], summary["suspected"]) == (0, 1)
    assert (await _link(db_session)).confidence == "suspected"
    assert (await api_client.get("/api/twins/review")).json()["total"] == 1
    assert (await api_client.get(f"/api/jobs/{right.id}")).json()["twin_count"] == 0
