"""`--shard INDEX/TOTAL` splits a run by test file, and the shards together run the
whole selection exactly once: CI runs the suite as two shards and merges nothing, so
a test that falls to no shard, or to both, would go unseen or run twice."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("backend_root_conftest_shard", BACKEND / "conftest.py")
assert spec and spec.loader
root_conftest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(root_conftest)

FILES = [f"test_{name}.py" for name in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta")]


@pytest.mark.parametrize("total", [1, 2, 3, 4])
def test_every_file_falls_to_one_shard_in_range_and_the_shards_share_the_files(total):
    paths = [f"tests/test_module_{n}.py" for n in range(400)]
    shards = Counter(root_conftest.shard_of(path, total) for path in paths)
    assert set(shards) == set(range(1, total + 1))
    # No shard carries much more than its share.
    assert max(shards.values()) < 1.25 * len(paths) / total


def test_a_file_keeps_its_shard_from_one_process_to_the_next():
    """Python's own `hash()` of a string changes per process; xdist workers and the
    two CI runners are separate processes and must all agree."""
    probe = "import sys; sys.path.insert(0, sys.argv[1]); import conftest; print(conftest.shard_of('tests/test_alpha.py', 7))"
    seen = {
        subprocess.run(
            [sys.executable, "-c", probe, str(BACKEND)],
            env={**os.environ, "PYTHONHASHSEED": seed}, capture_output=True, text=True, timeout=60, check=True,
        ).stdout.strip()
        for seed in ("1", "2", "3")
    }
    assert seen == {str(root_conftest.shard_of("tests/test_alpha.py", 7))}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A throwaway project with the real root conftest and a few test files, each
    test marked `odd` or not, so a run is quick and touches nothing of the suite."""
    shutil.copy(BACKEND / "conftest.py", tmp_path / "conftest.py")
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n    odd: an odd-numbered test\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    for name in FILES:
        (tests / name).write_text(
            "import pytest\n"
            + "".join(
                ("@pytest.mark.odd\n" if n % 2 else "") + f"def test_{n}():\n    pass\n"
                for n in range(3)
            )
        )
    return tmp_path


def _run(project: Path, *args: str) -> tuple[subprocess.CompletedProcess[str], set[str]]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")}
    report = project / f"report-{len(list(project.glob('report-*')))}.xml"
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", f"--junitxml={report}", *args],
        cwd=project, env=env, capture_output=True, text=True, timeout=120,
    )
    ran = set()
    if report.exists():
        for case in ET.parse(report).iter("testcase"):
            ran.add(f"{case.get('classname').replace('.', '/')}.py::{case.get('name')}")
    return done, ran


@pytest.mark.parametrize("workers", ["0", "2"])
def test_the_shards_run_the_whole_selection_once_with_every_file_whole(project, workers):
    whole, everything = _run(project, "-n", workers)
    assert whole.returncode == 0, whole.stdout + whole.stderr
    assert len(everything) == 3 * len(FILES)

    shards = {}
    for index in (1, 2, 3):
        done, ran = _run(project, "-n", workers, f"--shard={index}/3")
        # Under xdist a worker that cut a different shard fails collection outright.
        assert done.returncode == 0, done.stdout + done.stderr
        shards[index] = ran

    assert set().union(*shards.values()) == everything
    assert sum(len(ran) for ran in shards.values()) == len(everything)
    assert sum(1 for ran in shards.values() if ran) >= 2
    for index, ran in shards.items():
        files = {nodeid.split("::")[0] for nodeid in ran}
        assert all(root_conftest.shard_of(path, 3) == index for path in files)
        # A file is run whole by its shard, never part here and part there.
        assert all(sum(nodeid.startswith(path + "::") for nodeid in ran) == 3 for path in files)


def test_a_shard_of_a_marker_selection_is_that_shard_of_the_selection(project):
    """CI shards the `-m repo_wide` run too: each shard runs its own files' marked tests."""
    _, marked = _run(project, "-n", "0", "-m", "odd")
    first = _run(project, "-n", "0", "-m", "odd", "--shard=1/2")[1]
    second = _run(project, "-n", "0", "-m", "odd", "--shard=2/2")[1]
    assert marked and first | second == marked
    assert not first & second
    assert all(nodeid.endswith("::test_1") for nodeid in marked)


@pytest.mark.parametrize("workers", ["0", "2"])
def test_a_shard_with_none_of_the_selection_passes_and_an_empty_selection_does_not(project, workers):
    """A narrow selection can leave a shard nothing to run, and CI fails a step on
    pytest's "no tests collected"; a selection that is empty before the cut is a
    mistake either way and keeps that status."""
    target = "tests/test_alpha.py"
    owner = root_conftest.shard_of(target, 2)
    for index in (1, 2):
        done, ran = _run(project, "-n", workers, f"--shard={index}/2", target)
        assert done.returncode == 0, done.stdout + done.stderr
        assert len(ran) == (3 if index == owner else 0)
    done, ran = _run(project, "-n", workers, "-m", "not odd and odd", f"--shard={owner}/2")
    assert done.returncode == 5, done.stdout + done.stderr
    assert not ran


@pytest.mark.parametrize("value", ["0/2", "3/2", "2", "a/b", "1/0", "/2"])
def test_a_shard_outside_its_count_is_refused_before_anything_runs(project, value):
    done, ran = _run(project, "-n", "0", f"--shard={value}")
    assert done.returncode == 4, done.stdout + done.stderr
    assert "--shard takes INDEX/TOTAL" in done.stderr
    assert not ran
