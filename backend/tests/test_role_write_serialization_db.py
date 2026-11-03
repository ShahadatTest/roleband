"""Saves, pursuits and recipe drafts serialize across clients.

`ensure_favorite`, `upsert_pursuit` and `save_draft_revision` each read, then
write. Without a lock, two writers on one job (a second tab, the MCP agent and a
click) both see no row and both insert: the second commit is a
UniqueViolation, a 500 over HTTP and a raw IntegrityError to the agent. Two
pursuit updates both record the same old stage as `from_stage`. Two drafts
of one recipe both take `last + 1`; two first drafts both create the slug.

Each test holds the first writer's transaction open while the second runs
beside it, then commits the first: the second must wait, then see the first's
row. Real Postgres, two sessions.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.barriers import until_waiting
from tests.test_recipe_adapter import RECIPE
from tracker.agents import pursuits
from tracker.agents.pursuits import PursuitUpdate, ensure_favorite, upsert_pursuit
from tracker.db.models import (
    ConnectorRecipe,
    ConnectorRecipeRevision,
    Favorite,
    Job,
    Pursuit,
    PursuitEvent,
)
from tracker.db.recipe_store import save_draft_revision

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 4, tzinfo=UTC)


async def _a_job(db_session) -> Job:
    job = Job(
        company="openai", req_id="r1", dedupe_key="openai:r1", title="Staff PM",
        url="https://careers.example.test/r1", first_seen=NOW, last_seen=NOW, status="open",
        level_band="staff",
    )
    db_session.add(job)
    await db_session.commit()
    return job


async def _second_beside_the_first(db_session, first, second):
    """Run `first` and leave its transaction open; start `second` in another
    session; commit the first once the second has queued on a lock or
    finished; then let the second finish and commit.

    Locked, the second queues on the role's lock before its read. Unlocked, it
    reads "absent" and then finishes, or queues on the first's row. Either way
    the first commits after the second has reached its read or its lock, never
    before, which the controls at the end of this file hold."""
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as one, factory() as two:
        await first(one)
        later = asyncio.create_task(second(two))
        await until_waiting(db_session.bind, later)
        await one.commit()
        result = await asyncio.wait_for(later, 10)
        await two.commit()
        return result


async def test_two_first_saves_of_one_job_store_one_and_fail_neither(db_session):
    job = await _a_job(db_session)
    added = await _second_beside_the_first(
        db_session,
        lambda s: ensure_favorite(s, job.id),
        lambda s: ensure_favorite(s, job.id),
    )
    assert added is False
    rows = (await db_session.execute(select(Favorite.job_id))).scalars().all()
    assert rows == [job.id]


async def test_two_first_pursuits_of_one_job_make_one_pursuit(db_session):
    job = await _a_job(db_session)
    await _second_beside_the_first(
        db_session,
        lambda s: upsert_pursuit(s, job.id, PursuitUpdate(stage="saved"), actor="user"),
        lambda s: upsert_pursuit(s, job.id, PursuitUpdate(stage="applied"), actor="agent"),
    )
    (pursuit,) = (await db_session.execute(select(Pursuit))).scalars().all()
    assert pursuit.stage == "applied"
    events = (
        await db_session.execute(
            select(PursuitEvent.event_type, PursuitEvent.from_stage, PursuitEvent.to_stage)
            .order_by(PursuitEvent.id)
        )
    ).all()
    assert [tuple(e) for e in events] == [("created", None, "saved"), ("updated", "saved", "applied")]


async def test_two_stage_changes_record_the_chain_they_were_committed_in(db_session):
    """Broken rule caught: both events read the same old stage, so the
    history said saved -> applied and saved -> interviewing."""
    job = await _a_job(db_session)
    await upsert_pursuit(db_session, job.id, PursuitUpdate(stage="saved"), actor="user")
    await db_session.commit()

    await _second_beside_the_first(
        db_session,
        lambda s: upsert_pursuit(s, job.id, PursuitUpdate(stage="applied"), actor="user"),
        lambda s: upsert_pursuit(s, job.id, PursuitUpdate(stage="interviewing"), actor="agent"),
    )
    chain = (
        await db_session.execute(
            select(PursuitEvent.from_stage, PursuitEvent.to_stage).order_by(PursuitEvent.id)
        )
    ).all()
    assert [tuple(c) for c in chain] == [
        (None, "saved"), ("saved", "applied"), ("applied", "interviewing"),
    ]


async def test_two_first_drafts_of_one_recipe_keep_both_documents(db_session):
    def draft(s):
        return save_draft_revision(s, slug="demo-careers", document=RECIPE)

    await _second_beside_the_first(db_session, draft, draft)
    recipes = (await db_session.execute(select(ConnectorRecipe.slug))).scalars().all()
    versions = (
        await db_session.execute(
            select(ConnectorRecipeRevision.version).order_by(ConnectorRecipeRevision.version)
        )
    ).scalars().all()
    assert recipes == ["demo-careers"]
    assert versions == [1, 2]


async def test_two_later_drafts_take_the_next_two_versions(db_session):
    await save_draft_revision(db_session, slug="demo-careers", document=RECIPE)
    await db_session.commit()

    def draft(s):
        return save_draft_revision(s, slug="demo-careers", document=RECIPE)

    await _second_beside_the_first(db_session, draft, draft)
    versions = (
        await db_session.execute(
            select(ConnectorRecipeRevision.version).order_by(ConnectorRecipeRevision.version)
        )
    ).scalars().all()
    assert versions == [1, 2, 3]


async def _no_role_lock(_session, _job_id) -> None:
    return None


async def test_without_the_role_lock_the_second_save_meets_the_first_row(db_session, monkeypatch):
    """Positive control for the harness: with the lock removed, the second
    save reads "absent" before the first commits, so its insert fails. A
    harness that let the first commit before the second read would pass the
    save tests above with no lock at all."""
    monkeypatch.setattr(pursuits, "lock_role_writes", _no_role_lock)
    job = await _a_job(db_session)
    with pytest.raises(IntegrityError):
        await _second_beside_the_first(
            db_session,
            lambda s: ensure_favorite(s, job.id),
            lambda s: ensure_favorite(s, job.id),
        )


async def test_without_the_role_lock_both_stage_changes_read_the_same_old_stage(db_session, monkeypatch):
    """Positive control for the path that queues after its read: with the lock
    removed, the second change reads the stage the first is replacing and then
    waits on the first's row, so both events record `saved` as the old stage."""
    monkeypatch.setattr(pursuits, "lock_role_writes", _no_role_lock)
    job = await _a_job(db_session)
    await upsert_pursuit(db_session, job.id, PursuitUpdate(stage="saved"), actor="user")
    await db_session.commit()

    await _second_beside_the_first(
        db_session,
        lambda s: upsert_pursuit(s, job.id, PursuitUpdate(stage="applied"), actor="user"),
        lambda s: upsert_pursuit(s, job.id, PursuitUpdate(stage="interviewing"), actor="agent"),
    )
    chain = (
        await db_session.execute(
            select(PursuitEvent.from_stage, PursuitEvent.to_stage).order_by(PursuitEvent.id)
        )
    ).all()
    assert [tuple(c) for c in chain] == [
        (None, "saved"), ("saved", "applied"), ("saved", "interviewing"),
    ]
