"""`db_session` starts every test where truncating every table would.

The reset skips tables a test never wrote, so these hold it to the full
TRUNCATE's result: empty tables, restarted sequences, and no row a still-open
session commits afterwards.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from tests.barriers import until_waiting
from tests.conftest import _owned_sequences, _reset
from tracker.db.models import AppSetting, Base, ScrapeRun

pytestmark = pytest.mark.asyncio


async def _left_behind(conn) -> dict[str, object]:
    counts = (await conn.execute(text(" UNION ALL ".join(
        f"SELECT '{name}', count(*) FROM \"{name}\"" for name in Base.metadata.tables
    )))).all()
    moved = (await conn.execute(text(" UNION ALL ".join(
        f"SELECT '{name}', last_value FROM \"{name}\" WHERE is_called OR last_value <> {start}"
        for name, start in _owned_sequences.items()
    )))).all()
    return {**{name: count for name, count in counts if count}, **dict(moved)}


async def test_a_reset_leaves_every_table_empty_and_every_owned_sequence_restarted(db_session):
    assert "scrape_runs_id_seq" in _owned_sequences, "the sequences come from the real schema"
    db_session.add_all([AppSetting(key="planted", value={"n": 1}), ScrapeRun(status="running"), ScrapeRun(status="ok")])
    await db_session.commit()
    first = sorted((await db_session.scalars(text("SELECT id FROM scrape_runs"))).all())
    await db_session.execute(text("DELETE FROM scrape_runs WHERE id = :id"), {"id": first[-1]})
    # A sequence moved with no row left behind, and one set back without being called.
    sequences = [name for name in _owned_sequences if name != "scrape_runs_id_seq"]
    await db_session.execute(text(f"SELECT setval('\"{sequences[0]}\"', 41)"))
    await db_session.execute(text(f"SELECT setval('\"{sequences[1]}\"', 50, false)"))
    await db_session.commit()

    async with db_session.bind.begin() as conn:
        assert set(await _left_behind(conn)) >= {"app_settings", "scrape_runs", "scrape_runs_id_seq", *sequences[:2]}
        files = await _relfilenodes(conn)
        await _reset(conn)
    async with db_session.bind.connect() as conn:
        assert await _left_behind(conn) == {}
        after = await _relfilenodes(conn)
    assert after["company_fact"] == files["company_fact"], "a table nobody wrote is left alone, so this checked the narrow reset"
    assert after["scrape_runs"] != files["scrape_runs"]

    db_session.add(ScrapeRun(status="running"))
    await db_session.commit()
    assert (await db_session.scalars(text("SELECT id FROM scrape_runs"))).all() == [1]


async def test_a_reset_waits_for_a_session_that_has_not_committed_yet(db_session):
    """A row still uncommitted when the reset reads is invisible to it; the reset
    must not let that row survive into the next test."""
    engine = db_session.bind
    async with engine.connect() as writer, engine.connect() as resetter:
        await writer.execute(text("INSERT INTO app_settings (key, value) VALUES ('late', '{}'::jsonb)"))
        pid = (await resetter.execute(text("SELECT pg_backend_pid()"))).scalar()
        await resetter.commit()
        reset = asyncio.create_task(_reset_and_commit(resetter))
        await until_waiting(engine, reset, pid=pid)
        assert not reset.done(), "the reset waits on the writer's lock instead of reading past it"
        await writer.commit()
        await asyncio.wait_for(reset, 10)
    async with engine.connect() as conn:
        assert await _left_behind(conn) == {}


async def _relfilenodes(conn) -> dict[str, int]:
    rows = await conn.execute(text("SELECT relname, relfilenode FROM pg_class WHERE relname IN ('company_fact', 'scrape_runs')"))
    return dict(rows.all())


async def _reset_and_commit(conn) -> None:
    async with conn.begin():
        await _reset(conn)
