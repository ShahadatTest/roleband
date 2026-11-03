"""Health under the supervisor: stale data asks for a scan instead of killing
one, a live scan process is not reconciled as stuck, and a database that cannot
be reached is brought back by the supervisor itself."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker

from tracker.db import job_store
from tracker.db import session as db_session_module
from tracker.db.models import JobRequest, JobRun
from tracker.platform.paths import REPO_ROOT
from tracker.supervisor import entries, gate, results
from tracker.supervisor.dispatch import Dispatcher
from tracker.supervisor.service import serve
from tracker.workflows import watchdog

REAL_POPEN = subprocess.Popen
REAL_KILL = os.kill
REAL_KILLPG = os.killpg

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]


@pytest.fixture(autouse=True)
def real_processes(no_escape, monkeypatch):
    """One `sleep` stands in for a scan's process; it is this file's own."""
    monkeypatch.setattr(subprocess, "Popen", REAL_POPEN)
    monkeypatch.setattr(os, "kill", REAL_KILL)
    monkeypatch.setattr(os, "killpg", REAL_KILLPG)


@pytest_asyncio.fixture
async def scoped(db_session, monkeypatch):
    """Every `session_scope` the entries open lands on the scratch database."""
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    @asynccontextmanager
    async def session_scope():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    monkeypatch.setattr(db_session_module, "session_scope", session_scope)
    monkeypatch.setattr(watchdog, "session_scope", session_scope)
    return db_session


async def test_stale_data_asks_for_one_scan_and_never_restarts_a_live_one(scoped):
    live = await job_store.open_run(scoped, "scan", "scan", trigger="schedule")
    await scoped.commit()

    await watchdog.ring_scan()
    await watchdog.ring_scan()

    scoped.expire_all()
    queued = list(await scoped.scalars(select(JobRequest).where(JobRequest.state == job_store.QUEUED)))
    assert [(r.job, r.requested_by) for r in queued] == [("scan", "catch_up")], "two catch-ups are one request"
    runs = list(await scoped.scalars(select(JobRun)))
    assert [(r.id, r.state) for r in runs] == [(live.id, job_store.STARTING)], "the live scan is untouched"


async def test_a_live_scan_whose_process_exists_counts_as_alive_and_a_dead_one_does_not(scoped, monkeypatch):
    sleeper = REAL_POPEN(["sleep", "30"], start_new_session=True)
    try:
        run = await job_store.open_run(scoped, "scan", "scan", trigger="schedule")
        await job_store.mark_running(scoped, run.id, pid=sleeper.pid, pgid=sleeper.pid, proc_started_at=None)
        other = await job_store.open_run(scoped, "backup", "backup", trigger="schedule")
        await job_store.mark_running(scoped, other.id, pid=1, pgid=1, proc_started_at=None)
        await scoped.commit()
        assert await entries.scan_process_alive()
    finally:
        sleeper.kill()
        sleeper.wait()
    assert not await entries.scan_process_alive(), "a scan whose group is gone is not alive"


async def test_without_a_database_the_alive_check_says_no_rather_than_failing(monkeypatch):
    @asynccontextmanager
    async def unreachable():
        raise OSError("connection refused")
        yield

    monkeypatch.setattr(db_session_module, "session_scope", unreachable)
    assert await entries.scan_process_alive() is False


class _Response:
    def __init__(self, status: int, payload: dict | None = None) -> None:
        self.status_code = status
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def stale_world(monkeypatch, tmp_path):
    """The machine as the watchdog reads it: database up, API healthy, data stale.
    Boundaries only: the HTTP replies, the reachability probe, the alert sinks."""
    calls: dict[str, list] = {"processes": [], "reconcile": []}

    async def reachable() -> bool:
        return True

    async def http_get(_client, _base, path, _timeout):
        return _Response(200, {}) if path == "/api/health" else _Response(200, {"status": "stale"})

    async def reconcile(*args):
        calls["reconcile"].append(args)
        return 0

    monkeypatch.setattr(watchdog, "_db_reachable", reachable)
    monkeypatch.setattr(watchdog, "_http_get", http_get)
    monkeypatch.setattr(watchdog, "reconcile_stale_runs", reconcile)
    monkeypatch.setattr(watchdog, "should_catch_up", lambda payload: payload.get("status") == "stale")
    monkeypatch.setattr(watchdog, "stale_derivations", lambda payload: [])
    # Nothing here may start a process: no launchctl, no agent restarted.
    real_run = subprocess.run

    def run(args, *a, **k):
        calls["processes"].append(list(args))
        return real_run(["true"], *a, **k)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(watchdog, "dispatch_alerts", lambda prev, firing: None)
    monkeypatch.setattr(watchdog, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(watchdog, "BACKUPS_DIR", tmp_path / "backups")

    @asynccontextmanager
    async def no_session():
        yield None

    monkeypatch.setattr(watchdog, "session_scope", no_session)
    return calls


async def test_stale_data_rings_a_scan_and_never_reconciles_a_live_one(stale_world):
    rung: list[str] = []

    async def ring() -> None:
        rung.append("scan")

    firing = await watchdog.run_once(catch_up=ring, reconcile_runs=False)
    assert firing.get("stale_data")
    assert rung == ["scan"]
    assert stale_world["processes"] == [], "no launchd agent is restarted"
    assert stale_world["reconcile"] == [], "a live scan process is not reconciled as stuck"


async def test_the_catch_up_is_a_scan_request_by_default():
    """No caller can get a restart of a scheduler agent back: there is none."""
    import inspect

    assert inspect.signature(watchdog.run_once).parameters["catch_up"].default is watchdog.ring_scan


async def test_an_unhealthy_api_is_reported_and_restarted_by_nobody_here(stale_world, monkeypatch):
    """The supervisor that runs the API restarts it; the health pass only says so."""
    async def api_down(_client, _base, path, _timeout):
        return None

    async def nothing_live() -> bool:
        return False

    monkeypatch.setattr(watchdog, "_http_get", api_down)
    monkeypatch.setattr(entries, "scan_process_alive", nothing_live)
    firing = await entries.health()
    assert firing.get("api_down")
    assert stale_world["processes"] == []


@pytest_asyncio.fixture
async def backup_world(stale_world, db_session, monkeypatch, tmp_path):
    """The health pass with the job tables real: everything else healthy, and
    a dump an hour old, well inside the age limit."""
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    @asynccontextmanager
    async def session_scope():
        async with factory() as session:
            yield session
            await session.commit()

    async def fresh(_client, _base, path, _timeout):
        return _Response(200, {})

    monkeypatch.setattr(watchdog, "session_scope", session_scope)
    monkeypatch.setattr(watchdog, "_http_get", fresh)
    dumps = tmp_path / "backups"
    dumps.mkdir()
    dump = dumps / "roleband_20261019_063000.dump"
    dump.write_bytes(b"dump")
    hour_ago = time.time() - 3600
    os.utime(dump, (hour_ago, hour_ago))
    return dumps


async def _backup_run(db_session, state: str, exit_code: int | None) -> None:
    run = await job_store.open_run(db_session, "backup", "backup", trigger="schedule")
    assert run is not None
    result = results.summarize("backup", exit_code, None) if state == job_store.EXITED else None
    await job_store.finish_run(db_session, run.id, state=state, exit_code=exit_code, result=result)
    await db_session.commit()


@pytest.mark.parametrize(
    ("state", "exit_code", "alerts"),
    [
        (job_store.EXITED, 1, True),
        (job_store.TIMED_OUT, None, True),
        (job_store.SPAWN_FAILED, None, True),
        (job_store.EXITED, 0, False),
        (job_store.RUN_CANCELLED, None, False),
    ],
)
async def test_a_failed_backup_run_alerts_on_the_next_pass_while_the_newest_dump_is_still_fresh(
    backup_world, db_session, state, exit_code, alerts,
):
    await _backup_run(db_session, state, exit_code)
    firing = await watchdog.run_once(catch_up=_nothing, reconcile_runs=False)
    assert bool(firing.get("backup_stale")) is alerts


async def test_a_dump_that_landed_after_the_failed_run_clears_the_alert(backup_world, db_session):
    await _backup_run(db_session, job_store.EXITED, 1)
    later = time.time() + 60
    os.utime(backup_world / "roleband_20261019_063000.dump", (later, later))
    firing = await watchdog.run_once(catch_up=_nothing, reconcile_runs=False)
    assert not firing.get("backup_stale")


async def test_only_an_ended_backup_run_counts_so_a_live_one_after_a_failure_does_not_hide_it(backup_world, db_session):
    await _backup_run(db_session, job_store.EXITED, 1)
    assert await job_store.open_run(db_session, "backup", "backup", trigger="schedule") is not None
    await db_session.commit()
    firing = await watchdog.run_once(catch_up=_nothing, reconcile_runs=False)
    assert firing.get("backup_stale")


async def test_without_any_backup_run_recorded_only_the_dump_age_decides(backup_world):
    firing = await watchdog.run_once(catch_up=_nothing, reconcile_runs=False)
    assert not firing.get("backup_stale")


async def _nothing() -> None:
    return None


class _Failing(Dispatcher):
    errors: list[BaseException] = []

    async def adopt(self):
        return []

    async def tick(self, now=None):
        raise self.errors.pop(0) if self.errors else RuntimeError("no more")


async def test_an_unreachable_database_is_recovered_by_the_supervisor_and_a_query_bug_is_not(db_session, tmp_path):
    recoveries: list[str] = []
    dispatcher = _Failing(
        factory=async_sessionmaker(db_session.bind), repo_root=REPO_ROOT, data_dir=tmp_path,
        zone=ZoneInfo("UTC"), jobs=(), read_gate=lambda _root: gate.Reading(True, None),
    )
    dispatcher.errors = [
        OperationalError("SELECT 1", {}, OSError("connection refused")),
        OperationalError("SELECT 1", {}, OSError("connection refused")),
        ProgrammingError("SELECT nope", {}, Exception("syntax error")),
    ]
    stop = asyncio.Event()
    service = asyncio.create_task(
        serve(
            dispatcher, db_session.bind, stop, idle_seconds=0.05,
            recover=lambda: recoveries.append("recover") or None, recover_every_seconds=60,
        )
    )
    await asyncio.sleep(0.5)
    stop.set()
    await service
    assert recoveries == ["recover"], "recovered once, not once per failing tick, and never for a SQL bug"


class _Unmigrated(Dispatcher):
    adopts = 0
    ticks = 0

    async def adopt(self):
        self.adopts += 1
        if self.adopts < 3:
            raise ProgrammingError("SELECT job_runs", {}, Exception('relation "job_runs" does not exist'))
        return []

    async def tick(self, now=None):
        self.ticks += 1
        return []


async def test_a_database_without_the_job_tables_is_waited_out_not_crashed_on(db_session, tmp_path):
    """Under launchd a crash would loop; the supervisor waits and looks again,
    and supervises once the tables are there."""
    dispatcher = _Unmigrated(
        factory=async_sessionmaker(db_session.bind), repo_root=REPO_ROOT, data_dir=tmp_path,
        zone=ZoneInfo("UTC"), jobs=(), read_gate=lambda _root: gate.Reading(True, None),
    )
    stop = asyncio.Event()
    service = asyncio.create_task(serve(dispatcher, db_session.bind, stop, idle_seconds=0.05))
    deadline = asyncio.get_running_loop().time() + 5
    while dispatcher.ticks == 0 and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.05)
    stop.set()
    await service
    assert dispatcher.adopts == 3
    assert dispatcher.ticks >= 1
