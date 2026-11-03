"""Test-run settings pytest needs before it imports the test tree.

`pytest.ini` asks xdist for `-n auto`, which xdist resolves at startup, before
`tests/conftest.py` is loaded; only a conftest at the rootdir is read that early.
`--shard` is here too, because an option has to be registered by then.
"""

from __future__ import annotations

import hashlib
import os

import pytest

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


def shard_of(test_file: str, total: int) -> int:
    """The shard, 1 to `total`, that runs every test in `test_file`.

    A file stays whole on one shard, so its module fixtures are built once. The
    hash is of the path alone, so every machine and every xdist worker agrees,
    and a new file moves no other file to a different shard.
    """
    digest = hashlib.sha256(test_file.encode()).digest()
    return int.from_bytes(digest[:8], "big") % total + 1


def _parse_shard(value: str) -> tuple[int, int]:
    index, sep, total = value.partition("/")
    if not (sep and index.isdigit() and total.isdigit() and 1 <= int(index) <= int(total)):
        raise pytest.UsageError(f"--shard takes INDEX/TOTAL with 1 <= INDEX <= TOTAL, not {value!r}")
    return int(index), int(total)


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--shard",
        metavar="INDEX/TOTAL",
        help="run only the test files that fall to shard INDEX of TOTAL; the TOTAL shards together run the whole selection",
    )


def pytest_configure(config) -> None:
    if config.getoption("--shard"):
        _parse_shard(config.getoption("--shard"))


#: How many tests the run selected before `--shard` cut it.
_SELECTED = pytest.StashKey[int]()


# Last, so `-m` and `-k` have already deselected: a shard cuts the selection.
@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items) -> None:
    value = config.getoption("--shard")
    if not value:
        return
    index, total = _parse_shard(value)
    config.stash[_SELECTED] = len(items)
    if hasattr(config, "workeroutput"):
        config.workeroutput["shard_selected"] = len(items)
    kept, dropped = [], []
    for item in items:
        (kept if shard_of(item.nodeid.split("::", 1)[0], total) == index else dropped).append(item)
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = kept


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error) -> None:  # noqa: ARG001 - xdist hook signature
    """Under xdist the workers collect; the controller learns their selection here."""
    selected = getattr(node, "workeroutput", {}).get("shard_selected", 0)
    node.config.stash[_SELECTED] = max(node.config.stash.get(_SELECTED, 0), selected)


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001 - pytest hook signature
    """A shard that none of the selection falls to has passed, and the run that
    selected nothing at all still says so."""
    if session.exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED and session.config.stash.get(_SELECTED, 0):
        session.exitstatus = pytest.ExitCode.OK
