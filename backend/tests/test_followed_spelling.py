"""`is_followed()` (SQL) and `is_followed_row()` (Python) are one rule: the
Walk's inventory counts filter loaded rows in Python while
promotion and retention filter in SQL. A condition added to one and not the
other would count companies promotion never admits."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tracker.db.models import TrackedCompany
from tracker.db.queries.companies import is_followed, is_followed_row

ROWS = [("on-active", True, "active"), ("on-pending", True, "pending"),
        ("off-active", False, "active"), ("off-pending", False, "pending")]


@pytest.mark.asyncio
async def test_the_python_spelling_of_followed_matches_the_sql_one(db_session):
    for slug, enabled, status in ROWS:
        db_session.add(TrackedCompany(slug=slug, display=slug, adapter="greenhouse", board_token=slug,
                                      status=status, enabled=enabled, visible=True, source="directory"))
    await db_session.commit()
    slugs = [row[0] for row in ROWS]
    loaded = (await db_session.scalars(select(TrackedCompany).where(TrackedCompany.slug.in_(slugs)))).all()
    by_sql = set((await db_session.scalars(
        select(TrackedCompany.slug).where(is_followed(), TrackedCompany.slug.in_(slugs))
    )).all())
    by_python = {row.slug for row in loaded if is_followed_row(row)}
    assert by_sql == by_python == {"on-active"}
