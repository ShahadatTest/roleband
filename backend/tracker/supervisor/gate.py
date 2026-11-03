"""The preflight gate: whether this exact tree is proven safe to run unattended.

`deploy/preflight.sh` owns the rule (what counts as dirt, the fingerprint, the
cached proof); this module only asks it, with `--status`, which never runs the
suite. One implementation, so the gate and the proof cannot disagree.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tracker.platform.paths import PACKAGED
from tracker.supervisor.due import Gate

SCRIPT = Path("deploy") / "preflight.sh"

#: `preflight.sh` exit codes.
PROVEN = 0
NOT_YET = 3
REFUSED = 75
TREE_MOVED = 76
#: Another preflight holds the script's lock: no verdict on this tree.
BUSY = 77


@dataclass(frozen=True)
class Reading:
    proven: bool
    #: The tree's fingerprint; None for a clean, skipped or unversioned tree.
    fingerprint: str | None


def read(repo_root: Path) -> Reading:
    """Ask the script. A script that cannot answer proves nothing."""
    if PACKAGED:
        return Reading(proven=True, fingerprint=None)
    try:
        done = subprocess.run(  # noqa: S603 - our own script, fixed arguments
            ["bash", str(repo_root / SCRIPT), "--status"],
            cwd=repo_root, capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return Reading(proven=False, fingerprint=None)
    last = (done.stdout.strip().splitlines() or [""])[-1].strip()
    fingerprint = last if len(last) == 64 else None
    return Reading(proven=done.returncode == PROVEN, fingerprint=fingerprint)


class Tracker:
    """Turns readings and preflight outcomes into the gate the due function reads.

    In memory: after a supervisor restart an unproven tree is checked once more,
    which costs one suite run and loses nothing."""

    def __init__(self) -> None:
        self._unproven: str | None = None
        self._since: datetime | None = None
        self._failed: str | None = None

    def observe(self, reading: Reading, now: datetime, *, checking: bool) -> Gate:
        if reading.proven:
            self._unproven = self._since = None
            return Gate.PASSED
        if reading.fingerprint != self._unproven:
            self._unproven, self._since = reading.fingerprint, now
        if checking:
            return Gate.RUNNING
        if reading.fingerprint is not None and reading.fingerprint == self._failed:
            return Gate.FAILED
        return Gate.UNKNOWN

    @property
    def unproven(self) -> str | None:
        return self._unproven

    def changed_since(self) -> datetime | None:
        """Since when the current unproven tree has stood, for the preflight's
        settle time; None when there is nothing to check. A tree that already
        failed is not checked again until it changes."""
        if self._unproven is None or self._unproven == self._failed:
            return None
        return self._since

    def finished(self, fingerprint: str | None, exit_code: int | None) -> None:
        """Record a preflight run's verdict on the tree it was asked to check."""
        if fingerprint is not None and exit_code == REFUSED:
            self._failed = fingerprint


def clear_residue(repo_root: Path, python: str) -> None:
    """What a stopped suite left behind, cleared by the script that ran it
    (`--clear-residue`): its temp root is the script's to name."""
    if PACKAGED:
        return
    env = {**os.environ, "ROLEBAND_PREFLIGHT_PYTHON": python}
    try:
        subprocess.run(  # noqa: S603 - our own script, fixed arguments
            ["bash", str(repo_root / SCRIPT), "--clear-residue"],
            cwd=repo_root, env=env, capture_output=True, text=True, timeout=300, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass
