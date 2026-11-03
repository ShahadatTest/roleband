"""`deploy/preflight.sh` runs one suite at a time.

The scheduler and the directory sweep tick on the same interval. When both find
a dirty tree, two full suites share the machine, each runs past the cap, and
neither records a pass, so every later tick runs both again and no scan ever
starts. With the lock, the second tick skips and its next tick reuses the proof
the first one recorded.

Each case runs a COPY of the script in a scratch git checkout whose backend is
dirty. The checkout's `backend/.venv/bin/python` is a stand-in suite that logs
each start and sleeps, so a test can see how many suites ran and overlap two
preflights on purpose.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("shasum") is None,
    reason="preflight.sh needs git and shasum",
)


@pytest.fixture
def checkout(tmp_path):
    repo = tmp_path / "checkout"
    (repo / "deploy").mkdir(parents=True)
    shutil.copy2(ROOT / "deploy" / "preflight.sh", repo / "deploy" / "preflight.sh")
    (repo / "backend").mkdir()
    (repo / "backend" / "module.py").write_text("VALUE = 1\n")
    (repo / ".gitignore").write_text("backend/.venv/\ndata/\n")
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "base"]):
        subprocess.run(["git", *args], cwd=repo, env=env, check=True)
    (repo / "backend" / "module.py").write_text("VALUE = 2\n")

    suite = repo / "backend" / ".venv" / "bin" / "python"
    suite.parent.mkdir(parents=True)
    # Only a pytest run is a suite: the script also runs this interpreter to clear
    # what a killed suite left behind, which this stand-in answers with nothing.
    suite.write_text(
        '#!/bin/sh\n[ "$1 $2" = "-m pytest" ] || exit 0\necho "suite $$" >> "$SUITE_LOG"\n'
        'sleep "${SUITE_SECONDS:-0}"\nexit "${SUITE_RC:-0}"\n'
    )
    suite.chmod(0o755)
    (repo / "data").mkdir()
    env["SUITE_LOG"] = str(tmp_path / "suites.log")
    env.pop("ROLEBAND_SKIP_PREFLIGHT", None)
    return repo, env


def _start(repo: Path, env: dict, **extra: str) -> subprocess.Popen:
    return subprocess.Popen(
        ["bash", str(repo / "deploy" / "preflight.sh")],
        env={**env, **extra},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _run(repo: Path, env: dict, **extra: str) -> subprocess.CompletedProcess:
    proc = _start(repo, env, **extra)
    out, err = proc.communicate(timeout=60)
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


def _suites(env: dict) -> list[str]:
    log = Path(env["SUITE_LOG"])
    return log.read_text().splitlines() if log.exists() else []


def _lock(repo: Path) -> Path:
    return repo / "data" / "preflight.lock"


def test_a_live_holder_makes_the_next_preflight_skip_without_a_suite(checkout):
    repo, env = checkout
    os.symlink(str(os.getpid()), _lock(repo))

    result = _run(repo, env)

    # Busy, not a refusal: a supervisor reads 75 as a verdict on the tree.
    assert result.returncode == 77, result.stdout + result.stderr
    assert f"another preflight (pid {os.getpid()})" in result.stderr
    assert _suites(env) == []
    assert os.readlink(_lock(repo)) == str(os.getpid()), (
        "a skipping tick must leave the holder's lock"
    )


def test_a_lock_left_by_a_dead_holder_is_taken_over(checkout):
    repo, env = checkout
    gone = subprocess.Popen(["true"])
    gone.wait()
    os.symlink(str(gone.pid), _lock(repo))

    result = _run(repo, env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_suites(env)) == 1
    assert not os.path.lexists(_lock(repo)), "the holder releases the lock when it exits"


def test_two_preflights_at_once_run_one_suite_and_both_share_its_proof(checkout):
    repo, env = checkout

    first = _start(repo, env, SUITE_SECONDS="3")
    second = _start(repo, env, SUITE_SECONDS="3")
    codes = sorted(p.wait(timeout=60) for p in (first, second))

    assert len(_suites(env)) == 1
    assert codes == [0, 77]
    later = _run(repo, env)
    assert later.returncode == 0
    assert "using cached proof" in later.stdout
    assert len(_suites(env)) == 1, "the skipped tick's next run reuses the recorded pass"


def test_a_failing_suite_still_releases_the_lock(checkout):
    repo, env = checkout

    result = _run(repo, env, SUITE_RC="1")

    assert result.returncode == 75
    assert "SUITE FAILED" in result.stderr
    assert not os.path.lexists(_lock(repo))
    assert _run(repo, env).returncode == 0, "the next tick is not locked out"
