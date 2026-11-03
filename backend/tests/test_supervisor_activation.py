"""Activation: landed code reaches the running system, and only when it can run.

Readiness is read from a throwaway git repository: HEAD, the dependency
fingerprint `./setup.sh` records, and the tree the served dashboard was built
from. The watcher's decisions run against a stand-in dispatcher, so every
landing (schema pending, dependencies pending, a dashboard to build, a build
that fails) is replayed without processes.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tracker.supervisor import activation
from tracker.supervisor.activation import Readiness, Step, Watcher, next_step


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"},
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str], message: str = "change") -> str:
    for name, body in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-q")
    _commit(root, {
        "backend/requirements.txt": "fastapi==1\n",
        "backend/app.py": "x = 1\n",
        "dashboard/package-lock.json": "{}\n",
        "dashboard/src/main.ts": "export {}\n",
        ".gitignore": "data/\ndashboard/dist/\n",
    }, "base")
    return root


def _built(repo: Path, tree: str | None) -> None:
    stamp = repo / activation.DIST_STAMP
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(f"{tree}\n" if tree else "")


# --- readiness ----------------------------------------------------------------------


def test_the_dependency_fingerprint_moves_with_what_setup_installs_and_nothing_else(repo):
    before = activation.dependency_fingerprint(repo)
    _commit(repo, {"backend/app.py": "x = 2\n", "dashboard/src/main.ts": "export const a = 1\n"})
    assert activation.dependency_fingerprint(repo) == before, "code is not a dependency"
    _commit(repo, {"backend/requirements.txt": "fastapi==2\n"})
    assert activation.dependency_fingerprint(repo) != before
    moved = activation.dependency_fingerprint(repo)
    _commit(repo, {"dashboard/package-lock.json": '{"v": 2}\n'})
    assert activation.dependency_fingerprint(repo) != moved


def test_dependencies_are_ready_once_recorded_pending_after_a_change_and_unknown_unrecorded(repo, tmp_path):
    data = tmp_path / "data"
    assert activation.assess(repo, data, schema_ready=True).dependencies == activation.UNKNOWN
    activation.record_dependencies(repo, data)
    assert activation.assess(repo, data, schema_ready=True).dependencies == activation.READY
    _commit(repo, {"backend/requirements.txt": "fastapi==2\n"})
    readiness = activation.assess(repo, data, schema_ready=True)
    assert readiness.dependencies == activation.PENDING
    assert readiness.held_by == activation.DEPENDENCIES_PENDING


def test_a_dashboard_is_stale_until_built_from_head_s_tree(repo, tmp_path):
    data = tmp_path / "data"
    assert activation.assess(repo, data, schema_ready=True).dashboard_stale, "never built"
    _built(repo, activation.dashboard_tree(repo))
    assert not activation.assess(repo, data, schema_ready=True).dashboard_stale
    _commit(repo, {"backend/app.py": "x = 3\n"})
    assert not activation.assess(repo, data, schema_ready=True).dashboard_stale, "a backend landing builds nothing"
    _commit(repo, {"dashboard/src/main.ts": "export const b = 2\n"})
    assert activation.assess(repo, data, schema_ready=True).dashboard_stale


def test_dirty_content_is_not_a_landing(repo):
    """Identity is HEAD: a peer's uncommitted edit restarts nothing."""
    before = activation.head(repo)
    (repo / "backend" / "app.py").write_text("x = 'half done'\n")
    assert activation.head(repo) == before


# --- the decision -------------------------------------------------------------------

READY = Readiness(head="new", schema=True, dependencies=activation.READY, dashboard_stale=False)


@pytest.mark.parametrize(
    ("readiness", "kwargs", "expected"),
    [
        (READY, {}, Step(activation.RESTART)),
        (Readiness("old", True, activation.READY, False), {}, Step(activation.NOTHING)),
        (Readiness("new", False, activation.READY, True), {}, Step(activation.HOLD, activation.SCHEMA_PENDING)),
        (Readiness("new", True, activation.PENDING, False), {}, Step(activation.HOLD, activation.DEPENDENCIES_PENDING)),
        (Readiness("new", True, activation.UNKNOWN, False), {}, Step(activation.RESTART)),
        (Readiness("new", True, activation.READY, True), {}, Step(activation.BUILD)),
        (Readiness("new", True, activation.READY, True), {"building": True}, Step(activation.WAIT_FOR_BUILD)),
        (Readiness("new", True, activation.READY, True), {"failed_tree": "t1"}, Step(activation.HOLD, activation.BUILD_FAILED)),
        (Readiness("old", True, activation.READY, True), {}, Step(activation.BUILD)),
    ],
    ids=[
        "landed and ready restarts", "nothing landed", "schema pending holds even a build",
        "dependencies pending hold", "unknown dependencies do not hold", "a stale dashboard is built first",
        "a running build is waited for", "a tree that failed to build is not built again",
        "an unbuilt dashboard is built without a landing",
    ],
)
def test_what_activation_does_next(readiness, kwargs, expected):
    arguments = {"building": False, "failed_tree": None, "tree": "t1", **kwargs}
    assert next_step("old", readiness, **arguments) == expected


# --- the watcher, against a stand-in dispatcher --------------------------------------


class StandIn:
    def __init__(self, repo: Path, data: Path) -> None:
        self.repo_root, self.data_dir = repo, data
        self.schema = True
        self.refreshed = 0
        self.dependencies_ready = True
        self.asked: list[str] = []
        self.building = False
        self.build_ok = True

    def refresh_heads(self) -> None:
        self.refreshed += 1

    async def schema_ready(self) -> bool:
        return self.schema

    async def pending(self, job: str) -> bool:
        return self.building

    async def last_run_succeeded(self, job: str) -> bool:
        return self.build_ok

    async def ask(self, job: str, *, requested_by: str) -> None:
        self.asked.append(job)
        self.building = True


@pytest.fixture
def watched(repo, tmp_path):
    data = tmp_path / "data"
    activation.record_dependencies(repo, data)
    _built(repo, activation.dashboard_tree(repo))
    stand_in = StandIn(repo, data)
    return stand_in, Watcher(stand_in, every_seconds=60)


async def _look(watcher: Watcher, at: float) -> Step:
    return await watcher.look(at)


@pytest.mark.asyncio
async def test_a_backend_landing_restarts_once_ready_and_holds_on_a_pending_migration(repo, watched):
    stand_in, watcher = watched
    assert (await _look(watcher, 0)).action == activation.NOTHING
    _commit(repo, {"backend/app.py": "x = 9\n"})
    stand_in.schema = False
    assert await _look(watcher, 30) == Step(activation.NOTHING), "looks once a minute"
    assert await _look(watcher, 60) == Step(activation.HOLD, activation.SCHEMA_PENDING)
    assert stand_in.refreshed == 1, "database jobs now wait for the new code's schema"
    assert watcher.held == activation.SCHEMA_PENDING
    stand_in.schema = True
    assert await _look(watcher, 120) == Step(activation.RESTART)
    assert stand_in.refreshed == 1, "HEAD did not move again"


@pytest.mark.asyncio
async def test_pending_dependencies_hold_the_database_jobs(repo, watched):
    stand_in, watcher = watched
    _commit(repo, {"backend/requirements.txt": "fastapi==3\n"})
    assert await _look(watcher, 0) == Step(activation.HOLD, activation.DEPENDENCIES_PENDING)
    assert stand_in.dependencies_ready is False
    activation.record_dependencies(repo, stand_in.data_dir)
    assert await _look(watcher, 60) == Step(activation.RESTART)
    assert stand_in.dependencies_ready is True


@pytest.mark.asyncio
async def test_a_dashboard_landing_builds_first_then_restarts(repo, watched):
    stand_in, watcher = watched
    _commit(repo, {"dashboard/src/main.ts": "export const c = 3\n"})
    assert await _look(watcher, 0) == Step(activation.BUILD)
    assert stand_in.asked == ["dashboard_build"]
    assert await _look(watcher, 1) == Step(activation.WAIT_FOR_BUILD), "a running build is looked at every turn"
    _built(repo, activation.dashboard_tree(repo))
    stand_in.building = False
    assert await _look(watcher, 2) == Step(activation.RESTART), "and its end restarts at once"
    assert stand_in.asked == ["dashboard_build"], "built once"
    assert await _look(watcher, 3) == Step(activation.NOTHING), "then back to once a minute"


@pytest.mark.asyncio
async def test_a_failed_build_holds_the_restart_and_is_not_retried_until_the_tree_moves(repo, watched):
    stand_in, watcher = watched
    _commit(repo, {"dashboard/src/main.ts": "export const broken = \n"})
    assert await _look(watcher, 0) == Step(activation.BUILD)
    stand_in.building, stand_in.build_ok = False, False
    assert await _look(watcher, 60) == Step(activation.HOLD, activation.BUILD_FAILED)
    assert await _look(watcher, 120) == Step(activation.HOLD, activation.BUILD_FAILED)
    assert stand_in.asked == ["dashboard_build"], "the old API and the old dashboard keep serving together"
    _commit(repo, {"dashboard/src/main.ts": "export const fixed = 1\n"})
    assert await _look(watcher, 180) == Step(activation.BUILD)


@pytest.mark.asyncio
async def test_a_dashboard_built_without_a_landing_restarts_only_the_api(repo, watched):
    """At a first start with no dashboard built: the API must restart to mount it."""
    stand_in, watcher = watched
    _built(repo, None)
    assert await _look(watcher, 0) == Step(activation.BUILD)
    _built(repo, activation.dashboard_tree(repo))
    stand_in.building = False
    assert await _look(watcher, 60) == Step(activation.RESTART_API)
    assert await _look(watcher, 120) == Step(activation.NOTHING)


def test_setup_records_what_it_installed_from(repo, tmp_path, monkeypatch, capsys):
    from tracker.platform import paths

    data = tmp_path / "data"
    monkeypatch.setattr(paths, "REPO_ROOT", repo)
    monkeypatch.setattr(paths, "DATA_DIR", data)
    assert activation.main(["record-deps"]) == 0
    assert activation.installed_dependencies(data) == activation.dependency_fingerprint(repo)
    assert activation.main(["nonsense"]) == 2


@pytest.mark.asyncio
async def test_while_a_build_runs_a_turn_asks_only_whether_it_ended(repo, watched, monkeypatch):
    """The busy loop turns every second while the build runs: git is read on the
    minute, the build's state every turn, and its end acts at once."""
    stand_in, watcher = watched
    _commit(repo, {"dashboard/src/main.ts": "export const d = 4\n"})
    assert await _look(watcher, 0) == Step(activation.BUILD)

    reads: list[tuple[str, ...]] = []
    real_git = activation._git
    monkeypatch.setattr(activation, "_git", lambda root, *args: reads.append(args) or real_git(root, *args))
    asked: list[str] = []
    real_pending = stand_in.pending

    async def pending(job: str) -> bool:
        asked.append(job)
        return await real_pending(job)

    stand_in.pending = pending
    for at in (1, 2, 30, 59):
        assert await _look(watcher, at) == Step(activation.WAIT_FOR_BUILD)
    assert reads == [], "no git between the minutes"
    assert asked == ["dashboard_build"] * 4, "but every turn asks whether the build ended"

    assert await _look(watcher, 60) == Step(activation.WAIT_FOR_BUILD)
    assert reads, "the checkout is read again on the minute"
    reads.clear()
    _built(repo, activation.dashboard_tree(repo))
    stand_in.building = False
    assert await _look(watcher, 61) == Step(activation.RESTART), "its end restarts at once"
    assert stand_in.asked == ["dashboard_build"], "built once"
