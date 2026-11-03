"""Small, atomic preparation facts shared by the packaged engine's processes."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from tracker.platform.launcher import InstallationIdentity


@dataclass(frozen=True)
class Preparation:
    database: str = "waiting"
    model: str = "waiting"
    service: str = "starting"
    downloaded_bytes: int = 0
    total_bytes: int = 0
    tier: str | None = None
    reason: str | None = None
    format: int = 1

    @property
    def ready(self) -> bool:
        return self.database == "ready" and self.service == "ready"


def snapshot(data: Path) -> dict[str, Any] | None:
    state = read(data)
    return asdict(state) if state else None


def payload(data: Path, identity: InstallationIdentity, *, packaged: bool = True) -> dict[str, Any]:
    state = asdict(read(data) or Preparation()) if packaged else None
    return {"status": "ok", "launcher": identity, "preparation": state}


def read(data: Path) -> Preparation | None:
    path = data / "launcher" / "preparation.json"
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 8192:
            return None
        value = Preparation(**json.loads(path.read_text()))
        if (
            type(value.format) is not int or value.format != 1
            or value.database not in {"waiting", "creating", "ready", "failed"}
            or value.model not in {"waiting", "downloading", "verifying", "ready", "unused", "failed"}
            or value.service not in {"starting", "ready", "failed"}
            or type(value.downloaded_bytes) is not int or type(value.total_bytes) is not int
            or not 0 <= value.downloaded_bytes <= value.total_bytes
            or value.tier not in {None, "fp32", "int8"}
            or not (value.reason is None or isinstance(value.reason, str))
        ):
            return None
        return value
    except (OSError, ValueError, TypeError):
        return None


def update(data: Path, **changes: Any) -> Preparation:
    directory = data / "launcher"
    for folder in (data, directory):
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = folder.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("Preparation directory must belong to this account")
    descriptor = os.open(directory / "preparation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        value = replace(read(data) or Preparation(), **changes)
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".preparation-", delete=False) as output:
            temporary = Path(output.name)
            try:
                output.write((json.dumps(asdict(value)) + "\n").encode())
                output.flush()
                os.replace(temporary, directory / "preparation.json")
            finally:
                temporary.unlink(missing_ok=True)
        return value
    finally:
        os.close(descriptor)
