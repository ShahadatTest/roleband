"""The supervisor service: woken by a commit, alone on its database, and a stop
that leaves running jobs alone."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tracker.db import job_store
from tracker.db.models import JobRun, JobStatus
from tracker.platform.paths import REPO_ROOT
from tracker.platform.power import Power as Machine
from tracker.supervisor import gate, logs, runner, singleton
from tracker.supervisor.dispatch import Dispatcher
from tracker.supervisor.registry import JobSpec, OnRequest, Power
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


NAP = JobSpec("nap", ("{python}", "-c", "import time; time.sleep(30)"), OnRequest(), power=Power.NONE, uses_database=False)


class Counting(Dispatcher):
    """Counts the full looks, the cheap busy-turn looks and the power readings."""

    ticks = 0
    settles = 0
    readings = 0

    async def tick(self, now=None):
        self.ticks += 1
        return await super().tick(now)

    async def settle(self):
        self.settles += 1
        return await super().settle()


def _machine(dispatcher: Counting) -> Machine:
    dispatcher.readings += 1
    return Machine(dark_wake=False, on_battery=False)


def _dispatcher(db_session, tmp_path, jobs=(NAP,)) -> Counting:
    dispatcher = Counting(
        factory=async_sessionmaker(db_session.bind, expire_on_commit=False),
        repo_root=REPO_ROOT, data_dir=tmp_path, zone=ZoneInfo("UTC"), jobs=jobs,
        read_gate=lambda _root: gate.Reading(True, None),
        wake_log=lambda: None,
    )
    dispatcher.power = lambda: _machine(dispatcher)
    return dispatcher


async def _live(db_session) -> list[JobRun]:
    db_session.expire_all()
    return list(await db_session.scalars(select(JobRun).where(JobRun.state.in_(job_store.LIVE))))


async def _eventually(check, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = await check()
        if found:
            return found
        await asyncio.sleep(0.05)
    raise AssertionError("not in time")


async def test_a_committed_request_wakes_the_supervisor_long_before_its_poll(db_session, tmp_path):
    stop = asyncio.Event()
    dispatcher = _dispatcher(db_session, tmp_path)
    service = asyncio.create_task(serve(dispatcher, db_session.bind, stop, idle_seconds=60))
    try:
        await _eventually(lambda: asyncio.sleep(0, result=dispatcher.ticks >= 1))
        await job_store.ring(db_session, "nap", requested_by="cli")
        await db_session.commit()
        started = time.monotonic()
        [run] = await _eventually(lambda: _live(db_session), timeout=3)
        assert time.monotonic() - started < 3, "the notification, not the 60 s poll, started it"
    finally:
        stop.set()
        await service
        for watched in dispatcher.watched.values():
            REAL_KILLPG(watched.launched.pgid, signal.SIGKILL)


async def test_a_second_supervisor_never_dispatches_while_the_first_holds_the_database(db_session, tmp_path):
    stop = asyncio.Event()
    first = _dispatcher(db_session, tmp_path)
    second = _dispatcher(db_session, tmp_path / "other")
    one = asyncio.create_task(serve(first, db_session.bind, stop, idle_seconds=0.1))
    await _eventually(lambda: asyncio.sleep(0, result=first.ticks >= 1))
    two = asyncio.create_task(serve(second, db_session.bind, stop, idle_seconds=0.1, lock_retry_seconds=0.1))
    await asyncio.sleep(0.6)
    stop.set()
    await asyncio.gather(one, two)

    assert first.ticks > 1
    assert second.ticks == 0
    again = await singleton.hold(db_session.bind)
    assert again is not None, "a stopped supervisor gives the database up"
    await singleton.release(again)


async def test_a_stop_ends_supervision_and_leaves_the_running_job_running(db_session, tmp_path):
    await job_store.ring(db_session, "nap", requested_by="cli")
    await db_session.commit()
    stop = asyncio.Event()
    dispatcher = _dispatcher(db_session, tmp_path)
    service = asyncio.create_task(serve(dispatcher, db_session.bind, stop, idle_seconds=0.1))
    [run] = await _eventually(lambda: _live(db_session))
    await _eventually(lambda: asyncio.sleep(0, result=bool(dispatcher.watched)))
    pgid = next(iter(dispatcher.watched.values())).launched.pgid

    stop.set()
    await service
    try:
        REAL_KILL(pgid, 0)
        [still] = await _live(db_session)
        assert still.id == run.id, "the run stays live for the next supervisor to adopt"
    finally:
        REAL_KILLPG(pgid, signal.SIGKILL)


class FakeApi:
    """The service's view of the API: tended each look, stopped on the way out."""

    def __init__(self, tmp_path) -> None:
        self.log = tmp_path / "api.log"
        self.state = "running"
        self.events: list[str] = []

    async def tend(self, now) -> None:
        self.events.append("tend")

    async def stop(self, grace_seconds: float = 30.0) -> None:
        self.events.append("stop")

    def status(self):
        return job_store.Status(key="api", job="api", state=self.state, since=datetime.now(UTC))


class ScriptedWatcher:
    held = None
    building = False

    def __init__(self, steps) -> None:
        self.steps = list(steps)

    async def look(self, now):
        from tracker.supervisor.activation import NOTHING, Step

        return self.steps.pop(0) if self.steps else Step(NOTHING)


async def test_landed_code_restarts_the_supervisor_only_after_the_api_stops_and_the_lock_is_free(db_session, tmp_path):
    from tracker.supervisor.activation import NOTHING, RESTART, Step

    api = FakeApi(tmp_path)
    order: list[str] = []

    def reexec() -> None:
        order.extend(api.events[-1:])

    stop = asyncio.Event()
    dispatcher = _dispatcher(db_session, tmp_path)
    watcher = ScriptedWatcher([Step(NOTHING), Step(RESTART)])
    await asyncio.wait_for(
        serve(dispatcher, db_session.bind, stop, idle_seconds=0.05, api=api, watcher=watcher, reexec=reexec),
        timeout=10,
    )
    assert order[0] == "stop", "the API stops before the exec"
    assert api.events.count("tend") == 2
    again = await singleton.hold(db_session.bind)
    assert again is not None, "the lock is free for the new image"
    await singleton.release(again)
    rows = {row.key: row for row in await db_session.scalars(select(JobStatus))}
    assert rows["api"].state == "running", "the API publishes its row beside the jobs"


async def test_a_dashboard_built_without_a_landing_restarts_only_the_api(db_session, tmp_path):
    from tracker.supervisor.activation import RESTART_API, Step

    api = FakeApi(tmp_path)
    reexecs: list[int] = []
    stop = asyncio.Event()
    dispatcher = _dispatcher(db_session, tmp_path)
    service = asyncio.create_task(
        serve(dispatcher, db_session.bind, stop, idle_seconds=0.05, api=api,
              watcher=ScriptedWatcher([Step(RESTART_API)]), reexec=lambda: reexecs.append(1))
    )
    await _eventually(lambda: asyncio.sleep(0, result=api.events.count("tend") >= 2))
    stop.set()
    await service
    assert api.events[:3] == ["tend", "stop", "tend"], "stopped, then started again by the next look"
    assert reexecs == []


async def test_the_loop_beats_while_it_supervises_and_while_it_is_paused(db_session, tmp_path):
    from tracker.supervisor import maintenance

    beats: list[float] = []
    stop = asyncio.Event()
    dispatcher = _dispatcher(db_session, tmp_path)
    service = asyncio.create_task(
        serve(dispatcher, db_session.bind, stop, idle_seconds=0.05, pause_poll_seconds=0.05,
              beat=lambda: beats.append(time.monotonic()))
    )
    try:
        await _eventually(lambda: asyncio.sleep(0, result=len(beats) >= 3))
        maintenance.request(tmp_path, by="test")
        await _eventually(lambda: asyncio.sleep(0, result=maintenance.answered(tmp_path, alive=lambda _p: True) is not None
                                                and maintenance.answered(tmp_path, alive=lambda _p: True).state == "paused"))
        paused_at = len(beats)
        await _eventually(lambda: asyncio.sleep(0, result=len(beats) >= paused_at + 3))
    finally:
        maintenance.lift(tmp_path)
        stop.set()
        await service


#: Writes past the rotation limit, then stays alive so the supervisor watches it.
LOUD = JobSpec(
    "loud",
    ("{python}", "-c", f"import sys, time; sys.stdout.write('x' * {logs.LIMIT_BYTES + 1}); sys.stdout.flush(); time.sleep(30)"),
    OnRequest(), power=Power.NONE, uses_database=False,
)


async def test_a_run_whose_log_rotates_says_so_and_a_run_in_another_log_does_not(db_session, tmp_path):
    log = runner.log_path(tmp_path, LOUD)
    earlier = await job_store.open_run(db_session, "loud", "loud:earlier", trigger="request")
    elsewhere = await job_store.open_run(db_session, "nap", "nap:elsewhere", trigger="request")
    assert earlier is not None and elsewhere is not None
    earlier_id, elsewhere_id = earlier.id, elsewhere.id
    for run, path in ((earlier, log), (elsewhere, runner.log_path(tmp_path, NAP))):
        await job_store.mark_running(db_session, run.id, pid=1, pgid=1, proc_started_at=None,
                                     log_path=str(path), log_offset=0)
        await job_store.finish_run(db_session, run.id, state=job_store.EXITED, exit_code=0)
    await job_store.ring(db_session, "loud", requested_by="cli")
    await db_session.commit()
    stop = asyncio.Event()
    dispatcher = _dispatcher(db_session, tmp_path, jobs=(NAP, LOUD))
    service = asyncio.create_task(serve(dispatcher, db_session.bind, stop, idle_seconds=0.05, busy_seconds=0.05))

    async def rotated() -> list[JobRun]:
        db_session.expire_all()
        return list(await db_session.scalars(select(JobRun).where(JobRun.log_rotated.is_(True))))

    try:
        marked = await _eventually(rotated, timeout=15)
        assert logs.rotated(log).stat().st_size > logs.LIMIT_BYTES
        assert log.stat().st_size < logs.LIMIT_BYTES
        live = [run for run in marked if run.state in job_store.LIVE]
        assert len(live) == 1 and live[0].job == "loud", "the run that wrote past the limit"
        assert earlier_id in {run.id for run in marked}, "an earlier run in the same file"
        assert elsewhere_id not in {run.id for run in marked}
    finally:
        stop.set()
        await service
        for watched in dispatcher.watched.values():
            REAL_KILLPG(watched.launched.pgid, signal.SIGKILL)


async def test_the_supervisor_bounds_its_own_log_the_alerts_and_the_postgres_server_log(db_session, tmp_path):
    pgdata = tmp_path / "pg"
    shared = logs.shared(tmp_path, pgdata)
    for path in shared:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * (logs.LIMIT_BYTES + 1))
    stop = asyncio.Event()
    dispatcher = _dispatcher(db_session, tmp_path)
    service = asyncio.create_task(serve(dispatcher, db_session.bind, stop, idle_seconds=0.05, rotate=shared))
    try:
        await _eventually(lambda: asyncio.sleep(0, result=all(logs.rotated(p).exists() for p in shared)))
    finally:
        stop.set()
        await service
    assert {p.name for p in shared} == {"supervisor.log", "alerts.log", "log"}
    assert pgdata / "log" in shared
    assert all(p.stat().st_size == 0 for p in shared)


# --- the busy loop: cheap turns between full looks ---------------------------------

QUICK = JobSpec("quick", ("{python}", "-c", "import time; time.sleep(0.5)"), OnRequest(), power=Power.NONE, uses_database=False)


async def _shut(stop: asyncio.Event, service: asyncio.Task, dispatcher: Dispatcher) -> None:
    stop.set()
    await service
    for watched in dispatcher.watched.values():
        try:
            REAL_KILLPG(watched.launched.pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass


async def _busy(db_session, tmp_path, jobs=(NAP, QUICK), **timing):
    """A supervisor whose `nap` run is under way, after the turn that started it."""
    await job_store.ring(db_session, "nap", requested_by="cli")
    await db_session.commit()
    stop = asyncio.Event()
    dispatcher = _dispatcher(db_session, tmp_path, jobs=jobs)
    service = asyncio.create_task(serve(dispatcher, db_session.bind, stop, **timing))
    await _eventually(lambda: asyncio.sleep(0, result=bool(dispatcher.watched)))
    await asyncio.sleep(0.2)
    return stop, service, dispatcher


async def test_a_supervisor_waiting_on_a_running_job_only_watches_it_between_full_looks(db_session, tmp_path):
    """No plan, no `pmset`, no status write while nothing changes: each turn
    is the one query that asks whether the run was cancelled."""
    statements: list[str] = []

    def counted(_conn, _cursor, statement, *_args) -> None:
        statements.append(statement)

    stop, service, dispatcher = await _busy(db_session, tmp_path, idle_seconds=60, busy_seconds=0.05)
    event.listen(db_session.bind.sync_engine, "before_cursor_execute", counted)
    try:
        ticks, settles, readings = dispatcher.ticks, dispatcher.settles, dispatcher.readings
        statements.clear()
        await asyncio.sleep(1.0)
        turns = dispatcher.settles - settles
        assert turns >= 5, "every busy turn still watches for the end"
        assert dispatcher.ticks == ticks, "nothing ended, nothing rang, the idle interval is far"
        assert dispatcher.readings == readings, "no power reading"
        assert not [s for s in statements if "job_status" in s], "no status rewritten"
        assert all(s.lstrip().upper().startswith("SELECT") for s in statements), statements
        assert len(statements) <= turns + 1
    finally:
        event.remove(db_session.bind.sync_engine, "before_cursor_execute", counted)
        await _shut(stop, service, dispatcher)


async def test_while_a_job_runs_the_full_look_and_the_heartbeat_still_come_every_idle_interval(db_session, tmp_path):
    stop, service, dispatcher = await _busy(db_session, tmp_path, idle_seconds=0.4, busy_seconds=0.05)
    try:
        db_session.expire_all()
        before = (await db_session.get(JobStatus, job_store.SUPERVISOR_KEY)).updated_at
        ticks, settles = dispatcher.ticks, dispatcher.settles
        await asyncio.sleep(1.5)
        looks = dispatcher.ticks - ticks
        assert 2 <= looks <= 6, f"{looks} full looks in 1.5 s at a 0.4 s idle interval"
        assert dispatcher.settles - settles > looks, "the turns between them are the cheap ones"
        db_session.expire_all()
        after = (await db_session.get(JobStatus, job_store.SUPERVISOR_KEY)).updated_at
        assert after > before, "the supervisor's row stays fresh while it only waits"
    finally:
        await _shut(stop, service, dispatcher)


async def test_an_end_is_recorded_and_published_within_a_busy_turn_while_the_full_look_is_far(db_session, tmp_path):
    await job_store.ring(db_session, "quick", requested_by="cli")
    await db_session.commit()
    stop = asyncio.Event()
    dispatcher = _dispatcher(db_session, tmp_path, jobs=(QUICK,))
    service = asyncio.create_task(serve(dispatcher, db_session.bind, stop, idle_seconds=60, busy_seconds=0.2))

    async def ended() -> list[JobRun]:
        db_session.expire_all()
        return list(await db_session.scalars(
            select(JobRun).where(JobRun.job == "quick", JobRun.state == job_store.EXITED)
        ))

    async def published() -> JobStatus | None:
        db_session.expire_all()
        status = await db_session.get(JobStatus, "quick")
        return status if status is not None and status.state != "running" else None

    try:
        await _eventually(lambda: asyncio.sleep(0, result=bool(dispatcher.watched)))
        [watched] = dispatcher.watched.values()
        process = watched.launched.process
        await _eventually(lambda: asyncio.sleep(0, result=process.poll() is not None), timeout=10)
        exited = time.monotonic()
        await _eventually(ended, timeout=3)
        assert time.monotonic() - exited < 1.5, "recorded within a busy turn or so"
        # The end and its status are two commits of one turn, with the plan between
        # them, so a read can land in the gap: wait for the status. With nothing
        # left running the next turn is the idle interval away, so a status that
        # follows within seconds is the one this turn published.
        status = await _eventually(published, timeout=3)
        assert (status.state, status.run_id) == ("idle", None), "and the status says so"
    finally:
        await _shut(stop, service, dispatcher)


async def test_a_request_rung_while_a_job_runs_starts_at_once(db_session, tmp_path):
    stop, service, dispatcher = await _busy(db_session, tmp_path, idle_seconds=60, busy_seconds=0.05)
    try:
        ticks = dispatcher.ticks
        await asyncio.sleep(0.3)
        assert dispatcher.ticks == ticks, "steady: only cheap turns"
        await job_store.ring(db_session, "quick", requested_by="cli")
        await db_session.commit()
        rung = time.monotonic()

        async def started() -> list[JobRun]:
            db_session.expire_all()
            return list(await db_session.scalars(select(JobRun).where(JobRun.job == "quick")))

        await _eventually(started, timeout=3)
        assert time.monotonic() - rung < 2, "the notification made the next look a full one"
    finally:
        await _shut(stop, service, dispatcher)


class SteadyApi(FakeApi):
    """An API whose row holds still until its state changes, as the real one's does."""

    def __init__(self, tmp_path) -> None:
        super().__init__(tmp_path)
        self.state = "starting"
        self.since = datetime.now(UTC)

    def status(self):
        return job_store.Status(key="api", job="api", state=self.state, since=self.since)


async def test_a_change_in_the_api_s_row_is_published_by_the_next_turn(db_session, tmp_path):
    api = SteadyApi(tmp_path)
    await job_store.ring(db_session, "nap", requested_by="cli")
    await db_session.commit()
    stop = asyncio.Event()
    dispatcher = _dispatcher(db_session, tmp_path)
    service = asyncio.create_task(
        serve(dispatcher, db_session.bind, stop, idle_seconds=60, busy_seconds=0.05, api=api)
    )

    async def api_row() -> str | None:
        db_session.expire_all()
        row = await db_session.get(JobStatus, "api")
        return row.state if row is not None else None

    try:
        await _eventually(lambda: asyncio.sleep(0, result=bool(dispatcher.watched)))
        await asyncio.sleep(0.2)
        assert await api_row() == "starting"
        ticks = dispatcher.ticks
        api.state, api.since = "running", datetime.now(UTC)

        async def running() -> bool:
            return await api_row() == "running"

        await _eventually(running, timeout=2)
        assert dispatcher.ticks > ticks
        settled = dispatcher.ticks
        await asyncio.sleep(0.3)
        assert dispatcher.ticks == settled, "one full look per change, not one per turn"
    finally:
        await _shut(stop, service, dispatcher)
