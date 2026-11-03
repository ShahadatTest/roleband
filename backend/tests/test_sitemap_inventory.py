"""Inventory and destination contracts through the real sitemap adapters."""

import json
from pathlib import Path

import httpx
import pytest

from scripts.check_catalog_tokens import Probe, check_probe
from tracker.config import get_settings
from tracker.connectors import build_adapter
from tracker.platform.ratelimit import RateLimiter

FIX = Path(__file__).parent / "fixtures/listings/radancy"
POSTING = (FIX / "job_100980904800.html").read_text()
ROOT = "https://careers.arm.com/sitemap.xml"
JOB = "https://careers.arm.com/job/x/1"


def document(urls, *, index=False):
    root, tag = ("sitemapindex", "sitemap") if index else ("urlset", "url")
    return f'<{root} xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(
        f"<{tag}><loc>{url}</loc></{tag}>" for url in urls
    ) + f"</{root}>"


def adapter_for(routes):
    asked = []

    def handle(request):
        url = str(request.url)
        asked.append(url)
        value = routes.get(url, POSTING)
        return value if isinstance(value, httpx.Response) else httpx.Response(200, text=value)

    adapter = build_adapter("arm", "radancy", board_token="careers.arm.com")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True)
    adapter._limiter = RateLimiter(0)
    return adapter, asked


@pytest.mark.asyncio
async def test_sitemap_document_ceiling_is_not_complete():
    children = [f"https://careers.arm.com/child{i}.xml" for i in range(21)]
    adapter, asked = adapter_for({ROOT: document(children, index=True), **{
        child: document([f"https://careers.arm.com/job/x/{i}"])
        for i, child in enumerate(children)
    }})
    async with adapter._client:
        jobs = [job async for job in adapter.fetch()]
    assert jobs and adapter.truncated
    assert children[-1] not in asked
    assert not adapter.drift.listing_invalidated, "our limit is not source pathology"


@pytest.mark.asyncio
async def test_nested_indexes_are_read_once_even_with_a_cycle():
    child, leaf = "https://careers.arm.com/child.xml", "https://careers.arm.com/leaf.xml"
    adapter, asked = adapter_for({
        ROOT: document([child], index=True),
        child: document([ROOT, leaf], index=True), leaf: document([JOB]),
    })
    async with adapter._client:
        jobs = [job async for job in adapter.fetch()]
    assert [job.req_id for job in jobs] == ["1"]
    assert asked == [ROOT, child, leaf, JOB]
    assert adapter.drift.listing_complete and not adapter.truncated


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    "http://127.0.0.1:8010/job/x/2", "https://[::1]/job/x/2",
    "https://169.254.169.254/private.xml", "https://other.example/job/x/2",
])
async def test_sitemap_cannot_request_another_destination(bad):
    adapter, asked = adapter_for({ROOT: document([JOB, bad])})
    async with adapter._client:
        jobs = [job async for job in adapter.fetch()]
    assert bad not in asked
    assert [job.req_id for job in jobs] == ["1"]
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_posting_redirect_is_checked_before_following():
    bad = "https://127.0.0.1/job/x/2"
    adapter, asked = adapter_for({ROOT: document([JOB]), JOB: httpx.Response(302, headers={"location": bad})})
    async with adapter._client:
        jobs = [job async for job in adapter.fetch()]
    assert bad not in asked and not jobs
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_deel_cannot_collect_another_organization():
    fixture = Path(__file__).parent / "fixtures/listings/deel/page1.json"
    sitemap = json.loads(fixture.read_text())["html"]
    asked = []

    def handle(request):
        asked.append(str(request.url))
        return httpx.Response(200, text=sitemap.replace("/klarna/", "/other/"))

    adapter = build_adapter("klarna", "deel", board_token="klarna")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    async with adapter._client:
        assert [job async for job in adapter.fetch()] == []
    assert asked == ["https://jobs.deel.com/klarna/sitemap.xml"]
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_index_only_probe_and_collection_agree():
    child = "https://careers.arm.com/child.xml"
    adapter, _ = adapter_for({ROOT: document([child], index=True), child: document([JOB])})
    async with adapter._client:
        result = await check_probe(adapter._client, Probe("arm", "radancy", "careers.arm.com", "test"))
        jobs = [job async for job in adapter.fetch()]
    assert result["state"] == "live" and result["count"] == len(jobs) == 1


@pytest.mark.asyncio
async def test_unread_child_probe_is_unknown_not_empty():
    child = "https://careers.arm.com/child.xml"
    adapter, _ = adapter_for({ROOT: document([child], index=True), child: httpx.Response(503)})
    async with adapter._client:
        result = await check_probe(adapter._client, Probe("arm", "radancy", "careers.arm.com", "test"))
    assert result["state"] == "unknown"


@pytest.mark.asyncio
async def test_empty_inventory_is_distinct_from_a_marketing_page():
    adapter, _ = adapter_for({ROOT: document([])})
    async with adapter._client:
        result = await check_probe(adapter._client, Probe("arm", "radancy", "careers.arm.com", "test"))
        assert [job async for job in adapter.fetch()] == []
    assert result["state"] == "empty"
    # Proven empty: no pathology, and never closure evidence.
    assert adapter.drift.empty_proven and not adapter.drift.listing_invalidated
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_xml_entities_are_decoded_and_namespaced_indexes_work():
    child = "https://careers.arm.com/jobs.xml?region=us&amp;page=1"
    decoded = child.replace("&amp;", "&")
    adapter, asked = adapter_for({ROOT: document([child], index=True), decoded: document([JOB])})
    async with adapter._client:
        assert len([job async for job in adapter.fetch()]) == 1
    assert decoded in asked and adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_real_adapter_client_pins_public_addresses(monkeypatch):
    from tests.fake_network import RecordingBackend, scripted_resolver
    from tracker.platform import safe_fetch

    inner = RecordingBackend()
    resolve, _ = scripted_resolver({"careers.arm.com": ["127.0.0.1"]})
    guard = safe_fetch.PublicOnlyBackend(inner, resolve)
    monkeypatch.setattr(safe_fetch, "PublicOnlyBackend", lambda: guard)
    async with build_adapter("arm", "radancy", board_token="careers.arm.com") as adapter:
        assert [job async for job in adapter.fetch()] == []
    assert inner.connected == [] and not adapter.drift.listing_complete


@pytest.mark.asyncio
@pytest.mark.parametrize("root,state", [
    (httpx.Response(404), "dead"),
    (httpx.Response(200, text="<html><body>Careers at Arm</body></html>"), "dead"),
    (httpx.Response(503), "unknown"),
    (httpx.Response(429), "unknown"),
])
async def test_a_root_the_board_does_not_serve_is_judged_like_any_route(root, state):
    """A wrong token stays the loud failure; a throttled host judges nothing."""
    adapter, _ = adapter_for({ROOT: root})
    async with adapter._client:
        result = await check_probe(adapter._client, Probe("arm", "radancy", "careers.arm.com", "test"))
    assert result["state"] == state
    assert "count" not in result


@pytest.mark.asyncio
async def test_a_failed_child_keeps_read_postings_and_withholds_closure():
    good, bad = "https://careers.arm.com/a.xml", "https://careers.arm.com/b.xml"
    adapter, asked = adapter_for({
        ROOT: document([good, bad, good], index=True),
        # The retry loop stays real; retry timing is tested in test_platform.py.
        good: document([JOB]), bad: httpx.Response(500, headers={"Retry-After": "0"}),
    })
    async with adapter._client:
        jobs = [job async for job in adapter.fetch()]
    assert [job.req_id for job in jobs] == ["1"]
    assert asked.count(good) == 1, "a child named twice is read once"
    assert asked.count(bad) == get_settings().scraper_max_retries + 1
    assert adapter.drift.listing_invalidated and not adapter.truncated


@pytest.mark.asyncio
async def test_pages_that_are_not_inventory_neither_fetch_nor_cost_closure():
    """Deel's sitemap names the board root beside its postings."""
    fixture = Path(__file__).parent / "fixtures/listings/deel/page1.json"
    sitemap = json.loads(fixture.read_text())["html"]
    extra = "".join(f"<url><loc>{u}</loc></url>" for u in (
        "https://jobs.deel.com/klarna", "https://jobs.deel.com/klarnax/about", "https://elsewhere.example/",
    ))
    sitemap = sitemap.replace("</urlset>", extra + "</urlset>")
    asked = []

    def handle(request):
        asked.append(str(request.url))
        return httpx.Response(200, text=sitemap if request.url.path.endswith("sitemap.xml") else POSTING)

    adapter = build_adapter("klarna", "deel", board_token="klarna")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    async with adapter._client:
        jobs = [job async for job in adapter.fetch()]
    assert jobs and adapter.drift.listing_complete
    assert not any(url.endswith(("/klarna", "/about", "example/")) for url in asked)
