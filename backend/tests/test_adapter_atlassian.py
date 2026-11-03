"""Atlassian's own careers endpoint.

The contracts, each on what a seeker would get wrong if it broke:

* **Locations are places.** Every supported form of `"City - Country - address"`
  becomes a city or a country, never the typed street address; remote entries
  mark the role remote without inventing a place.
* **Repeats are not losses.** The endpoint repeats rows verbatim; they are
  deduplicated with no alert, and a repeat that DIFFERS is noted, not dropped.
* **Pay comes only from the pay block.** A band is read from `payRanges` alone;
  the `compensation` paragraph is prose, even if it contains a number.
* **The token checker can read it.** The probe targets the one fixed route and
  reports identity `unstated` (the listing names no tenant).

"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts.check_catalog_tokens import (
    CATALOG_ONLY,
    LIVE,
    UNSTATED,
    Probe,
    board_probe_for,
    check_probe,
)
from tracker.connectors import build_adapter, structure_job_detail
from tracker.connectors.detail.base import PAY_SECTION_KEY, sections_to_text
from tracker.connectors.listing.atlassian import LISTINGS_URL, parse_location
from tracker.intelligence_runtime.disclosed_comp import pay_input_text
from tracker.platform.ratelimit import RateLimiter
from tracker.schema import WorkplaceType

ROWS = json.loads((Path(__file__).parent / "fixtures/listings/atlassian/page1.json").read_text())


def _adapter(payload=ROWS, status=200):
    adapter = build_adapter("atlassian", "atlassian")
    adapter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(status, json=payload))
    )
    adapter._limiter = RateLimiter(0)
    return adapter


async def _jobs(adapter):
    return [job async for job in adapter.fetch()]


@pytest.mark.parametrize(("raw", "label", "remote"), [
    ("San Francisco - United States -   San Francisco, California 94104 United States",
     "San Francisco, United States", False),
    ("Remote - UK - Remote", "UK", True),
    ("Remote - Remote", None, True),
    ("Mountain View - United States or Remote -   Mountain View, California 94041 United States",
     "Mountain View, United States", True),
    ("Canada -     Canada", "Canada", False),
    ("Remote - Netherlands -     Netherlands", "Netherlands", True),
    ("Gdańsk - Poland -   Gdańsk,  80-280 Poland", "Gdańsk, Poland", False),
])
def test_every_measured_location_form_becomes_a_place(raw, label, remote):
    place, is_remote = parse_location(raw)
    assert (place.label if place else None) == label
    assert is_remote is remote
    assert not any(ch.isdigit() for ch in (label or "")), "never the typed street address"


@pytest.mark.asyncio
async def test_verbatim_repeats_are_deduplicated_without_an_alert():
    adapter = _adapter()
    jobs = await _jobs(adapter)

    assert len(ROWS) == 7 and len(jobs) == 5
    assert len({j.req_id for j in jobs}) == 5
    assert adapter.drift.listing_complete and adapter.drift.alerts == []
    japan = next(j for j in jobs if j.req_id == "25583")
    assert japan.locations == ["Japan"] and japan.workplace_type is WorkplaceType.REMOTE
    offices = next(j for j in jobs if j.req_id == "26268")
    assert offices.locations == ["San Francisco, United States", "Seattle, United States"]
    assert offices.workplace_type is WorkplaceType.UNKNOWN, "no remote entry: not asserted either way"
    assert all(j.department for j in jobs)
    # The posting's own page on whichever Atlassian iCIMS portal hosts it
    # (interns sit on `campus-americas`, most roles on `globalcareers-atlassian`).
    assert httpx.URL(offices.url).host.endswith(".icims.com") and "/jobs/26268/" in offices.url


@pytest.mark.asyncio
async def test_a_repeat_that_differs_is_noted_and_the_first_kept():
    first = ROWS[0]
    changed = {**first, "title": "Something else"}
    adapter = _adapter([first, changed])
    jobs = await _jobs(adapter)

    assert [j.title for j in jobs] == [first["title"]]
    assert any("different content" in str(a) for a in adapter.drift.alerts)
    assert adapter.drift.listing_complete, "a changed repeat is not a lost posting"


@pytest.mark.asyncio
@pytest.mark.parametrize(("payload", "status"), [({"jobs": []}, 200), (ROWS, 503)])
async def test_a_payload_that_is_not_the_board_invalidates_the_listing(payload, status, monkeypatch):
    from tracker.config import get_settings

    monkeypatch.setattr(get_settings(), "scraper_max_retries", 0)
    adapter = _adapter(payload, status)
    assert await _jobs(adapter) == []
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_the_band_is_read_from_the_pay_block_only():
    adapter = _adapter()
    jobs = {j.req_id: j for j in await _jobs(adapter)}

    salaried = jobs["25813"]
    structure_job_detail(salaried, adapter.drift, payload=salaried.detail_payload, source="atlassian")
    comp = salaried.source_disclosed_comp
    assert (comp.base_min, comp.base_max, comp.currency) == (122400, 159800, "USD")
    pay = salaried.description_sections[-1]
    assert pay.key == PAY_SECTION_KEY
    # The model pay pass reads that block, not the whole description.
    stored = SimpleNamespace(
        description_sections=[s.as_dict() for s in salaried.description_sections],
        description_text=sections_to_text(salaried.description_sections),
    )
    assert pay_input_text(stored) == (pay.content, "pay_section")

    # Negative control: figures in the philosophy paragraph are never a band.
    row = {**salaried.detail_payload, "payRanges": None,
           "compensation": "<p>Base pay between $100,000 - $150,000 is typical in the industry.</p>"}
    job = next(j for j in await _jobs(_adapter([row])))
    structure_job_detail(job, adapter.drift, payload=job.detail_payload, source="atlassian")
    assert job.source_disclosed_comp is None
    assert job.description_sections, "the prose is still kept"


@pytest.mark.asyncio
async def test_the_token_checker_reads_the_fixed_route():
    probe = board_probe_for("atlassian")
    assert probe.url_for("atlassian") == LISTINGS_URL
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=ROWS))) as client:
        result = await check_probe(client, Probe("atlassian", "atlassian", "atlassian", CATALOG_ONLY))
    assert result["state"] == LIVE and result["identity"] == UNSTATED
