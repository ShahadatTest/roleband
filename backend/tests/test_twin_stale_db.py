"""The twin pass drains its backlog instead of re-scoring its head.

Real Postgres, fixed vectors, the real twin pass. A run that touches more
postings than the cap reaches the newest in the next run, an unchanged posting
is not read again, and a posting whose inputs moved is read again together
with the newer postings scored against it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from tracker.config import get_settings
from tracker.db.models import Job, JobTwinLink
from tracker.lineage.twins import detect_twins
from tracker.workflows.post_passes import PostPassContext, _pass_twins

pytestmark = pytest.mark.asyncio

NOW = datetime.now(UTC)
COMMON = (
    "Lead the payments platform team. You will set the roadmap with product, grow a team of "
    "eight engineers, and own reliability for card issuing and settlement across regions. "
) * 5
#: What sets each opening apart, so a pair reads as two roles and not one.
PARTNERS = (
    "You will partner with the risk team on fraud models.",
    "You will partner with the treasury team on liquidity.",
    "You will partner with the compliance team on licensing.",
)


def _vector() -> list[float]:
    vec = [0.0] * get_settings().embedding_dim
    vec[0] = 1.0
    return vec


async def _jobs(session, count: int, *, company: str = "stripe") -> list[Job]:
    jobs = [
        Job(
            company=company, title="Engineering Manager, Payments", url=f"https://jobs.example.test/{company}/{n}",
            req_id=f"9{n:05d}", dedupe_key=f"{company}:{n}", level_band="staff",
            family="engineering_management", locations=["Dublin, Ireland"], location_cities=["Dublin, IE"],
            department="Engineering", description_text=COMMON + PARTNERS[n],
            status="open", first_seen=NOW - timedelta(days=3, minutes=-n), last_seen=NOW, total_days_open=3,
            repost_count=0, in_scope=True, embedding=_vector(), embedded_at=NOW - timedelta(days=3),
        )
        for n in range(count)
    ]
    session.add_all(jobs)
    await session.commit()
    return jobs


async def _run(session, touched: list[int], *, cap: int) -> None:
    settings = get_settings().model_copy(update={"twin_max_per_run": cap})
    ctx = PostPassContext(
        session=session, touched_ids=touched, per_source={"stripe": {"errors": []}, "plaid": {"errors": []}},
        settings=settings, max_list=None,
    )
    await _pass_twins(ctx)
    await session.commit()


async def _stamps(session, jobs: list[Job]) -> list[datetime | None]:
    by_id = dict((await session.execute(select(Job.id, Job.twin_checked_at))).all())
    return [by_id[job.id] for job in jobs]


async def test_a_run_that_touches_more_than_the_cap_reaches_the_newest_posting_next_run(db_session):
    jobs = await _jobs(db_session, 3)
    touched = [job.id for job in jobs]

    await _run(db_session, touched, cap=2)
    first = await _stamps(db_session, jobs)
    assert first[0] and first[1] and first[2] is None

    # The same postings touched again, unchanged: only the one left is read.
    await _run(db_session, touched, cap=2)
    second = await _stamps(db_session, jobs)
    assert second[:2] == first[:2], "an unchanged posting is not read again"
    assert second[2] is not None
    # It is the newest, the side that proposes a pair: its link is there.
    assert sorted((await db_session.execute(select(JobTwinLink.job_b_id))).scalars().all()) == [jobs[1].id, jobs[2].id]

    await _run(db_session, touched, cap=2)
    assert await _stamps(db_session, jobs) == second, "nothing is stale, so nothing is read"


@pytest.mark.parametrize(
    "change",
    [
        {"title": "Engineering Manager, Payments Platform"},
        {"level_band": "principal"},
        {"department": "Payments"},
        {"embedded_at": func.now()},
    ],
    ids=["title", "band", "department", "re_embedded"],
)
async def test_a_posting_whose_inputs_moved_is_read_again_with_the_newer_ones_scored_against_it(db_session, change):
    oldest, middle, newest = await _jobs(db_session, 3)
    (other,) = await _jobs(db_session, 1, company="plaid")
    await _run(db_session, [], cap=10)
    before = await _stamps(db_session, [oldest, middle, newest, other])
    assert all(before)
    proposed_it = set((await db_session.execute(
        select(JobTwinLink.job_b_id).where(JobTwinLink.job_a_id == oldest.id)
    )).scalars().all())
    assert proposed_it

    await db_session.execute(update(Job).where(Job.id == oldest.id).values(**change))
    await db_session.commit()
    await _run(db_session, [], cap=10)

    after = await _stamps(db_session, [oldest, middle, newest, other])
    reread = {job.id for job, was, now in zip((oldest, middle, newest, other), before, after, strict=True) if now > was}
    assert oldest.id in reread
    assert proposed_it <= reread, "a posting that proposed it is read again"
    if "level_band" not in change:
        # Still in its group: every newer posting scored against it is read again.
        assert {middle.id, newest.id} <= reread
    assert other.id not in reread, "a posting at another company is not"


async def test_a_person_s_verdict_on_a_twin_re_reads_the_posting_that_proposed_it(db_session):
    older, newer = await _jobs(db_session, 2)
    await detect_twins(db_session, None)
    before = await _stamps(db_session, [older, newer])
    await db_session.execute(update(JobTwinLink).values(status="rejected", reviewed_at=NOW))
    await db_session.commit()

    summary = await detect_twins(db_session, None)
    assert summary["processed"] == 2
    after = await _stamps(db_session, [older, newer])
    assert after[0] > before[0] and after[1] > before[1]
    # The verdict stands: the detector never rewrites a decided pair.
    assert (await db_session.execute(select(JobTwinLink.status))).scalars().all() == ["rejected"]
