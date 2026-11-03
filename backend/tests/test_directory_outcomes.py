"""Directory checks use real adapter drift and source-bound semantics."""

import time

import httpx
import pytest

from tests.factories import scope_filter
from tracker.company_directory import DirectoryCompany
from tracker.connectors.listing import base
from tracker.platform.breaker import BreakerPool
from tracker.platform.clock import SourceClock
from tracker.platform.http import RetryDeadlineExceeded
from tracker.platform.ratelimit import RateLimiterPool
from tracker.workflows.directory_sweep import check_company

#: A radar that admits nothing: these boards answer no posting to judge.
NO_RADAR = scope_filter(bands=(), roles=(), tracks=(), locations=(), domains=())


@pytest.mark.asyncio
async def test_a_stalled_request_is_a_source_failure_not_our_budget(monkeypatch):
    from tracker.workflows import directory_sweep

    now = [time.monotonic()]
    clock = SourceClock(stall_seconds=1, hard_deadline=now[0] + 120, clock=lambda: now[0])
    monkeypatch.setattr(directory_sweep, "SourceClock", lambda **kw: clock)

    def handle(request):
        now[0] += 2
        raise RetryDeadlineExceeded("no response before stall")

    monkeypatch.setattr(base, "make_tier_client", lambda *a, **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(handle)))
    result = await check_company(
        DirectoryCompany("fixture", "Fixture", "board", "workable", "fixture", None, 0),
        NO_RADAR, limiter_pool=RateLimiterPool(), breaker_pool=BreakerPool(),
        budget_seconds=120, stall_seconds=1,
    )
    assert result.outcome == "failed" and "SourceStalled" in result.error


@pytest.mark.asyncio
@pytest.mark.parametrize("case,expected", [("malformed", "failed"), ("deadline", "bounded")])
async def test_http_boundary_failures_are_not_successful_negative_checks(monkeypatch, case, expected):
    def handle(request):
        if case == "deadline":
            raise RetryDeadlineExceeded("offline deadline")
        return httpx.Response(200, json={"name": "Fixture", "unexpected": []})

    monkeypatch.setattr(base, "make_tier_client", lambda *a, **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(handle)))
    result = await check_company(
        DirectoryCompany("fixture", "Fixture", "board", "workable", "fixture", None, 0),
        NO_RADAR, limiter_pool=RateLimiterPool(), breaker_pool=BreakerPool(),
        budget_seconds=120, stall_seconds=30,
    )
    assert result.outcome == expected
    assert result.scanned == result.roles_for_you == 0
    assert result.error, "incomplete attempts need an observable reason"


@pytest.mark.asyncio
async def test_a_reads_only_clock_is_the_backstop_and_the_stall(monkeypatch):
    """No first-read ceiling and no pass deadline: a read may run as long as it
    makes progress, up to the 30 min backstop."""
    from tracker.workflows import directory_sweep

    made: list[dict] = []

    def recording_clock(**kw):
        made.append(kw)
        return SourceClock(**kw)

    monkeypatch.setattr(directory_sweep, "SourceClock", recording_clock)
    monkeypatch.setattr(base, "make_tier_client", lambda *a, **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"name": "Fixture", "jobs": []}))))
    before = time.monotonic()
    await check_company(
        DirectoryCompany("fixture", "Fixture", "board", "workable", "fixture", None, 0),
        NO_RADAR, limiter_pool=RateLimiterPool(), breaker_pool=BreakerPool(),
        stall_seconds=90, budget_seconds=1800,
    )
    (clock,) = made
    assert clock["stall_seconds"] == 90
    assert 1790 <= clock["hard_deadline"] - before <= 1810
