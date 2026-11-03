"""Jobs whose own return value is the run's raw result.

    python -m tracker.supervisor.entries <job>

The job runs in this process, as its usual command would, and the value it
returns is written to the file named by `ROLEBAND_JOB_RAW` (and printed, for the
log). `results.summarize` turns it into the run's structured result: a tick that
found its lock held, one that found nothing due and one that read boards all
exit 0, and only the value tells them apart.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Callable, Coroutine, Sequence
from pathlib import Path
from typing import Any

from tracker.supervisor import child

#: Where an entry's raw result goes; set by the runner for every job.
RAW_ENV = "ROLEBAND_JOB_RAW"
#: How much of an entry's return value its log line keeps.
LOG_CHARS = 4000
#: Set for a network job in a rehearsal: the entry sends no request. The scan
#: still plans its tick, which reads only the database.
DRY_RUN_ENV = "ROLEBAND_JOB_DRY_RUN"


async def scan() -> dict[str, Any]:
    """One scheduler tick. Due plugin runs, the awake sample and the usage send
    are not the tick's: each has its own schedule, none behind the preflight."""
    from tracker.platform.paths import PACING_DIR
    from tracker.platform.ratelimit import enable_shared_pacing
    from tracker.workflows.scheduler import tick

    enable_shared_pacing(PACING_DIR)
    return await tick(dry_run=False, sample_awake=False, send_usage=False)


async def directory() -> list[dict[str, Any]]:
    """The directory sweep's passes, as `directory_sweep.main` runs them."""
    from tracker.config import get_settings
    from tracker.platform.paths import PACING_DIR
    from tracker.platform.ratelimit import enable_shared_pacing
    from tracker.workflows.directory_sweep import sweep_under_lock

    enable_shared_pacing(PACING_DIR)
    return await sweep_under_lock(
        run_seconds=get_settings().directory_sweep_run_seconds,
        report=lambda result: print(json.dumps(result, default=str), flush=True),
    )


async def plugins_due() -> dict[str, Any]:
    """Ask for every scheduled plugin job that is due. Never in a maintenance
    wake; each run then waits for mains power through its own request."""
    from tracker.db.session import session_scope
    from tracker.platform.power import read_power
    from tracker.plugins.runtime import plugins_when_due

    async with session_scope() as session:
        return await plugins_when_due(session, trigger="schedule", power=read_power)


async def usage_send() -> dict[str, Any]:
    """The usage-sharing send. `flush_if_due` decides whether one is due and
    waits out a maintenance wake itself."""
    from tracker.db.session import session_scope
    from tracker.platform.power import read_power
    from tracker.usage_stats.flush import flush_if_due

    return await flush_if_due(scope=session_scope, power=read_power)


async def role_discovery(argv: Sequence[str]) -> dict[str, Any]:
    """The scope inventory refresh, with the arguments the request carries."""
    from tracker.platform.paths import PACING_DIR
    from tracker.platform.ratelimit import enable_shared_pacing
    from tracker.workflows.discover_roles import _parse_args, discover

    enable_shared_pacing(PACING_DIR)
    args = _parse_args(argv)
    return await discover(companies=args.company, max_list=args.max_list, locations=args.location)


async def reembed() -> dict[str, Any]:
    """The corpus re-embed after a tier switch: the new tier's model first, then
    every vector. Another embedder (a hand-run backfill) holding the lock is a
    turn not taken, not a failure."""
    from tracker.semantic.backfill import AlreadyEmbedding, run

    try:
        return await run(open_only=False, refresh=False, embed=True, provision_first=True)
    except AlreadyEmbedding:
        return {"ran": False, "reason": "another embedder is running"}


async def prices() -> dict[str, Any]:
    """The price refresh, through the post-pass runner that records it: the
    prices lock for the run, every request reserved in the ledger first."""
    from tracker.config import get_settings
    from tracker.db.session import session_scope
    from tracker.workflows.post_passes import run_scheduled_pass

    async with session_scope() as session:
        return await run_scheduled_pass("prices", session, get_settings())


async def scan_process_alive() -> bool:
    """Whether a supervised scan run is live and its process group still exists."""
    from tracker.db import job_store
    from tracker.db.session import session_scope
    from tracker.supervisor import runner

    try:
        async with session_scope() as session:
            live = [run for run in await job_store.live_runs(session) if run.job == "scan"]
    except Exception:  # noqa: BLE001 - no database: the pass's own recovery runs first
        return False
    return any(run.pgid is not None and runner.group_alive(run.pgid) for run in live)


async def health() -> dict[str, Any]:
    """The watchdog's pass, with the supervisor's catch-up and reconcile rules."""
    from tracker.workflows.watchdog import run_once

    return await run_once(reconcile_runs=not await scan_process_alive())


async def backup() -> dict[str, Any]:
    from tracker.config import get_settings
    from tracker.platform.backups import dump_database
    from tracker.platform.paths import DATA_DIR

    server = await asyncio.to_thread(get_settings().ensure_embedded_server)
    archive = await asyncio.to_thread(dump_database, server, DATA_DIR / "backups")
    return {"archive": str(archive)}


ENTRIES: dict[str, Callable[[], Coroutine[Any, Any, Any]]] = {
    "scan": scan,
    "directory": directory,
    "health": health,
    "plugins_due": plugins_due,
    "usage_send": usage_send,
    "reembed": reembed,
    "prices": prices,
    "backup": backup,
}

async def dry_run(argv: Sequence[str]) -> dict[str, Any]:
    """What a network job whose command is not an entry runs in a rehearsal."""
    return {"dry_run": True, "argv": list(argv)}


async def _rehearsed(name: str) -> dict[str, Any]:
    if name == "scan":
        from tracker.workflows.scheduler import tick

        return {"dry_run": True, "tick": await tick(dry_run=True)}
    return {"dry_run": True}


#: Entries that take the rest of the command line (a request's `argv`).
WITH_ARGUMENTS: dict[str, Callable[[Sequence[str]], Coroutine[Any, Any, Any]]] = {
    "role_discovery": role_discovery,
    "dry_run": dry_run,
}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    name, rest = (args[0], args[1:]) if args else ("", [])
    if not (name in ENTRIES and not rest) and name not in WITH_ARGUMENTS:
        names = ",".join([*ENTRIES, *WITH_ARGUMENTS])
        print(f"usage: python -m tracker.supervisor.entries {{{names}}} [arguments]", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("pixeltable_pgserver").setLevel(logging.WARNING)
    if os.environ.get(DRY_RUN_ENV) == "1" and name != "dry_run":
        work = _rehearsed(name)
    elif name in WITH_ARGUMENTS:
        work = WITH_ARGUMENTS[name](rest)
    else:
        work = ENTRIES[name]()
    raw: Any = asyncio.run(work)
    # The whole value goes to the run's result; the log gets its head, so a
    # ten-minute tick's plan does not become most of the log.
    printed = json.dumps(raw, default=str)
    print(printed if len(printed) <= LOG_CHARS else printed[:LOG_CHARS] + " ...", flush=True)
    target = os.environ.get(RAW_ENV)
    if target:
        child.write_result(Path(target), json.loads(json.dumps(raw, default=str)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
