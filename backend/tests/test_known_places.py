"""Places reused instead of a posting-page read: only fresh, open, placed rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tracker.db.models import Job
from tracker.db.repo import load_known_places

pytestmark = pytest.mark.usefixtures("no_escape")


def _job(req_id, *, company="deloitte", status="open", fetched_days_ago=1, locations=("Austin, Texas",)):
    now = datetime.now(UTC)
    return Job(
        company=company, req_id=req_id, dedupe_key=f"{company}:{req_id}", title="Senior Manager",
        url=f"https://example.test/{req_id}", status=status, locations=list(locations),
        level_band="senior", family="swe",
        first_seen=now - timedelta(days=30), last_seen=now, total_days_open=30, repost_count=0,
        description_text="text" if fetched_days_ago is not None else None,
        description_fetched_at=now - timedelta(days=fetched_days_ago) if fetched_days_ago is not None else None,
    )


@pytest.mark.asyncio
async def test_only_open_rows_read_within_the_window_with_a_place_are_reused(db_session):
    db_session.add_all([
        _job("fresh"),
        _job("stale", fetched_days_ago=30),
        _job("never-read", fetched_days_ago=None),
        _job("closed", status="closed"),
        _job("placeless", locations=()),
        _job("other-company", company="kpmg"),
    ])
    await db_session.flush()

    known = await load_known_places(db_session, ["deloitte"], refresh_days=14)

    assert known == {"deloitte": {"fresh": ("Austin, Texas",)}}
    assert await load_known_places(db_session, ["deloitte"], refresh_days=0) == {}
