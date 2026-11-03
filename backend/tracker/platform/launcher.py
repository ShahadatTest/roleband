"""Local installation identity and the installed engine's discovery file."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import stat
import tempfile
from pathlib import Path
from typing import Literal, TypedDict

MAX_REGISTRATION_BYTES = 8192
MAX_PLIST_BYTES = 32768


class InstallationIdentity(TypedDict):
    product: Literal["roleband"]
    instance: str
    api_origin: str
    version: str
    format: Literal[1]


def installation_identity(
    root: Path, *, api_host: str, api_port: int, version: str,
) -> InstallationIdentity:
    """Name a resolved checkout without publishing its filesystem path."""
    hosts = {
        "localhost": "localhost", "127.0.0.1": "127.0.0.1", "::1": "[::1]",
        "0.0.0.0": "127.0.0.1", "::": "[::1]",
    }
    host = hosts.get(api_host.lower())
    if host is None or not 1 <= api_port <= 65535:
        raise ValueError("Launcher discovery requires a loopback API address and a valid port")
    return {
        "product": "roleband",
        "instance": hashlib.sha256(os.fsencode(root.resolve())).hexdigest()[:24],
        "api_origin": f"http://{host}:{api_port}",
        "version": version,
        "format": 1,
    }


def registration_path(home: Path) -> Path:
    return home / ".roleband" / "launcher" / "installation.json"


def installed_checkout(root: Path, *, home: Path) -> bool:
    """Only the checkout named by the user's installed item may publish itself."""
    path = home / "Library" / "LaunchAgents" / "com.roleband.plist"
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            return False
        with path.open("rb") as handle:
            data = handle.read(MAX_PLIST_BYTES + 1)
        if len(data) > MAX_PLIST_BYTES:
            return False
        item = plistlib.loads(data)
        if not isinstance(item, dict) or item.get("Label") != "com.roleband" or "Program" in item:
            return False
        args = item.get("ProgramArguments")
        directory = item.get("WorkingDirectory")
        if not isinstance(args, list) or len(args) != 1 or not isinstance(args[0], str):
            return False
        if not isinstance(directory, str):
            return False
        program, working = Path(args[0]), Path(directory)
        return (
            program.is_absolute() and working.is_absolute()
            and program.resolve(strict=True) == (root / "deploy" / "roleband").resolve(strict=True)
            and working.resolve(strict=True) == (root / "backend").resolve(strict=True)
        )
    except (OSError, ValueError, RuntimeError, plistlib.InvalidFileException):
        return False


def _private_directory(home: Path) -> Path:
    for path in (home / ".roleband", home / ".roleband" / "launcher"):
        path.mkdir(mode=0o700, exist_ok=True)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("Launcher discovery directory must be owned by the current user")
    directory = registration_path(home).parent
    directory.chmod(0o700)
    return directory


def register_installation(root: Path, identity: InstallationIdentity, *, home: Path) -> bool:
    """Atomically refresh discovery only for the installed checkout."""
    if not installed_checkout(root, home=home):
        return False
    directory = _private_directory(home)
    target = registration_path(home)
    if target.is_symlink():
        raise ValueError("Launcher discovery file must not be a symbolic link")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".installation-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write((json.dumps(identity, sort_keys=True) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def unregister_installation(root: Path, *, home: Path) -> bool:
    """Remove only this checkout's registration, before its item is uninstalled."""
    if not installed_checkout(root, home=home):
        return False
    target = registration_path(home)
    try:
        for directory in (home / ".roleband", target.parent):
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                return False
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            return False
        with target.open("rb") as handle:
            data = handle.read(MAX_REGISTRATION_BYTES + 1)
        if len(data) > MAX_REGISTRATION_BYTES:
            return False
        identity = json.loads(data)
        expected = installation_identity(root, api_host="127.0.0.1", api_port=1, version="")
        if (
            not isinstance(identity, dict) or identity.get("product") != "roleband"
            or identity.get("format") != 1 or identity.get("instance") != expected["instance"]
        ):
            return False
        target.unlink()
    except (OSError, ValueError):
        return False
    return True
