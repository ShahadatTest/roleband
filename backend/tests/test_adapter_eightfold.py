"""Eightfold as a multi-tenant family, on both of its APIs.

The contract suite covers the v2 API. These tests cover the PCSX route and
envelope, camelCase fields, relative posting URL, and detail call.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from tracker.connectors import build_adapter
from tracker.connectors.listing.eightfold import parse_tenant
from tracker.connectors.recipes.outcome import classify_source_outcome
from tracker.schema import WorkplaceType
from tracker.workflows.collection_types import empty_stats, judge_listing

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "listings" / "eightfold"
PAYPAL = "paypal.eightfold.ai|paypal.com|pcsx"


@pytest.fixture(autouse=True)
def _no_pacing(monkeypatch):
    """Recovery passes are several requests to one host; the live pacer would
    make each test wait out real politeness delays."""
    from tracker.config import get_settings

    monkeypatch.setattr(get_settings(), "scraper_min_delay_seconds", 0)
    monkeypatch.setattr(get_settings(), "scraper_max_retries", 0)


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


async def _collect(adapter, handler):
    requested: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(recording)) as client:
        adapter._client = client
        jobs = [job async for job in adapter.fetch()]
        return jobs, requested, client


@pytest.mark.asyncio
async def test_a_pcsx_tenant_is_listed_from_the_pcsx_route_and_envelope():
    page = _load("pcsx_page1.json")
    adapter = build_adapter("paypal", "eightfold", board_token=PAYPAL)

    jobs, requested, _ = await _collect(adapter, lambda _r: httpx.Response(200, json=page))

    assert [r.url.path for r in requested] == ["/api/pcsx/search"]
    assert requested[0].url.host == "paypal.eightfold.ai"
    assert requested[0].url.params["domain"] == "paypal.com"
    assert "num" not in requested[0].url.params  # a v2-only parameter
    assert [j.req_id for j in jobs] == [str(p["id"]) for p in page["data"]["positions"]]

    first = jobs[0]
    assert first.title == "Software Engineer"
    # `positionUrl` is relative on PCSX; a relative URL would be unopenable.
    assert first.url == "https://paypal.eightfold.ai/careers/job/274922421610"
    assert first.locations == ["Central Singapore, Singapore"]  # a place
    assert first.workplace_type is WorkplaceType.ONSITE
    assert first.posted_at == datetime.fromtimestamp(1789948800, tz=UTC)
    assert first.department == "Software Engineering"
    assert adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_pcsx_tenant_hydrates_from_position_details():
    detail = _load("pcsx_detail.json")
    adapter = build_adapter("paypal", "eightfold", board_token=PAYPAL)
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(200, json=detail)

    jobs, _, _ = await _collect(adapter, lambda _r: httpx.Response(200, json=_load("pcsx_page1.json")))
    job = jobs[0]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter._client = client
        await adapter.hydrate(job)

    assert requested[0].url.path == "/api/pcsx/position_details"
    assert requested[0].url.params["position_id"] == job.req_id
    assert requested[0].url.params["domain"] == "paypal.com"
    assert job.description_complete is True
    assert job.description_html.startswith("<p")
    assert job.detail_payload["jobDescription"] == job.description_html


@pytest.mark.asyncio
async def test_a_tenant_answering_the_wrong_api_breaks_the_listing_loudly():
    """PayPal's real answer on the v2 route. A tenant that moves product must
    surface as a broken listing — which suppresses closure — never as an empty
    board that would close every one of its postings."""
    adapter = build_adapter("paypal", "eightfold", board_token="paypal.eightfold.ai|paypal.com")

    jobs, requested, _ = await _collect(
        adapter, lambda _r: httpx.Response(403, json={"message": "Not authorized for PCSX"})
    )

    assert jobs == []
    assert requested[0].url.path == "/api/apply/v2/jobs"
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_netflix_stays_on_v2_with_no_stored_token():
    adapter = build_adapter("netflix", "eightfold")
    _, requested, _ = await _collect(adapter, lambda _r: httpx.Response(404))
    assert requested[0].url.host == "explore.jobs.netflix.net"
    assert requested[0].url.path == "/api/apply/v2/jobs"
    assert requested[0].url.params["domain"] == "netflix.com"


@pytest.mark.parametrize(
    ("token", "pcsx"),
    [("explore.jobs.netflix.net|netflix.com", False), (PAYPAL, True)],
)
def test_a_tenant_token_names_host_domain_and_api(token, pcsx):
    tenant = parse_tenant(token)
    assert tenant.pcsx is pcsx
    assert tenant.domain.endswith(".com")


@pytest.mark.parametrize(
    "token",
    ["paypal.eightfold.ai", "paypal.eightfold.ai|", "|paypal.com",
     "paypal.eightfold.ai|paypal.com|v3", "a|b|pcsx|extra"],
)
def test_a_malformed_tenant_token_is_refused_by_name(token):
    with pytest.raises(ValueError, match="eightfold"):
        parse_tenant(token)


@pytest.mark.asyncio
async def test_a_company_with_no_tenant_configured_is_refused_not_guessed():
    adapter = build_adapter("unknown-co", "eightfold")
    with pytest.raises(ValueError, match="no Eightfold host/domain configured"):
        await _collect(adapter, lambda _r: httpx.Response(200, json={}))


# -- a drifting sort ------------------------------------------------ #
# The relevance order can list one posting twice and never list the newest
# one; a timestamp pass lists it. Each case is one page per
# pass (count 3, page size 10), so the requests ARE the passes.

def _pcsx_page(ids: list[str], count: int = 3) -> dict:
    return {"data": {"count": count, "positions": [
        {"id": i, "name": f"Role {i}", "locations": ["London, United Kingdom"]} for i in ids
    ]}}


def _by_order(pages: dict[str, list[str]], count: int = 3):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_pcsx_page(pages[request.url.params["sort_by"]], count))
    return handler


@pytest.mark.asyncio
async def test_a_posting_one_order_hides_is_recovered_by_another():
    adapter = build_adapter("paypal", "eightfold", board_token=PAYPAL)
    jobs, requested, _ = await _collect(
        adapter, _by_order({"relevance": ["a", "b", "b"], "timestamp": ["a", "c", "b"]})
    )

    assert [r.url.params["sort_by"] for r in requested] == ["relevance", "timestamp"]
    assert sorted(j.req_id for j in jobs) == ["a", "b", "c"]  # each once, none lost
    assert adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_listing_still_short_after_every_pass_is_not_complete():
    """Claiming this listing complete would close the posting it never showed."""
    adapter = build_adapter("paypal", "eightfold", board_token=PAYPAL)
    jobs, requested, _ = await _collect(
        adapter, _by_order({"relevance": ["a", "b", "b"], "timestamp": ["a", "b", "a"]})
    )

    assert len(requested) == 3
    assert sorted(j.req_id for j in jobs) == ["a", "b"]
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_listing_that_reaches_its_count_costs_one_pass():
    adapter = build_adapter("paypal", "eightfold", board_token=PAYPAL)
    _, requested, _ = await _collect(
        adapter, _by_order({"relevance": ["a", "b", "c"], "timestamp": []})
    )
    assert len(requested) == 1
    assert adapter.drift.listing_complete


# -- a board that shrinks during the walk ------------------------------- #
# Micron's board counts 2,883 and serves 2,880: postings close while a long walk
# is under way. The board's own end is a known shortfall, never a broken listing.

def _shrunk_board(count: int, served: int):
    def handler(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params["start"])
        ids = [f"p{n}" for n in range(start, min(start + 10, served))]
        return httpx.Response(200, json=_pcsx_page(ids, count))
    return handler


def _outcome(adapter, scanned: int) -> str:
    stats = {**empty_stats(), "scanned": scanned}
    judge_listing(stats, adapter, cut=False)
    return classify_source_outcome(stats).value


@pytest.mark.asyncio
async def test_a_board_that_shrank_mid_walk_is_a_counted_loss_read_once():
    adapter = build_adapter("paypal", "eightfold", board_token=PAYPAL)
    jobs, requested, _ = await _collect(adapter, _shrunk_board(count=403, served=400))

    assert len(jobs) == 400
    # One pass: the board ran out, so no order can reach its count.
    assert {r.url.params["sort_by"] for r in requested} == {"relevance"}
    assert len(requested) == 41
    assert adapter.drift.records_dropped == 3
    assert not adapter.drift.listing_invalidated
    # Closure stays off, and three of 403 is a moving board, not a broken one.
    assert not adapter.drift.listing_complete
    assert _outcome(adapter, len(jobs)) == "lossy"


@pytest.mark.asyncio
async def test_a_board_that_ends_after_one_page_of_many_is_still_a_broken_listing():
    adapter = build_adapter("paypal", "eightfold", board_token=PAYPAL)
    jobs, _, _ = await _collect(adapter, _shrunk_board(count=403, served=10))

    assert len(jobs) == 10
    assert adapter.drift.records_dropped == 393
    assert not adapter.drift.listing_complete
    assert _outcome(adapter, len(jobs)) == "degraded"
