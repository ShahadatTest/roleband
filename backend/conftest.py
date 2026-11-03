"""Test-run settings pytest needs before it imports the test tree.

`pytest.ini` asks xdist for `-n auto`, which xdist resolves at startup, before
`tests/conftest.py` is loaded; only a conftest at the rootdir is read that early.
"""

from __future__ import annotations

import os

#: The fewest workers a run gets: what a four-CPU CI runner can give.
MIN_WORKERS = 4
#: The most workers a run gets; past it the workers contend more than they gain.
MAX_WORKERS = 10
#: Memory set aside per worker: each imports the app and holds its own scratch
#: database's connections, and the rest of the machine keeps the remainder.
GIB_PER_WORKER = 3
#: Cores left to the rest of the machine (Postgres included) during a run.
SPARE_CPUS = 4


def worker_budget(cpus: int, memory_gib: float) -> int:
    """Workers for `-n auto` on a machine with `cpus` cores and `memory_gib` of RAM."""
    return max(MIN_WORKERS, min(MAX_WORKERS, cpus - SPARE_CPUS, int(memory_gib // GIB_PER_WORKER)))


def _memory_gib() -> float:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (AttributeError, OSError, ValueError):
        return 0.0


def pytest_xdist_auto_num_workers(config) -> int | None:  # noqa: ARG001 - pytest hook signature
    # An explicit PYTEST_XDIST_AUTO_NUM_WORKERS is xdist's own setting; its
    # default hook reads it once this one declines.
    if os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS"):
        return None
    return worker_budget(os.cpu_count() or 1, _memory_gib())
