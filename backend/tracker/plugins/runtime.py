"""When plugin jobs run, and how the supervisor is asked to run them.

A plugin job runs in its own process, `tracker.plugins.cli run`, which is the
host (`host.run_job`): never inside the API, the scheduler tick or the pipeline,
which never import the plugin SDK. The supervisor starts it, one run per plugin
at a time, when asked (`spawn_run` rings a `plugin_run` request). Three things
ask:

- the supervisor's `plugins_due` job (`plugins_when_due`), for every scheduled
  job that is due. It never asks in a maintenance wake, and a scheduled run
  waits for mains power;
- Sync (`POST /api/sync`), for the same due jobs; work the user starts skips
  the mains gate, never the dark-wake gate;
- Refresh now (`POST /api/plugins/{id}/refresh`), for one job, due or not.

**Due** (`due_jobs`, pure, over `schedule.next_start`): runnable, not paused,
the job's schedule (the user's choice, else the manifest's) is not `manual`,
nothing of this plugin is running, and the job's next start has come: never
run; a pass in progress (a clean or partial run that said `more`)
`CONTINUE_AFTER` its last run; an attempt that did not go through
`RETRY_AFTER` it; else one interval (a day, a week, 30 days) after the start of its last whole pass. Re-enabling a plugin that has
a clean snapshot fetches nothing: its rows answer again at once.

**Liveness** is a PID plus its command, never a PID alone: a `running` row
whose process is gone is closed `error` by `reconcile_dead_runs`, so a killed
runner never blocks the next one. Disable cancels the plugin's queued requests,
asks the supervisor to stop its run, and sends the host SIGTERM (`stop_runs`),
which also reaches a run started by hand: the run ends `stopped`. A company it had already published whole stays read, its rows
not repeated already retired at that publish; nothing after is.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db import job_store
from tracker.db.models import JobRun, PluginRun
from tracker.platform.paths import DATA_DIR, PACKAGED, REPO_ROOT
from tracker.plugins import store
from tracker.plugins.registry import InstallRecord, install_records
from tracker.plugins.schedule import CONTINUE_AFTER, INTERVALS, RETRY_AFTER, RunRecord, next_start

logger = logging.getLogger(__name__)

__all__ = [
    "CONTINUE_AFTER",
    "RETRY_AFTER",
    "WEEKLY",
    "DueJob",
    "RunRecord",
    "due_jobs",
    "plugins_when_due",
    "reconcile_dead_runs",
    "run_records",
    "runner_alive",
    "spawn_reestimate",
    "spawn_run",
    "start_due",
    "stop_runs",
]

WEEKLY = INTERVALS["weekly"]
#: The module the supervisor's `plugin_run` job runs, and `reestimate`'s.
RUN_MODULE = "tracker.plugins.cli"
REESTIMATE_MODULE = "tracker.plugins.reestimate_cli"
#: An argv naming one of these proves a PID is a plugin runner. The supervisor
#: starts `RUN_MODULE`; `scripts.plugin` is the command people type, and a run
#: started before a landing keeps the argv it started with. Either is a runner
#: that disable and pause must still stop.
RUNNER_MARKERS = (RUN_MODULE, "scripts.plugin")


@dataclass(frozen=True)
class DueJob:
    plugin_id: str
    job: str
    #: never_clean | continues | daily | weekly | monthly
    reason: str


def _jobs(record: InstallRecord) -> list[Mapping[str, Any]]:
    return [j for j in record.manifest.get("jobs", ()) if isinstance(j, Mapping)]


def due_jobs(installs: Iterable[InstallRecord], runs: Iterable[RunRecord], now: datetime) -> list[DueJob]:
    """Every scheduled job that should start now (`schedule.next_start`), none of
    a plugin that is running. Pure."""
    runs = list(runs)
    busy = {r.plugin_id for r in runs if r.outcome == "running"}
    out: list[DueJob] = []
    for record in installs:
        if record.plugin_id in busy:
            continue
        for job in _jobs(record):
            nxt = next_start(record, job, runs)
            if nxt is not None and (nxt.at is None or nxt.at <= now):
                out.append(DueJob(record.plugin_id, str(job.get("name")), nxt.reason))
    return out


async def run_records(session: AsyncSession) -> list[RunRecord]:
    rows = (
        await session.execute(select(PluginRun.plugin_id, PluginRun.job, PluginRun.outcome, PluginRun.started_at,
                                     PluginRun.ended_at, PluginRun.continues))
    ).all()
    return [RunRecord(*row) for row in rows]


# --------------------------------------------------------------------------- #
# Processes
# --------------------------------------------------------------------------- #


def _command(pid: int) -> str:
    try:
        done = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "command="], capture_output=True, check=False, text=True,
        )
    except Exception:  # noqa: BLE001 - ps failure means "do not trust this pid"
        return ""
    return done.stdout.strip()


def runner_alive(pid: int | None, *, command: Callable[[int], str] | None = None) -> bool:
    """Whether `pid` is a live plugin runner (never a recycled PID)."""
    if pid is None:
        return False
    line = (command or _command)(pid)
    return any(marker in line for marker in RUNNER_MARKERS)


async def reconcile_dead_runs(session: AsyncSession, *, command: Callable[[int], str] | None = None) -> list[int]:
    """Close as `error` every `running` row whose runner is gone. Commits nothing."""
    rows = (await session.execute(select(PluginRun).where(PluginRun.outcome == "running"))).scalars().all()
    dead = [r.id for r in rows if not runner_alive(r.pid, command=command)]
    await store.close_dead_runs(session, dead)
    return dead


def _python() -> str:
    """The checkout's interpreter (a worktree has none: the running one)."""
    if PACKAGED:
        return sys.executable
    venv = REPO_ROOT / "backend" / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


#: (argv, log path) -> anything. Tests pass one to see the command a run would
#: get; without one, the supervisor is asked.
Spawner = Callable[[Sequence[str], Path], Any]

#: The registry's command for a plugin run, before its arguments.
RUN_PREFIX = 4  # python -m tracker.plugins.cli run


async def _ring(
    session: AsyncSession, job: str, *, argument: str | None, requested_by: str, args: dict[str, Any]
) -> None:
    await job_store.ring(session, job, argument=argument, requested_by=requested_by, args=args)


async def spawn_run(
    session: AsyncSession, plugin_id: str, job: str, *, trigger: str, spawner: Spawner | None = None,
) -> Any:
    """Ask for `tracker.plugins.cli run <plugin> <job>`, in the caller's transaction.

    One run per plugin at a time: a second job of the same plugin waits for
    the first instead of finding the host lock taken. `trigger` travels with the
    request, so a scheduled run waits for mains power and one the user asked
    for does not."""
    argv = [_python(), "-m", RUN_MODULE, "run", plugin_id, job, "--trigger", trigger]
    if spawner is not None:
        return spawner(argv, DATA_DIR / "logs" / "plugin_run.log")
    await _ring(
        session, "plugin_run", argument=plugin_id, requested_by=f"plugin_{trigger}",
        args={"argv": argv[RUN_PREFIX:], "trigger": trigger},
    )
    return None


#: How long the re-estimate a decision asks for waits for a run holding the
#: lock (a scrape, a backfill) before leaving the move to the next caller.
FOLLOW_WAIT_SECONDS = 600


async def spawn_reestimate(session: AsyncSession, *, spawner: Spawner | None = None) -> Any:
    """Ask for `tracker.plugins.reestimate_cli`, in the caller's transaction:
    after enable, disable or remove. Requests coalesce while queued, so a burst
    of decisions is one re-estimate; it waits for the run lock, within
    `FOLLOW_WAIT_SECONDS`, rather than ask once."""
    argv = [_python(), "-m", REESTIMATE_MODULE, "--wait", str(FOLLOW_WAIT_SECONDS)]
    if spawner is not None:
        return spawner(argv, DATA_DIR / "logs" / "reestimate.log")
    await _ring(session, "reestimate", argument=None, requested_by="plugin_decision", args={})
    return None


async def start_due(
    session: AsyncSession, *, trigger: str, now: datetime | None = None, spawner: Spawner | None = None,
) -> list[DueJob]:
    """Ask for every due job, and commit; the caller has already applied the
    power gates."""
    due = await _due_now(session, now)
    await _spawn_all(session, due, trigger=trigger, spawner=spawner)
    return due


async def _spawn_all(
    session: AsyncSession, due: Sequence[DueJob], *, trigger: str, spawner: Spawner | None,
) -> None:
    for item in due:
        await spawn_run(session, item.plugin_id, item.job, trigger=trigger, spawner=spawner)
        logger.info("plugin:%s %s asked for (%s, %s)", item.plugin_id, item.job, trigger, item.reason)
    if due and spawner is None:
        await session.commit()


async def _due_now(session: AsyncSession, now: datetime | None) -> list[DueJob]:
    # Dead runs are closed first, whatever may run: a host killed mid-run whose
    # plugin was then turned off would otherwise read as running for good.
    if await session.scalar(select(PluginRun.id).where(PluginRun.outcome == "running").limit(1)) is not None:
        await reconcile_dead_runs(session)
        await session.commit()
    installs = await install_records(session)
    if not any(rec.runnable for rec in installs):
        return []
    return due_jobs(installs, await run_records(session), now or datetime.now(UTC))


async def stop_runs(
    session: AsyncSession,
    plugin_id: str,
    *,
    command: Callable[[int], str] | None = None,
    kill: Callable[[int, int], None] | None = None,
) -> list[int]:
    """Stop `plugin_id`'s work: cancel its queued requests, ask the supervisor to
    stop its run, and SIGTERM every live runner, a hand-started one included;
    each run ends `stopped`. A `running` row whose runner is gone is closed
    `error`. Commits, so Disable, Pause and Uninstall never leave one reading as
    running and the supervisor sees the cancel."""
    key = job_store.instance_key("plugin_run", plugin_id)
    await job_store.cancel_queued(session, key=key)
    supervised = await session.scalar(
        select(JobRun.id).where(JobRun.key == key, JobRun.state.in_(job_store.LIVE)).limit(1)
    )
    if supervised is not None:
        await job_store.request_cancel(session, supervised, reason="plugin_stop")
    await session.commit()
    rows = (
        await session.execute(
            select(PluginRun.id, PluginRun.pid).where(PluginRun.plugin_id == plugin_id,
                                                       PluginRun.outcome == "running")
        )
    ).all()
    stopped: list[int] = []
    dead: list[int] = []
    for run_id, pid in rows:
        if pid is not None and runner_alive(pid, command=command):
            try:
                (kill or os.kill)(pid, signal.SIGTERM)
                stopped.append(pid)
            except ProcessLookupError:
                dead.append(run_id)
        else:
            dead.append(run_id)
    if dead:
        await store.close_dead_runs(session, dead)
        await session.commit()
    return stopped


async def plugins_when_due(
    session: AsyncSession,
    *,
    trigger: str,
    power: Callable[[], Any],
    spawner: Spawner | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Start the due plugin jobs if the machine allows it now.

    Never in a maintenance wake. A scheduled run also waits for mains
    power; work the user starts (Sync) does not. `power` reads the machine
    (`platform.power.read_power`), and only when a job is due: with no plugin
    installed this is one query and nothing else."""
    due = await _due_now(session, now)
    if not due:
        return {"started": [], "waiting": None}
    waiting = power().wait_reason(mains=trigger == "schedule")
    if waiting is not None:
        return {"started": [], "waiting": waiting}
    await _spawn_all(session, due, trigger=trigger, spawner=spawner)
    return {"started": [f"{d.plugin_id}:{d.job}" for d in due], "waiting": None}
