"""A later HTTP failure cannot erase successful enumeration pages."""

import json
import re
import time
from pathlib import Path

import httpx
import pytest

from tests.factories import scope_for
from tracker.connectors import build_adapter
from tracker.connectors.listing import base
from tracker.enrich.enricher import annotate, passes_filters
from tracker.platform.clock import SourceClock
from tracker.platform.http import RetryDeadlineExceeded
from tracker.platform.ratelimit import RateLimiter, RateLimiterPool
from tracker.workflows.collection import collect_source

FIX = Path(__file__).parent / "fixtures/listings"


@pytest.mark.asyncio
@pytest.mark.parametrize("name,company,token", [
    ("kpmg", "kpmg", None), ("smartrecruiters", "roland-berger", "RolandBerger"),
])
@pytest.mark.parametrize("failure", ["deadline", "transport", "expired_after_response"])
async def test_completed_rows_survive_without_post_bound_network(monkeypatch, name, company, token, failure):
    page = json.loads((FIX / name / "page1.json").read_text())["html"]
    if name == "kpmg":
        page = re.sub(r'(data-action="count">)12', r'\g<1>24', page)
    requests = []
    now = [time.monotonic()]
    clock = SourceClock(stall_seconds=1000, hard_deadline=now[0] + 120, clock=lambda: now[0])

    def handle(request):
        requests.append(str(request.url))
        if len(requests) == 1:
            return httpx.Response(200, text=page)
        if failure == "transport":
            raise httpx.ConnectError("late offline failure", request=request)
        if failure == "expired_after_response":
            now[0] += 121
            return httpx.Response(200, text="")
        now[0] += 121
        raise RetryDeadlineExceeded("offline budget exhausted")

    monkeypatch.setattr(base, "make_tier_client", lambda *a, **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(handle)))
    built = []

    def factory(*args, **kwargs):
        adapter = build_adapter(*args, **kwargs)
        adapter._limiter = RateLimiter(0)
        adapter.settings = adapter.settings.model_copy(update={"scraper_max_retries": 0})
        built.append(adapter)
        return adapter

    # Establish a scope from a real first-page row without touching a network.
    if name == "kpmg":
        from tracker.connectors.listing.kpmg import parse_cards

        samples = [build_adapter(company, name)._job(card) for card in parse_cards(page)]
    else:
        from tracker.connectors.listing.smartrecruiters import parse_groups

        samples = list(build_adapter(company, name, board_token=token)._group_jobs(parse_groups(page)))
    sample = next(job for job in samples if passes_filters(annotate(job), scope_for(job)))

    class NoNetwork:
        async def resolve(self, ctx):
            pytest.fail("partial enumeration must not start compensation requests")

    result = await collect_source(
        company, {"adapter": name, "board_token": token}, scope_for(sample), NoNetwork(),
        max_list=None, hydrate=True, limiter_pool=RateLimiterPool(), deadline=clock,
        adapter_factory=factory,
    )
    assert len(requests) == 2
    assert result.enriched and sample.dedupe_key() in result.seen_keys
    assert result.stats["scanned"] > 0 and not result.list_complete
    if failure == "transport":
        assert result.stats["errors"] and not result.stats["bounded"]
    else:
        assert result.stats["bounded"]
    assert list(built[0].drain_completed()) == [], "handoff transfers ownership exactly once"
