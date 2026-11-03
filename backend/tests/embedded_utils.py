"""Shared helpers for tests that drive a real embedded cluster.

The psql runner is the production one (`run_psql`), not a re-implementation:
these tests exist to pin the embedded server's behavior, and a private test
copy of the runner would drift from it.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from tracker.platform.embedded_db import (
    EmbeddedServer,
    run_psql,
    stop_server,
)


def destroy(pgdata: Path) -> None:
    """Stop and delete a throwaway cluster.

    Stopped through `stop_server`, the production shutdown. Upstream's
    `get_server(pgdata, cleanup_mode="delete").cleanup()` cannot do it:
    `get_server` hands back the handle `ensure_server` already cached in this
    process, whose mode is `None`, so the mode asked for is ignored and
    `.cleanup()` returns before stopping anything, leaving the server running.
    """
    stop_server(pgdata)
    if pgdata.exists():
        shutil.rmtree(pgdata)


def running_clusters(root: Path) -> dict[Path, int]:
    """Postmasters running now with a data directory inside `root`, as pgdata -> PID.

    Read from the process table rather than from `postmaster.pid`: the question
    is whether a server is still running, and a lock file can outlive its server
    or vanish under a live one. Only a postmaster is started with `-D`, never its
    backends, so each server appears once. Containment is by path component, so
    `db2` is not inside `db`.
    """
    try:
        import psutil  # a pgserver dependency: without it no server was started
    except ImportError:
        return {}

    root = root.resolve()
    found: dict[Path, int] = {}
    for proc in psutil.process_iter(["pid", "name"]):
        if not (proc.info["name"] or "").startswith("postgres"):
            continue
        cmdline = _arguments(proc)
        if "-D" not in cmdline[:-1]:
            continue
        pgdata = Path(cmdline[cmdline.index("-D") + 1]).resolve()
        if pgdata.is_relative_to(root):
            found[pgdata] = proc.info["pid"]
    return found


def _arguments(proc) -> list[str]:
    """A process's command line, or none once it has exited.

    On macOS, reading the arguments of a process that exits meanwhile can raise
    SystemError or AccessDenied (EINVAL from KERN_PROCARGS2) instead of
    NoSuchProcess. A process still running is asked again rather than skipped:
    skipping a live postmaster would report a leaked server as stopped. One that
    stays AccessDenied belongs to another user, and none of those is a test's."""
    import psutil

    for attempt in range(3):
        try:
            return proc.cmdline()
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return []
        except (SystemError, psutil.AccessDenied):
            if not proc.is_running():
                return []
            if attempt == 2:
                if sys.exc_info()[0] is psutil.AccessDenied:
                    return []
                raise
    return []


def stop_clusters_under(root: Path) -> None:
    """Destroy every cluster still running inside `root`.

    The session-end backstop for a test whose own teardown never ran.
    Servers are found in the process table and only inside `root`, so this
    cannot reach another run's servers or the live cluster. Raises if any is
    still running afterwards: a server that survives teardown is a leak the run
    must report, not absorb.
    """
    failures = []
    for pgdata in sorted(running_clusters(root)):
        try:
            destroy(pgdata)
        except Exception as exc:  # noqa: BLE001 - stop the rest, then report every one
            failures.append(f"{pgdata}: {exc}")
    failures += [f"{pgdata}: still running" for pgdata in sorted(running_clusters(root))]
    if failures:
        raise RuntimeError("embedded Postgres outlived its test session:\n" + "\n".join(failures))


def psql(server: EmbeddedServer, statement: str) -> str:
    """One statement against a test server, raising on SQL error."""
    return run_psql(server.dsn(), server.bin_dir, statement)


def cluster_locale() -> str:
    """The locale a test's throwaway cluster is made with: the one the
    settings resolve, as the app's own cluster is. A host without
    `en_US.UTF-8` sets `ROLEBAND_DB_LOCALE=C.UTF-8` and every cluster, the
    tests' included, must honour it."""
    from tracker.config import get_settings
    from tracker.platform.embedded_db import DEFAULT_LOCALE

    return get_settings().db_locale or DEFAULT_LOCALE
