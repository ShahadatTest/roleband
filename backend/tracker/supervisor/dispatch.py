"""The supervisor's loop: settle what ended, stop what must stop, start what is due.

One `tick` is one look at the world. Order matters: ends are recorded before
anything starts, so a key whose run just ended is free in the same tick, and the
starts read the gate after the preflight that may have just proven the tree.

Every database step commits before the process step it allows: a claim is
committed before its spawn, so a supervisor that dies in between leaves a run
row that the next one settles (`adopt.reconcile`), never a process nobody knows.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tracker.db import job_store
from tracker.db.models import JobRun
from tracker.platform.power import Power, read_power, read_wake_log
from tracker.supervisor import adopt, child, gate, results, runner
from tracker.supervisor.clock import awake_seconds
from tracker.supervisor.due import Gate, World
from tracker.supervisor.entries import DRY_RUN_ENV
from tracker.supervisor.plan import Planned, code_heads, plan, schema_ready
from tracker.supervisor.registry import JOBS, JobSpec
from tracker.workflows import schedule_plan

logger = logging.getLogger("tracker.supervisor")

#: Why a watched run is being stopped.
CANCEL = "cancel"
TIMEOUT = "timeout"


@dataclass
class Watched:
    job: JobSpec
    key: str
    launched: runner.Launched
    #: CANCEL or TIMEOUT once a stop has begun.
    stopping: str | None = None
    stop_task: asyncio.Task | None = None
    #: The tree a preflight run was asked to check.
    fingerprint: str | None = None


def _detail(row: Planned) -> dict:
    """What the status says beside the state: queued requests, what the last run
    came to (a refusal, a wait, a lock held elsewhere), and work it left for
    later with when that can start (the prices job's "N more after")."""
    detail: dict = {}
    if row.facts.queued:
        detail["queued"] = row.facts.queued
    last = row.last_result or {}
    if last.get("kind"):
        detail["last"] = {"kind": last["kind"], "reason": last.get("reason")}
    if last.get("deferred"):
        detail["waiting"] = {"count": last["deferred"], "until": last.get("next_at")}
    return detail


ENTRIES_COMMAND = ("{python}", "-m", "tracker.supervisor.entries")


def rehearsed(job: JobSpec) -> JobSpec:
    """`job` as a rehearsal runs it: an entry told to send nothing, or, for a
    command that is not an entry, the entry that does nothing."""
    command = job.command
    if command[: len(ENTRIES_COMMAND)] != ENTRIES_COMMAND:
        command = (*ENTRIES_COMMAND, "dry_run")
    return replace(job, command=command, env=(*job.env, (DRY_RUN_ENV, "1")))


@dataclass
class Dispatcher:
    factory: async_sessionmaker[AsyncSession]
    repo_root: Path
    data_dir: Path
    zone: tzinfo
    jobs: Sequence[JobSpec] = JOBS
    python: str = sys.executable
    env: Mapping[str, str] | None = None
    code_version: str | None = None
    power: Callable[[], Power] = read_power
    #: The preflight gate's reader; None for a supervisor run with no gate (tests
    #: of jobs that are not gated).
    read_gate: Callable[[Path], gate.Reading] | None = gate.read
    #: The gate asks git about the tree, so the answer is reused this long, and
    #: read afresh whenever a preflight starts or ends.
    gate_every_seconds: float = 30.0
    #: A power reading is two `pmset` processes, so it is reused for this long of
    #: awake time and of wall-clock time: awake time stops while the machine
    #: sleeps, and a sleep longer than this always means a fresh reading.
    power_every_seconds: float = 30.0
    #: How often the supervisor records the machine as awake (`schedule_plan`
    #: learns the usual hours from it); None takes no samples.
    awake_every: timedelta | None = schedule_plan.SAMPLE_SPAN
    #: `pmset -g log`, read once, to seed a first sample's past week.
    wake_log: Callable[[], str | None] = read_wake_log
    #: How often old runs and finished requests are pruned (`job_store.prune`).
    prune_every: timedelta | None = timedelta(hours=1)
    #: A rehearsal: network jobs run without their requests (`entries.DRY_RUN_ENV`).
    dry_run_network: bool = False
    #: Clears what a stopped preflight suite left behind (`residue.clean`); its own
    #: trap cannot run after a SIGKILL.
    clear_residue: Callable[[], object] | None = None
    #: Set by activation: False while the checkout's dependencies are not installed.
    dependencies_ready: bool = True
    #: Rows published beside the jobs' (the API's), and why landed code is held,
    #: for the supervisor's own row.
    status_sources: list[Callable[[], job_store.Status]] = field(default_factory=list)
    held: Callable[[], str | None] | None = None
    watched: dict[int, Watched] = field(default_factory=dict)
    gate_tracker: gate.Tracker = field(default_factory=gate.Tracker)

    def __post_init__(self) -> None:
        self._by_name = {job.name: job for job in self.jobs}
        self._heads = code_heads()
        self._gate_reading: gate.Reading | None = None
        self._gate_read_at: float | None = None
        self._gate_was_checking = False
        self._power_reading: Power | None = None
        self._power_read_at: tuple[float, datetime] | None = None
        self._sampled_at: datetime | None = None
        self._pruned_at: datetime | None = None

    # --- start of a supervisor -------------------------------------------------

    async def adopt(self) -> list[tuple[int, adopt.Verdict]]:
        """Settle every run a predecessor left live; watch the ones still running."""
        verdicts: list[tuple[int, adopt.Verdict]] = []
        async with self.factory() as session:
            for run in await job_store.live_runs(session):
                verdict = adopt.reconcile(
                    run,
                    is_run=runner.is_run,
                    find_run=runner.find_run,
                    read_result=lambda run_id: child.read_result(runner.result_path(self.data_dir, run_id)),
                )
                verdicts.append((run.id, verdict))
                spec = self._by_name.get(run.job)
                if verdict.action == "adopt" and spec is not None and verdict.pid is not None:
                    if run.pid is None:
                        await job_store.mark_running(
                            session, run.id, pid=verdict.pid, pgid=verdict.pid,
                            proc_started_at=runner.started_at(verdict.pid),
                        )
                    self.watched[run.id] = Watched(
                        spec, run.key,
                        runner.Launched(
                            run_id=run.id, pid=verdict.pid, pgid=run.pgid or verdict.pid,
                            proc_started_at=run.proc_started_at,
                            log_path=Path(run.log_path) if run.log_path else runner.log_path(self.data_dir, spec),
                            log_offset=run.log_offset or 0, process=None, since_awake=awake_seconds(),
                        ),
                    )
                else:
                    await job_store.finish_run(
                        session, run.id, state=verdict.state or job_store.LOST,
                        exit_code=verdict.exit_code, result=verdict.result,
                    )
            await session.commit()
        return verdicts

    # --- one look ----------------------------------------------------------------

    async def tick(self, now: datetime | None = None) -> list[Planned]:
        now = now or datetime.now(UTC)
        await self._settle()
        await self._stops()
        planned = await self._starts(now)
        await self._prune(now)
        return planned

    async def _prune(self, now: datetime) -> None:
        """Retention: ten-minute ticks would otherwise grow `job_runs` for ever."""
        if self.prune_every is None:
            return
        if self._pruned_at is not None and now - self._pruned_at < self.prune_every:
            return
        self._pruned_at = now
        async with self.factory() as session:
            pruned = await job_store.prune(session, now)
            await session.commit()
        if pruned.runs or pruned.requests:
            logger.info("pruned %s runs and %s requests", pruned.runs, pruned.requests)

    async def _settle(self) -> int:
        """Record every watched run that has ended; how many did."""
        ended = 0
        for run_id, watched in list(self.watched.items()):
            if watched.stop_task is not None and not watched.stop_task.done():
                continue
            if not self._ended(watched):
                continue
            result = child.read_result(runner.result_path(self.data_dir, run_id))
            exit_code = result.get("exit_code") if result else None
            process = watched.launched.process
            if exit_code is None and process is not None:
                exit_code = process.returncode
            raw = child.read_result(runner.raw_path(self.data_dir, run_id))
            if result is not None or process is not None:
                result = {**(result or {}), **results.summarize(watched.job.name, exit_code, raw)}
            async with self.factory() as session:
                run = await session.get(JobRun, run_id)
                cancelled = watched.stopping == CANCEL or (run is not None and run.cancel_requested_at is not None)
                if watched.stopping == TIMEOUT:
                    state = job_store.TIMED_OUT
                elif cancelled:
                    state = job_store.RUN_CANCELLED
                elif result is None and process is None:
                    # Adopted, gone, and no word from its trampoline.
                    state = job_store.LOST
                else:
                    state = job_store.EXITED
                await job_store.finish_run(session, run_id, state=state, exit_code=exit_code, result=result)
                await session.commit()
            # Recorded: the files were only the bridge for a supervisor that
            # restarts before it reads them.
            runner.result_path(self.data_dir, run_id).unlink(missing_ok=True)
            runner.raw_path(self.data_dir, run_id).unlink(missing_ok=True)
            if watched.job.name == "preflight":
                self.gate_tracker.finished(watched.fingerprint, exit_code)
                if state != job_store.EXITED and self.clear_residue is not None:
                    await asyncio.to_thread(self.clear_residue)
            del self.watched[run_id]
            ended += 1
            logger.info("%s run %s ended %s (exit %s)", watched.key, run_id, state, exit_code)
        return ended

    @staticmethod
    def _ended(watched: Watched) -> bool:
        process = watched.launched.process
        if process is not None:
            return process.poll() is not None
        # Adopted. After a re-exec it is still this process's child, and one that
        # exited stays a zombie, keeping its group alive, until it is reaped.
        try:
            os.waitpid(watched.launched.pid, os.WNOHANG)
        except ChildProcessError:
            pass
        return not runner.group_alive(watched.launched.pgid)

    async def _stops(self) -> int:
        """Begin the stop of every watched run that was cancelled or is over its
        timeout; how many stops began."""
        if not self.watched:
            return 0
        async with self.factory() as session:
            cancelled = set(
                await session.scalars(
                    select(JobRun.id).where(
                        JobRun.id.in_(list(self.watched)), JobRun.cancel_requested_at.is_not(None)
                    )
                )
            )
        began = 0
        for run_id, watched in self.watched.items():
            if watched.stopping is not None:
                continue
            timeout = watched.job.timeout_seconds
            if run_id in cancelled:
                self._stop(watched, CANCEL)
                began += 1
            elif timeout is not None and awake_seconds() - watched.launched.since_awake > timeout:
                self._stop(watched, TIMEOUT)
                began += 1
        return began

    def _stop(self, watched: Watched, why: str) -> None:
        watched.stopping = why
        process = watched.launched.process
        watched.stop_task = asyncio.create_task(
            runner.stop_group(
                watched.launched.pgid, watched.job.grace_seconds,
                reap=process.poll if process is not None else None,
            )
        )
        logger.info("stopping %s run %s: %s", watched.key, watched.launched.run_id, why)

    async def _starts(self, now: datetime) -> list[Planned]:
        world, changed = await self._world(now)
        await self._sample_awake(now, world)
        async with self.factory() as session:
            planned = await plan(session, now, world, jobs=self.jobs, changed_since=changed)
        for row in planned:
            if row.decision.start:
                await self._start(row)
        await self._publish(planned, now)
        return planned

    async def _read_power(self, now: datetime) -> Power:
        awake = awake_seconds()
        if self._power_reading is not None and self._power_read_at is not None:
            read_awake, read_wall = self._power_read_at
            fresh = timedelta(seconds=self.power_every_seconds)
            if awake - read_awake < self.power_every_seconds and timedelta(0) <= now - read_wall < fresh:
                return self._power_reading
        self._power_reading = await asyncio.to_thread(self.power)
        self._power_read_at = (awake, now)
        return self._power_reading

    async def _world(self, now: datetime) -> tuple[World, dict[str, datetime]]:
        power = await self._read_power(now)
        ready = await self.schema_ready()
        changed: dict[str, datetime] = {}
        if self.read_gate is None:
            current = Gate.PASSED
        else:
            checking = any(w.job.name == "preflight" for w in self.watched.values())
            stale = self._gate_read_at is None or awake_seconds() - self._gate_read_at >= self.gate_every_seconds
            if stale or self._gate_reading is None or checking != self._gate_was_checking:
                self._gate_reading = await asyncio.to_thread(self.read_gate, self.repo_root)
                self._gate_read_at = awake_seconds()
                self._gate_was_checking = checking
            reading = self._gate_reading
            current = self.gate_tracker.observe(reading, now, checking=checking)
            since = self.gate_tracker.changed_since()
            if since is not None:
                changed["preflight"] = since
        world = World(
            dark_wake=power.dark_wake, on_battery=power.on_battery, gate=current,
            schema_ready=ready, zone=self.zone, dependencies_ready=self.dependencies_ready,
        )
        return world, changed

    async def _sample_awake(self, now: datetime, world: World) -> None:
        """Here, not in the scan: a tick held by a failing preflight would teach
        the plan the machine was off. Never fails a look."""
        if self.awake_every is None or world.dark_wake:
            return
        if self._sampled_at is not None and now - self._sampled_at < self.awake_every:
            return
        self._sampled_at = now
        try:
            async with self.factory() as session:
                log = None
                if not await schedule_plan.has_samples(session):
                    log = await asyncio.to_thread(self.wake_log)
                power = Power(dark_wake=world.dark_wake, on_battery=world.on_battery)
                await schedule_plan.note_awake(session, now=now, read_power=lambda: power, read_log=lambda: log)
                await session.commit()
        except Exception:  # noqa: BLE001 - a sample never stops supervision
            logger.warning("could not record the machine awake", exc_info=True)

    async def _start(self, row: Planned) -> None:
        job, key = row.job, row.key
        extra: list[str] = []
        async with self.factory() as session:
            if row.decision.trigger == "request":
                claimed = await job_store.claim(session, key, code_version=self.code_version)
                if claimed is None:
                    await session.rollback()
                    return
                request, run = claimed
                extra = [str(part) for part in request.args.get("argv", [])]
            else:
                opened = await job_store.open_run(
                    session, job.name, key, trigger=row.decision.trigger or "schedule",
                    code_version=self.code_version,
                )
                if opened is None:
                    await session.rollback()
                    return
                run = opened
            await session.commit()
        fingerprint = None
        if job.name == "preflight":
            fingerprint = self.gate_tracker.unproven
            if fingerprint is not None:
                extra = ["--expect", fingerprint, *extra]
        if self.dry_run_network and job.network:
            job = rehearsed(job)
        try:
            launched = await asyncio.to_thread(
                runner.launch, job, run.id, repo_root=self.repo_root, data_dir=self.data_dir,
                extra=extra, env=self.env, python=self.python,
            )
        except OSError as error:
            logger.warning("could not start %s: %s", key, error)
            async with self.factory() as session:
                await job_store.finish_run(
                    session, run.id, state=job_store.SPAWN_FAILED, result={"error": str(error)[:500]}
                )
                await session.commit()
            return
        async with self.factory() as session:
            await job_store.mark_running(
                session, run.id, pid=launched.pid, pgid=launched.pgid,
                proc_started_at=launched.proc_started_at,
                log_path=str(launched.log_path), log_offset=launched.log_offset,
            )
            await session.commit()
        self.watched[run.id] = Watched(job, key, launched, fingerprint=fingerprint)
        logger.info("started %s as run %s (%s)", key, run.id, row.decision.trigger)

    async def _publish(self, planned: Sequence[Planned], now: datetime) -> None:
        running = {w.key: run_id for run_id, w in self.watched.items()}
        stopping = {w.key for w in self.watched.values() if w.stopping is not None}
        statuses = []
        for row in planned:
            decision = row.decision
            state = "stopping" if row.key in stopping else (
                "running" if row.key in running else decision.state
            )
            statuses.append(
                job_store.Status(
                    key=row.key, job=row.job.name, state=state, since=now,
                    reason=None if state in ("running", "stopping") else decision.reason,
                    next_at=decision.next_at, run_id=running.get(row.key),
                    detail=_detail(row),
                )
            )
        statuses.extend(source() for source in self.status_sources)
        statuses.append(
            job_store.Status(
                key=job_store.SUPERVISOR_KEY, job="supervisor", state="running", since=now,
                reason=self.held() if self.held is not None else None,
                detail={"pid": os.getpid(), "checkout": str(self.repo_root), "version": self.code_version},
            )
        )
        async with self.factory() as session:
            await job_store.publish(session, statuses)
            await session.commit()

    # --- activation ----------------------------------------------------------------

    def refresh_heads(self) -> None:
        """Read the schema heads of the code on disk, which the next child runs."""
        self._heads = code_heads()

    async def schema_ready(self) -> bool:
        async with self.factory() as session:
            return await schema_ready(session, self._heads)

    async def pending(self, job: str) -> bool:
        """A request for `job` is queued or one of its runs is live."""
        async with self.factory() as session:
            queued = (await job_store.queues(session)).get(job)
            live = any(run.job == job for run in await job_store.live_runs(session))
        return live or bool(queued and queued.count)

    async def last_run_succeeded(self, job: str) -> bool:
        async with self.factory() as session:
            run = (await job_store.latest_runs(session)).get(job)
        return run is not None and run.state == job_store.EXITED and run.exit_code == 0

    async def ask(self, job: str, *, requested_by: str) -> None:
        async with self.factory() as session:
            await job_store.ring(session, job, requested_by=requested_by)
            await session.commit()

    # --- maintenance --------------------------------------------------------------

    async def drain(self, *, cancel: bool, reason: str = "maintenance") -> None:
        """With `cancel`, ask every watched run to stop; the stops themselves
        happen in `settle`, as for any cancel. Without, the runs finish."""
        if not cancel or not self.watched:
            return
        async with self.factory() as session:
            for run_id in self.watched:
                await job_store.request_cancel(session, run_id, reason=reason)
            await session.commit()

    async def settle(self) -> bool:
        """A look that starts nothing: record what ended, stop what must stop.
        True when a run ended or a stop began, which the published status and
        the next start depend on."""
        ended = await self._settle()
        began = await self._stops()
        return bool(ended or began)

    async def publish_paused(self, now: datetime | None = None) -> None:
        async with self.factory() as session:
            await job_store.publish_paused(
                session, now or datetime.now(UTC),
                detail={"pid": os.getpid(), "checkout": str(self.repo_root), "version": self.code_version},
            )
            await session.commit()

    async def wait_for_stops(self) -> None:
        tasks = [w.stop_task for w in self.watched.values() if w.stop_task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
