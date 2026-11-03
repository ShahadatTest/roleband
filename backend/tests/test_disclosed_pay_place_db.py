"""A text band is read again when the place that selects it changes.

The text pass picks, among bands a posting states per city, the one for the
posting's first place (`first_place(locations)`). A stale gate that checked
only the text (`content_changed_at`) and the parser version would let a
listing that changed ONLY its primary place keep the band chosen for the old
one: Adyen's "Chicago $235,000 - $317,000 / San Francisco $258,000 -
$348,000" moved from Chicago to San Francisco would still show Chicago's.

The pass stamps the place key it read (`jobs.disclosed_place_key`) and owes
a touched row whose key moved. Real path: `upsert_job` -> commit ->
`run_post_passes` over the real fingerprint, disclosed-pay and period passes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from tests.factories import ADYEN_PAY_TEXT
from tracker.config import get_settings
from tracker.db.models import AiTaskLog, Job, ScrapeRun
from tracker.db.repo import load_company_jobs, upsert_job
from tracker.schema import EnrichedJob, LevelBand, LevelConfidence, RawJob
from tracker.workflows import post_passes
from tracker.workflows.post_passes import POST_PASSES, PostPassContext, run_post_passes

pytestmark = pytest.mark.asyncio

CO = "adyen"
CHICAGO = (235_000, 317_000)
SAN_FRANCISCO = (258_000, 348_000)


def _posting(req: str, locations: list[str]) -> EnrichedJob:
    raw = RawJob(
        company=CO, req_id=req, title="Staff Software Engineer", url=f"https://x.test/{req}",
        locations=list(locations), description_html=f"<p>{ADYEN_PAY_TEXT}</p>",
    )
    return EnrichedJob(
        raw=raw, level_band=LevelBand.STAFF, level_confidence=LevelConfidence.CONFIRMED,
        family="software_engineering", location_groups=[],
    )


async def _scan(session, rows: list[EnrichedJob]) -> list[int]:
    run = ScrapeRun(status="running")
    session.add(run)
    await session.flush()
    existing = await load_company_jobs(session, CO)
    touched = []
    for enriched in rows:
        job, _new = await upsert_job(session, run, enriched, existing)
        touched.append(job.id)
    await session.commit()
    return touched


async def _passes(session, touched: list[int], monkeypatch) -> None:
    names = {"content_fingerprint", "disclosed_comp", "pay_periods"}
    monkeypatch.setattr(post_passes, "POST_PASSES", tuple(p for p in POST_PASSES if p.name in names))
    settings = get_settings().model_copy(
        update={"intelligence_extract_in_pipeline": True, "intelligence_max_per_run": 50}
    )
    await run_post_passes(
        PostPassContext(
            session=session, touched_ids=list(touched), per_source={}, settings=settings,
            max_list=None,
        )
    )


async def _bands(session) -> dict[str, tuple]:
    rows = (await session.scalars(select(Job).execution_options(populate_existing=True))).all()
    return {j.req_id: (j.disclosed_base_min, j.disclosed_base_max) for j in rows}


async def _reads(session) -> int:
    return await session.scalar(select(func.count()).select_from(AiTaskLog))


async def test_a_listing_that_changes_only_its_place_gets_that_places_band(db_session, monkeypatch):
    first = [
        _posting("move", ["Chicago, IL"]),
        _posting("swap", ["Chicago, IL", "San Francisco, CA"]),
        _posting("same", ["Chicago, IL"]),
    ]
    touched = await _scan(db_session, first)
    await _passes(db_session, touched, monkeypatch)
    assert await _bands(db_session) == {"move": CHICAGO, "swap": CHICAGO, "same": CHICAGO}
    reads = await _reads(db_session)

    second = [
        _posting("move", ["San Francisco, CA"]),
        _posting("swap", ["San Francisco, CA", "Chicago, IL"]),
        _posting("same", ["Chicago, IL"]),
    ]
    touched = await _scan(db_session, second)
    await _passes(db_session, touched, monkeypatch)

    assert await _bands(db_session) == {"move": SAN_FRANCISCO, "swap": SAN_FRANCISCO, "same": CHICAGO}
    # Only the two whose place moved were read again.
    assert await _reads(db_session) == reads + 2


async def test_a_rerun_at_the_same_place_reads_nothing(db_session, monkeypatch):
    touched = await _scan(db_session, [_posting("same", ["Chicago, IL"])])
    await _passes(db_session, touched, monkeypatch)
    reads = await _reads(db_session)
    touched = await _scan(db_session, [_posting("same", ["Chicago, IL"])])
    await _passes(db_session, touched, monkeypatch)
    assert await _reads(db_session) == reads


async def test_a_spelling_of_the_same_city_is_no_change(db_session, monkeypatch):
    """The key is the place the selector reads (cities and metros), never the
    raw string: "Chicago, IL" and "Chicago, Illinois, United States" are one."""
    touched = await _scan(db_session, [_posting("same", ["Chicago, IL"])])
    await _passes(db_session, touched, monkeypatch)
    reads = await _reads(db_session)
    touched = await _scan(db_session, [_posting("same", ["Chicago, Illinois, United States"])])
    await _passes(db_session, touched, monkeypatch)
    assert await _reads(db_session) == reads


async def test_a_connector_band_is_never_read_from_the_text(db_session, monkeypatch):
    touched = await _scan(db_session, [_posting("api", ["Chicago, IL"])])
    job = (await db_session.scalars(select(Job))).one()
    job.disclosed_base_min, job.disclosed_base_max = 100_000, 120_000
    job.disclosed_source = "connector"
    await db_session.commit()

    touched = await _scan(db_session, [_posting("api", ["San Francisco, CA"])])
    await _passes(db_session, touched, monkeypatch)
    assert await _bands(db_session) == {"api": (100_000, 120_000)}


async def test_a_band_read_before_the_key_existed_is_read_once_more(db_session, monkeypatch):
    """A row processed before the key existed has none: it is owed once (the
    place it was read for is unknown), then stable."""
    touched = await _scan(db_session, [_posting("old", ["San Francisco, CA"])])
    await _passes(db_session, touched, monkeypatch)
    job = (await db_session.scalars(select(Job))).one()
    job.disclosed_place_key = None
    job.disclosed_base_min, job.disclosed_base_max = CHICAGO  # read for another place
    await db_session.commit()

    touched = await _scan(db_session, [_posting("old", ["San Francisco, CA"])])
    await _passes(db_session, touched, monkeypatch)
    assert await _bands(db_session) == {"old": SAN_FRANCISCO}
    reads = await _reads(db_session)
    touched = await _scan(db_session, [_posting("old", ["San Francisco, CA"])])
    await _passes(db_session, touched, monkeypatch)
    assert await _reads(db_session) == reads


async def test_one_run_reads_the_band_of_every_posting_a_large_company_lists(db_session, monkeypatch):
    """The read is deterministic and costs about a millisecond a posting, so
    the default bounds one transaction, not a model's latency: a company that
    lists a hundred and more postings has them all read on its first scan."""
    touched = await _scan(db_session, [_posting(f"r{n}", ["Chicago, IL"]) for n in range(120)])
    names = {"content_fingerprint", "disclosed_comp", "pay_periods"}
    monkeypatch.setattr(post_passes, "POST_PASSES", tuple(p for p in POST_PASSES if p.name in names))
    settings = get_settings().model_copy(update={"intelligence_extract_in_pipeline": True})
    await run_post_passes(
        PostPassContext(session=db_session, touched_ids=touched, per_source={}, settings=settings, max_list=None)
    )
    bands = await _bands(db_session)
    assert len(bands) == 120
    assert set(bands.values()) == {CHICAGO}
