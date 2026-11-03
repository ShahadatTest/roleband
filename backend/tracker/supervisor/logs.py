"""Bounded log files that a child writes to directly.

A supervised child is detached: it outlives a supervisor restart. So it never
writes through a pipe to the supervisor, whose death would end it with SIGPIPE.
It writes to a file opened for append, and the supervisor rotates that file by
copying it aside and truncating it; the child's appends continue at the new end.
The few lines written between the copy and the truncate are lost, which is the
price of rotating a file another process holds open.
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

#: The largest an active log may grow before it is rotated.
LIMIT_BYTES = 10 * 1024 * 1024
#: How much of the supervisor's own launchd stream is kept at start.
STREAM_KEEP_BYTES = 1024 * 1024


def shared(data_dir: Path, pgdata: Path) -> tuple[Path, ...]:
    """The logs the supervisor bounds that belong to no job: its own, the alerts
    the health job appends one line at a time, and the embedded Postgres server's,
    which `pg_ctl -l` opens for append (absent with an external server)."""
    return (data_dir / "logs" / "supervisor.log", data_dir / "alerts.log", pgdata / "log")


def rotated(path: Path) -> Path:
    return path.with_name(path.name + ".1")


def open_append(path: Path) -> int:
    """A file descriptor for appending to `path`, readable by its owner only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)


def rotate(path: Path, limit: int = LIMIT_BYTES) -> bool:
    """Copy `path` to `<path>.1` and empty it when it is over `limit`. One
    rotated copy is kept, so a log never takes more than twice its limit."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return False
    if size <= limit:
        return False
    shutil.copyfile(path, rotated(path))
    os.truncate(path, 0)
    return True


def trim(path: Path, keep: int = STREAM_KEEP_BYTES) -> bool:
    """Keep only the last `keep` bytes of `path`.

    For the file launchd points the supervisor's stdout and stderr at, opened
    write-only and appended to forever: launchd's descriptors append at the new
    end once the file is cut."""
    try:
        info = path.stat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_size <= keep:
        return False
    with open(path, "rb+") as stream:
        stream.seek(info.st_size - keep)
        tail = stream.read()
        stream.seek(0)
        stream.write(tail)
        stream.truncate()
    return True
