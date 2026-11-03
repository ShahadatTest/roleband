"""Follow-up reminders follow the pursuit, not the scan clock.

A `pursuit_due` reconcile run only at a scrape's finalization rings nothing
when nothing is followed, only Workday is followed (never collected
automatically), or bindings are hours apart, and a pursuit ended from Job detail
(Rejected, Withdrawn) would keep its reminder until the next run. A reminder
dismissed for one follow-up must not swallow the next one on that pursuit (a
row keyed by pursuit keeps `dismissed_at`), and a reconcile run at write time
beside the run's own must not deadlock on the reminder rows.

Real Postgres; the pursuit writes go through the real HTTP route and MCP tool.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.barriers import until_waiting
from tracker.db.models import Job, Notification, Pursuit
from tracker.notifications.pursuit_due import generate_pursuit_due_notifications

pytestmark = pytest.mark.asyncio


async def _job(db_session) -> Job:
    now = datetime.now(UTC)
    job = Job(
        company="openai", req_id="r1", dedupe_key="openai:r1", title="Staff PM",
        url="https://careers.example.test/r1", level_band="staff", status="open",
        first_seen=now - timedelta(days=5), last_seen=now, in_scope=True,
    )
    db_session.add(job)
    await db_session.commit()
    return job


async def _reminders(db_session) -> list[Notification]:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as session:
        return list(
            (
                await session.scalars(
                    select(Notification).where(Notification.category == "pursuit_due")
                )
            ).all()
        )


def _due(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


async def test_a_follow_up_set_already_owed_rings_without_a_scan(api_client, db_session):
    job = await _job(db_session)
    response = await api_client.put(
        f"/api/jobs/{job.id}/pursuit",
        json={"stage": "applied", "next_action": "Email the recruiter", "next_action_due": _due(1)},
    )
    assert response.status_code == 200, response.text
    (row,) = await _reminders(db_session)
    assert row.job_id == job.id and "Email the recruiter" in (row.body or "")


async def test_ending_a_pursuit_retracts_its_reminder_at_once(api_client, db_session):
    job = await _job(db_session)
    db_session.add(Pursuit(job_id=job.id, stage="applied", next_action_due=datetime.now(UTC) - timedelta(days=1)))
    await db_session.commit()
    await generate_pursuit_due_notifications(db_session)  # the last run's reconcile
    await db_session.commit()
    assert len(await _reminders(db_session)) == 1

    response = await api_client.put(f"/api/jobs/{job.id}/pursuit", json={"stage": "rejected"})
    assert response.status_code == 200, response.text
    assert await _reminders(db_session) == []


async def test_a_dismissed_reminder_never_swallows_the_next_follow_up(api_client, db_session):
    job = await _job(db_session)
    await api_client.put(
        f"/api/jobs/{job.id}/pursuit", json={"stage": "applied", "next_action_due": _due(3)}
    )
    (first,) = await _reminders(db_session)
    dismissed = await api_client.post(f"/api/notifications/{first.id}/dismiss")
    assert dismissed.status_code == 200, dismissed.text

    # The next follow-up, set already owed (the agent's "due today").
    await api_client.put(f"/api/jobs/{job.id}/pursuit", json={"next_action_due": _due(0.1)})

    (row,) = await _reminders(db_session)
    assert row.dismissed_at is None and row.read_at is None
    assert row.created_at > first.created_at


async def test_the_same_follow_up_stays_dismissed(api_client, db_session):
    """Negative control: a reconcile that finds the same due time refreshes
    the row's wording only; the person's dismissal stands."""
    job = await _job(db_session)
    await api_client.put(
        f"/api/jobs/{job.id}/pursuit", json={"stage": "applied", "next_action_due": _due(3)}
    )
    (first,) = await _reminders(db_session)
    await api_client.post(f"/api/notifications/{first.id}/dismiss")
    await api_client.put(f"/api/jobs/{job.id}/pursuit", json={"notes": "called twice"})
    await generate_pursuit_due_notifications(db_session)
    await db_session.commit()

    (row,) = await _reminders(db_session)
    assert row.id == first.id and row.dismissed_at is not None


async def test_the_agent_setting_an_owed_follow_up_rings(db_session, scratch_scope):
    import tracker.mcp.server as server
    from tracker.agents.config import AgentAccessConfig, set_agent_access

    await set_agent_access(db_session, AgentAccessConfig(enabled=True, allow_writes=True))
    await db_session.commit()
    job = await _job(db_session)

    await server.update_pursuit(
        job.id, stage="applied", next_action_due=datetime.now(UTC) - timedelta(hours=2)
    )
    assert len(await _reminders(db_session)) == 1


async def test_an_idle_tick_rings_a_follow_up_that_fell_due(db_session, scratch_scope, monkeypatch):
    """No binding due, no run: the follow-up that fell due since the last
    write still rings (DB-only; the tick already waited out a maintenance
    wake before it got here)."""
    from tracker.workflows import scheduler

    job = await _job(db_session)
    db_session.add(Pursuit(job_id=job.id, stage="applied", next_action_due=datetime.now(UTC) - timedelta(minutes=5)))
    await db_session.commit()

    async def nothing_due(_now, **_):
        return scheduler.TickPlan([])

    async def no_retention(_now):
        class Done:
            removed, more = 0, False
        return Done()

    monkeypatch.setattr(scheduler, "plan_tick", nothing_due)
    monkeypatch.setattr(scheduler, "retention_when_idle", no_retention)

    result = await scheduler.run_once()

    assert result["reason"] == "nothing due"
    assert result["reminders"] == {"owed": 1}
    assert len(await _reminders(db_session)) == 1


async def test_two_reconciles_run_one_after_the_other(db_session):
    """Broken rule caught: a write-time reconcile beside the run's own touched
    the reminder rows in opposite orders and Postgres aborted one."""
    job = await _job(db_session)
    db_session.add(Pursuit(job_id=job.id, stage="applied", next_action_due=datetime.now(UTC) - timedelta(days=1)))
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as one, factory() as two:
        await generate_pursuit_due_notifications(one)
        later = asyncio.create_task(generate_pursuit_due_notifications(two))
        await until_waiting(db_session.bind, later)
        assert not later.done(), "the second reconcile must wait for the first transaction"
        await one.commit()
        assert await asyncio.wait_for(later, 10) == 1
        await two.commit()
    assert len(await _reminders(db_session)) == 1


async def test_the_reconcile_holds_its_lock_until_its_transaction_ends(db_session):
    """The serialization above, by contract rather than by row timing."""
    from sqlalchemy import text

    from tracker.notifications.pursuit_due import PURSUIT_DUE_LOCK_KEY

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as one, factory() as probe:
        await generate_pursuit_due_notifications(one)
        held = await probe.scalar(
            # This database only: parallel workers' scratch databases (and the
            # live one) hold the same key in their own lock space.
            text(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = :k "
                "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
            ),
            {"k": PURSUIT_DUE_LOCK_KEY},
        )
        await one.commit()
    assert held == 1
