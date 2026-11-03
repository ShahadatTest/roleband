"""Maintenance mode and `stop --jobs`: the running jobs stop (or finish, when
drained), the supervisor lets go of the database and starts nothing, and it
resumes when maintenance is lifted. With no supervisor running, `stop --jobs`
stops what a dead one left behind itself.

Real processes and the test database; every process is a fake job started here.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tracker.db import job_store
from tracker.db.models import JobRequest, JobRun, JobStatus
from tracker.platform.paths import REPO_ROOT
from tracker.platform.power import Power as Machine
from tracker.supervisor import __main__ as cli
from tracker.supervisor import gate, maintenance, singleton
from tracker.supervisor.dispatch import Dispatcher
from tracker.supervisor.registry import JobSpec, OnRequest, Power
from tracker.supervisor.residue import pid_alive
from tracker.supervisor.service import serve

REAL_POPEN = subprocess.Popen
REAL_KILL = os.kill
REAL_KILLPG = os.killpg

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]


@pytest.fixture(autouse=True)
def real_processes(no_escape, monkeypatch):
    """The fake jobs here are real processes this file starts and ends."""
    monkeypatch.setattr(subprocess, "Popen", REAL_POPEN)
    monkeypatch.setattr(os, "kill", REAL_KILL)
    monkeypatch.setattr(os, "killpg", REAL_KILLPG)


#: Ends by itself after a while, so a failing assertion never leaves it behind.
NAP = JobSpec("nap", ("{python}", "-c", "import time; time.sleep(30)"), OnRequest(), power=Power.NONE, uses_database=False)
SHORT = JobSpec("short", ("{python}", "-c", "import time; time.sleep(1.5)"), OnRequest(), power=Power.NONE, uses_database=False)
QUICK = JobSpec("quick", ("{python}", "-c", "pass"), OnRequest(), power=Power.NONE, uses_database=False)


def _dispatcher(db_session, tmp_path, jobs=(NAP, SHORT, QUICK)) -> Dispatcher:
    return Dispatcher(
        factory=async_sessionmaker(db_session.bind, expire_on_commit=False),
        repo_root=REPO_ROOT, data_dir=tmp_path, zone=ZoneInfo("UTC"), jobs=jobs,
        power=lambda: Machine(dark_wake=False, on_battery=False),
        read_gate=lambda _root: gate.Reading(True, None),
        wake_log=lambda: None,
    )


async def _eventually(check, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = check()
        if asyncio.iscoroutine(found):
            found = await found
        if found:
            return found
        await asyncio.sleep(0.05)
    raise AssertionError("not in time")


async def _runs(db_session, job: str) -> list[JobRun]:
    db_session.expire_all()
    return list(await db_session.scalars(select(JobRun).where(JobRun.job == job).order_by(JobRun.id)))


def _paused(data_dir):
    given = maintenance.answered(data_dir, alive=pid_alive)
    return given is not None and given.state == maintenance.PAUSED


async def _ring(db_session, job: str) -> None:
    await job_store.ring(db_session, job, requested_by="cli")
    await db_session.commit()


def _kill_watched(dispatcher: Dispatcher) -> None:
    for watched in dispatcher.watched.values():
        try:
            REAL_KILLPG(watched.launched.pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


# --- the files --------------------------------------------------------------------


async def test_an_answer_counts_only_from_a_live_process_and_for_the_standing_request(tmp_path):
    first = maintenance.request(tmp_path, by="cli")
    assert maintenance.request(tmp_path, by="other") == first, "a second `on` keeps the standing request"
    maintenance.answer(tmp_path, maintenance.PAUSED, first)
    assert maintenance.answered(tmp_path, alive=lambda pid: pid == os.getpid()).state == maintenance.PAUSED
    assert maintenance.answered(tmp_path, alive=lambda _pid: False) is None, "its supervisor died"

    maintenance.lift(tmp_path)
    assert maintenance.answered(tmp_path, alive=lambda _pid: True) is None, "nothing stands to be answered"
    maintenance.request(tmp_path, by="cli")
    assert maintenance.answered(tmp_path, alive=lambda _pid: True) is None, "it answered an earlier request"


# --- the supervisor ----------------------------------------------------------------


async def test_maintenance_stops_the_running_job_lets_go_and_resumes_when_lifted(db_session, tmp_path):
    await _ring(db_session, "nap")
    stop = asyncio.Event()
    dispatcher = _dispatcher(db_session, tmp_path)
    service = asyncio.create_task(
        serve(dispatcher, db_session.bind, stop, idle_seconds=0.1, busy_seconds=0.05, pause_poll_seconds=0.05)
    )
    try:
        await _eventually(lambda: bool(dispatcher.watched))
        pgid = next(iter(dispatcher.watched.values())).launched.pgid

        maintenance.request(tmp_path, by="test")
        await _eventually(lambda: _paused(tmp_path))
        # The engine is shared with this test, so this reads the pool before the
        # test's next query refills it.
        assert db_session.bind.pool.checkedin() == 0, "a paused supervisor keeps no pooled connection"
        [run] = await _runs(db_session, "nap")
        assert (run.state, run.cancel_reason) == (job_store.RUN_CANCELLED, "maintenance")
        with pytest.raises(ProcessLookupError):
            REAL_KILLPG(pgid, 0)
        db_session.expire_all()
        assert (await db_session.get(JobStatus, job_store.SUPERVISOR_KEY)).state == job_store.MAINTENANCE
        assert (await db_session.get(JobStatus, "nap")).reason == job_store.MAINTENANCE

        held = await singleton.hold(db_session.bind)
        assert held is not None, "a paused supervisor holds no lock"
        await singleton.release(held)

        await _ring(db_session, "quick")
        await asyncio.sleep(0.5)
        assert await _runs(db_session, "quick") == [], "nothing starts while paused"

        maintenance.lift(tmp_path)
        [done] = await _eventually(lambda: _finished(db_session, "quick"))
        assert done.exit_code == 0
        assert maintenance.last_answer(tmp_path, alive=pid_alive) is None, "the answer goes with the pause"
    finally:
        stop.set()
        await service
        _kill_watched(dispatcher)


async def _finished(db_session, job: str) -> list[JobRun]:
    runs = await _runs(db_session, job)
    return runs if runs and all(run.state not in job_store.LIVE for run in runs) else []


async def test_a_drain_waits_for_the_running_job_to_finish_by_itself(db_session, tmp_path):
    await _ring(db_session, "short")
    stop = asyncio.Event()
    dispatcher = _dispatcher(db_session, tmp_path)
    service = asyncio.create_task(
        serve(dispatcher, db_session.bind, stop, idle_seconds=0.1, busy_seconds=0.05, pause_poll_seconds=0.05)
    )
    try:
        await _eventually(lambda: bool(dispatcher.watched))
        maintenance.request(tmp_path, by="test", drain=True)
        await _eventually(lambda: maintenance.answered(tmp_path, alive=pid_alive) is not None)
        assert not _paused(tmp_path), "it is still running"
        await _eventually(lambda: _paused(tmp_path))
        [run] = await _runs(db_session, "short")
        assert (run.state, run.exit_code, run.cancel_requested_at) == (job_store.EXITED, 0, None)
    finally:
        maintenance.lift(tmp_path)
        stop.set()
        await service
        _kill_watched(dispatcher)


async def test_a_supervisor_that_starts_in_maintenance_touches_nothing(db_session, tmp_path):
    maintenance.request(tmp_path, by="test")
    await _ring(db_session, "quick")
    stop = asyncio.Event()
    dispatcher = _dispatcher(db_session, tmp_path)
    service = asyncio.create_task(
        serve(dispatcher, db_session.bind, stop, idle_seconds=0.1, pause_poll_seconds=0.05)
    )
    try:
        await _eventually(lambda: _paused(tmp_path))
        await asyncio.sleep(0.3)
        assert await singleton.holder(db_session.bind) is None
        assert await _runs(db_session, "quick") == []
        assert await db_session.get(JobStatus, job_store.SUPERVISOR_KEY) is None, "not even a status row"
    finally:
        stop.set()
        await service


# --- the command line --------------------------------------------------------------


@pytest.fixture
def cli_on_test_db(db_session, tmp_path, monkeypatch):
    from tracker.db import session as db
    from tracker.platform import paths

    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "get_engine", lambda: db_session.bind)
    monkeypatch.setattr(db, "get_session_factory", lambda: async_sessionmaker(db_session.bind, expire_on_commit=False))
    return tmp_path


async def test_maintenance_on_with_no_supervisor_leaves_the_request_standing(cli_on_test_db, capsys):
    code, answered = await cli._maintenance_on(drain=False, wait=1, by="cli")
    assert (code, answered) == (0, False)
    assert maintenance.requested(cli_on_test_db) is not None
    assert "no supervisor is running" in capsys.readouterr().out
    assert await cli._maintenance_off(wait=1) == 0
    assert maintenance.requested(cli_on_test_db) is None


async def test_stop_jobs_with_no_supervisor_stops_what_a_dead_one_left(db_session, cli_on_test_db, capsys):
    """The run's job must be one the registry knows: only those are adopted."""
    left = JobSpec("reestimate", ("{python}", "-c", "import time; time.sleep(30)"), OnRequest(),
                   power=Power.NONE, uses_database=False)
    dead = _dispatcher(db_session, cli_on_test_db, jobs=(left,))
    await _ring(db_session, "reestimate")
    await dead.tick()
    [run] = await _runs(db_session, "reestimate")
    pgid = run.pgid
    orphan = dead.watched[run.id].launched.process

    async def reap():
        # launchd reaps a dead supervisor's orphan; here the test process stands in.
        while orphan.poll() is None:
            await asyncio.sleep(0.05)

    reaper = asyncio.create_task(reap())
    try:
        assert await cli._stop_jobs(wait=20) == 0
        [run] = await _runs(db_session, "reestimate")
        assert (run.state, run.cancel_reason) == (job_store.RUN_CANCELLED, "stop_jobs")
        with pytest.raises(ProcessLookupError):
            REAL_KILLPG(pgid, 0)
        assert maintenance.requested(cli_on_test_db) is not None, "nothing starts until it is lifted"
        assert "every job is stopped" in capsys.readouterr().out
    finally:
        _kill_watched(dead)
        reaper.cancel()
        maintenance.lift(cli_on_test_db)


async def test_stop_jobs_never_stops_runs_while_another_supervisor_holds_the_database(
    db_session, cli_on_test_db, capsys
):
    held = await singleton.hold(db_session.bind)
    try:
        assert await cli._stop_jobs_here(wait=1) == 1
        assert "did not answer" in capsys.readouterr().out
    finally:
        await singleton.release(held)
    requests = list(await db_session.scalars(select(JobRequest)))
    assert requests == []
