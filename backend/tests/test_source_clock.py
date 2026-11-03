"""SourceClock: progress-based liveness with a hard ceiling.

The contract that matters: a source is alive while it produces, and the two
bounds mean different things — silence is the source's fault, the ceiling is
ours. Everything downstream (health, retry eligibility) keys off that split.
"""

from __future__ import annotations

from tracker.platform.clock import SourceClock, deadline_of


class FakeClock:
    """Explicit time so liveness tests never sleep or race a real clock."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _clock(stall=90.0, ceiling=1800.0, at=1000.0):
    c = FakeClock(at)
    return SourceClock(stall_seconds=stall, hard_deadline=at + ceiling, clock=c), c


class TestEffectiveDeadline:
    def test_at_is_the_nearer_of_the_two_bounds(self):
        sc, _ = _clock(stall=90.0, ceiling=1800.0, at=1000.0)
        # Stall (1090) bites long before the ceiling (2800).
        assert sc.at == 1090.0

    def test_ceiling_wins_when_it_is_nearer_than_the_stall_window(self):
        sc, _ = _clock(stall=90.0, ceiling=10.0, at=1000.0)
        assert sc.at == 1010.0

    def test_remaining_never_goes_negative(self):
        sc, c = _clock(stall=5.0)
        c.advance(500)
        assert sc.remaining() == 0.0


class TestProgressSlidesOnlyTheStallBound:
    def test_progress_pushes_the_stall_deadline_forward(self):
        sc, c = _clock(stall=90.0)
        assert sc.at == 1090.0
        c.advance(60)
        sc.progress()
        assert sc.at == 1150.0  # 1060 + 90

    def test_progress_never_moves_the_ceiling(self):
        """A source that keeps producing still stops at the hard bound."""
        sc, c = _clock(stall=90.0, ceiling=100.0)
        for _ in range(50):
            c.advance(10)
            sc.progress()
        assert sc.hard_deadline == 1100.0
        assert sc.at == 1100.0  # clamped by the ceiling, not the slid stall
        assert sc.exhausted() is True

    def test_steady_progress_keeps_a_slow_source_alive_far_past_a_fixed_budget(self):
        """The whole point: 1300s of steady work must not be cut at 300s."""
        sc, c = _clock(stall=90.0, ceiling=1800.0)
        for _ in range(130):  # 1300s of work, an item every 10s
            c.advance(10)
            sc.progress()
            assert sc.stalled() is False
        assert sc.expired() is False


class TestStalledVersusExhausted:
    def test_silence_is_a_stall(self):
        sc, c = _clock(stall=90.0, ceiling=1800.0)
        c.advance(91)
        assert sc.stalled() is True
        assert sc.exhausted() is False

    def test_hitting_the_ceiling_is_not_a_stall(self):
        """Ceiling expiry must stay distinguishable: it is our bound, not a
        pathology, and routing it through `stalled()` would re-run the
        quarantine cascade this design exists to stop."""
        sc, c = _clock(stall=90.0, ceiling=100.0)
        for _ in range(20):  # keep producing right up to the ceiling
            c.advance(5)
            sc.progress()
        assert sc.exhausted() is True
        assert sc.stalled() is False

    def test_a_live_producing_source_is_neither(self):
        sc, c = _clock()
        c.advance(30)
        sc.progress()
        assert sc.stalled() is False
        assert sc.exhausted() is False
        assert sc.expired() is False

    def test_expired_covers_either_bound(self):
        stalled, c1 = _clock(stall=10.0, ceiling=1800.0)
        c1.advance(11)
        assert stalled.expired() is True

        ceiled, c2 = _clock(stall=1800.0, ceiling=10.0)
        c2.advance(11)
        assert ceiled.expired() is True


class TestBlockingClip:
    def test_remaining_bounds_a_single_await(self):
        """No one await may outlive the window — the cooperative check cannot
        interrupt a coroutine already parked inside one."""
        sc, c = _clock(stall=90.0)
        c.advance(60)
        assert sc.remaining() == 30.0

    def test_remaining_respects_the_ceiling_even_after_progress(self):
        sc, c = _clock(stall=90.0, ceiling=100.0)
        c.advance(95)
        sc.progress()  # would slide the stall bound to 1185
        assert sc.remaining() == 5.0  # but the ceiling is at 1100


class TestClockOwnsItsOwnTime:
    """The clock is injectable, so it must answer time questions itself — a
    caller reading `time.monotonic()` would be comparing two timelines."""

    def test_allows_is_answered_against_the_injected_clock(self):
        sc, c = _clock(stall=90.0)
        assert sc.allows(30.0) is True
        c.advance(70)
        assert sc.allows(30.0) is False  # only 20s left
        assert sc.allows(10.0) is True

    def test_allows_respects_the_ceiling_too(self):
        sc, c = _clock(stall=1800.0, ceiling=50.0)
        assert sc.allows(60.0) is False
        assert sc.allows(10.0) is True
        c.advance(45)
        assert sc.allows(10.0) is False


class TestDeadlineResolution:
    def test_resolves_a_clock_to_its_effective_deadline(self):
        sc, _ = _clock(stall=90.0)
        assert deadline_of(sc) == sc.at

    def test_passes_a_bare_float_through(self):
        assert deadline_of(1234.5) == 1234.5

    def test_none_stays_unbounded(self):
        assert deadline_of(None) is None

    def test_resolution_tracks_progress(self):
        """Transports re-resolve per attempt, so a slid deadline must be seen."""
        sc, c = _clock(stall=90.0)
        first = deadline_of(sc)
        c.advance(60)
        sc.progress()
        assert deadline_of(sc) > first


class TestDegenerateConfiguration:
    def test_zero_stall_window_expires_immediately(self):
        sc, _ = _clock(stall=0.0)
        assert sc.stalled() is True

    def test_negative_stall_is_clamped_not_inverted(self):
        sc, _ = _clock(stall=-5.0)
        assert sc.at == 1000.0  # not 995.0

    def test_a_ceiling_already_in_the_past_is_exhausted_at_once(self):
        c = FakeClock(1000.0)
        sc = SourceClock(stall_seconds=90.0, hard_deadline=900.0, clock=c)
        assert sc.exhausted() is True
        assert sc.remaining() == 0.0
