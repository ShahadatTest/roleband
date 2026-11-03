"""Every open row the text pass owes is read, however old and whether or not a
run reached it.

The pass reads the rows a run touched, newest first, up to a cap per run. On
its own that starves: while every run brings more owed rows than the cap, a
posting first seen weeks ago is touched by run after run and never read, and
a row written by a run that stopped before its post-passes is owed by nothing
until a later run happens to touch it. Its pay then reads "not read yet" when
the text states a band. The owed backlog is a second queue, oldest first,
with a budget of its own.

Real path: `upsert_job` -> commit -> `run_post_passes` over the real
fingerprint, disclosed-pay and period passes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, update

from tracker.config import get_settings
from tracker.db.models import AiTaskLog, Job, ScrapeRun
from tracker.db.repo import load_company_jobs, upsert_job
from tracker.schema import EnrichedJob, LevelBand, LevelConfidence, RawJob
from tracker.workflows import post_passes
from tracker.workflows.post_passes import POST_PASSES, PostPassContext, run_post_passes

pytestmark = pytest.mark.asyncio

CO = "qualcomm"
PAY_TEXT = "The pay range for this position is $150,000.00 - $210,000.00 per year."
BAND = (150_000, 210_000)


def _posting(req: str) -> EnrichedJob:
    raw = RawJob(
        company=CO, req_id=req, title="Staff Software Engineer", url=f"https://x.test/{req}",
        locations=["San Diego, CA"], description_html=f"<p>{PAY_TEXT}</p>",
    )
    return EnrichedJob(
        raw=raw, level_band=LevelBand.STAFF, level_confidence=LevelConfidence.CONFIRMED,
        family="software_engineering", location_groups=[],
    )


async def _scan(session, reqs: list[str]) -> list[int]:
    """One run's writes, committed; its post-passes are the caller's to run."""
    run = ScrapeRun(status="running")
    session.add(run)
    await session.flush()
    existing = await load_company_jobs(session, CO)
    touched = []
    for req in reqs:
        job, _new = await upsert_job(session, run, _posting(req), existing)
        touched.append(job.id)
    await session.commit()
    return touched


async def _passes(session, touched: list[int], monkeypatch, *, cap: int) -> None:
    names = {"content_fingerprint", "disclosed_comp", "pay_periods"}
    monkeypatch.setattr(post_passes, "POST_PASSES", tuple(p for p in POST_PASSES if p.name in names))
    settings = get_settings().model_copy(
        update={"intelligence_extract_in_pipeline": True, "intelligence_max_per_run": cap}
    )
    await run_post_passes(
        PostPassContext(
            session=session, touched_ids=list(touched), per_source={}, settings=settings,
            max_list=None,
        )
    )


async def _unread(session) -> set[str]:
    rows = (
        await session.scalars(
            select(Job).where(Job.structured_at.is_(None)).execution_options(populate_existing=True)
        )
    ).all()
    return {j.req_id for j in rows}


async def _band(session, req: str) -> tuple:
    job = await session.scalar(
        select(Job).where(Job.req_id == req).execution_options(populate_existing=True)
    )
    return job.disclosed_base_min, job.disclosed_base_max


async def _reads(session) -> int:
    return await session.scalar(select(func.count()).select_from(AiTaskLog))


async def test_an_old_owed_row_is_read_while_newer_rows_keep_arriving(db_session, monkeypatch):
    # Three postings written by a run that never reached its post-passes.
    old = ["old-1", "old-2", "old-3"]
    await _scan(db_session, old)

    # Each later run lists them again and finds two new postings, as many as
    # its cap: the touched rows alone, newest first, would never reach `old`.
    listed = list(old)
    for n in range(3):
        listed += [f"new-{n}-a", f"new-{n}-b"]
        touched = await _scan(db_session, listed)
        await _passes(db_session, touched, monkeypatch, cap=2)

    assert await _unread(db_session) == set()
    for req in old:
        assert await _band(db_session, req) == BAND


async def test_rows_a_stopped_run_left_are_read_by_a_run_that_touched_none_of_them(
    db_session, monkeypatch,
):
    await _scan(db_session, ["left-1", "left-2"])
    assert await _unread(db_session) == {"left-1", "left-2"}

    await _passes(db_session, [], monkeypatch, cap=50)

    assert await _unread(db_session) == set()
    assert await _band(db_session, "left-1") == BAND
    reads = await _reads(db_session)

    # Nothing is owed any more, so the next run reads nothing.
    await _passes(db_session, [], monkeypatch, cap=50)
    assert await _reads(db_session) == reads


async def test_the_backlog_reads_in_scope_rows_first_and_never_closed_or_connector_rows(
    db_session, monkeypatch,
):
    await _scan(db_session, ["out-of-scope", "in-scope", "closed", "connector"])
    await db_session.execute(update(Job).where(Job.req_id == "out-of-scope").values(in_scope=False))
    await db_session.execute(update(Job).where(Job.req_id == "closed").values(status="closed"))
    await db_session.execute(
        update(Job).where(Job.req_id == "connector").values(disclosed_source="connector")
    )
    await db_session.commit()

    # The out-of-scope row is the oldest, yet a budget of one reads the
    # in-scope row first: the Board shows in-scope rows.
    await _passes(db_session, [], monkeypatch, cap=1)
    assert await _unread(db_session) == {"out-of-scope", "closed", "connector"}

    await _passes(db_session, [], monkeypatch, cap=1)
    await _passes(db_session, [], monkeypatch, cap=1)
    # A closed posting is off the Board, and a connector's band is never the
    # text pass's to read.
    assert await _unread(db_session) == {"closed", "connector"}
    assert await _reads(db_session) == 2
