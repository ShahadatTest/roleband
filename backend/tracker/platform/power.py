"""Whether this machine is properly awake, and on mains power.

A laptop with its lid shut is not simply asleep. macOS wakes it for a few
seconds every quarter of an hour to do maintenance (a dark wake: the CPU and
the network run, the display and audio do not), then puts it back to sleep.
launchd starts our agents in them, so a sync begun in one reads for seconds,
freezes, and reads for seconds more a quarter of an hour later: the run
stretches across hours of sleep, a read that crosses a sleep cannot close a
posting, and the run holds the run lock until after the lid opens. Nobody
sees a result while the lid is shut, so background reads start only in a full
wake (`Power.dark_wake`).

The scan of the whole directory reads for hours a day. On battery that
is the user's battery, so it waits for mains power (`Power.on_battery`); the
companies the user follows are read on battery too.

The schedule plan also reads `pmset -g log` once, to seed when the
machine has usually been on (`full_wake_intervals`): a full wake or a boot
begins an interval, a sleep or a dark wake ends it.

Both answers come from `pmset`, asked afresh each time (it answers in a few
milliseconds). A machine without it (Linux) or an answer this cannot read
counts as awake on mains power: a probe that fails never stops collection.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime

#: Why background reads wait, as the agents log and report it.
WAITING_FOR_FULL_WAKE = "waiting for a full wake: the machine is awake only for maintenance"
WAITING_FOR_MAINS = "waiting for mains power: the machine is on battery"

#: `pmset -g systemstate`: "Current System Capabilities are: CPU Graphics Audio Network".
_CAPABILITIES = re.compile(r"Current System Capabilities are:([^\n]*)")
#: `pmset -g batt`: "Now drawing from 'AC Power'" (or 'Battery Power', 'UPS Power').
_DRAWING_FROM = re.compile(r"Now drawing from '([^']+)'")
_MAINS = "AC Power"


@dataclass(frozen=True)
class Power:
    """One reading of the machine."""

    #: Awake for maintenance only: the CPU runs, the display does not.
    dark_wake: bool
    #: Drawing from anything but mains power (a battery, or a UPS).
    on_battery: bool

    def wait_reason(self, *, mains: bool = False) -> str | None:
        """Why background reads should not start now, or None if they may.

        `mains`: the work also waits for mains power (the directory scan)."""
        if self.dark_wake:
            return WAITING_FOR_FULL_WAKE
        if mains and self.on_battery:
            return WAITING_FOR_MAINS
        return None


def dark_wake_in(systemstate: str | None) -> bool:
    """A dark wake is the CPU without graphics, as `IOPMIsADarkWake` reads it.
    No readable capability line is no dark wake."""
    match = _CAPABILITIES.search(systemstate or "")
    if match is None:
        return False
    capabilities = set(match.group(1).split())
    return "CPU" in capabilities and "Graphics" not in capabilities


def on_battery_in(batt: str | None) -> bool:
    """Drawing from anything but mains power. No readable source is mains."""
    match = _DRAWING_FROM.search(batt or "")
    return match is not None and match.group(1) != _MAINS


def _pmset(*args: str) -> str | None:
    executable = shutil.which("pmset")
    if executable is None:
        return None
    try:
        done = subprocess.run(
            [executable, *args], capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def read_power() -> Power:
    """This machine, now."""
    return Power(
        dark_wake=dark_wake_in(_pmset("-g", "systemstate")),
        on_battery=on_battery_in(_pmset("-g", "batt")),
    )


#: One `pmset -g log` event: "YYYY-MM-DD HH:MM:SS +0200 Wake <pad>\t<details>".
#: The type is the padded column before the tab, so "Wake Requests" is its own
#: type and never read as a wake.
_LOG_EVENT = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [+-]\d{4}) (\S(?:.*?\S)?)\s*\t"
)
#: Types that begin a full wake: a wake with the display ("Wake", which macOS
#: also writes for "DarkWake to FullWake") and a boot ("Start", powerd started).
_FULL_WAKE_BEGINS = frozenset({"Wake", "Start"})
#: Types that end one. A dark wake is maintenance: the machine is
#: not in use, so it ends a full wake rather than continuing it.
_FULL_WAKE_ENDS = frozenset({"Sleep", "DarkWake"})


def full_wake_intervals(log: str | None, now: datetime) -> list[tuple[datetime, datetime]]:
    """When this machine was properly awake, as `pmset -g log` recorded it.

    macOS keeps about a week of this log. Each interval runs from a full wake
    (or a boot) to the next sleep or dark wake; one still open at the end of the
    log runs to `now`. Before the log's first event the state is unknown, and
    unknown is not awake. No log (Linux, or pmset refused) is no intervals.
    """
    intervals: list[tuple[datetime, datetime]] = []
    began: datetime | None = None
    for line in (log or "").splitlines():
        match = _LOG_EVENT.match(line)
        if match is None:
            continue
        kind = match.group(2)
        if kind not in _FULL_WAKE_BEGINS and kind not in _FULL_WAKE_ENDS:
            continue
        at = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S %z")
        if kind in _FULL_WAKE_BEGINS:
            began = began or at
        elif began is not None:
            if at > began:
                intervals.append((began, at))
            began = None
    if began is not None and now > began:
        intervals.append((began, now))
    return intervals


def read_wake_log() -> str | None:
    """`pmset -g log`, or None where there is none. Tens of thousands of lines,
    so it is read once, when there is no history of our own yet."""
    executable = shutil.which("pmset")
    if executable is None:
        return None
    try:
        done = subprocess.run(
            [executable, "-g", "log"], capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None
