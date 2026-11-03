"""What one source's reads cost, counted by the shared transports.

A source's completed requests, retries and response bytes reach its stats and
its `scrape_source_runs` row, counted exactly, a retry after a 429 included;
the latest `Retry-After` it received travels as a moment, in both header forms.
A source whose reads never reach a shared transport records NULL, never zero,
and a read outside any collection counts nowhere.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from tracker.connectors.runtime.tiers import CurlHttpxTransport
from tracker.platform.http import RetryPolicy, request_with_retry, stream_with_retry
from tracker.platform.transport_tally import TransportTally, retry_after_seconds, tally_transport

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
NO_WAIT = RetryPolicy(max_retries=2, max_backoff=0)


def _answers(*responses: httpx.Response) -> httpx.AsyncClient:
    queue = list(responses)
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: queue.pop(0)))


def test_both_retry_after_forms_read_as_seconds_from_now():
    assert retry_after_seconds("120", NOW) == 120.0
    assert retry_after_seconds("Mon, 19 Oct 2026 14:00:00 GMT", NOW) == 7200.0
    assert retry_after_seconds("Mon, 19 Oct 2026 11:00:00 GMT", NOW) == 0.0, "a date already past"
    assert retry_after_seconds("soon", NOW) is None
    assert retry_after_seconds(None, NOW) is None


@pytest.mark.asyncio
async def test_a_retry_after_a_429_is_counted_exactly(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _answers(
        httpx.Response(429, headers={"Retry-After": "7200"}, content=b"slow down"),
        httpx.Response(200, content=b"<html>jobs</html>"),
    )
    with tally_transport() as tally:
        response = await request_with_retry(client, "GET", "https://boards.example.test/acme", retry=NO_WAIT)
    assert response.status_code == 200
    assert (tally.requests, tally.retries, tally.bytes_received) == (2, 1, len(b"slow down") + len(b"<html>jobs</html>"))
    asked = tally.retry_after_until - datetime.now(UTC)
    assert timedelta(hours=1, minutes=59) < asked <= timedelta(hours=2)


@pytest.mark.asyncio
async def test_a_streamed_body_counts_its_bytes_once_read():
    client = _answers(httpx.Response(200, content=b"x" * 5000))
    with tally_transport() as tally:
        async with stream_with_retry(client, "GET", "https://boards.example.test/acme", retry=NO_WAIT) as resp:
            assert len(await resp.aread()) == 5000
    assert (tally.requests, tally.retries, tally.bytes_received) == (1, 0, 5000)


@pytest.mark.asyncio
async def test_the_tls_tier_counts_the_same_way(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    answers = [SimpleNamespace(status_code=503, headers={"Retry-After": "30"}, content=b"busy", url="u"),
               SimpleNamespace(status_code=200, headers={}, content=b"<xml/>", url="u")]

    class Session:
        async def request(self, method, url, **kwargs):
            return answers.pop(0)

    client = httpx.AsyncClient(transport=CurlHttpxTransport(lambda: Session()))
    with tally_transport() as tally:
        await request_with_retry(client, "GET", "https://jobs.example.test/1", retry=NO_WAIT)
    assert (tally.requests, tally.retries, tally.bytes_received) == (2, 1, len(b"busy") + len(b"<xml/>"))
    assert tally.retry_after_until is not None


@pytest.mark.asyncio
async def test_a_read_outside_any_collection_counts_nowhere():
    outer = TransportTally()
    await request_with_retry(_answers(httpx.Response(200, content=b"ok")), "GET", "https://x.example.test",
                             retry=NO_WAIT)
    assert outer.stats()["requests"] is None


def test_a_source_that_bypassed_the_shared_transports_records_unknown_not_zero():
    assert TransportTally().stats() == {
        "requests": None, "retries": None, "bytes_received": None, "retry_after_until": None,
    }


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.asyncio
async def test_a_collected_source_carries_its_counts_into_its_stats(monkeypatch, no_escape):
    """Through a real adapter: the listing's first answer is a 429, its second
    the board. The source's stats name every request the board answered."""
    from pathlib import Path

    from tests.factories import STAFF_EM_SCOPE, NoComp
    from tracker.connectors import build_adapter
    from tracker.connectors.listing import base
    from tracker.platform.ratelimit import RateLimiter, RateLimiterPool
    from tracker.workflows.collection import collect_source

    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    board = (Path(__file__).parent / "fixtures/listings/greenhouse/page1.json").read_bytes()
    answered: list[int] = []

    def handle(request):
        if not answered:
            answered.append(429)
            return httpx.Response(429, headers={"Retry-After": "0"}, content=b"")
        answered.append(len(board))
        return httpx.Response(200, content=board, headers={"content-type": "application/json"})

    monkeypatch.setattr(base, "make_tier_client", lambda *a, **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(handle)))

    def factory(*args, **kwargs):
        adapter = build_adapter(*args, **kwargs)
        adapter._limiter = RateLimiter(0)
        return adapter

    result = await collect_source(
        "anthropic", {"adapter": "greenhouse", "board_token": "anthropic"}, STAFF_EM_SCOPE, NoComp(),
        max_list=None, hydrate=False, limiter_pool=RateLimiterPool(), adapter_factory=factory,
    )
    assert result.stats["scanned"] > 0
    assert (result.stats["requests"], result.stats["retries"]) == (len(answered), 1)
    assert result.stats["bytes_received"] == sum(n for n in answered if n != 429)
