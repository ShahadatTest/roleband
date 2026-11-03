"""What a killed test suite leaves behind, and its removal.

    python -m tracker.supervisor.residue <basetemp>

Killing a suite's process group does not end everything it started. A test's
throwaway cluster is started by `pg_ctl`, which detaches the server into a
session of its own, so it outlives the group; and each worker's scratch database
`roleband_test_<pid>` stays in the configured server, because only the worker's
own session end drops it.

The preflight runs its suite with a temp root of its own (`--basetemp`), so every
cluster under that root is the preflight's to stop, whoever else is testing on
this machine. A scratch database is dropped only when the process its name
carries is gone: a suite still running elsewhere keeps its own.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

#: `tests/conftest.py` names each worker's scratch database after its PID.
TEST_DATABASE = re.compile(r"roleband_test_(\d+)")

_PS_ENV = {"LC_ALL": "C", "PATH": "/bin:/usr/bin"}


def _ps(*args: str) -> str:
    try:
        done = subprocess.run(  # noqa: S603 - fixed system tool
            ["ps", *args], capture_output=True, text=True, timeout=5, check=False, env=_PS_ENV
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def pid_alive(pid: int) -> bool:
    return bool(_ps("-o", "pid=", "-p", str(pid)).strip())


def clusters_under(root: Path) -> list[Path]:
    """Data directories of the postmasters running now inside `root`.

    Read from the process table: a `postmaster.pid` can outlive its server. Only
    a postmaster is started with `-D`, never its backends. Containment is by path
    component, so `tmp2` is not inside `tmp`."""
    root = root.resolve()
    found = set()
    for line in _ps("-axo", "command=").splitlines():
        words = line.split()
        if not words or not Path(words[0]).name.startswith("postgres") or "-D" not in words[:-1]:
            continue
        pgdata = Path(words[words.index("-D") + 1]).resolve()
        if pgdata.is_relative_to(root):
            found.add(pgdata)
    return sorted(found)


def stop_clusters(root: Path) -> list[str]:
    """Stop every cluster under `root`; the failures, one line each."""
    from tracker.platform.embedded_db import stop_server

    failures = []
    for pgdata in clusters_under(root):
        try:
            stop_server(pgdata)
        except Exception as error:  # noqa: BLE001 - stop the rest, then report
            failures.append(f"{pgdata}: {error}")
    return failures


async def drop_dead_test_databases(url: URL, *, alive: Callable[[int], bool] = pid_alive) -> list[str]:
    """Drop every `roleband_test_<pid>` database whose process is gone; the names
    dropped. Without FORCE: a database something still uses is left for later."""
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    dropped = []
    try:
        async with admin.connect() as conn:
            names = (await conn.execute(text("SELECT datname FROM pg_database"))).scalars().all()
            for name in names:
                match = TEST_DATABASE.fullmatch(name)
                if match is None or alive(int(match.group(1))):
                    continue
                try:
                    await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
                except Exception:  # noqa: BLE001 - in use or already gone: next time
                    continue
                dropped.append(name)
    finally:
        await admin.dispose()
    return dropped


def clean(root: Path, url: URL | None) -> dict[str, list[str]]:
    """Stop the clusters under `root`, remove it once nothing runs there, and drop
    dead scratch databases on the server at `url` (skipped when None)."""
    failures = stop_clusters(root)
    if root.exists() and not clusters_under(root):
        shutil.rmtree(root, ignore_errors=True)
    dropped: list[str] = []
    if url is not None:
        try:
            dropped = asyncio.run(drop_dead_test_databases(url))
        except Exception as error:  # noqa: BLE001 - a server that is down holds nothing to drop now
            failures.append(f"scratch databases: {error}")
    return {"failures": failures, "dropped": dropped}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m tracker.supervisor.residue <basetemp>", file=sys.stderr)
        return 2
    try:
        from tracker.config import get_settings

        url: URL | None = make_url(get_settings().database_url)
    except Exception:  # noqa: BLE001 - no server configured: only the clusters
        url = None
    outcome = clean(Path(args[0]), url)
    for name in outcome["dropped"]:
        print(f"roleband/preflight: dropped the scratch database {name} of a suite that is gone")
    for line in outcome["failures"]:
        print(f"roleband/preflight: could not clean up {line}", file=sys.stderr)
    return 1 if outcome["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
