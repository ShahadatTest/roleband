"""`python -m tracker.supervisor`: the supervisor's command line.

    python -m tracker.supervisor plan                 what every job would do now, and why
    python -m tracker.supervisor run                  supervise until stopped
    python -m tracker.supervisor stop --jobs          stop every running job, then start nothing
    python -m tracker.supervisor maintenance on|off   let go of the database (a restore), or resume
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from tracker.platform.local_zone import local_zone
from tracker.supervisor.due import Gate

if TYPE_CHECKING:
    from tracker.supervisor.plan import Planned


def _render(planned: Iterable[Planned]) -> str:
    lines = [f"{'job':<16} {'key':<24} {'state':<8} {'start':<6} {'reason':<20} next"]
    for row in planned:
        decision = row.decision
        next_at = decision.next_at.astimezone().strftime("%Y-%m-%d %H:%M") if decision.next_at else "-"
        lines.append(
            f"{row.job.name:<16} {row.key:<24} {decision.state:<8} "
            f"{'yes' if decision.start else 'no':<6} {decision.reason or '-':<20} {next_at}"
        )
    return "\n".join(lines)


async def _plan() -> int:
    from tracker.db.session import session_scope
    from tracker.supervisor.plan import plan, read_world

    zone = local_zone()
    async with session_scope() as session:
        # No preflight verdict is read here: gated jobs show it as pending.
        world = await read_world(session, zone=zone, gate=Gate.UNKNOWN)
        planned = await plan(session, datetime.now(UTC), world)
    flags = []
    if world.dark_wake:
        flags.append("maintenance wake")
    if world.on_battery:
        flags.append("on battery")
    if not world.schema_ready:
        flags.append("schema behind the code")
    print(_render(planned))
    if flags:
        print("\n" + ", ".join(flags))
    return 0


async def _run(*, dry_run_network: bool = False) -> int:
    import signal

    from tracker.config import get_settings
    from tracker.db.session import get_engine, get_session_factory
    from tracker.platform.paths import DATA_DIR, REPO_ROOT
    from tracker.platform.version import code_version
    from tracker.supervisor import gate, logs
    from tracker.supervisor.activation import Watcher
    from tracker.supervisor.api import ApiService
    from tracker.supervisor.dispatch import Dispatcher
    from tracker.supervisor.launcher import refresh_registration
    from tracker.supervisor.liveness import Heartbeat
    from tracker.supervisor.service import serve
    from tracker.workflows.watchdog import recover_db

    log_dir = DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    own_log = log_dir / "supervisor.log"
    # launchd points the supervisor's own streams here, for what happens before
    # logging starts; it appends forever unless cut at each start.
    logs.trim(log_dir / "launchd.log")
    logging.basicConfig(
        filename=own_log,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("pixeltable_pgserver").setLevel(logging.WARNING)
    # One line per API health probe, every 30 s, would be most of this log.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    refresh_registration()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)

    zone = local_zone()
    engine = get_engine()
    dispatcher = Dispatcher(
        factory=get_session_factory(),
        repo_root=REPO_ROOT,
        data_dir=DATA_DIR,
        zone=zone,
        code_version=code_version(),
        clear_residue=lambda: gate.clear_residue(REPO_ROOT, sys.executable),
        dry_run_network=dry_run_network,
    )
    if dry_run_network:
        logging.getLogger("tracker.supervisor").info("rehearsal: network jobs send no request")
    settings = get_settings()
    api = ApiService(repo_root=REPO_ROOT, data_dir=DATA_DIR, host=settings.api_host, port=settings.api_port)

    def reexec() -> None:
        logging.shutdown()
        os.execv(sys.executable, [sys.executable, "-m", "tracker.supervisor", *sys.argv[1:]])

    # A loop that stops beating ends the process; launchd starts a fresh one.
    heartbeat = Heartbeat(on_stall=lambda: api.process.terminate() if api.process else None)
    heartbeat.start()
    try:
        await serve(
            dispatcher, engine, stop, rotate=logs.shared(DATA_DIR, settings.embedded_pgdata()), recover=recover_db,
            api=api, watcher=Watcher(dispatcher), reexec=reexec, beat=heartbeat.beat,
        )
    finally:
        heartbeat.stop()
    return 0


async def _wait_for[T](check: Callable[[], T], seconds: float, *, every: float = 0.5) -> T:
    """`check()` until it returns something truthy, for up to `seconds`."""
    deadline = asyncio.get_running_loop().time() + seconds
    while True:
        found = check()
        if found or asyncio.get_running_loop().time() >= deadline:
            return found
        await asyncio.sleep(every)


async def _maintenance_on(*, drain: bool, wait: float, by: str) -> tuple[int, bool]:
    """(exit code, whether a supervisor answered). Leaves the request standing
    either way: a supervisor that starts later stays paused until it is lifted."""
    from tracker.db.session import get_engine
    from tracker.platform.paths import DATA_DIR
    from tracker.supervisor import maintenance, singleton
    from tracker.supervisor.residue import pid_alive

    standing = maintenance.request(DATA_DIR, by=by, drain=drain)
    print(f"maintenance requested ({'waiting for' if standing.drain else 'stopping'} the running jobs)")
    if maintenance.answered(DATA_DIR, alive=pid_alive) is None:
        try:
            holder = await singleton.holder(get_engine())
        except Exception as error:  # noqa: BLE001 - a database that is down has no supervisor on it
            holder = None
            print(f"the database cannot be reached ({error})")
        if holder is None:
            print("no supervisor is running on this database")
            return 0, False

    def paused() -> maintenance.Answer | None:
        given = maintenance.answered(DATA_DIR, alive=pid_alive)
        return given if given is not None and given.state == maintenance.PAUSED else None

    given = await _wait_for(paused, wait)
    if given is None:
        state = maintenance.answered(DATA_DIR, alive=pid_alive)
        print(f"the supervisor has not paused after {wait:.0f} s ({state.state if state else 'no answer'})")
        return 1, True
    print(f"the supervisor (pid {given.pid}) is paused: no job runs, no connection is held")
    return 0, True


async def _maintenance_off(*, wait: float) -> int:
    from tracker.platform.paths import DATA_DIR
    from tracker.supervisor import maintenance
    from tracker.supervisor.residue import pid_alive

    if not maintenance.lift(DATA_DIR):
        print("maintenance was not on")
        return 0
    if maintenance.last_answer(DATA_DIR, alive=pid_alive) is None:
        print("maintenance lifted")
        return 0
    resumed = await _wait_for(lambda: maintenance.last_answer(DATA_DIR, alive=pid_alive) is None, wait)
    print("maintenance lifted: the supervisor resumed" if resumed else
          f"maintenance lifted, but the supervisor has not resumed after {wait:.0f} s")
    return 0 if resumed else 1


async def _stop_jobs(*, wait: float) -> int:
    """Every running job stopped, by the supervisor when one runs, else here."""
    code, answered = await _maintenance_on(drain=False, wait=wait, by="stop --jobs")
    if not answered:
        code = await _stop_jobs_here(wait=wait)
    if code == 0:
        print("every job is stopped; nothing starts until `python -m tracker.supervisor maintenance off`")
    return code


async def _stop_jobs_here(*, wait: float) -> int:
    """No supervisor runs: adopt what a dead one left running and stop it, holding
    the supervisor lock so none starts dispatching meanwhile."""
    from tracker.db.session import get_engine, get_session_factory
    from tracker.platform.paths import DATA_DIR, REPO_ROOT
    from tracker.supervisor import singleton
    from tracker.supervisor.dispatch import Dispatcher

    engine = get_engine()
    held = await singleton.hold(engine)
    if held is None:
        print("a supervisor holds the database but did not answer; nothing stopped")
        return 1
    try:
        zone = local_zone()
        dispatcher = Dispatcher(
            factory=get_session_factory(), repo_root=REPO_ROOT, data_dir=DATA_DIR, zone=zone,
            read_gate=None, awake_every=None,
        )
        await dispatcher.adopt()
        if not dispatcher.watched:
            print("no job was running")
            return 0
        print(f"stopping {len(dispatcher.watched)} running job(s)")
        await dispatcher.drain(cancel=True, reason="stop_jobs")

        async def settled() -> bool:
            deadline = asyncio.get_running_loop().time() + wait
            while dispatcher.watched and asyncio.get_running_loop().time() < deadline:
                await dispatcher.settle()
                await asyncio.sleep(0.5)
            return not dispatcher.watched

        if not await settled():
            print(f"{len(dispatcher.watched)} job(s) still running after {wait:.0f} s")
            return 1
        return 0
    finally:
        await singleton.release(held)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tracker.supervisor")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan", help="what every job would do now, and why; writes nothing")
    running = commands.add_parser(
        "run",
        help="supervise: start what is due, watch what runs; a stop leaves jobs running",
    )
    running.add_argument(
        "--dry-run-network", action="store_true",
        help="a rehearsal: jobs that reach a third party run without sending anything",
    )
    stopping = commands.add_parser("stop", help="stop every running job and start nothing until resumed")
    stopping.add_argument("--jobs", action="store_true", required=True, help="the jobs, not the supervisor")
    stopping.add_argument("--wait", type=float, default=120.0, help="seconds to wait for the jobs to end")
    paused = commands.add_parser("maintenance", help="pause the supervisor off the database, or resume it")
    paused.add_argument("switch", choices=("on", "off"))
    paused.add_argument("--drain", action="store_true", help="wait for running jobs instead of stopping them")
    paused.add_argument("--wait", type=float, default=120.0, help="seconds to wait for the supervisor")
    args = parser.parse_args(argv)
    if args.command == "plan":
        return asyncio.run(_plan())
    if args.command == "run":
        return asyncio.run(_run(dry_run_network=args.dry_run_network))
    if args.command == "stop":
        return asyncio.run(_stop_jobs(wait=args.wait))
    if args.command == "maintenance":
        if args.switch == "off":
            return asyncio.run(_maintenance_off(wait=args.wait))
        return asyncio.run(_maintenance_on(drain=args.drain, wait=args.wait, by="cli"))[0]
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
