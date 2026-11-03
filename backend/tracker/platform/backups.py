"""Verified logical backups using the embedded server's matching client tools."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from tracker.platform.embedded_db import EmbeddedServer, run_psql


class BackupError(RuntimeError):
    """No verified backup could be published."""


def _run(server: EmbeddedServer, tool: str, *args: str) -> None:
    result = subprocess.run(
        [str(server.tool(tool)), *args], capture_output=True, text=True, timeout=1800,
    )
    if result.returncode:
        raise BackupError(f"{tool} failed: {result.stderr.strip()[:500]}")


def dump_database(server: EmbeddedServer, directory: Path, *, now: datetime | None = None) -> Path:
    """Publish only a fully readable dump, retain 14 dailies and every monthly.

    An empty jobs table may create a first baseline, but cannot replace evidence
    that a populated database existed. The secret key stays outside the archive.
    """
    monthly = directory / "monthly"
    for folder in (directory, monthly):
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        if folder.is_symlink():
            raise BackupError(f"backup directory is a symbolic link: {folder}")
        folder.chmod(0o700)
    for path in directory.rglob("*.dump"):
        if path.is_symlink():
            raise BackupError(f"backup is a symbolic link: {path}")
        path.chmod(0o600)
    rows = int(run_psql(server.dsn(), server.bin_dir, "SELECT count(*) FROM jobs"))
    if rows == 0 and (any(directory.glob("*.dump")) or any(monthly.glob("*.dump"))):
        raise BackupError("jobs table is empty but prior backups exist; refusing to supersede them")
    when = now or datetime.now().astimezone()
    stamp = when.strftime("%Y%m%d_%H%M%S_%f")
    final = directory / f"roleband_{stamp}.dump"
    fd, name = tempfile.mkstemp(dir=directory, prefix=".backup-", suffix=".partial")
    os.close(fd)
    staged = Path(name)
    try:
        _run(server, "pg_dump", server.dsn(), "-Fc", "-f", str(staged))
        _run(server, "pg_restore", "--file", os.devnull, str(staged))
        staged.replace(final)
        if not any(monthly.glob(f"roleband_{when:%Y%m}*.dump")):
            fd, name = tempfile.mkstemp(dir=monthly, prefix=".backup-", suffix=".partial")
            os.close(fd)
            copy = Path(name)
            try:
                shutil.copyfile(final, copy)
                copy.replace(monthly / final.name)
            finally:
                copy.unlink(missing_ok=True)
        for old in sorted(directory.glob("roleband_*.dump"), reverse=True)[14:]:
            old.unlink()
        return final
    finally:
        staged.unlink(missing_ok=True)
