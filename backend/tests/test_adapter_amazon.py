"""Amazon transport adapter — search.json paging, field mapping, location narrowing.

The list payload inlines the full description + qualifications, so `fetch()` yields
complete postings (no hydrate round-trip). These tests pin the request shape (one
paged query per configured location group) and the hit -> RawJob mapping, and
confirm the inlined description flows through the detail connector into a grounded
source-disclosed comp band.
"""

from __future__ import annotations

import httpx
import pytest

from tracker.connectors.detail import structure_job_detail
from tracker.connectors.listing.amazon import AmazonAdapter
from tracker.connectors.listing.base import RateLimiter

_HIT = {
    "id_icims": "10473800",
    "title": "Senior Software Development Engineer",
    "job_path": "/en/jobs/10473800/senior-software-development-engineer",
    "normalized_location": "Sunnyvale, California, USA",
    "city": "Sunnyvale",
    "state": "CA",
    "posted_date": "July 14, 2026",
    "job_category": "Software Development",
    "team": {"label": "team-aws"},
    "description": (
        "Design distributed systems at scale.<br/><br/>Our compensation reflects the "
        "cost of labor across several US geographic markets. The base pay for this "
        "position ranges from $151,300/year in our lowest geographic market up to "
        "$261,500/year in our highest geographic market. Amazon is a total "
        "compensation company. Dependent on the position offered, equity may be provided."
    ),
    "basic_qualifications": "- 8+ years of experience",
    "preferred_qualifications": "- AWS experience",
    "locations": [
        '{"normalizedLocation":"Sunnyvale, California, USA","type":"ONSITE"}',
        '{"normalizedLocation":"Seattle, Washington, USA","type":"ONSITE"}',
    ],
}


def _adapter(handler) -> AmazonAdapter:
    adapter = AmazonAdapter("amazon")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)  # no inter-page pacing in tests
    return adapter


@pytest.mark.asyncio
async def test_fetch_pages_each_location_group_and_maps_fields():
    calls: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        # Return the single hit on the first page of each group, then empty.
        offset = request.url.params.get("offset")
        jobs = [_HIT] if offset == "0" else []
        return httpx.Response(200, json={"hits": 1, "jobs": jobs})

    adapter = _adapter(handler)
    jobs = [job async for job in adapter.fetch()]

    # One RawJob total: the same req_id is deduped across the location groups.
    assert len(jobs) == 1
    job = jobs[0]
    assert job.company == "amazon"
    assert job.req_id == "10473800"
    assert job.url == "https://www.amazon.jobs/en/jobs/10473800/senior-software-development-engineer"
    assert "Sunnyvale, California, USA" in job.locations
    assert "Seattle, Washington, USA" in job.locations  # secondary location parsed
    assert job.team == "team-aws"
    assert job.posted_at is not None
    # One query issued per configured location group.
    group_states = {
        c.params.get("normalized_state_name[]") or c.params.get("normalized_country_code[]")
        for c in calls
        if c.params.get("offset") == "0"
    }
    # One query per PLANNED group (default scope), not per manifest entry.
    assert len(group_states) == len(AmazonAdapter('amazon').planned_location_items())


@pytest.mark.asyncio
async def test_inlined_description_structures_into_grounded_source_comp():
    def handler(request: httpx.Request) -> httpx.Response:
        jobs = [_HIT] if request.url.params.get("offset") == "0" else []
        return httpx.Response(200, json={"hits": 1, "jobs": jobs})

    adapter = _adapter(handler)
    job = [j async for j in adapter.fetch()][0]

    # Mirror the pipeline's central structuring call.
    structure_job_detail(job, adapter.drift, payload=job.detail_payload, source="amazon")

    assert any(s.key == "pay_and_benefits" for s in job.description_sections)
    assert job.source_disclosed_comp is not None
    assert job.source_disclosed_comp.base_min == 151300
    assert job.source_disclosed_comp.base_max == 261500
    assert job.source_disclosed_comp.pay_basis == "base"


@pytest.mark.asyncio
async def test_non_200_search_records_drift_and_yields_nothing():
    def handler(request: httpx.Request) -> httpx.Response:
        # 404 is not in the base adapter's retry set, so it surfaces immediately.
        return httpx.Response(404, text="not found")

    adapter = _adapter(handler)
    jobs = [job async for job in adapter.fetch()]

    assert jobs == []
    assert any(a["message"] == "non-200 search" for a in adapter.drift.alerts)
