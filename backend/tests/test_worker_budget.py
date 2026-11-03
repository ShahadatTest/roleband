"""`-n auto` gives a run as many workers as the machine can spare, within bounds,
and an explicit count, as preflight sets, always wins."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("backend_root_conftest", BACKEND / "conftest.py")
assert spec and spec.loader
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)


@pytest.mark.parametrize(
    ("cpus", "memory_gib", "workers"),
    [
        (4, 16, 4),     # a hosted CI runner: what it always had
        (14, 48, 10),   # a large workstation: capped
        (64, 256, 10),  # a very large one: still capped
        (12, 24, 8),    # cores and memory both bind
        (16, 12, 4),    # memory binds below the floor: the floor
        (8, 16, 4),     # a laptop: never fewer than before
        (2, 0, 4),      # memory unknown: the floor
    ],
)
def test_the_budget_leaves_room_and_never_drops_below_the_old_default(cpus, memory_gib, workers):
    assert budget.worker_budget(cpus, memory_gib) == workers


def test_an_explicit_count_is_left_to_xdist(monkeypatch):
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "4")
    assert budget.pytest_xdist_auto_num_workers(config=None) is None
    monkeypatch.delenv("PYTEST_XDIST_AUTO_NUM_WORKERS")
    assert budget.pytest_xdist_auto_num_workers(config=None) == budget.worker_budget(
        os.cpu_count() or 1, budget._memory_gib()
    )


def test_a_run_started_like_preflight_uses_the_pinned_count():
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")}
    env["PYTEST_XDIST_AUTO_NUM_WORKERS"] = "3"
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
         f"{Path(__file__).name}::test_the_budget_leaves_room_and_never_drops_below_the_old_default"],
        cwd=BACKEND / "tests", env=env, capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert re.search(r"\b3 workers\b", done.stdout), done.stdout
