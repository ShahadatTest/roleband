"""Two clocks: awake time for timeouts, and the gap that says the machine slept.

A laptop with its lid shut is asleep for hours. A timeout counted in wall-clock
time would end a healthy scan the moment the lid opens, so timeouts count awake
time: `CLOCK_UPTIME_RAW` on macOS, which stops while the machine sleeps, and
`CLOCK_MONOTONIC` elsewhere, which on Linux stops during suspend too. Named
explicitly rather than through `time.monotonic()`, whose source an interpreter
may change.
"""

from __future__ import annotations

import time

_AWAKE = getattr(time, "CLOCK_UPTIME_RAW", time.CLOCK_MONOTONIC)

#: Wall-clock time running ahead of awake time by more than this means a sleep.
SLEEP_GAP_SECONDS = 60.0


def awake_seconds() -> float:
    """Seconds the machine has been awake, from an arbitrary origin."""
    return time.clock_gettime(_AWAKE)


class SleepDetector:
    """Notices that the machine slept between two looks."""

    def __init__(self, wall: float | None = None, awake: float | None = None) -> None:
        self._wall = time.time() if wall is None else wall
        self._awake = awake_seconds() if awake is None else awake

    def slept(self, wall: float | None = None, awake: float | None = None) -> float:
        """Seconds asleep since the last look (0 when awake throughout)."""
        wall = time.time() if wall is None else wall
        awake = awake_seconds() if awake is None else awake
        gap = (wall - self._wall) - (awake - self._awake)
        self._wall, self._awake = wall, awake
        return gap if gap > SLEEP_GAP_SECONDS else 0.0
