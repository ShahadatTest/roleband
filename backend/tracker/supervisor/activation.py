"""Landed code reaches the running system without a manual restart.

    python -m tracker.supervisor.activation record-deps

Identity is HEAD, never dirty content: uncommitted edits in the checkout are a
peer's unfinished work, which is the preflight's business, not a reason to
restart. Every minute the supervisor reads HEAD. When it has moved, the new code
is checked before anything is touched:

1. schema: the code's alembic heads against the database's revision;
2. dependencies: a fingerprint of what `./setup.sh` installs from, against the one
   it recorded (`data/installed-deps.json`); no record is unknown, not pending;
3. dashboard: the tree the served dashboard was built from against HEAD's.

A pending schema or dependency set holds everything: the API keeps serving the
old code, running jobs finish on it, and no job that touches the database starts
(the dispatcher reads the new code's heads). Otherwise a stale dashboard is
rebuilt aside and swapped in, then the supervisor restarts itself on the new
code, the API with it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from tracker.platform.paths import PACKAGED

if TYPE_CHECKING:
    from tracker.supervisor.dispatch import Dispatcher

#: What `./setup.sh` installs from. The robots matcher is installed editable, so
#: only its own declared dependencies need an install when they change.
DEPENDENCY_PATHS = (
    "backend/requirements.txt",
    "backend/requirements-dev.txt",
    "backend/requirements-optional.txt",
    "backend/constraints",
    "robots/python/pyproject.toml",
    "dashboard/package-lock.json",
)
INSTALLED_DEPS = "installed-deps.json"
#: Written into the built dashboard by `deploy/build_dashboard.sh`.
DIST_STAMP = Path("dashboard") / "dist" / ".roleband-tree"

READY = "ready"
PENDING = "pending"
UNKNOWN = "unknown"

# Reason codes, as the status speaks them.
SCHEMA_PENDING = "schema_pending"
DEPENDENCIES_PENDING = "dependencies_pending"
BUILD_FAILED = "build_failed"


def _git(repo_root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, repo-local
            ["git", "-C", str(repo_root), *args], capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = done.stdout.strip()
    return out if done.returncode == 0 and out else None


def head(repo_root: Path) -> str | None:
    return _git(repo_root, "rev-parse", "HEAD")


def dependency_fingerprint(repo_root: Path, rev: str = "HEAD") -> str | None:
    """One hash over the committed objects of every dependency path at `rev`."""
    lines = []
    for path in DEPENDENCY_PATHS:
        lines.append(f"{path}={_git(repo_root, 'rev-parse', f'{rev}:{path}') or '-'}")
    if all(line.endswith("=-") for line in lines):
        return None
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def record_dependencies(repo_root: Path, data_dir: Path) -> str | None:
    """What `./setup.sh` calls once it has installed: the fingerprint of HEAD."""
    fingerprint = dependency_fingerprint(repo_root)
    if fingerprint is None:
        return None
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / INSTALLED_DEPS
    partial = target.with_name(target.name + ".partial")
    partial.write_text(json.dumps({"fingerprint": fingerprint, "head": head(repo_root)}), encoding="utf-8")
    partial.replace(target)
    return fingerprint


def installed_dependencies(data_dir: Path) -> str | None:
    try:
        raw = json.loads((data_dir / INSTALLED_DEPS).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    value = raw.get("fingerprint") if isinstance(raw, dict) else None
    return value if isinstance(value, str) else None


def dashboard_tree(repo_root: Path) -> str | None:
    return _git(repo_root, "rev-parse", "HEAD:dashboard")


def built_tree(repo_root: Path) -> str | None:
    try:
        return (repo_root / DIST_STAMP).read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None


@dataclass(frozen=True)
class Readiness:
    head: str | None
    schema: bool
    dependencies: str
    #: The served dashboard was built from another tree than HEAD's (or none).
    dashboard_stale: bool

    @property
    def held_by(self) -> str | None:
        """Why the new code cannot run yet, or None."""
        if not self.schema:
            return SCHEMA_PENDING
        if self.dependencies == PENDING:
            return DEPENDENCIES_PENDING
        return None


def assess(repo_root: Path, data_dir: Path, *, schema_ready: bool) -> Readiness:
    installed = installed_dependencies(data_dir)
    wanted = dependency_fingerprint(repo_root)
    if installed is None or wanted is None:
        dependencies = UNKNOWN
    else:
        dependencies = READY if installed == wanted else PENDING
    tree = dashboard_tree(repo_root)
    stale = tree is not None and built_tree(repo_root) != tree
    return Readiness(head=head(repo_root), schema=schema_ready, dependencies=dependencies, dashboard_stale=stale)


# --- what to do next --------------------------------------------------------------

NOTHING = "nothing"
HOLD = "hold"
BUILD = "build"
WAIT_FOR_BUILD = "wait_for_build"
RESTART = "restart"


@dataclass(frozen=True)
class Step:
    action: str
    reason: str | None = None


def next_step(
    running_head: str | None,
    readiness: Readiness,
    *,
    building: bool,
    failed_tree: str | None,
    tree: str | None,
) -> Step:
    """Pure: from the code this supervisor runs and the checkout's readiness,
    what to do now. A dashboard tree whose build failed is not built again
    until the tree changes; the restart waits with it, so the old API keeps
    serving the old dashboard it matches."""
    landed = readiness.head is not None and readiness.head != running_head
    if readiness.held_by is not None:
        return Step(HOLD, readiness.held_by) if landed else Step(NOTHING)
    if building:
        return Step(WAIT_FOR_BUILD)
    if readiness.dashboard_stale:
        if tree is not None and tree == failed_tree:
            return Step(HOLD, BUILD_FAILED)
        return Step(BUILD)
    return Step(RESTART) if landed else Step(NOTHING)


def main(argv: Sequence[str] | None = None) -> int:
    from tracker.platform.paths import DATA_DIR, REPO_ROOT

    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["record-deps"]:
        print("usage: python -m tracker.supervisor.activation record-deps", file=sys.stderr)
        return 2
    fingerprint = record_dependencies(REPO_ROOT, DATA_DIR)
    print(f"installed dependencies recorded: {fingerprint}" if fingerprint else "not a git checkout: nothing recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# --- the watcher ------------------------------------------------------------------

#: A step the service acts on, beyond NOTHING, HOLD and the build's own waits.
RESTART_API = "restart_api"


class Watcher:
    """Looks at the checkout every `every_seconds` of awake time and says what
    the service should do. Holds the only state activation needs: the code this
    process runs, the dashboard tree whose build failed, and whether the API has
    yet to serve a dashboard built since it started."""

    def __init__(self, dispatcher: Dispatcher, *, every_seconds: float = 60.0) -> None:
        self.dispatcher = dispatcher
        self.repo_root: Path = dispatcher.repo_root
        self.data_dir: Path = dispatcher.data_dir
        self.every_seconds = every_seconds
        self.running_head = None if PACKAGED else head(self.repo_root)
        self.seen_head = self.running_head
        self.failed_tree: str | None = None
        self.held: str | None = None
        self._last: float | None = None
        self._build_requested = False

    @property
    def building(self) -> bool:
        """A dashboard build it asked for has not been seen to end."""
        return self._build_requested

    async def look(self, now_awake: float) -> Step:
        if PACKAGED:
            return Step(NOTHING)
        recent = self._last is not None and now_awake - self._last < self.every_seconds
        if recent and not self._build_requested:
            return Step(NOTHING)
        # While a build it asked for runs, every turn asks only whether it has
        # ended: the restart that serves it follows its end at once, and the
        # checkout is read again on the minute.
        if recent and await self.dispatcher.pending("dashboard_build"):
            return Step(WAIT_FOR_BUILD)
        self._last = now_awake
        current = await asyncio.to_thread(head, self.repo_root)
        if current != self.seen_head:
            # The children run the checkout on disk: from now on the dispatcher
            # holds database jobs until the database is at that code's schema.
            self.seen_head = current
            await asyncio.to_thread(self.dispatcher.refresh_heads)
        readiness = await asyncio.to_thread(
            assess, self.repo_root, self.data_dir, schema_ready=await self.dispatcher.schema_ready()
        )
        self.dispatcher.dependencies_ready = readiness.dependencies != PENDING
        tree = await asyncio.to_thread(dashboard_tree, self.repo_root)
        building = await self.dispatcher.pending("dashboard_build")
        if self._build_requested and not building:
            self._build_requested = False
            if await self.dispatcher.last_run_succeeded("dashboard_build"):
                readiness = await asyncio.to_thread(
                    assess, self.repo_root, self.data_dir, schema_ready=readiness.schema
                )
                if readiness.head == self.running_head and not readiness.dashboard_stale:
                    self.held = None
                    return Step(RESTART_API)
            else:
                self.failed_tree = tree
        step = next_step(
            self.running_head, readiness, building=building, failed_tree=self.failed_tree, tree=tree,
        )
        if step.action == BUILD:
            await self.dispatcher.ask("dashboard_build", requested_by="activation")
            self._build_requested = True
        self.held = step.reason if step.action == HOLD else None
        return step
