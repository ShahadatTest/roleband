"""Liveness heartbeat: the ticker that keeps a run's ``heartbeat_at`` fresh.

The ticker is exercised without a live database, against a fake
``session_scope`` recording its UPDATEs: what matters here is that it keeps
beating across a failed beat and stops on cancel.

What the beat MEANS is next door. ``reconcile_stale_runs`` answers to real
Postgres in ``test_stale_runs.py`` (a check on its SQL string would pass a
reconciler that stopped flipping rows), beside the one predicate it shares with
``/api/status``'s stuck count. The pure liveness decision that
consumes the heartbeat is ``is_run_active`` (``test_api_sync.py``, and held to
the SQL predicate row by row in ``test_stale_runs.py``).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import tracker.workflows.pipeline as pipeline


class _RecordingSession:
    """Captures every execute(stmt, params) and returns a rowcount result."""

    def __init__(self, rowcount: int = 0) -> None:
        self.execs: list[tuple[str, dict | None]] = []
        self._rowcount = rowcount

    async def execute(self, stmt, params=None):
        self.execs.append((str(stmt), params))
        return SimpleNamespace(rowcount=self._rowcount)


@pytest.mark.asyncio
async def test_heartbeat_loop_bumps_heartbeat_then_stops_on_cancel(monkeypatch):
    session = _RecordingSession()

    @asynccontextmanager
    async def fake_scope():
        yield session

    monkeypatch.setattr(pipeline, "session_scope", fake_scope)

    task = pipeline._heartbeat_task(run_id=42, interval_seconds=0.001)
    await asyncio.sleep(0.02)  # let it beat several times
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert session.execs, "the loop must issue at least one heartbeat UPDATE"
    sql, params = session.execs[0]
    assert "heartbeat_at = now()" in sql
    assert "status = 'running'" in sql  # never resurrects a terminal run
    assert params == {"id": 42}


@pytest.mark.asyncio
async def test_heartbeat_loop_survives_a_failed_beat(monkeypatch):
    # One bad beat (e.g. a transient DB blip) must not kill the ticker.
    calls = {"n": 0}

    @asynccontextmanager
    async def flaky_scope():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient db error")
        yield _RecordingSession()

    monkeypatch.setattr(pipeline, "session_scope", flaky_scope)

    task = pipeline._heartbeat_task(run_id=7, interval_seconds=0.001)
    # The first failed beat logs its traceback, which a loaded host can take
    # well past one interval to format; the claim is the beat after it.
    for _ in range(500):
        if calls["n"] >= 2 or task.done():
            break
        await asyncio.sleep(0.01)
    still_running = not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls["n"] >= 2, "ticker should keep beating after a failed beat"
    assert still_running


@pytest.mark.asyncio
async def test_a_progress_write_that_fails_never_costs_the_run_its_beat(db_session, scratch_scope, monkeypatch):
    """Progress is display and the beat is liveness: a progress UPDATE that
    fails on every tick must still leave `heartbeat_at` fresh, or every guard
    reads the live run as dead."""
    from datetime import UTC, datetime, timedelta

    from tracker.db.models import ScrapeRun

    old = datetime.now(UTC) - timedelta(hours=1)
    run = ScrapeRun(status="running", heartbeat_at=old)
    db_session.add(run)
    await db_session.commit()

    tried = asyncio.Event()

    async def broken_progress(session, run_id, snapshot):
        tried.set()
        raise RuntimeError("notifications schema mismatch")

    monkeypatch.setattr(pipeline, "update_sync_progress", broken_progress)
    task = pipeline._heartbeat_task(
        run_id=run.id, interval_seconds=0.5, progress=SimpleNamespace(snapshot=lambda: {"done": 1}),
    )
    await asyncio.wait_for(tried.wait(), timeout=5)
    # Cancelled while the loop sleeps, after the first beat has finished.
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    run_id = run.id
    db_session.expire_all()
    beat = (await db_session.get(ScrapeRun, run_id)).heartbeat_at
    assert beat > old + timedelta(minutes=59)


@pytest.mark.asyncio
async def test_a_streak_of_failed_beats_warns_and_its_end_is_noted(caplog):
    from tracker.platform import heartbeat

    outcomes = iter([*([RuntimeError("down")] * 12), None, None])
    stop = asyncio.Event()

    async def tick():
        outcome = next(outcomes, None)
        if outcome is not None:
            raise outcome
        stop.set()

    caplog.set_level("DEBUG", logger="tracker.platform.heartbeat")
    task = asyncio.create_task(heartbeat.heartbeat_loop(tick, 0, log_name="probe"))
    await asyncio.wait_for(stop.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert [r.getMessage() for r in warnings] == [
        "probe tick failed (1 in a row)", "probe tick failed (11 in a row)",
    ]
    assert all(r.exc_info for r in warnings), "a warning carries its traceback"
    assert "probe beating again after 12 failed ticks" in [r.getMessage() for r in caplog.records]
