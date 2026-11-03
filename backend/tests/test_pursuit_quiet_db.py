"""A pursuit that has gone quiet raises a reminder, once per silence.

An application or interview with no follow-up date never prompted the user,
however long it went without news. A pursuit at a waiting stage whose last
activity is older than its stage waits now raises one reminder, keyed by that
activity: it rings once, again only after new activity has gone quiet in turn,
and leaves when the pursuit moves, gets a follow-up date or ends.

Real Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from tracker.db.models import Job, Notification, Pursuit
from tracker.notifications import pursuit_due
from tracker.notifications.pursuit_due import generate_pursuit_due_notifications, quiet_after

pytestmark = pytest.mark.asyncio


async def _pursuit(db_session, stage: str, idle: timedelta, *, due: datetime | None = None) -> Pursuit:
    now = datetime.now(UTC)
    job = Job(
        company="openai", req_id=f"r-{stage}", dedupe_key=f"openai:r-{stage}", title="Staff PM",
        url="https://careers.example.test/r1", level_band="staff", status="open",
        first_seen=now - timedelta(days=60), last_seen=now, in_scope=True,
    )
    db_session.add(job)
    await db_session.flush()
    pursuit = Pursuit(job_id=job.id, stage=stage, next_action_due=due)
    db_session.add(pursuit)
    await db_session.flush()
    await _idle(db_session, pursuit, idle)
    return pursuit


async def _idle(db_session, pursuit: Pursuit, idle: timedelta) -> None:
    await db_session.execute(
        update(Pursuit).where(Pursuit.id == pursuit.id).values(updated_at=datetime.now(UTC) - idle)
    )
    await db_session.commit()
    await db_session.refresh(pursuit)


async def _quiet(db_session) -> list[Notification]:
    await generate_pursuit_due_notifications(db_session)
    await db_session.commit()
    return list((await db_session.scalars(
        select(Notification).where(Notification.source_type == "quiet")
    )).all())


@pytest.mark.parametrize(("stage", "days"), [("applied", 21), ("interviewing", 12)])
async def test_a_pursuit_goes_quiet_exactly_at_its_stage_threshold(db_session, stage, days):
    pursuit = await _pursuit(db_session, stage, timedelta(days=days) - timedelta(hours=1))
    assert await _quiet(db_session) == []
    await _idle(db_session, pursuit, timedelta(days=days))
    (row,) = await _quiet(db_session)
    assert (row.category, row.source_id, row.meta["stage"]) == ("pursuit_due", pursuit.id, stage)
    assert row.title == f"No news from OpenAI in {days} days"


async def test_no_stage_goes_quiet_in_under_five_days(monkeypatch):
    monkeypatch.setattr(pursuit_due, "QUIET_AFTER_DAYS", {"applied": 2})
    assert quiet_after("applied") == timedelta(days=5)
    assert quiet_after("saved") is None


async def test_a_quiet_pursuit_rings_once_and_again_only_after_new_activity(db_session):
    pursuit = await _pursuit(db_session, "applied", timedelta(days=30))
    (first,) = await _quiet(db_session)
    first.read_at = datetime.now(UTC)
    await db_session.commit()
    (again,) = await _quiet(db_session)
    assert (again.id, again.read_at is not None) == (first.id, True), "the same silence does not ring twice"

    # New activity, then a new silence: a new reminder, unread.
    await _idle(db_session, pursuit, timedelta(days=22))
    (renewed,) = await _quiet(db_session)
    assert renewed.read_at is None
    assert renewed.meta["since"] != first.meta["since"]


@pytest.mark.parametrize("change", ["activity", "follow_up_date", "stage"])
async def test_a_quiet_reminder_leaves_when_the_pursuit_moves(db_session, change):
    pursuit = await _pursuit(db_session, "applied", timedelta(days=30))
    assert len(await _quiet(db_session)) == 1
    if change == "activity":
        await _idle(db_session, pursuit, timedelta(hours=1))
    elif change == "follow_up_date":
        pursuit.next_action_due = datetime.now(UTC) + timedelta(days=3)
        await db_session.commit()
    else:
        pursuit.stage = "rejected"
        await db_session.commit()
    assert await _quiet(db_session) == []


async def test_a_pursuit_with_a_follow_up_date_is_the_follow_up_reminder_s_alone(db_session):
    await _pursuit(db_session, "applied", timedelta(days=30), due=datetime.now(UTC) + timedelta(days=2))
    assert await _quiet(db_session) == []
