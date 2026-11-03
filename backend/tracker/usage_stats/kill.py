"""Environment switches that turn usage sharing off, whatever the user stored.

The environment can only turn sharing OFF: unlike `ai_egress`, there is no env
default that shares. Read live from `os.environ` on every check (not through
the cached `Settings`), so a switch set for one run is honoured by that run.

`ROLEBAND_NO_USAGE_STATS` is the product's own switch. `DO_NOT_TRACK` is the
cross-tool convention (consoledonottrack.com) and `CI` the one every CI service
sets; both are deliberately unprefixed (config.py's prefix rule names this
exception). launchd agents do not inherit a shell's environment, so a
machine-wide switch belongs in `backend/.env`, which `blocked_by` also reads.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

# `backend/.env`, the file `Settings` reads, for agents launchd starts.
from tracker.config import ENV_FILE

PRODUCT_SWITCH = "ROLEBAND_NO_USAGE_STATS"
SWITCHES = (PRODUCT_SWITCH, "DO_NOT_TRACK", "CI")

_FALSE = frozenset({"", "0", "false", "no", "off"})


def _dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        key, sep, raw = line.strip().partition("=")
        if sep and key in SWITCHES:
            values[key] = raw.strip().strip("\"'")
    return values


def blocked_by(environ: Mapping[str, str] | None = None, env_file: Path | None = None) -> str | None:
    """The first switch that is on, or None when sharing may proceed.

    `environ` defaults to the live `os.environ`, `env_file` to `ENV_FILE`."""
    sources: list[Mapping[str, str]] = [os.environ if environ is None else environ]
    path = ENV_FILE if env_file is None else env_file
    if path is not None:
        sources.append(_dotenv(path))
    for name in SWITCHES:
        for source in sources:
            value = source.get(name)
            if value is not None and value.strip().lower() not in _FALSE:
                return name
    return None
