"""Microsoft (Eightfold PCSX) adapter — search paging, mapping, detail + pay.

Fixtures mirror the real captured shapes: `/api/pcsx/search` returns
`data.positions[]` (+ a total `count`), and `/api/pcsx/position_details` returns
`data.jobDescription` HTML with bold section headers and a US base-pay line.
Tests pin one search per location term with req_id dedup + count-bounded stop,
the position->RawJob mapping, hydrate wiring, and the detail connector's section
split + grounded pay band.
"""

from __future__ import annotations

import httpx
import pytest

from tracker.connectors.detail import structure_job_detail
from tracker.connectors.detail.microsoft import MicrosoftDetailConnector
from tracker.connectors.listing.base import RateLimiter
from tracker.connectors.listing.microsoft import MicrosoftAdapter

_POSITION = {
    "id": 1970393556938818,
    "displayJobId": "200044003",
    "name": "Senior Customer Opportunity Lead",
    "locations": ["United States, Washington, Redmond"],
    "standardizedLocations": ["Redmond, WA, US"],
    "postedTs": 1784329483,
    "department": "Sales Strategy Enablement",
    "workLocationOption": "onsite",
    "atsJobId": "200044003",
    "positionUrl": "/careers/job/1970393556938818",
}

_DETAIL_HTML = (
    "<b>Overview</b><br><p>Lead customer opportunities across the field.</p>"
    "<br><br><b>Responsibilities</b><br><ul><li>Drive pipeline.</li></ul>"
    "<br><br><b>Qualifications</b><br><ul><li>8+ years experience.</li></ul>"
    "<br><p>Field Sales M5 - The typical base pay range for this role across the "
    "U.S. is USD $130,900 - $251,900 per year.</p>"
)
# Terms the adapter PLANS for the default scope, not every entry declared:
# the manifest is generated per country and a run only queries
# the groups its tracked scope relates to.
_TERM_COUNT = len(MicrosoftAdapter('microsoft').planned_location_terms())


def _adapter(handler) -> MicrosoftAdapter:
    adapter = MicrosoftAdapter("microsoft")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    return adapter


@pytest.mark.asyncio
async def test_fetch_pages_each_location_term_and_maps_fields():
    first_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/pcsx/search"
        start = request.url.params.get("start")
        term = request.url.params.get("location")
        if start == "0":
            first_pages.append(term)
            positions = [_POSITION]
        else:
            positions = []
        return httpx.Response(200, json={"status": 200, "data": {"positions": positions, "count": 1}})

    adapter = _adapter(handler)
    jobs = [j async for j in adapter.fetch()]

    # count=1 -> each term fetches one page then stops (start=10 >= 1); the shared
    # req_id dedups the position across every location term.
    assert len(jobs) == 1
    job = jobs[0]
    assert job.company == "microsoft"
    assert job.req_id == "1970393556938818"
    assert job.url == "https://apply.careers.microsoft.com/careers/job/1970393556938818"
    assert "Redmond, WA, US" in job.locations
    assert job.department == "Sales Strategy Enablement"
    assert job.posted_at is not None and job.posted_at.year == 2026
    assert job.description_complete is False
    assert len(first_pages) == _TERM_COUNT  # one search per configured location term


@pytest.mark.asyncio
async def test_hydrate_fetches_detail_and_structures_pay():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/pcsx/search":
            positions = [_POSITION] if request.url.params.get("start") == "0" else []
            return httpx.Response(200, json={"status": 200, "data": {"positions": positions, "count": 1}})
        # position_details
        assert request.url.params.get("position_id") == "1970393556938818"
        return httpx.Response(200, json={"status": 200, "data": {"jobDescription": _DETAIL_HTML}})

    adapter = _adapter(handler)
    job = [j async for j in adapter.fetch()][0]
    await adapter.hydrate(job)
    assert job.description_complete is True

    structure_job_detail(job, adapter.drift, payload=job.detail_payload, source="microsoft")
    keys = {s.key for s in job.description_sections}
    assert "responsibilities" in keys
    assert "qualifications" in keys
    assert "pay_and_benefits" in keys
    assert job.source_disclosed_comp is not None
    assert job.source_disclosed_comp.base_min == 130_900
    assert job.source_disclosed_comp.base_max == 251_900


def test_detail_connector_grounds_pay_and_splits_bold_headers():
    result = MicrosoftDetailConnector().parse_html(_DETAIL_HTML)
    titles = [s.title for s in result.sections]
    assert "Overview" in titles
    assert "Responsibilities" in titles
    assert result.source_disclosed_comp is not None
    assert result.source_disclosed_comp.base_min == 130_900


@pytest.mark.asyncio
async def test_non_200_search_records_drift():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Not authorized"})

    adapter = _adapter(handler)
    jobs = [j async for j in adapter.fetch()]
    assert jobs == []
    assert any(a["message"] == "non-200 search" for a in adapter.drift.alerts)
