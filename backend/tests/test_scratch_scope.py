"""`scratch_scope` gives every importer of `session_scope` the scratch database
and production's transaction rules.

A module that imported the name before the fixture ran still reaches the
scratch database, a scope that ends cleanly commits, and one that raises
rolls back and lets the error through. A copy that swallowed the error, or
committed what came before it, fails the second test.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tracker.db.models import AppSetting
from tracker.workflows import directory_sweep, scheduler

pytestmark = pytest.mark.asyncio


async def _keys(db_session) -> list[str]:
    db_session.expire_all()
    return list((await db_session.scalars(select(AppSetting.key).order_by(AppSetting.key))).all())


async def test_a_name_imported_before_the_fixture_commits_to_the_scratch_database(db_session, scratch_scope):
    async with directory_sweep.session_scope() as session:
        session.add(AppSetting(key="from_directory_sweep", value={}))
    async with scheduler.session_scope() as session:
        session.add(AppSetting(key="from_scheduler", value={}))
    async with scratch_scope() as session:
        session.add(AppSetting(key="from_the_fixture", value={}))

    assert await _keys(db_session) == ["from_directory_sweep", "from_scheduler", "from_the_fixture"]


async def test_a_scope_that_raises_rolls_back_and_re_raises(db_session, scratch_scope):
    with pytest.raises(ValueError, match="board answered 500"):
        async with directory_sweep.session_scope() as session:
            session.add(AppSetting(key="half_written", value={}))
            await session.flush()
            raise ValueError("board answered 500")

    assert await _keys(db_session) == []
