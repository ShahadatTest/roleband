"""Installed release metadata from the checkout's version and changelog."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tracker.platform.paths import REPO_ROOT, VERSION_FILE

_VERSION = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?", re.ASCII)


def validate_version(version: object) -> str:
    if not isinstance(version, str) or len(version) > 128 or not _VERSION.fullmatch(version):
        raise ValueError("The release version must be a semantic version")
    pre = version.split("+", 1)[0].partition("-")[2]
    if any(part.isdigit() and len(part) > 1 and part.startswith("0") for part in pre.split(".")):
        raise ValueError("Numeric prerelease identifiers cannot have leading zeroes")
    return version


def release_version(path: Path = VERSION_FILE) -> str:
    return validate_version(json.loads(path.read_text(encoding="utf-8"))["version"])


UNKNOWN_VERSION = "0.0.0+unknown"


def running_version(path: Path = VERSION_FILE) -> str:
    """The version a running process reports.

    Every entry point imports it, so a conflicted or half-edited package file must not stop
    the supervisor, the API and the CLI; the dashboard build reports that fault on its own.
    Releasing reads `release_version`, which still refuses it."""
    try:
        return release_version(path)
    except (OSError, ValueError, KeyError, TypeError):
        return UNKNOWN_VERSION


def release_notes(version: str, path: Path = REPO_ROOT / "CHANGELOG.md") -> str | None:
    if not _VERSION.fullmatch(version):
        return None
    try:
        with path.open("rb") as handle:
            data = handle.read(1048577)
        if len(data) > 1048576:
            return None
        lines = data.decode("utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    heading = re.compile(r"^## \[" + re.escape(version) + r"\](?: - \d{4}-\d{2}-\d{2})?\s*$")
    start = next((index + 1 for index, line in enumerate(lines) if heading.fullmatch(line)), None)
    if start is None:
        return None
    end = next((index for index in range(start, len(lines)) if lines[index].startswith("## ")), len(lines))
    notes = "\n".join(lines[start:end]).strip()
    return notes if notes and len(notes.encode("utf-8")) <= 65536 else None
