"""Progress-based source liveness: a sliding stall bound plus a hard ceiling.

The problem this closes: a fixed per-source time budget cannot tell *slow but
working* from *hung*. A board that legitimately needs 1300s and a source that
returns nothing at all both hit a 300s cap, so the cap truncates healthy sources
every run while a genuine hang survives to the end of its allowance.

A source is alive while it makes progress. `SourceClock` holds two bounds:

    stall    sliding  — pushed forward by `progress()`; expiry means silence
    ceiling  fixed    — never moves; expiry means "we stopped it", not "it broke"

That distinction is the point. Silence is a source pathology and must count
against the source (a `degraded` run resets every posting's absence count);
hitting *our* ceiling while still producing is our own
threshold talking, and must not. `at` collapses both to the single monotonic
timestamp every existing deadline consult-point already reads, so the bound
threads through the transports unchanged.

Two rules callers must honor, or the stall bound misreads healthy work:

* **Deliberate waits are not silence.** Time we chose to spend — rate-limiter
  pacing, retry backoff — must be followed by `progress()`. Otherwise a source
  politely obeying `Retry-After` is judged dead for good behavior.
* **Only completed work counts.** A response received or an item yielded is
  progress; *issuing* a request is not. Otherwise a source failing every
  request forever never looks stalled.

`clock` is injectable so tests need no patched module globals, matching the
"pass the bound in, keep the decision pure" style used by the outcome and
closure-scope helpers.

L0 by construction: this module imports nothing from `tracker`, so the
import-linter layer contract holds and any transport may depend on it.
"""

from __future__ import annotations

import time
from collections.abc import Callable

__all__ = [
    "STALLED",
    "BOUNDED",
    "SourceClock",
    "SuspensionMonitor",
    "deadline_of",
    "bound_fired",
]

#: The source went silent — its own pathology; counts against the source.
STALLED = "stalled"
#: Our ceiling expired while it was still producing — our bound; counts nothing
#: against the source.
BOUNDED = "bounded"


class SourceClock:
    """Sliding stall deadline plus an immutable hard ceiling for one source."""

    __slots__ = ("_stall_seconds", "_hard", "_clock", "_stall_at")

    def __init__(
        self,
        *,
        stall_seconds: float,
        hard_deadline: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        :param stall_seconds: how long a source may go silent before it is stalled.
        :param hard_deadline: monotonic timestamp this source must stop by regardless
            of progress. Bounds a pathologically slow trickle, which no amount of
            progress-tracking can catch.
        :param clock: monotonic time source; injected in tests.
        """
        self._stall_seconds = max(0.0, stall_seconds)
        self._hard = hard_deadline
        self._clock = clock
        self.progress()

    @property
    def at(self) -> float:
        """The effective deadline: whichever bound bites first.

        This is what `deadline_allows` and the per-item check read, so both
        bounds are enforced by the same deadline checks.
        """
        return min(self._stall_at, self._hard)

    @property
    def hard_deadline(self) -> float:
        return self._hard

    def progress(self) -> None:
        """Record a unit of completed work; slides the stall bound only.

        Never moves the ceiling — a source that keeps producing still stops at
        `hard_deadline`.
        """
        self._stall_at = self._clock() + self._stall_seconds

    def stalled(self) -> bool:
        """Silent too long: a source pathology (counts against the source)."""
        now = self._clock()
        return now >= self._stall_at and now < self._hard

    def exhausted(self) -> bool:
        """Hit our ceiling: our bound, not the source's fault (counts nothing against it)."""
        return self._clock() >= self._hard

    def expired(self) -> bool:
        return self._clock() >= self.at

    def remaining(self) -> float:
        """Seconds until the effective deadline; never negative.

        Callers clip blocking operations to this so no single `await` can
        outlive the bound — the cooperative check cannot interrupt a coroutine
        that is already parked inside one.
        """
        return max(0.0, self.at - self._clock())

    def allows(self, backoff: float) -> bool:
        """Whether sleeping ``backoff`` still fits inside the effective deadline.

        Answered against *this* clock rather than a caller-read one: the clock is
        injectable, so a caller comparing against `time.monotonic()` would be
        reading a different timeline than the bound it is checking.
        """
        return self._clock() + backoff <= self.at


class SuspensionMonitor:
    """How much wall-clock time passed that the monotonic clock never saw.

    `time.monotonic()` does not advance while the host is suspended — macOS
    sleep, a hypervisor pause, a SIGSTOP — but the wall clock does. The gap
    between the two elapsed times is therefore time during which this process
    was not running at all, and neither was the network stack it had sockets on.

    Why this needs measuring rather than assuming: a suspension does not raise,
    it lands as a *transport error on the far side of it*. Every connection open
    across the gap is dead on resume, so the first read after wake returns EOF
    and surfaces as `httpx.ReadError` with an empty message — indistinguishable,
    at the call site, from the source having broken. Runs that record such a
    `ReadError` sit on gaps of minutes and clean runs on gaps of seconds, so the
    gap is what separates "our laptop slept" from "the source is unwell".

    Portable by construction: CLOCK_MONOTONIC on Linux and `mach_absolute_time`
    on macOS both exclude suspend, so the same subtraction reads the same thing.

    The one false positive is a wall-clock *step* (an NTP correction large
    enough to clear the threshold). That is rare, and it is deliberately the
    safe direction to be wrong in: a false suspension costs one run of
    judgement rather than counting a false pathology against a healthy source.
    """

    __slots__ = ("_threshold", "_monotonic", "_wall", "_mono_started", "_wall_started")

    def __init__(
        self,
        *,
        threshold_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        """
        :param threshold_seconds: gap at or above which the host counts as suspended.
        :param monotonic: suspend-excluding clock; injected in tests.
        :param wall: suspend-including clock; injected in tests.
        """
        self._threshold = max(0.0, threshold_seconds)
        self._monotonic = monotonic
        self._wall = wall
        self._mono_started = monotonic()
        self._wall_started = wall()

    def suspended_seconds(self) -> float:
        """Wall time unaccounted for by the monotonic clock; never negative.

        Clamped at zero so a backwards wall-clock step reads as "no suspension"
        rather than as negative evidence.
        """
        wall_elapsed = self._wall() - self._wall_started
        monotonic_elapsed = self._monotonic() - self._mono_started
        return max(0.0, wall_elapsed - monotonic_elapsed)

    def suspended(self) -> bool:
        """Whether the host was suspended long enough to have killed sockets.

        A zero threshold would make every run suspended — scheduling jitter puts
        a few milliseconds between the two reads — so it is treated as "off".
        """
        if self._threshold <= 0:
            return False
        return self.suspended_seconds() >= self._threshold


def bound_fired(deadline: float | SourceClock | None) -> str | None:
    """Which bound (if any) says this source must stop now.

    Returns `STALLED`, `BOUNDED`, or `None` to continue. The single decision
    point for every collection loop: the pipeline and the discovery pass both
    ask it, so the two cannot drift onto different semantics.

    Stall is tested first because it is the tighter, more diagnostic bound. It is
    false once the ceiling is reached, so a source that produced right up to the
    ceiling is never mislabelled a stall. When no stall window is configured the
    two bounds coincide and the cut is attributed to us — the safer default,
    since without a stall window we cannot tell slow from silent.
    """
    if isinstance(deadline, SourceClock):
        if deadline.stalled():
            return STALLED
        if deadline.exhausted():
            return BOUNDED
        return None
    if deadline is not None and time.monotonic() >= deadline:
        # A bare float carries no way to tell the two apart; treat a plain
        # expired deadline as our bound rather than inventing a pathology.
        return BOUNDED
    return None


def deadline_of(deadline: float | SourceClock | None) -> float | None:
    """Resolve either deadline representation to a monotonic timestamp.

    Transports accept a bare float (a fixed deadline) or a `SourceClock` (a
    sliding one). Resolving in one place keeps every consult-point — and the
    two hand-copied retry loops — agnostic about which it was handed.
    """
    if isinstance(deadline, SourceClock):
        return deadline.at
    return deadline
