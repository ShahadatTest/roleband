"""Async min-delay rate limiting, shareable per backend scope.

Within a process, `RateLimiterPool` gives every consumer of one backend scope
one pacer. Across processes it cannot: the scheduler (and the manual sync it
also runs), the directory pass and role discovery each build their own pool, and
the directory reads Greenhouse, Workable, Ashby, SmartRecruiters and Lever under
the very scope names the scheduler paces. Two pools would mean up to twice a
host's allowance whenever both ran.

`enable_shared_pacing(directory)` closes that: every pool built afterwards in
the process reserves its slots in one small file per scope, so the per-scope
`min_delay` is the COMBINED bound for every process that enabled it. Only the
provider-facing entrypoints enable it; tests and ad-hoc scripts stay
process-local and never touch the live pacing state.

A reservation holds the file lock for a read and a write, never for the wait,
so neither process blocks behind the other's work: requests interleave at the
shared rate, first come first served. A manual sync started during a directory
pass therefore shares the host's allowance with it rather than waiting for the
pass to end.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

#: A stored slot further ahead than this is stale (a clock step, or a file left
#: by a run whose clock we do not share), never a queue to wait behind.
STALE_RESERVATION_SECONDS = 300.0

_shared_dir: Path | None = None


def enable_shared_pacing(directory: Path | None) -> None:
    """Pace every pool built afterwards in this process through `directory`."""
    global _shared_dir
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)
    _shared_dir = directory


class SharedSlot:
    """The next free request instant for one scope, shared by every process.

    Wall-clock seconds, because `time.monotonic()` is not promised to be
    comparable across processes (and restarts from zero at boot).
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def reserve(self, min_delay: float, now: float) -> float:
        """Claim the earliest instant at least `min_delay` after the last claim."""
        with open(self._path, "a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                handle.seek(0)
                try:
                    last = float(handle.read().decode() or "-inf")
                except ValueError:
                    last = float("-inf")
                if last - now > STALE_RESERVATION_SECONDS:
                    last = float("-inf")
                start = max(now, last + min_delay)
                handle.seek(0)
                handle.truncate()
                handle.write(repr(start).encode())
                handle.flush()
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
        return start


def _slot_path(directory: Path, scope: str) -> Path:
    """A readable, collision-free file name for any scope (`workday:host|site`)."""
    readable = re.sub(r"[^A-Za-z0-9._-]+", "_", scope)[:60]
    digest = hashlib.sha256(scope.encode()).hexdigest()[:12]
    return directory / f"{readable}-{digest}.slot"


class RateLimiter:
    """Simple min-delay pacer for one backend system."""

    def __init__(
        self,
        min_delay: float,
        *,
        shared: SharedSlot | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._min_delay = min_delay
        self._last = float("-inf")
        self._lock = asyncio.Lock()
        self._shared = shared
        self._clock = clock or (time.time if shared is not None else time.monotonic)
        self._sleep = sleep or asyncio.sleep

    async def wait(self) -> None:
        async with self._lock:
            if self._min_delay <= 0:
                return
            now = self._clock()
            if self._shared is not None:
                start = self._shared.reserve(self._min_delay, now)
            else:
                start = max(now, self._last + self._min_delay)
            if start > now:
                await self._sleep(start - now)
            self._last = max(start, self._clock())


class RateLimiterPool:
    """Shares one pacer per backend scope for the lifetime of a run.

    Different backends can make progress concurrently. Consumers hosted by the
    same backend (for example, two Greenhouse boards) share a pacer, so adding
    a consumer cannot multiply that backend's request rate. With shared pacing
    enabled, the same holds across processes.
    """

    def __init__(self, shared_dir: Path | None = None) -> None:
        self._limiters: dict[str, RateLimiter] = {}
        self._shared_dir = shared_dir if shared_dir is not None else _shared_dir

    def get(self, scope: str, min_delay: float) -> RateLimiter:
        limiter = self._limiters.get(scope)
        if limiter is None:
            shared = (
                SharedSlot(_slot_path(self._shared_dir, scope))
                if self._shared_dir is not None
                else None
            )
            limiter = RateLimiter(min_delay, shared=shared)
            self._limiters[scope] = limiter
        return limiter
