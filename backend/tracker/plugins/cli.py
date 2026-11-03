"""Install, approve, enable and run plugins from the command line.

    .venv/bin/python -m scripts.plugin <command>          # from backend/, as people type it
    .venv/bin/python -m tracker.plugins.cli run <id> <job>  # the supervisor's `plugin_run`

`scripts.plugin` lists the commands; both spellings run this module.

Installs land in `Settings.plugins_dir()` (`~/.roleband/plugins`). An update
lapses the approval: the plugin does not run again until approved again.
Enabling changes no answer until the plugin's first clean run.

`run` is the host process the supervisor starts for Sync, Refresh and the
scheduled runs (`plugins.runtime`). It imports the plugin SDK from this
checkout; the API and pipeline never do. SIGTERM stops a run: it ends
`stopped`; what it had already published whole stays read and retired, nothing
after is. Every decision goes through `tracker.plugins.lifecycle`, the code
Settings > Plugins runs too. A clean run, and a decision that moves the
reference set, end with a re-estimate in place, so the stored estimates follow.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.db.models import PluginInstall
from tracker.db.session import session_scope
from tracker.plugins import lifecycle, store
from tracker.plugins.install import SDK_DIR, InstallRefused, approval_text
from tracker.plugins.reestimate import reestimate
from tracker.plugins.registry import install_records
from tracker.plugins.schedule import SCHEDULES
from tracker.profiles.store import rematerialize_sources

#: One lifecycle decision about one plugin, as the CLI applies it.
Decision = Callable[[AsyncSession, str], Awaitable[lifecycle.Change]]


def _ensure_sdk() -> None:
    if str(SDK_DIR) not in sys.path:
        sys.path.insert(0, str(SDK_DIR))


async def _install(args: argparse.Namespace) -> int:
    _ensure_sdk()
    try:
        async with session_scope() as session:
            row, lapsed, change = await lifecycle.install(session, Path(args.path).resolve(),
                                                          plugins_dir=get_settings().plugins_dir(),
                                                          venv=not args.no_venv)
    except InstallRefused as exc:
        print("refused:\n  " + "\n  ".join(exc.problems), file=sys.stderr)
        return 1
    print(f"installed {row.plugin_id} {row.version} at {row.source_dir}")
    print("approval lapsed: approve it again before it runs" if lapsed else "needs approval before it runs")
    await _follow(change)
    return 0


async def _approve(args: argparse.Namespace) -> int:
    async with session_scope() as session:
        row = await session.get(PluginInstall, args.plugin)
        if row is None:
            print(f"no plugin {args.plugin!r} is installed", file=sys.stderr)
            return 1
        shown, fingerprint = approval_text(row.manifest), row.fingerprint
        print(json.dumps(shown, indent=2))
        if not args.yes and input("Approve this plugin as shown? [y/N] ").strip().lower() != "y":
            print("not approved")
            return 1
        change = await lifecycle.approve(session, args.plugin, fingerprint=fingerprint)
    print(f"approved {args.plugin}")
    await _follow(change)
    return 0


async def _decide(args: argparse.Namespace, decide: Decision, done: str) -> int:
    """Apply one lifecycle decision and follow the reference set if it moved."""
    async with session_scope() as session:
        change = await decide(session, args.plugin)
    if change.stopped:
        print(f"stopped the running job (pid {', '.join(map(str, change.stopped))}); it ends stopped; companies it had already published whole stay read")
    print(f"{done} {args.plugin}")
    await _follow(change)
    return 0


async def _follow(change: lifecycle.Change) -> None:
    if change.reference_moved:
        await _reestimate()


async def _rematerialize_cmd(args: argparse.Namespace) -> int:
    """Resolve again every profile a source claimed for, so claims no source
    of ours or selected plugin makes leave the profile columns at once."""
    async with session_scope() as session:
        companies = await rematerialize_sources(session, args.sources)
        await session.commit()
    print(f"resolved {len(companies)} companies again")
    return 0


async def _reestimate() -> None:
    """Move the stored estimates to the reference set the change made current.
    A scrape holding the lock does it before it collects."""
    async with session_scope() as session:
        result = await reestimate(session, take_lock=True)
    if result.applied:
        report = result.report
        print(f"estimates: {report['moved']} moved, {report['gained']} gained, {report['lost']} lost "
              f"of {report['jobs']} postings (change {result.change_id})")
    elif result.skipped:
        print("estimates: a scrape holds the lock; it re-estimates before it collects")


async def _schedule(args: argparse.Namespace) -> int:
    schedule = None if args.schedule == "default" else args.schedule
    async with session_scope() as session:
        await lifecycle.set_schedule(session, args.plugin, schedule)
    print(f"{args.plugin} runs {args.schedule if schedule else 'on its own schedule'}")
    return 0


async def _remove_data(args: argparse.Namespace) -> int:
    async with session_scope() as session:
        deleted, change = await lifecycle.remove_data(session, args.plugin, confirm=args.confirm)
    print(f"deleted {deleted}")
    await _follow(change)
    return 0


async def _order(args: argparse.Namespace) -> int:
    async with session_scope() as session:
        change = await lifecycle.set_order(session, args.slot, args.plugins)
    print(f"{args.slot}: {' > '.join(args.plugins) if args.plugins else 'id order'}")
    await _follow(change)
    return 0


async def _list(_args: argparse.Namespace) -> int:
    async with session_scope() as session:
        for rec in await install_records(session):
            print(f"{rec.plugin_id:32} {rec.state:16} slots={sorted(rec.slots)}")
    return 0


async def _run(args: argparse.Namespace) -> int:
    _ensure_sdk()
    from tracker.plugins.host import NotRunnable, installed_config, run_job

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, stop.set)
    async with session_scope() as session:
        row = await session.get(PluginInstall, args.plugin)
        if row is None:
            print(f"no plugin {args.plugin!r} is installed", file=sys.stderr)
            return 1
        config = installed_config(row, python=args.python, on_open=lambda run_id: print(f"run {run_id} started"))
        try:
            result = await run_job(session, args.plugin, args.job, trigger=args.trigger, config=config, stop=stop)
        except NotRunnable as exc:
            print(exc, file=sys.stderr)
            return 1
    print(f"run {result.run_id}: {result.outcome}; published {result.published}; retired {result.retired}")
    for refusal in result.refusals:
        print(f"  refused: {refusal}")
    if result.message:
        print(f"  {result.message}")
    if result.published:
        # Each company read whole is read from now: the stored
        # estimates follow whatever the run's end.
        await _reestimate()
    return 0 if result.outcome in ("clean", "partial") else 1


def _decision(decide: Decision, done: str) -> Callable[[argparse.Namespace], Coroutine[Any, Any, int]]:
    return lambda args: _decide(args, decide, done)


def main(argv: list[str] | None = None, *, prog: str = "tracker.plugins.cli") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Install, approve, enable and run plugins from the command line.")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("install", help="install or update from a plugin directory")
    p.add_argument("path")
    p.add_argument("--no-venv", action="store_true", help="skip building the venv (run with --python)")
    p = sub.add_parser("approve")
    p.add_argument("plugin")
    p.add_argument("--yes", action="store_true", help="approve without asking (what is shown is still stored)")
    for name in ("enable", "disable", "pause", "resume", "remove"):
        sub.add_parser(name).add_argument("plugin")
    p = sub.add_parser("schedule", help="how often its jobs run; default = the plugin's own")
    p.add_argument("plugin")
    p.add_argument("schedule", choices=[*SCHEDULES, "default"])
    p = sub.add_parser("remove-data", help="delete its pay-level and benefit rows (the plugin must be off)")
    p.add_argument("plugin")
    p.add_argument("--confirm", required=True, help="the plugin's id, typed")
    p = sub.add_parser("order", help="which plugin answers first in a slot; no ids = id order")
    p.add_argument("slot")
    p.add_argument("plugins", nargs="*")
    sub.add_parser("list")
    p = sub.add_parser("rematerialize", help="resolve again every profile these sources claimed for")
    p.add_argument("sources", nargs="+")
    p = sub.add_parser("run", help="run one job now; this process is the host")
    p.add_argument("plugin")
    p.add_argument("job")
    p.add_argument("--trigger", default="cli", choices=store.TRIGGERS)
    p.add_argument("--python", help="interpreter to run the plugin with instead of its venv (development)")
    args = ap.parse_args(argv)
    handlers: dict[str, Callable[[argparse.Namespace], Coroutine[Any, Any, int]]] = {
        "install": _install, "approve": _approve,
        "enable": _decision(lifecycle.enable, "enabled"),
        "disable": _decision(lifecycle.disable, "disabled"),
        "pause": _decision(lifecycle.pause, "paused"),
        "resume": _decision(lifecycle.resume, "resumed"),
        "remove": _decision(lifecycle.uninstall, "removed (its published rows are kept, unread)"),
        "schedule": _schedule, "remove-data": _remove_data, "order": _order, "list": _list, "run": _run,
        "rematerialize": _rematerialize_cmd,
    }
    try:
        return asyncio.run(handlers[args.command](args))
    except lifecycle.Refused as exc:
        print(exc.message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
