"""TikTok's search API: whole postings from the listing, pay from the page."""

from __future__ import annotations

import json

import httpx
import pytest

from tests.contracts.conftest import fixture_dir, load_fixture
from tracker.connectors import build_adapter, structure_job_detail
from tracker.connectors.listing.tiktok import PAGE_SIZE, pay_block, place_label
from tracker.enrich.classify import location_groups_for
from tracker.platform.ratelimit import RateLimiter
from tracker.schema import EmploymentType

PAGE = load_fixture("tiktok", "page1.json")
POSTING = (fixture_dir("tiktok") / "posting_7686714309884578101.html").read_text()


def _adapter(pages: list[dict], posting: str = POSTING):
    asked: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=posting)
        assert request.headers.get("website-path") == "tiktok"
        body = json.loads(request.content)
        asked.append(body)
        index = body["offset"] // body["limit"]
        return httpx.Response(200, json=pages[index] if index < len(pages) else pages[-1])

    adapter = build_adapter("tiktok", "tiktok")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0.0)
    return adapter, asked


def _page(rows: list[dict], count: int) -> dict:
    return {**PAGE, "data": {"job_post_list": rows, "count": count}}


async def _fetch(adapter):
    try:
        return [job async for job in adapter.fetch()]
    finally:
        await adapter._client.aclose()


@pytest.mark.asyncio
async def test_a_row_is_a_whole_posting_at_a_classifiable_place():
    adapter, asked = _adapter([PAGE])
    jobs = {job.req_id: job for job in await _fetch(adapter)}

    assert asked == [{**asked[0], "offset": 0, "limit": PAGE_SIZE}], "one page answers a board under its size"
    manager = jobs["7686714309884578101"]
    assert manager.title == "Workplace Manager"
    assert manager.url == "https://lifeattiktok.com/search/7686714309884578101"
    assert manager.locations == ["San Jose, California, United States of America"]
    assert manager.department == "Corporate Function / Support"
    assert manager.description_complete and "Minimum Qualification" in manager.description_html
    structure_job_detail(manager, adapter.drift, payload=manager.detail_payload, source="tiktok")
    assert [section.key for section in manager.description_sections] == ["responsibilities", "qualifications"]
    assert manager.source_disclosed_comp is None, "the listing states no pay"
    assert manager.source_facts.requisition_label == "A248054"
    assert manager.source_facts.employment_type_normalized is EmploymentType.FULL_TIME
    assert jobs["7665646635395188997"].source_facts.employment_type_normalized is EmploymentType.INTERN

    # Every place the fixture carries lands in exactly its own country.
    countries = {job.locations[0]: location_groups_for(job.locations) for job in jobs.values()}
    assert "singapore" in countries["Singapore"]
    assert "uk" in countries["London, England, United Kingdom"]
    assert "south_korea" in countries["Seoul, Korea, Republic of"]
    sydney = countries["Sydney, New South Wales, Australia"]
    assert "australia" in sydney and "uk" not in sydney, "New South Wales is not Wales"
    assert adapter.drift.listing_complete


def test_a_place_chain_drops_the_names_it_repeats():
    city = {"en_name": "Singapore", "parent": {"en_name": "Singapore", "parent": {"en_name": "Singapore"}}}
    assert place_label(city) == "Singapore"
    assert place_label(None) is None


@pytest.mark.asyncio
async def test_pages_are_walked_by_offset_until_the_stated_count():
    rows = PAGE["data"]["job_post_list"]
    first = [{**rows[i % 5], "id": f"9{i:05d}"} for i in range(PAGE_SIZE)]
    second = [{**rows[0], "id": "800001"}, {**rows[1], "id": "800002"}]
    adapter, asked = _adapter([_page(first, PAGE_SIZE + 2), _page(second, PAGE_SIZE + 2)])
    jobs = await _fetch(adapter)
    assert [body["offset"] for body in asked] == [0, PAGE_SIZE]
    assert len(jobs) == PAGE_SIZE + 2 and adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_fewer_postings_than_the_stated_count_keeps_nothing_closed():
    adapter, _ = _adapter([_page(PAGE["data"]["job_post_list"], 9)])
    jobs = await _fetch(adapter)
    assert len(jobs) == 5
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_refused_page_invalidates_the_listing():
    adapter = build_adapter("tiktok", "tiktok")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _r: httpx.Response(400, json={"code": 1, "message": "invalid request"})))
    adapter._limiter = RateLimiter(0.0)
    assert await _fetch(adapter) == []
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_hydrate_reads_the_us_pay_band_from_the_posting_page():
    adapter, _ = _adapter([PAGE])
    jobs = {job.req_id: job for job in await _fetch(adapter)}
    job = jobs["7686714309884578101"]
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, text=POSTING)))
    try:
        await adapter.hydrate(job)
    finally:
        await adapter._client.aclose()
    # The collector's next step, through the registry as it runs it.
    structure_job_detail(job, adapter.drift, payload=job.detail_payload, source="tiktok")
    assert (job.source_disclosed_comp.base_min, job.source_disclosed_comp.base_max) == (115200, 180000)
    assert [section.key for section in job.description_sections] == [
        "responsibilities", "qualifications", "pay_and_benefits",
    ]
    assert "Minimum Qualification(s):\n- Bachelor" in job.description_sections[1].content, "lines survive"


@pytest.mark.asyncio
async def test_a_posting_page_without_pay_leaves_the_band_unstated():
    adapter, _ = _adapter([PAGE])
    job = next(j for j in await _fetch(adapter) if j.req_id == "7686714309884578101")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _r: httpx.Response(200, text="<html><body><p>Job Information</p></body></html>")))
    try:
        await adapter.hydrate(job)
    finally:
        await adapter._client.aclose()
    structure_job_detail(job, adapter.drift, payload=job.detail_payload, source="tiktok")
    assert job.source_disclosed_comp is None
    assert [section.key for section in job.description_sections] == ["responsibilities", "qualifications"]


def test_a_page_without_a_pay_heading_states_no_pay():
    assert pay_block("<html><body><p>Job Information</p><div>Benefits only</div></body></html>") is None
    assert "$115200 - $180000" in pay_block(POSTING)
