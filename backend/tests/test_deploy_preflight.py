"""`deploy/preflight.sh` certifies exactly the tree it tested, and only that.

Each test copies the script into a throwaway git repository with a tiny suite of
its own, so the real suite never runs and the real checkout is never read.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "preflight.sh"
BACKEND = Path(__file__).resolve().parents[1]

PASSING = "def test_ok():\n    assert True\n"
#: A test at the repository root: collected only if the suite runs from the
#: wrong directory.
ROOT_TRAP = "def test_never_collected():\n    raise AssertionError('the suite ran from the repository root')\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"},
    ).stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "checkout"
    (root / "deploy").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "deploy" / "preflight.sh")
    (root / "backend").mkdir()
    (root / "backend" / "pytest.ini").write_text("[pytest]\n")
    (root / "backend" / "test_ok.py").write_text(PASSING)
    (root / "test_root_trap.py").write_text(ROOT_TRAP)
    for part in ("robots", "sdk/python", "dashboard"):
        (root / part).mkdir(parents=True)
        (root / part / "keep.txt").write_text("v1\n")
    (root / ".gitignore").write_text("data/\n")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _run(repo: Path, *args: str, cwd: Path | None = None, backend: bool = False) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "ROLEBAND_PREFLIGHT_PYTHON": sys.executable,
        "ROLEBAND_PREFLIGHT_TIMEOUT": "120",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if backend:
        # The cleanup is the backend's own module; the throwaway repo has none.
        env["PYTHONPATH"] = str(BACKEND)
    env.pop("ROLEBAND_SKIP_PREFLIGHT", None)
    return subprocess.run(
        ["bash", str(repo / "deploy" / "preflight.sh"), *args],
        cwd=cwd or repo, env=env, capture_output=True, text=True, timeout=180,
    )


def _status(repo: Path) -> tuple[int, str]:
    done = _run(repo, "--status")
    return done.returncode, done.stdout.strip().splitlines()[-1]


def _cache(repo: Path) -> Path:
    return repo / "data" / "preflight-passed.sha256"


def test_a_clean_tree_is_proven_without_running_anything(repo):
    assert _status(repo) == (0, "clean")


@pytest.mark.parametrize("path", ["backend/new_module.py", "robots/matcher.py", "sdk/python/runner.py", "deploy/run_x.sh"])
def test_dirt_in_any_unattended_code_needs_proof(repo, path):
    (repo / path).write_text("x = 1\n")
    code, fingerprint = _status(repo)
    assert code == 3
    assert len(fingerprint) == 64


def test_dirt_in_the_dashboard_needs_no_proof(repo):
    (repo / "dashboard" / "keep.txt").write_text("v2\n")
    assert _status(repo) == (0, "clean")


def test_a_passing_suite_proves_exactly_its_tree_and_runs_from_backend(repo):
    (repo / "backend" / "feature.py").write_text("x = 1\n")
    _, fingerprint = _status(repo)
    done = _run(repo, "--expect", fingerprint, cwd=repo.parent)
    assert done.returncode == 0, done.stdout + done.stderr
    assert _cache(repo).read_text().strip() == fingerprint
    assert _status(repo) == (0, fingerprint)

    (repo / "backend" / "feature.py").write_text("x = 2\n")
    assert _status(repo)[0] == 3, "a byte changed: the proof no longer covers the tree"


def test_a_fingerprint_that_is_not_the_tree_checks_nothing(repo):
    (repo / "backend" / "feature.py").write_text("x = 1\n")
    done = _run(repo, "--expect", "0" * 64)
    assert done.returncode == 76
    assert not _cache(repo).exists()


def test_an_edit_while_the_suite_runs_is_not_certified(repo):
    (repo / "backend" / "test_edits.py").write_text(
        "from pathlib import Path\n"
        "def test_a_peer_edits_meanwhile():\n"
        "    Path(__file__).with_name('late.py').write_text('y = 1')\n"
    )
    done = _run(repo)
    assert done.returncode == 76, done.stdout + done.stderr
    assert "changed while the suite ran" in done.stderr
    assert not _cache(repo).exists()


def test_a_failing_suite_refuses_and_certifies_nothing(repo):
    (repo / "backend" / "test_broken.py").write_text("def test_broken():\n    assert False\n")
    done = _run(repo)
    assert done.returncode == 75
    assert not _cache(repo).exists()


#: A suite that starts a throwaway cluster under its temp root, says so, and hangs:
#: the shape of a suite stopped mid-run.
HANGS_WITH_A_CLUSTER = (
    "import time\n"
    "from pathlib import Path\n"
    "from tracker.platform.embedded_db import ensure_server\n"
    "def test_hangs(tmp_path):\n"
    "    ensure_server(tmp_path / 'pg', database='probe')\n"
    "    Path(__file__).with_name('started').write_text('yes')\n"
    "    time.sleep(600)\n"
)


def _start_hanging_suite(repo: Path) -> subprocess.Popen:
    pytest.importorskip("pixeltable_pgserver", reason="embedded Postgres wheel not installed")
    (repo / "backend" / "test_hangs.py").write_text(HANGS_WITH_A_CLUSTER)
    env = {
        **os.environ,
        "ROLEBAND_PREFLIGHT_PYTHON": sys.executable,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(BACKEND),
    }
    env.pop("ROLEBAND_SKIP_PREFLIGHT", None)
    process = subprocess.Popen(
        ["bash", str(repo / "deploy" / "preflight.sh")], cwd=repo, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    started = repo / "backend" / "started"
    deadline = time.monotonic() + 120
    while not started.exists():
        assert process.poll() is None, "the suite ended before it started its cluster"
        assert time.monotonic() < deadline, "the suite never started its cluster"
        time.sleep(0.2)
    return process


def _basetemp(repo: Path) -> Path:
    """Where the script runs its suite: outside the checkout, one per checkout.
    The ambient TMPDIR, as the script reads it: a longer one would put the test
    clusters' sockets past the path limit."""
    digest = hashlib.sha256(str(repo).encode()).hexdigest()[:12]
    return Path(os.environ.get("TMPDIR", "/tmp").rstrip("/")) / f"roleband-preflight-{digest}" / "pytest"


def test_a_stopped_suite_leaves_no_cluster_running(repo):
    from tracker.supervisor.residue import clusters_under

    process = _start_hanging_suite(repo)
    assert clusters_under(_basetemp(repo)), "the suite's cluster is running"
    os.killpg(process.pid, signal.SIGTERM)
    assert process.wait(timeout=60) == 75
    assert clusters_under(_basetemp(repo)) == []
    assert not _cache(repo).exists()


def test_the_suite_writes_nothing_into_the_checkout(repo):
    """A test may refuse to write into a repository (private evaluation
    artifacts do), so the suite's temp root lies outside it."""
    (repo / "backend" / "test_where.py").write_text(
        "from pathlib import Path\n"
        "def test_where(tmp_path):\n"
        f"    assert not tmp_path.resolve().is_relative_to(Path({str(repo.resolve())!r}))\n"
    )
    done = _run(repo)
    assert done.returncode == 0, done.stdout + done.stderr


def test_clear_residue_stops_a_killed_suite_s_cluster_and_runs_no_suite(repo):
    from tracker.supervisor.residue import clusters_under, stop_clusters

    process = _start_hanging_suite(repo)
    try:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=30)
        assert clusters_under(_basetemp(repo))
        (repo / "backend" / "test_hangs.py").write_text("def test_never():\n    raise AssertionError('a suite ran')\n")
        done = _run(repo, "--clear-residue", backend=True)
        assert done.returncode == 0, done.stdout + done.stderr
        assert clusters_under(_basetemp(repo)) == []
        assert not _cache(repo).exists()
    finally:
        stop_clusters(_basetemp(repo))


def test_a_killed_suite_s_cluster_is_stopped_by_the_next_run(repo):
    from tracker.supervisor.residue import clusters_under, stop_clusters

    process = _start_hanging_suite(repo)
    try:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=30)
        assert clusters_under(_basetemp(repo)), "a SIGKILL leaves the cluster running"

        # A tree that still needs proof, so the next run reaches its suite; its
        # test takes a temp dir, so pytest clears the temp root before it runs,
        # data directory and all, after which no `pg_ctl stop` can reach the server.
        (repo / "backend" / "test_hangs.py").write_text("def test_ok(tmp_path):\n    assert True\n")
        (repo / "backend" / "started").unlink()
        done = _run(repo, backend=True)
        assert done.returncode == 0, done.stdout + done.stderr
        assert clusters_under(_basetemp(repo)) == []
    finally:
        stop_clusters(_basetemp(repo))
