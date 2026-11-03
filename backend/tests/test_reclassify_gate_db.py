"""The jobs reclassify passes read the whole table only after a classifier change.

A row a scan writes is classified by the current code, so between classifier
changes the domain, role and place passes read only the run's own rows. The
first run under a new classifier reads every row, then records the
classifier's fingerprint. Real Postgres; the passes run as the pipeline runs
them.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update

from tracker.config import get_settings
from tracker.db.models import Job
from tracker.workflows import post_passes
from tracker.workflows.post_passes import PostPassContext

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 1, tzinfo=UTC)
#: What each axis reads wrong when the row is left stale, and the pass under test.
PASSES = {
    "domains": (post_passes._pass_domains_backfill, {"domains": []}, lambda job: job.domains),
    "roles": (post_passes._pass_roles_backfill, {"family": None}, lambda job: job.family),
    "places": (post_passes._pass_places_backfill, {"location_groups": []}, lambda job: job.location_groups),
}


def _job(key: str) -> Job:
    return Job(
        company="amazon", req_id=key, dedupe_key=f"amazon:{key}", title="Staff Machine Learning Engineer",
        url=f"https://example.test/{key}", team=None, department=None,
        locations=["London, UK"], location_groups=[], domains=[],
        workplace_type="onsite", level_band="staff", level_confidence="confirmed",
        family=None, track="technical", comp_currency="USD",
        status="open", in_scope=True, first_seen=T0, last_seen=T0, description_sections=[],
    )


async def _run(session, run_pass, touched: list[int]) -> None:
    ctx = PostPassContext(session=session, touched_ids=touched, per_source={}, settings=get_settings(), max_list=None)
    await run_pass(ctx)
    await session.commit()


async def _read(session, read) -> dict[str, object]:
    session.expire_all()
    return {job.req_id: read(job) for job in (await session.scalars(select(Job))).all()}


@pytest.mark.parametrize("axis", list(PASSES))
async def test_a_pass_reads_every_row_once_per_classifier_and_the_run_s_rows_between(db_session, monkeypatch, axis):
    run_pass, stale, read = PASSES[axis]
    first, second = _job("first"), _job("second")
    db_session.add_all([first, second])
    await db_session.commit()

    # Never read under this classifier: every row is.
    await _run(db_session, run_pass, [])
    fresh = await _read(db_session, read)
    assert fresh["first"] and fresh["first"] == fresh["second"], "both rows were read"

    # The same classifier: only the run's own row is read again.
    await db_session.execute(update(Job).values(**stale))
    await db_session.commit()
    await _run(db_session, run_pass, [first.id])
    after = await _read(db_session, read)
    assert after["first"] == fresh["first"]
    assert not after["second"], "a row the run did not write is not read"

    # A changed classifier reads every row again.
    monkeypatch.setattr(post_passes, "classifier_fingerprint", lambda: "a classifier changed since")
    await _run(db_session, run_pass, [])
    assert await _read(db_session, read) == fresh
