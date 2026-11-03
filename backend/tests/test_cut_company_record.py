"""A company cut by a bound outside its collection keeps an honest record.

Collection streams each kept row to the run's writer, which writes and commits
it. When the per-source backstop or the run's deadline then cuts the company,
its collection is replaced by a failure with nothing in it, yet the rows it
streamed are on the Board. The run and source records count them: a record that
said kept 0 beside jobs_new 2 contradicts itself, and the outcome stays the
failure the cut was.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.factories import make_company
from tracker.config import get_settings
from tracker.db.models import Job, ScrapeRun, ScrapeSourceRun, SourceBinding
from tracker.schema import EnrichedJob, LevelBand, LevelConfidence, RawJob
from tracker.workflows.collection_types import ScanMode, failed_collection
from tracker.workflows.pipeline import _RunWriter
from tracker.workflows.progress import RunProgress

pytestmark = pytest.mark.asyncio


def _row(req: str) -> EnrichedJob:
    raw = RawJob(
        company="acme", req_id=req, title="Staff Software Engineer", url=f"https://x.test/{req}",
        locations=["Remote"], description_html="<p>Build things.</p>",
    )
    return EnrichedJob(
        raw=raw, level_band=LevelBand.STAFF, level_confidence=LevelConfidence.CONFIRMED,
        family="software_engineering", location_groups=[],
    )


async def test_rows_streamed_before_a_backstop_cut_are_counted_as_kept(db_session):
    db_session.add(make_company("acme", "Acme"))
    await db_session.flush()
    db_session.add(SourceBinding(
        company_slug="acme", connector_kind="adapter", connector_id="greenhouse",
        status="stable", closure_capability="authoritative",
    ))
    run = ScrapeRun(status="running")
    db_session.add(run)
    await db_session.commit()

    totals = {"seen": 0, "new": 0, "closed": 0}
    per_source: dict[str, dict] = {}
    writer = _RunWriter(
        db_session, run, {"acme": {"adapter": "greenhouse", "board_token": "acme", "board_region": None,
                                   "enabled": True, "consent": None}},
        scan_mode=ScanMode.RECONCILE, max_list=None, progress=RunProgress(companies_total=1),
        touched_ids=[], per_source=per_source, outcomes={}, drift_all=[], totals=totals,
        settings=get_settings(),
    )
    writer.row("acme", _row("r1"))
    writer.row("acme", _row("r2"))
    writer.collected("acme", failed_collection("acme", "SourceUnresponsive: acme hit the 30s backstop"))
    writer.close()
    await writer.drain()

    assert len((await db_session.scalars(select(Job))).all()) == 2, "the streamed rows are written"
    record = (await db_session.scalars(select(ScrapeSourceRun))).one()
    assert (record.kept, record.jobs_new, record.outcome) == (2, 2, "failed")
    assert per_source["acme"]["kept"] == 2
    assert (run.jobs_seen, run.jobs_new) == (2, 2)
