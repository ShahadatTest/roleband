"""Deel sitemap listing and JSON-LD posting pages.

The contracts, each on what a seeker would get wrong if it broke:

* **The org sitemap is the board**, and a posting id is the uuid in its URL.
* **A posting page becomes a posting** from its JSON-LD, with schema.org's
  employment type kept.
* **The robots-disallowed routes are never requested** — neither `/api/` nor a
  posting's `/application` page.

"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tracker.connectors import build_adapter
from tracker.connectors.extract.payload import job_posting
from tracker.connectors.listing.deel import posting_id, posting_urls, sitemap_url
from tracker.platform.ratelimit import RateLimiter
from tracker.schema import EmploymentType

FIX = Path(__file__).parent / "fixtures/listings/deel"
SITEMAP = json.loads((FIX / "page1.json").read_text())["html"]
POSTING = (FIX / "job_5d3636f8.html").read_text()
URLS = posting_urls(SITEMAP)


def _adapter(sitemap: str = SITEMAP):
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        if request.url.path.endswith("sitemap.xml"):
            return httpx.Response(200, text=sitemap)
        return httpx.Response(200, text=POSTING)

    adapter = build_adapter("klarna", "deel", board_token="klarna")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    return adapter, asked


async def _jobs(adapter):
    return [job async for job in adapter.fetch()]


def test_the_org_sitemap_is_the_board():
    assert sitemap_url("klarna") == "https://jobs.deel.com/klarna/sitemap.xml"
    assert len(URLS) == 4
    assert posting_id(URLS[0]) == "5d3636f8-0712-4fe2-a1f4-84358440d272"
    # The board root and a category-ish URL are not postings.
    assert posting_id("https://jobs.deel.com/klarna") is None
    with pytest.raises(ValueError, match="org slug"):
        sitemap_url("jobs.deel.com/klarna")


@pytest.mark.asyncio
async def test_a_listed_posting_becomes_a_posting():
    adapter, asked = _adapter()
    jobs = await _jobs(adapter)

    assert asked == [sitemap_url("klarna"), *URLS]
    assert len(jobs) == 4 and adapter.drift.listing_complete and adapter.drift.alerts == []
    job = jobs[0]
    assert job.req_id == "5d3636f8-0712-4fe2-a1f4-84358440d272"
    assert job.title == "Customer Trust and Experience Agent (Fully Remote - Sweden)"
    assert job.locations == ["Sweden"]
    assert job.posted_at is not None and job.posted_at.date().isoformat() == "2026-04-21"
    assert job.description_complete and len(job.description_html) > 1000
    # Deel states schema.org's own word, so it is kept and normalized.
    assert job.source_facts.employment_type_raw == "CONTRACTOR"
    assert job.source_facts.employment_type_normalized is EmploymentType.CONTRACT
    assert job.source_facts.tenant_identity == "klarna"


@pytest.mark.asyncio
async def test_the_disallowed_routes_are_never_requested():
    """robots disallows `/api/` and `/*/job-details/*/application`; the board
    page renders from the first, which is why the sitemap is the listing."""
    adapter, asked = _adapter()
    await _jobs(adapter)

    assert asked, "the adapter did request something"
    for url in asked:
        assert "/api/" not in url, url
        assert not url.endswith("/application"), url


def test_the_posting_page_states_the_employer():
    posting = job_posting(POSTING)
    assert posting["hiringOrganization"]["name"] == "Klarna"
