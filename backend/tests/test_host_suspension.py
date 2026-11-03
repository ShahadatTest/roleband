"""The host going to sleep mid-scrape, and three places it could be misread.

A suspended laptop is invisible at the point it happens. `time.monotonic()`
simply stops, the process resumes as if nothing occurred, and the only trace is
that every socket opened before the gap is dead after it. The first read on one
returns EOF, `httpcore` maps that onto `ReadError`, and `anyio.EndOfStream`
carries no message, so unguarded the whole event reaches the user as the
string ``"ReadError: "`` filed against whichever source happened to be
mid-listing.

These tests pin the three separate mistakes that would make that possible:

* an unmeasured gap, so nothing can tell our sleep from a sick source;
* `ReadError` missing from the retryable transport set, so a recoverable socket
  death ends a source outright, while the *same* physical teardown arriving as
  `RemoteProtocolError` is retried and survives;
* an empty exception message interpolated straight into the notification.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from tests.factories import scope_filter
from tracker.platform.clock import SuspensionMonitor
from tracker.platform.http import RetryPolicy, request_with_retry
from tracker.platform.util import describe_exception


class _Clock:
    """A clock that can be advanced independently of its twin.

    Suspension is precisely the two clocks disagreeing, so the fake has to allow
    them to disagree — a single shared fake could not express the condition.
    """

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _monitor(threshold: float = 60.0) -> tuple[SuspensionMonitor, _Clock, _Clock]:
    monotonic, wall = _Clock(1_000.0), _Clock(1_700_000_000.0)
    return (
        SuspensionMonitor(threshold_seconds=threshold, monotonic=monotonic, wall=wall),
        monotonic,
        wall,
    )


# --- measuring the gap ------------------------------------------------------ #


def test_ordinary_work_is_not_a_suspension():
    """Both clocks advance together while the process is running. Ten minutes of
    real scraping must read as zero suspension, or every run is 'suspended' and
    the outcome it feeds becomes meaningless."""
    monitor, monotonic, wall = _monitor()
    for _ in range(60):
        monotonic.advance(10.0)
        wall.advance(10.0)

    assert monitor.suspended_seconds() == 0.0
    assert monitor.suspended() is False


def test_the_gap_is_wall_time_the_monotonic_clock_never_saw():
    """A real shape: 279s of work with the machine asleep for 987s in the
    middle. The monotonic clock stops during macOS sleep and the wall
    clock does not, so their difference is the sleep and nothing else."""
    monitor, monotonic, wall = _monitor()

    monotonic.advance(279.2)  # work actually done
    wall.advance(279.2)
    wall.advance(987.0)  # asleep: only the wall clock moves

    assert monitor.suspended_seconds() == pytest.approx(987.0)
    assert monitor.suspended() is True


def test_a_gap_under_the_threshold_is_scheduler_jitter_not_sleep():
    """A gap below the configured threshold must not mark a healthy run
    suspended. Treating every nonzero gap as sleep creates false suspensions."""
    monitor, monotonic, wall = _monitor(threshold=60.0)
    monotonic.advance(500.0)
    wall.advance(550.3)  # A 50.3s gap stays below the threshold.

    assert monitor.suspended_seconds() == pytest.approx(50.3)
    assert monitor.suspended() is False


def test_a_backwards_wall_clock_step_is_not_negative_suspension():
    """An NTP correction that moves the wall clock back must read as no
    suspension, never as a negative number that would cancel a later real gap."""
    monitor, monotonic, wall = _monitor()
    monotonic.advance(120.0)
    wall.advance(-30.0)

    assert monitor.suspended_seconds() == 0.0
    assert monitor.suspended() is False


def test_a_zero_threshold_disables_detection_rather_than_firing_always():
    """0 is the documented off switch. Read naively as `gap >= 0` it would make
    every run suspended, which is the most damaging possible misreading: every
    source would go health-inert and nothing would ever be judged again."""
    monitor, monotonic, wall = _monitor(threshold=0.0)
    monotonic.advance(10.0)
    wall.advance(10_000.0)

    assert monitor.suspended_seconds() == pytest.approx(9_990.0)
    assert monitor.suspended() is False


# --- the retryable transport set -------------------------------------------- #


def _transport(items: list[httpx.Response | Exception]) -> httpx.MockTransport:
    calls = iter(items)

    def handler(_request: httpx.Request) -> httpx.Response:
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.MockTransport(handler)


async def _send(items: list[httpx.Response | Exception]) -> httpx.Response:
    async with httpx.AsyncClient(transport=_transport(items)) as client:
        return await request_with_retry(
            client, "GET", "https://x.test/", retry=RetryPolicy(max_retries=2)
        )


@pytest.mark.parametrize(
    "exc",
    [
        # The socket death a resumed host leaves behind: un-retried, it ends
        # the run.
        httpx.ReadError(""),
        httpx.WriteError("broken pipe"),
        httpx.CloseError("closed"),
        # Sibling of ReadTimeout under TimeoutException, NOT under ConnectError,
        # which is how it slips past an enumerated tuple.
        httpx.ConnectTimeout("too slow"),
        httpx.WriteTimeout("too slow"),
        httpx.PoolTimeout("no connection free"),
    ],
)
@pytest.mark.asyncio
async def test_a_recoverable_transport_failure_is_retried(exc, monkeypatch):
    """Every one of these means the request never got an answer and the next
    attempt gets a fresh connection. Raised on the first occurrence, any of them
    would kill the source's entire remaining listing."""

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    response = await _send([exc, httpx.Response(200, json={"ok": True})])

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_the_two_faces_of_one_teardown_are_now_treated_alike(monkeypatch):
    """A closed connection can surface as RemoteProtocolError or ReadError.
    Retryability must not depend on which exception httpcore raises."""

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    ok = httpx.Response(200, json={"ok": True})

    goaway = await _send([httpx.RemoteProtocolError("<ConnectionTerminated>"), ok])
    eof = await _send([httpx.ReadError(""), httpx.Response(200, json={"ok": True})])

    assert goaway.status_code == eof.status_code == 200


@pytest.mark.parametrize(
    "exc",
    [
        # Faults in the request we built or the environment we run in. Retrying
        # is the same mistake again, so widening the set must not sweep them in.
        httpx.UnsupportedProtocol("no scheme"),
        httpx.LocalProtocolError("bad header"),
        httpx.ProxyError("proxy refused"),
    ],
)
@pytest.mark.asyncio
async def test_an_unrecoverable_transport_failure_is_still_raised(exc, monkeypatch):
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    with pytest.raises(type(exc)):
        await _send([exc, httpx.Response(200)])


@pytest.mark.asyncio
async def test_retrying_still_gives_up_rather_than_looping(monkeypatch):
    """Widening the set must not turn a genuinely dead source into an infinite
    retry: the budget still ends the attempt and the caller still sees the
    exception."""

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    with pytest.raises(httpx.ReadError):
        await _send([httpx.ReadError("") for _ in range(3)])


# --- the empty message that reached the bell -------------------------------- #


def test_an_exception_with_no_message_still_says_something():
    """An empty exception message must not leave a diagnostic ending in a
    bare colon; the exception type must still give the reader a useful cause."""
    assert describe_exception(httpx.ReadError("")) == "ReadError (no detail)"
    assert describe_exception(httpx.ReadError("   ")) == "ReadError (no detail)"


def test_an_exception_with_a_message_is_unchanged():
    assert describe_exception(httpx.ConnectError("no route to host")) == (
        "ConnectError: no route to host"
    )


# --- the pipeline seam ------------------------------------------------------ #


@pytest.mark.asyncio
async def test_collect_source_files_a_slept_through_run_against_the_host(monkeypatch):
    """End to end at the seam that files the notification.

    The adapter behaves as a source read across a sleep does: it yields part of a
    listing and then raises the socket death the suspension left behind. What
    must come out is `suspended` — our host — rather than `degraded`, which is a
    verdict on the source and three of which quarantine its binding.
    """
    from tracker.connectors.listing.base import RateLimiterPool, SchemaDriftDetector
    from tracker.connectors.recipes.outcome import (
        RESETS_ABSENCE,
        SourceOutcome,
        classify_source_outcome,
    )
    from tracker.platform import clock as clock_module
    from tracker.schema import RawJob
    from tracker.workflows import collection as collection_module

    class _SleptThrough:
        """Yields a page, then dies the way a resumed socket does."""

        def __init__(self) -> None:
            self.drift = SchemaDriftDetector("microsoft")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def fetch(self):
            yield RawJob(
                company="microsoft",
                req_id="1",
                title="Principal Product Manager",
                url="https://example.test/1",
                locations=["Redmond, WA"],
            )
            raise httpx.ReadError("")

    # Wall clock jumps 987s that the monotonic clock never sees — the machine
    # asleep, as `pmset` records it. Substituted at the
    # pipeline's own reference to the class, so this also pins that
    # `collect_source` actually consults a monitor rather than guessing.
    monotonic, wall = _Clock(1_000.0), _Clock(1_700_000_000.0)

    def _slept(*, threshold_seconds):
        monitor = clock_module.SuspensionMonitor(
            threshold_seconds=threshold_seconds, monotonic=monotonic, wall=wall
        )
        wall.advance(987.0)  # the host goes down after collection starts
        return monitor

    monkeypatch.setattr(collection_module, "SuspensionMonitor", _slept)

    empty_scope = scope_filter(bands=(), roles=(), tracks=(), locations=(), domains=())
    result = await collection_module.collect_source(
        "microsoft",
        {"adapter": "fake"},
        empty_scope,
        object(),
        max_list=None,
        hydrate=False,
        limiter_pool=RateLimiterPool(),
        adapter_factory=lambda *args, **kwargs: _SleptThrough(),
    )

    assert result.stats["suspended"] is True
    assert result.stats["suspended_seconds"] == pytest.approx(987.0)
    # The transport error is still recorded (the listing really is incomplete)
    # but it does not read as a message about the source.
    assert result.stats["errors"] == ["ReadError (no detail)"]

    outcome = classify_source_outcome(result.stats)
    assert outcome is SourceOutcome.SUSPENDED
    assert outcome not in RESETS_ABSENCE
    # Not counting against the source is not permission to close: we cannot claim a req is gone
    # from a listing we slept through.
    assert result.list_complete is False


@pytest.mark.asyncio
async def test_a_listing_read_across_a_sleep_closes_nothing_even_when_it_finished(monkeypatch):
    """The collector's half of the one listing judgement: the
    adapter finished cleanly, no error, every row served, and the host still
    slept inside the read. A gap we cannot see inside is no listing to close
    jobs against, so the run is `suspended` and never complete. The directory
    read, which only counts, does not cut on this (`test_directory_sweep`)."""
    from tracker.connectors.listing.base import RateLimiterPool, SchemaDriftDetector
    from tracker.connectors.recipes.outcome import SourceOutcome, classify_source_outcome
    from tracker.platform import clock as clock_module
    from tracker.schema import RawJob
    from tracker.workflows import collection as collection_module

    class _Finished:
        def __init__(self) -> None:
            self.drift = SchemaDriftDetector("microsoft")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def fetch(self):
            for n in range(2):
                yield RawJob(company="microsoft", req_id=str(n), title="Principal Product Manager",
                             url=f"https://example.test/{n}", locations=["Redmond, WA"])

    monotonic, wall = _Clock(1_000.0), _Clock(1_700_000_000.0)

    def _slept(*, threshold_seconds):
        monitor = clock_module.SuspensionMonitor(
            threshold_seconds=threshold_seconds, monotonic=monotonic, wall=wall
        )
        wall.advance(987.0)
        return monitor

    monkeypatch.setattr(collection_module, "SuspensionMonitor", _slept)
    empty_scope = scope_filter(bands=(), roles=(), tracks=(), locations=(), domains=())
    result = await collection_module.collect_source(
        "microsoft", {"adapter": "fake"}, empty_scope, object(),
        max_list=None, hydrate=False, limiter_pool=RateLimiterPool(),
        adapter_factory=lambda *args, **kwargs: _Finished(),
    )

    assert result.stats["errors"] == [] and result.stats["scanned"] == 2
    assert result.stats["suspended"] is True
    assert result.list_complete is False
    assert classify_source_outcome({**result.stats, "list_complete": result.list_complete}) is (
        SourceOutcome.SUSPENDED
    )
