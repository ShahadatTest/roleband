"""The dispatcher runs jobs end to end: real processes, real Postgres, fake jobs.

A request becomes a run that exits and completes the request; a schedule starts
a job once and not again while it runs; a timeout and a cancel stop a job and
say which; a supervisor that restarts adopts a job still running and records
how it ended; a gated job waits for the preflight; a job that cannot start
gives its request back.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from tracker.db import job_store
from tracker.db.models import JobRequest, JobRun, JobStatus, MachineAwakeSample
from tracker.platform.paths import REPO_ROOT
from tracker.platform.power import Power as Machine
from tracker.supervisor import gate
from tracker.supervisor import plan as planning
from tracker.supervisor.dispatch import Dispatcher
from tracker.supervisor.registry import Every, JobSpec, OnRequest, Power

REAL_POPEN = subprocess.Popen
REAL_KILL = os.kill
REAL_KILLPG = os.killpg

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]


@pytest.fixture(autouse=True)
def real_processes(no_escape, monkeypatch):
    """Starting and signalling processes is the behaviour under test; every
    process is a fake job this file starts under `tmp_path`."""
    monkeypatch.setattr(subprocess, "Popen", REAL_POPEN)
    monkeypatch.setattr(os, "kill", REAL_KILL)
    monkeypatch.setattr(os, "killpg", REAL_KILLPG)


def _job(name: str, code: str, schedule=None, **fields) -> JobSpec:
    return JobSpec(
        name, ("{python}", "-c", code), schedule or OnRequest(),
        power=Power.NONE, uses_database=False, **fields,
    )


ECHO = _job("echo", "print('did the work'); raise SystemExit(4)")
SLEEPER = _job("sleeper", "import time; print('ready', flush=True); time.sleep(60)", timeout_seconds=1, grace_seconds=1)
GATED = _job("gated", "pass", gated=True)
TICKER = _job("ticker", "import time; time.sleep(1)", Every(600))
JOBS = (ECHO, SLEEPER, GATED, TICKER)


PROVEN = gate.Reading(True, None)


def _dispatcher(db_session, tmp_path, *, gate_reading=PROVEN, jobs=JOBS) -> Dispatcher:
    return Dispatcher(
        factory=async_sessionmaker(db_session.bind, expire_on_commit=False),
        repo_root=REPO_ROOT,
        data_dir=tmp_path,
        zone=ZoneInfo("UTC"),
        jobs=jobs,
        power=lambda: Machine(dark_wake=False, on_battery=False),
        read_gate=lambda _root: gate_reading,
        gate_every_seconds=0,
        wake_log=lambda: None,
    )


@pytest.mark.parametrize("versions", ["missing", "behind", "exact", "extra"])
async def test_planning_and_dispatch_hold_database_work_until_the_exact_schema(db_session, tmp_path, monkeypatch, versions):
    assert await db_session.scalar(text("SELECT to_regclass('alembic_version')")) is None
    heads = planning.code_heads()
    ready = versions == "exact"
    monkeypatch.setattr(planning, "read_power", lambda: Machine(dark_wake=False, on_battery=False))
    job = replace(_job("needs_database", "pass"), uses_database=True)
    try:
        if versions != "missing":
            await db_session.execute(text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)"))
            revisions = {"old_revision"} if versions == "behind" else heads
            if versions == "extra":
                revisions = revisions | {"unrecognized_head"}
            for revision in revisions:
                await db_session.execute(text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": revision})
        await job_store.ring(db_session, job.name, requested_by="settings")
        await db_session.commit()

        dispatcher = _dispatcher(db_session, tmp_path, jobs=(job,))
        assert await dispatcher.schema_ready() is ready
        dispatched_world, _ = await dispatcher._world(datetime.now(UTC))
        planned_world = await planning.read_world(db_session, zone=ZoneInfo("UTC"), gate=planning.Gate.PASSED)
        assert dispatched_world.schema_ready is planned_world.schema_ready is ready
        for world in (planned_world, dispatched_world):
            [row] = await planning.plan(db_session, datetime.now(UTC), world, jobs=(job,))
            assert row.decision.start is ready
            if not ready:
                assert row.decision.reason == "schema_pending"
    finally:
        await db_session.rollback()
        if versions != "missing":
            await db_session.execute(text("DROP TABLE IF EXISTS alembic_version"))
            await db_session.commit()


async def _until_settled(dispatcher: Dispatcher, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while dispatcher.watched and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
        await dispatcher.tick()
    assert not dispatcher.watched, "the job did not end in time"


async def _runs(db_session, job: str) -> list[JobRun]:
    db_session.expire_all()
    return list(await db_session.scalars(select(JobRun).where(JobRun.job == job).order_by(JobRun.id)))


async def test_a_request_becomes_a_run_that_exits_and_completes_the_request(db_session, tmp_path):
    request = await job_store.ring(db_session, "echo", requested_by="cli")
    await db_session.commit()
    request_id = request.id
    dispatcher = _dispatcher(db_session, tmp_path)

    await dispatcher.tick()
    [run] = await _runs(db_session, "echo")
    assert (run.state, run.trigger, run.request_id) == (job_store.RUNNING, "request", request_id)
    assert run.pid and run.log_path

    await _until_settled(dispatcher)
    [run] = await _runs(db_session, "echo")
    await db_session.refresh(request)
    assert (run.state, run.exit_code) == (job_store.EXITED, 4)
    assert request.state == job_store.DONE
    assert "did the work" in open(run.log_path).read()


async def test_a_scheduled_job_starts_once_and_not_again_while_it_runs(db_session, tmp_path):
    dispatcher = _dispatcher(db_session, tmp_path, jobs=(TICKER,))
    await dispatcher.tick()
    await dispatcher.tick()
    runs = await _runs(db_session, "ticker")
    assert len(runs) == 1
    assert runs[0].trigger == "schedule"
    await _until_settled(dispatcher)
    await dispatcher.tick()
    assert len(await _runs(db_session, "ticker")) == 1, "its next start is a period away"


async def test_a_job_over_its_timeout_is_stopped_and_recorded_as_timed_out(db_session, tmp_path):
    await job_store.ring(db_session, "sleeper", requested_by="cli")
    await db_session.commit()
    dispatcher = _dispatcher(db_session, tmp_path)
    await dispatcher.tick()
    await asyncio.sleep(1.3)
    await _until_settled(dispatcher)
    [run] = await _runs(db_session, "sleeper")
    assert run.state == job_store.TIMED_OUT


async def test_a_cancelled_run_is_stopped_and_its_request_cancelled(db_session, tmp_path):
    long = replace(SLEEPER, timeout_seconds=None)
    request = await job_store.ring(db_session, "sleeper", requested_by="sync")
    await db_session.commit()
    dispatcher = _dispatcher(db_session, tmp_path, jobs=(long,))
    await dispatcher.tick()
    [run] = await _runs(db_session, "sleeper")
    assert await job_store.request_cancel(db_session, run.id, reason="sync_cancel")
    await db_session.commit()

    await _until_settled(dispatcher)
    [run] = await _runs(db_session, "sleeper")
    await db_session.refresh(request)
    assert run.state == job_store.RUN_CANCELLED
    assert run.exit_code == -signal.SIGTERM
    assert request.state == job_store.CANCELLED


async def test_a_restarted_supervisor_adopts_a_running_job_and_records_its_end(db_session, tmp_path):
    flag = tmp_path / "finish"
    # Gives up after a minute, so a failing assertion never leaves it looping.
    waiting = _job(
        "waiter",
        f"import pathlib, time\nend = time.time() + 60\n"
        f"while not pathlib.Path({str(flag)!r}).exists() and time.time() < end: time.sleep(0.05)\n"
        "raise SystemExit(6)",
    )
    await job_store.ring(db_session, "waiter", requested_by="cli")
    await db_session.commit()
    first = _dispatcher(db_session, tmp_path, jobs=(waiting,))
    await first.tick()
    [run] = await _runs(db_session, "waiter")
    # The supervisor goes away; its child does not. A real orphan is reaped by
    # launchd once it exits; here the test process stands in for launchd.
    orphan = first.watched[run.id].launched.process
    del first

    second = _dispatcher(db_session, tmp_path, jobs=(waiting,))
    [(run_id, verdict)] = await second.adopt()
    assert (run_id, verdict.action, verdict.pid) == (run.id, "adopt", run.pid)
    await second.tick()
    assert len(await _runs(db_session, "waiter")) == 1, "an adopted run is not started again"

    flag.touch()
    orphan.wait(timeout=10)
    await _until_settled(second)
    [run] = await _runs(db_session, "waiter")
    assert (run.state, run.exit_code) == (job_store.EXITED, 6)


async def test_a_gated_job_waits_for_the_preflight_and_says_so(db_session, tmp_path):
    await job_store.ring(db_session, "gated", requested_by="cli")
    await db_session.commit()
    unproven = gate.Reading(False, "a" * 64)
    dispatcher = _dispatcher(db_session, tmp_path, gate_reading=unproven, jobs=(GATED,))
    await dispatcher.tick()

    assert await _runs(db_session, "gated") == []
    status = await db_session.get(JobStatus, "gated")
    assert (status.state, status.reason, status.detail) == ("waiting", "preflight_running", {"queued": 1})

    dispatcher.read_gate = lambda _root: gate.Reading(True, None)
    await dispatcher.tick()
    assert len(await _runs(db_session, "gated")) == 1


async def test_a_job_that_cannot_start_gives_its_request_back(db_session, tmp_path):
    broken = _job("broken", "pass", cwd="no/such/directory")
    request = await job_store.ring(db_session, "broken", requested_by="cli")
    await db_session.commit()
    dispatcher = _dispatcher(db_session, tmp_path, jobs=(broken,))
    await dispatcher.tick()

    [run] = await _runs(db_session, "broken")
    await db_session.refresh(request)
    assert run.state == job_store.SPAWN_FAILED
    assert (request.state, request.attempts) == (job_store.QUEUED, 1)


async def test_every_job_and_the_supervisor_publish_a_status(db_session, tmp_path):
    dispatcher = _dispatcher(db_session, tmp_path, jobs=(ECHO, GATED))
    await dispatcher.tick()
    rows = {row.key: row for row in await db_session.scalars(select(JobStatus))}
    assert set(rows) == {"echo", "gated", job_store.SUPERVISOR_KEY}
    assert rows["echo"].state == "idle"
    assert rows[job_store.SUPERVISOR_KEY].detail["pid"] == os.getpid()


async def test_a_preflight_is_asked_to_check_exactly_the_tree_it_was_started_for(db_session, tmp_path):
    """The run gets `--expect <fingerprint>`, and a refusal of that tree holds
    gated work as failed until the tree changes."""
    seen = tmp_path / "argv"
    fake = JobSpec(
        "preflight",
        ("{python}", "-c", f"import sys, pathlib; pathlib.Path({str(seen)!r}).write_text(' '.join(sys.argv[1:])); raise SystemExit(75)"),
        OnRequest(), power=Power.NONE, uses_database=False,
    )
    tree = "b" * 64
    dispatcher = _dispatcher(db_session, tmp_path, gate_reading=gate.Reading(False, tree), jobs=(fake, GATED))
    await job_store.ring(db_session, "preflight", requested_by="cli")
    await job_store.ring(db_session, "gated", requested_by="cli")
    await db_session.commit()

    await dispatcher.tick()
    await _until_settled(dispatcher)
    assert seen.read_text() == f"--expect {tree}"
    await dispatcher.tick()
    status = await db_session.get(JobStatus, "gated")
    await db_session.refresh(status)
    assert status.reason == "preflight_failed"
    assert dispatcher.gate_tracker.changed_since() is None, "a refused tree is not checked again until it changes"
    requests = list(await db_session.scalars(select(JobRequest).where(JobRequest.job == "gated")))
    assert [r.state for r in requests] == [job_store.QUEUED]


async def test_a_run_records_what_its_turn_was_from_the_job_s_own_return_value(db_session, tmp_path):
    """Exit 0 is not the answer: a tick that found nothing due says so, and
    retention can then keep fewer of those runs."""
    code = (
        "import json, os, pathlib\n"
        "raw = {'ran': False, 'reason': 'nothing due', 'work': []}\n"
        "pathlib.Path(os.environ['ROLEBAND_JOB_RAW']).write_text(json.dumps(raw))\n"
    )
    fake_scan = _job("scan", code)
    await job_store.ring(db_session, "scan", requested_by="cli")
    await db_session.commit()
    dispatcher = _dispatcher(db_session, tmp_path, jobs=(fake_scan,))
    await dispatcher.tick()
    await _until_settled(dispatcher)

    [run] = await _runs(db_session, "scan")
    assert run.state == job_store.EXITED
    assert run.result["exit_code"] == 0
    assert run.result["kind"] == "nothing_due"
    assert list((tmp_path / "run").iterdir()) == [], "recorded, so the bridge files go"


async def test_a_stopped_preflight_has_its_leftovers_cleared_and_a_finished_one_does_not(db_session, tmp_path):
    """The script's own trap cannot run after a SIGKILL, so the supervisor clears
    a stopped suite's clusters and scratch databases itself."""
    cleared: list[str] = []
    stubborn = JobSpec(
        "preflight",
        ("{python}", "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"),
        OnRequest(), power=Power.NONE, uses_database=False, timeout_seconds=1, grace_seconds=1,
    )
    dispatcher = _dispatcher(db_session, tmp_path, gate_reading=gate.Reading(False, "c" * 64), jobs=(stubborn,))
    dispatcher.clear_residue = lambda: cleared.append("stopped")
    await job_store.ring(db_session, "preflight", requested_by="cli")
    await db_session.commit()
    await dispatcher.tick()
    await _until_settled(dispatcher)
    [run] = await _runs(db_session, "preflight")
    assert run.state == job_store.TIMED_OUT
    assert cleared == ["stopped"]

    finishing = replace(stubborn, command=("{python}", "-c", "pass"), timeout_seconds=None)
    dispatcher = _dispatcher(db_session, tmp_path, gate_reading=gate.Reading(False, "d" * 64), jobs=(finishing,))
    dispatcher.clear_residue = lambda: cleared.append("finished")
    await job_store.ring(db_session, "preflight", requested_by="cli")
    await db_session.commit()
    await dispatcher.tick()
    await _until_settled(dispatcher)
    assert (await _runs(db_session, "preflight"))[-1].state == job_store.EXITED
    assert cleared == ["stopped"], "a suite that ended by itself cleared up after itself"


async def _samples(db_session) -> list[tuple[datetime, str]]:
    db_session.expire_all()
    rows = await db_session.scalars(select(MachineAwakeSample).order_by(MachineAwakeSample.seen_at))
    return [(row.seen_at, row.source) for row in rows]


async def test_the_supervisor_samples_the_machine_awake_every_ten_minutes_even_while_collection_waits(db_session, tmp_path):
    """The plan learns the usual hours from these; a sample taken inside a gated
    tick taught it the machine was off whenever the preflight failed."""
    dispatcher = _dispatcher(db_session, tmp_path, gate_reading=gate.Reading(False, "e" * 64), jobs=(GATED,))
    dispatcher.gate_tracker.finished("e" * 64, gate.REFUSED)
    await job_store.ring(db_session, "gated", requested_by="cli")
    await db_session.commit()
    start = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
    await dispatcher.tick(start)
    await dispatcher.tick(start + timedelta(minutes=9))
    await dispatcher.tick(start + timedelta(minutes=10))
    assert await _samples(db_session) == [(start, "tick"), (start + timedelta(minutes=10), "tick")]
    status = await db_session.get(JobStatus, "gated")
    assert status.reason == "preflight_failed"


async def test_a_maintenance_wake_is_not_a_sample_and_does_not_delay_the_next(db_session, tmp_path):
    dispatcher = _dispatcher(db_session, tmp_path, jobs=(ECHO,))
    dispatcher.power = lambda: Machine(dark_wake=True, on_battery=False)
    dark = datetime(2026, 10, 19, 3, 0, tzinfo=UTC)
    await dispatcher.tick(dark)
    assert await _samples(db_session) == []
    dispatcher.power = lambda: Machine(dark_wake=False, on_battery=False)
    await dispatcher.tick(dark + timedelta(minutes=5))
    assert await _samples(db_session) == [(dark + timedelta(minutes=5), "tick")]


async def test_only_the_first_sample_ever_reads_the_wake_log(db_session, tmp_path):
    reads: list[int] = []
    dispatcher = _dispatcher(db_session, tmp_path, jobs=(ECHO,))
    dispatcher.wake_log = lambda: reads.append(1) or None
    start = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
    await dispatcher.tick(start)
    await dispatcher.tick(start + timedelta(minutes=10))
    assert reads == [1]
    assert len(await _samples(db_session)) == 2


async def test_a_rehearsal_runs_network_jobs_without_their_requests_and_local_jobs_for_real(db_session, tmp_path):
    from tracker.supervisor.dispatch import rehearsed

    marker = tmp_path / "reached"
    network = _job("network", f"import pathlib; pathlib.Path({str(marker)!r}).write_text('sent')", network=True)
    local = _job("local", "print('local work')")
    dispatcher = _dispatcher(db_session, tmp_path, jobs=(network, local))
    dispatcher.dry_run_network = True
    await job_store.ring(db_session, "network", requested_by="cli")
    await job_store.ring(db_session, "local", requested_by="cli")
    await db_session.commit()
    await dispatcher.tick()
    await _until_settled(dispatcher)

    [sent] = await _runs(db_session, "network")
    assert not marker.exists(), "the network job's own command never ran"
    assert sent.result["kind"] == "nothing_due" and sent.result["reason"] == "dry_run"
    [done] = await _runs(db_session, "local")
    assert (done.state, done.exit_code) == (job_store.EXITED, 0)
    assert "local work" in open(done.log_path).read()

    scan = rehearsed(JobSpec("scan", ("{python}", "-m", "tracker.supervisor.entries", "scan"), OnRequest(), network=True))
    assert scan.command[-1] == "scan", "an entry keeps its command and is told to send nothing"
    assert ("ROLEBAND_JOB_DRY_RUN", "1") in scan.env


async def test_an_adopted_run_that_is_still_our_child_is_reaped_when_it_exits(db_session, tmp_path):
    """After a re-exec the supervisor's jobs are still its children, with no
    handle to reap them by: an exited one would stay a zombie and keep its
    group alive for ever."""
    quick = _job("quick", "import time; time.sleep(0.5); raise SystemExit(3)")
    await job_store.ring(db_session, "quick", requested_by="cli")
    await db_session.commit()
    before = _dispatcher(db_session, tmp_path, jobs=(quick,))
    await before.tick()
    [run] = await _runs(db_session, "quick")
    kept = before.watched[run.id].launched.process  # never polled: the old image's handle is gone

    after = _dispatcher(db_session, tmp_path, jobs=(quick,))
    [(_, verdict)] = await after.adopt()
    assert verdict.action == "adopt"
    await _until_settled(after, timeout=10)
    [run] = await _runs(db_session, "quick")
    assert (run.state, run.exit_code) == (job_store.EXITED, 3)
    assert kept.returncode is None, "reaped through the pid, not through the handle"



async def test_a_status_carries_the_queue_the_last_outcome_and_the_work_left_for_later():
    from tracker.supervisor.dispatch import _detail
    from tracker.supervisor.due import Decision, Facts
    from tracker.supervisor.plan import Planned

    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    row = Planned(
        ECHO, "echo", Facts(now=now, queued=2), Decision(False, None, "idle"),
        {"kind": "waiting", "reason": "rate_limited", "deferred": 9, "next_at": "2026-10-19T13:00:00+00:00"},
    )
    assert _detail(row) == {
        "queued": 2,
        "last": {"kind": "waiting", "reason": "rate_limited"},
        "waiting": {"count": 9, "until": "2026-10-19T13:00:00+00:00"},
    }
    assert _detail(Planned(ECHO, "echo", Facts(now=now), Decision(False, None, "idle"))) == {}


async def test_retention_runs_once_an_hour(db_session, tmp_path, monkeypatch):
    calls: list[datetime] = []
    real = job_store.prune

    async def counted(session, now=None, **kwargs):
        calls.append(now)
        return await real(session, now, **kwargs)

    monkeypatch.setattr(job_store, "prune", counted)
    dispatcher = _dispatcher(db_session, tmp_path, jobs=(ECHO,))
    start = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
    await dispatcher.tick(start)
    await dispatcher.tick(start + timedelta(minutes=59))
    await dispatcher.tick(start + timedelta(minutes=60))
    assert calls == [start, start + timedelta(minutes=60)]


WAKEFUL = replace(_job("wakeful", "pass"), power=Power.AWAKE)


async def test_a_power_reading_is_reused_for_a_while_and_read_again_after_a_sleep(db_session, tmp_path, monkeypatch):
    """A reading is two `pmset` processes. Awake time stops while the lid is
    shut, so only the wall clock tells a reading from before a sleep, and the
    wake after a sleep is often a maintenance wake."""
    from tracker.supervisor import dispatch
    from tracker.supervisor.due import WAITING_FOR_WAKE

    awake = [1000.0]
    monkeypatch.setattr(dispatch, "awake_seconds", lambda: awake[0])
    machine = [Machine(dark_wake=False, on_battery=False)]
    reads: list[Machine] = []

    def power() -> Machine:
        reads.append(machine[0])
        return machine[0]

    dispatcher = _dispatcher(db_session, tmp_path, jobs=(WAKEFUL,))
    dispatcher.power = power
    start = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
    await dispatcher.tick(start)
    awake[0] += 10
    await dispatcher.tick(start + timedelta(seconds=10))
    assert len(reads) == 1, "reused inside its interval"

    # The lid was shut for a quarter of an hour; this is a maintenance wake.
    machine[0] = Machine(dark_wake=True, on_battery=False)
    awake[0] += 2
    await job_store.ring(db_session, "wakeful", requested_by="cli")
    await db_session.commit()
    [row] = await dispatcher.tick(start + timedelta(minutes=15))
    assert len(reads) == 2, "a sleep is never bridged by an old reading"
    assert (row.decision.start, row.decision.reason) == (False, WAITING_FOR_WAKE)

    machine[0] = Machine(dark_wake=False, on_battery=False)
    awake[0] += 29
    [row] = await dispatcher.tick(start + timedelta(minutes=15, seconds=29))
    assert len(reads) == 2 and not row.decision.start
    awake[0] += 1
    [row] = await dispatcher.tick(start + timedelta(minutes=15, seconds=30))
    assert len(reads) == 3, "read again once its interval of awake time is over"
    assert row.decision.start
    await _until_settled(dispatcher)


async def test_settle_says_whether_a_run_ended_or_a_stop_began(db_session, tmp_path):
    """The busy loop's cheap turn: the service follows it with a full look, which
    publishes and starts, only when it says something changed."""
    await job_store.ring(db_session, "sleeper", requested_by="cli")
    await db_session.commit()
    dispatcher = _dispatcher(db_session, tmp_path, jobs=(SLEEPER,))
    await dispatcher.tick()
    assert len(dispatcher.watched) == 1
    assert await dispatcher.settle() is False, "nothing ended and nothing is due to stop"

    await asyncio.sleep(1.2)
    assert await dispatcher.settle() is True, "its timeout began a stop"
    ended = None
    deadline = time.monotonic() + 10
    while dispatcher.watched and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
        ended = await dispatcher.settle()
    assert not dispatcher.watched
    assert ended is True, "the turn that recorded the end says so"
    assert await dispatcher.settle() is False
    [run] = await _runs(db_session, "sleeper")
    assert run.state == job_store.TIMED_OUT
