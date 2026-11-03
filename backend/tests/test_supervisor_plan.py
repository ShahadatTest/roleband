"""The supervisor's view of one moment, read from real Postgres.

One supervisor per database; code ahead of the schema holds the database jobs;
a queued request starts its job; a plugin run is one key per plugin, and the
trigger its request carries decides whether battery holds it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from tracker.db import job_store
from tracker.supervisor import singleton
from tracker.supervisor.due import Gate, World
from tracker.supervisor.plan import code_heads, plan, schema_ready

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
CLEAR = World(dark_wake=False, on_battery=False, gate=Gate.PASSED, schema_ready=True, zone=ZoneInfo("Europe/Paris"))


async def test_a_second_supervisor_on_the_same_database_does_not_get_the_lock(db_session):
    engine = db_session.bind
    first = await singleton.hold(engine)
    assert first is not None
    try:
        assert await singleton.hold(engine) is None
        assert await singleton.holder(engine) is not None
    finally:
        await singleton.release(first)
    again = await singleton.hold(engine)
    assert again is not None, "a released holder gives the lock up"
    await singleton.release(again)


async def test_a_supervisor_of_another_database_on_the_server_is_not_this_one_s(db_session):
    """Worktrees and scratch copies share the server, each with its own database."""
    import uuid

    from sqlalchemy.ext.asyncio import create_async_engine

    url = db_session.bind.url
    other_name = f"roleband_other_{uuid.uuid4().hex[:8]}"
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{other_name}"'))
    other = create_async_engine(url.set(database=other_name))
    try:
        held = await singleton.hold(other)
        assert held is not None
        try:
            assert await singleton.holder(other) is not None
            assert await singleton.holder(db_session.bind) is None
        finally:
            await singleton.release(held)
    finally:
        await other.dispose()
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{other_name}" WITH (FORCE)'))
        await admin.dispose()


async def test_a_holder_that_dies_gives_the_lock_up(db_session):
    """The OS closes a dead process's connection, and the session's lock with it."""
    engine = db_session.bind
    first = await singleton.hold(engine)
    assert first is not None
    await first.invalidate()
    again = await singleton.hold(engine)
    assert again is not None
    await singleton.release(again)


async def test_the_schema_is_ready_only_at_exactly_the_code_s_revisions(db_session):
    heads = code_heads()
    assert len(heads) == 1, "the migration chain has one head"
    assert not await schema_ready(db_session), "an absent version table is not ready"
    await db_session.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num varchar(32) PRIMARY KEY)"))
    await db_session.execute(text("DELETE FROM alembic_version"))
    await db_session.execute(text("INSERT INTO alembic_version VALUES ('a9c3e7b1d5f2')"))
    assert not await schema_ready(db_session), "a database one migration behind is not ready"
    await db_session.execute(text("UPDATE alembic_version SET version_num = :head"), {"head": next(iter(heads))})
    assert await schema_ready(db_session)
    await db_session.execute(text("INSERT INTO alembic_version VALUES ('unrecognized_head')"))
    assert not await schema_ready(db_session), "an extra database head is not the code's exact schema"
    await db_session.rollback()


async def test_a_queued_request_starts_its_job_and_a_live_run_holds_its_key(db_session):
    await job_store.ring(db_session, "reembed", requested_by="settings")
    await job_store.open_run(db_session, "scan", "scan", trigger="schedule")
    await db_session.commit()

    by_key = {row.key: row.decision for row in await plan(db_session, NOW, CLEAR)}
    assert by_key["reembed"].start
    assert by_key["reembed"].trigger == "request"
    assert not by_key["scan"].start
    assert by_key["scan"].state == "running"
    assert not by_key["reestimate"].start, "a job nobody asked for stays idle"


async def test_plugin_runs_are_one_key_per_plugin_and_battery_holds_only_scheduled_ones(db_session):
    await job_store.ring(
        db_session, "plugin_run", requested_by="plugin", argument="ladders", args={"trigger": "schedule"}
    )
    await job_store.ring(
        db_session, "plugin_run", requested_by="plugin", argument="reported", args={"trigger": "manual"}
    )
    await db_session.commit()

    battery = World(dark_wake=False, on_battery=True, gate=Gate.PASSED, schema_ready=True, zone=CLEAR.zone)
    by_key = {row.key: row.decision for row in await plan(db_session, NOW, battery)}
    assert set(k for k in by_key if k.startswith("plugin_run")) == {"plugin_run:ladders", "plugin_run:reported"}
    assert by_key["plugin_run:ladders"].reason == "waiting_for_mains"
    assert by_key["plugin_run:reported"].start


async def test_code_ahead_of_the_schema_holds_the_scan_but_not_the_preflight(db_session):
    behind = World(dark_wake=False, on_battery=False, gate=Gate.PASSED, schema_ready=False, zone=CLEAR.zone)
    by_key = {row.key: row.decision for row in await plan(db_session, NOW, behind)}
    assert by_key["scan"].reason == "schema_pending"
    assert by_key["preflight"].reason is None
