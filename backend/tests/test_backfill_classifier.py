"""`scripts.backfill_classifier`: the same derivations as the post-passes.

A stored row classified before a rule change is fixed by the next run's
`roles_backfill`, `levels_backfill` and inventory re-derivation; the script
runs the same derivations at once. Real commits on the scratch database: a
dry run reports and writes nothing, `--apply` writes exactly the rows the
passes would, and a rerun finds nothing left.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from scripts import backfill_classifier
from tracker.db.inventory_store import CLASSIFIED_WITH_KEY
from tracker.db.models import Job, PostingInventory
from tracker.enrich.inventory import classifier_fingerprint
from tracker.settings_store import get_setting_dict

pytestmark = pytest.mark.asyncio
T0 = datetime(2026, 10, 8, tzinfo=UTC)
FRONTLINE = "Retail Lead Associate (Reduced-Time), Customer Experience Operations"
DURATION = "B2B Event Marketing Manager (6-Month Contract)"
CONTROL = "Senior Software Engineer"


def _job(key: str, title: str, **over) -> Job:
    row = dict(
        company="acme", req_id=key, dedupe_key=f"acme:{key}", title=title,
        url=f"https://careers.example.test/{key}", status="open", in_scope=False,
        level_band="senior", level_confidence="confirmed", level_basis="generic",
        family="software_engineering", track="technical", locations=["New York, NY, USA"],
        location_groups=["new_york"], domains=[], comp_currency="USD", first_seen=T0, last_seen=T0,
    )
    row.update(over)
    return Job(**row)


def _posting(key: str, title: str, **over) -> PostingInventory:
    row = dict(
        dedupe_key=f"acme:{key}", company="acme", req_id=key, title=title,
        url=f"https://careers.example.test/{key}", level_band="senior", level_confidence="confirmed",
        level_basis="unmapped", family="customer_success", track="technical",
        content_hash=f"stale-{key}", first_seen_at=T0, last_seen_at=T0,
    )
    row.update(over)
    return PostingInventory(**row)


@pytest_asyncio.fixture
async def scoped(db_session, scratch_scope):
    """Every `session_scope` the code under test opens lands on the scratch DB."""
    db_session.add_all([
        # Classified by older rules: a store role filed in a discipline, a
        # contract length read as rung 6, and a row the rules read the same.
        _job("front", FRONTLINE, level_band="entry", family="customer_success", track="technical"),
        _job("dur", DURATION, level_basis="unmapped", family="marketing_communications", track="technical"),
        _job("ctl", CONTROL),
        _posting("front", FRONTLINE, level_band="entry", level_basis="generic"),
        _posting("dur", DURATION, family="marketing_communications"),
    ])
    await db_session.commit()
    return db_session


async def _jobs(session) -> dict[str, tuple]:
    rows = (await session.execute(select(Job.req_id, Job.family, Job.level_band, Job.level_basis))).all()
    return {r.req_id: (r.family, r.level_band, r.level_basis) for r in rows}


async def _postings(session) -> dict[str, tuple]:
    rows = (await session.execute(
        select(PostingInventory.req_id, PostingInventory.family, PostingInventory.level_band)
    )).all()
    return {r.req_id: (r.family, r.level_band) for r in rows}


async def test_a_dry_run_reports_what_the_passes_would_change_and_writes_nothing(scoped):
    before = (await _jobs(scoped), await _postings(scoped))
    stats = await backfill_classifier.backfill(apply=False)

    assert stats["family_moves"][("customer_success", None)] == 1
    assert stats["level_moves"][("senior", "mid")] == 1
    assert stats["inventory_families"][("customer_success", None)] == 1
    assert stats["inventory_bands"][("senior", "mid")] == 1
    scoped.expire_all()
    assert (await _jobs(scoped), await _postings(scoped)) == before


async def test_apply_writes_the_fixed_rows_and_a_rerun_finds_nothing(scoped):
    await backfill_classifier.backfill(apply=True, batch=1)

    scoped.expire_all()
    jobs = await _jobs(scoped)
    assert jobs["front"][0] is None and jobs["front"][1] == "entry"  # Entry kept, no discipline
    assert jobs["dur"][1:] == ("mid", "none")  # a contract length states no level
    assert jobs["ctl"] == ("software_engineering", "senior", "generic")  # untouched
    postings = await _postings(scoped)
    assert postings["front"] == (None, "entry")
    assert postings["dur"][1] == "mid"
    assert (await get_setting_dict(scoped, CLASSIFIED_WITH_KEY)) == {"fingerprint": classifier_fingerprint()}

    again = await backfill_classifier.backfill(apply=False)
    assert (again["jobs_roles"], again["jobs_levels"], again["inventory"]) == (0, 0, 0)
