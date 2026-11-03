"""Contracts for tracker.platform primitives (http retry, paging, locks)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from tracker.platform.clock import SourceClock
from tracker.platform.http import RetryPolicy, make_client, request_with_retry
from tracker.platform.locks import AlreadyRunning, run_lock
from tracker.platform.paging import expand_saturated, paginate


class _FakeClock:
    """Explicit monotonic time so liveness assertions never race a real clock."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def _noop_sleep(_seconds: float) -> None:
    return None


def _transport(responses: list[httpx.Response | Exception]) -> httpx.MockTransport:
    calls = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_request_with_retry_honors_retry_after_then_succeeds(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    transport = _transport(
        [
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await request_with_retry(
            client, "GET", "https://x.test/", retry=RetryPolicy(max_retries=2)
        )
    assert resp.status_code == 200
    assert sleeps == [7.0]


@pytest.mark.asyncio
async def test_request_with_retry_exhausts_and_returns_last_response(monkeypatch):
    async def fake_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    transport = _transport([httpx.Response(503), httpx.Response(503)])
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await request_with_retry(
            client, "GET", "https://x.test/", retry=RetryPolicy(max_retries=1)
        )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_request_with_retry_raises_transport_error_after_budget(monkeypatch):
    async def fake_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    transport = _transport(
        [httpx.ConnectError("boom"), httpx.ConnectError("boom"), httpx.ConnectError("boom")]
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.ConnectError):
            await request_with_retry(
                client, "GET", "https://x.test/", retry=RetryPolicy(max_retries=2)
            )


def test_make_client_defaults_mirror_httpx():
    client = make_client(timeout=20.0)
    assert client.follow_redirects is False
    assert client.timeout == httpx.Timeout(20.0)


@pytest.mark.asyncio
async def test_paginate_stops_on_empty_page():
    pages = [["a", "b"], ["c"], []]

    async def fetch(i: int):
        return pages[i]

    got = [x async for x in paginate(fetch, max_pages=10)]
    assert got == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_paginate_cycle_guard_fires_on_all_repeat_page():
    pages = [["a", "b"], ["a", "b"], ["never-reached"]]
    repeats: list[int] = []

    async def fetch(i: int):
        return pages[i]

    got = [
        x
        async for x in paginate(
            fetch, max_pages=10, dedupe_key=lambda x: x, on_repeat=repeats.append
        )
    ]
    assert got == ["a", "b"]
    assert repeats == [1]


@pytest.mark.asyncio
async def test_paginate_respects_max_pages():
    async def fetch(i: int):
        return [f"item-{i}"]

    got = [x async for x in paginate(fetch, max_pages=3)]
    assert got == ["item-0", "item-1", "item-2"]


# --- expand_saturated: a window is not a listing --------- #


def _tree(totals: dict[str, int], children: dict[str, list[str]]):
    """A fake source: declared totals per query, and each query's facets."""
    probed: list[str] = []

    async def declared_total(q: str) -> int | None:
        probed.append(q)
        return totals.get(q)

    return declared_total, (lambda q: children.get(q, [])), probed


@pytest.mark.asyncio
async def test_expand_saturated_leaves_an_unsaturated_query_alone():
    """The guard against over-splitting: a query under the window is a real
    listing, so refining it would multiply requests for nothing."""
    total, refine, probed = _tree({"usa": 4_000}, {"usa": ["wa", "ca"]})

    assert await expand_saturated(["usa"], declared_total=total, refine=refine, window=10_000) == [
        "usa"
    ]
    assert probed == ["usa"]


@pytest.mark.asyncio
async def test_expand_saturated_splits_at_the_window_without_probing_the_leaves():
    """At the window the number is the window, so the query is a view. It is
    replaced by its facets — and those are NOT probed: a leaf reports its own
    total on the first page it pages anyway, so probing here would cost one
    wasted request per leaf."""
    total, refine, probed = _tree({"usa": 10_000}, {"usa": ["wa", "ca", "ny"]})

    leaves = await expand_saturated(
        ["usa"], declared_total=total, refine=refine, window=10_000
    )

    assert leaves == ["wa", "ca", "ny"]
    assert probed == ["usa"], "only the node that could be split is probed"


@pytest.mark.asyncio
async def test_expand_saturated_keeps_a_leaf_still_saturated_at_the_depth_cap():
    """Honest rather than complete: when splitting runs out of depth the leaf is
    still returned, so the caller pages it and records `truncated`. Dropping it
    would silently shrink coverage; claiming it complete would authorize closing
    everything the window hides."""
    total, refine, probed = _tree(
        {"world": 10_000, "usa": 10_000, "uk": 500, "wa": 40},
        {"world": ["usa", "uk"], "usa": ["wa"]},
    )

    leaves = await expand_saturated(
        ["world"], declared_total=total, refine=refine, window=10_000, max_depth=2
    )

    assert leaves == ["uk", "wa"], "uk resolved at depth 2; usa split once more"
    assert probed == ["world", "usa", "uk"]


@pytest.mark.asyncio
async def test_expand_saturated_fails_safe_when_the_total_is_unknown():
    """A probe that errored is not evidence of saturation. The query is kept
    whole and paged as an unrefined query."""
    total, refine, _ = _tree({}, {"usa": ["wa", "ca"]})

    assert await expand_saturated(["usa"], declared_total=total, refine=refine, window=10) == [
        "usa"
    ]


@pytest.mark.asyncio
async def test_expand_saturated_keeps_a_saturated_query_with_no_facet_to_split_on():
    """Saturated but unrefinable (no declared facet) still has to be collected."""
    total, refine, _ = _tree({"sgp": 10_000}, {})

    assert await expand_saturated(["sgp"], declared_total=total, refine=refine, window=10_000) == [
        "sgp"
    ]


def test_run_lock_excludes_second_holder(tmp_path):
    lock_path = tmp_path / "x.lock"
    with run_lock(lock_path):
        with pytest.raises(AlreadyRunning), run_lock(lock_path):
            pass
    # Released: can take it again.
    with run_lock(lock_path):
        pass


# --- Retry-After is bounded ------------------------------------------------ #


@pytest.mark.asyncio
async def test_retry_after_is_capped_so_a_remote_header_cannot_park_the_process(
    monkeypatch,
):
    """A remote party must not choose how long our process blocks.

    Unbounded, `Retry-After: 3600` is a literal one-hour sleep on any path that
    passes no deadline. The signal is kept, the bound is ours.
    """
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    transport = _transport(
        [
            httpx.Response(429, headers={"Retry-After": "3600"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await request_with_retry(
            client,
            "GET",
            "https://x.test/",
            retry=RetryPolicy(max_retries=2, max_backoff=30.0),
        )

    assert resp.status_code == 200
    assert sleeps == [30.0]  # capped, not 3600


@pytest.mark.asyncio
async def test_a_retry_after_inside_the_cap_is_still_honored_exactly(monkeypatch):
    """The cap must not flatten every backoff to max_backoff."""
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    transport = _transport(
        [
            httpx.Response(503, headers={"Retry-After": "5"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with httpx.AsyncClient(transport=transport) as client:
        await request_with_retry(
            client,
            "GET",
            "https://x.test/",
            retry=RetryPolicy(max_retries=2, max_backoff=30.0),
        )

    assert sleeps == [5.0]


# --- progress feeds the sliding deadline ----------------------------------- #


@pytest.mark.asyncio
async def test_a_received_response_counts_as_progress(monkeypatch):
    """Liveness must be fed by the transport, not only by yielded items: a
    source paging through out-of-scope jobs yields nothing for long stretches."""
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
    clock = _FakeClock(1000.0)
    sc = SourceClock(stall_seconds=90.0, hard_deadline=1_000_000.0, clock=clock)

    transport = _transport([httpx.Response(200, json={"ok": True})])
    clock.advance(60)  # 30s of window left before the request
    async with httpx.AsyncClient(transport=transport) as client:
        await request_with_retry(
            client, "GET", "https://x.test/", retry=RetryPolicy(), deadline=sc
        )

    assert sc.at == 1150.0  # slid to now(1060) + 90
    assert sc.stalled() is False


@pytest.mark.asyncio
async def test_a_deliberate_backoff_is_not_counted_as_source_silence(monkeypatch):
    """Time we chose to spend waiting must not read as the source going quiet,
    or a source politely obeying a 429 is judged dead for good behavior."""
    real_advance: list[float] = []

    async def sleep_advances_the_clock(seconds: float) -> None:
        real_advance.append(seconds)
        clock.advance(seconds)

    monkeypatch.setattr(asyncio, "sleep", sleep_advances_the_clock)
    clock = _FakeClock(1000.0)
    # Window shorter than the backoff: without progress-after-sleep the source
    # would look stalled purely because it waited as instructed.
    sc = SourceClock(stall_seconds=20.0, hard_deadline=1_000_000.0, clock=clock)

    transport = _transport(
        [
            httpx.Response(429, headers={"Retry-After": "15"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await request_with_retry(
            client,
            "GET",
            "https://x.test/",
            retry=RetryPolicy(max_retries=2, max_backoff=30.0),
            deadline=sc,
        )

    assert resp.status_code == 200
    assert real_advance == [15.0]
    assert sc.stalled() is False
