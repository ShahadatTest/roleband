"""Oracle Cloud HCM: paging inside the finder, completeness, detail.

The contracts, each on what a seeker would get wrong if it broke:

* **Paging moves.** `offset` travels inside `finder` (outside it, page 1 repeats
  forever) and the walk stops at the declared total.
* **Complete means proved.** unique == `TotalJobsCount` is complete. A shortfall
  is complete only when the listed postings equal the workplace-type facet total
  (Fortinet's counted-but-unlistable posting, noted); any other shortfall —
  including one caused by rows repeating across pages — invalidates.
* **Detail adds the body, never the recruiter.** `hydrate` reads the
  description, workplace and category; contact fields are never copied.

"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tracker.connectors import build_adapter
from tracker.connectors.listing.oracle import declared_total, parse_tenant
from tracker.platform.ratelimit import RateLimiter
from tracker.schema import WorkplaceType

FIX = Path(__file__).parent / "fixtures/listings/oracle"
PAGE = json.loads((FIX / "page1.json").read_text())
DETAIL = json.loads((FIX / "detail_23073.json").read_text())
ROWS = PAGE["items"][0]["requisitionList"]
TOKEN = "edel.fa.us2.oraclecloud.com|CX_2001"


def _body(rows, *, total, typed):
    body = {**PAGE["items"][0], "requisitionList": rows, "TotalJobsCount": total}
    body["workplaceTypesFacet"] = (
        [] if typed is None else [{"Id": "ORA_ON_SITE", "Name": "On-site", "TotalCount": typed}]
    )
    return {"items": [body]}


def _adapter(pages: dict[int, dict], detail=DETAIL):
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("recruitingCEJobRequisitionDetails"):
            return httpx.Response(200, json=detail)
        finder = request.url.params["finder"]
        offset = int(finder.split("offset=")[1].split(",")[0])
        return httpx.Response(200, json=pages.get(offset, _body([], total=0, typed=None)))

    adapter = build_adapter("fortinet", "oracle", board_token=TOKEN)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    return adapter, requests


async def _jobs(adapter):
    return [job async for job in adapter.fetch()]


def _rows(n, start=0):
    return [{**ROWS[i % len(ROWS)], "Id": str(90000 + start + i)} for i in range(n)]


@pytest.mark.asyncio
async def test_offset_travels_inside_the_finder_and_the_walk_stops_at_the_total():
    first, second = _rows(200), _rows(50, start=200)
    adapter, requests = _adapter({
        0: _body(first, total=250, typed=250),
        200: _body(second, total=250, typed=250),
    })
    jobs = await _jobs(adapter)

    assert len(jobs) == 250 and adapter.drift.listing_complete and adapter.drift.alerts == []
    finders = [r.url.params["finder"] for r in requests]
    assert finders == [
        "findReqs;siteNumber=CX_2001,limit=200,offset=0,sortBy=POSTING_DATES_DESC",
        "findReqs;siteNumber=CX_2001,limit=200,offset=200,sortBy=POSTING_DATES_DESC",
    ]
    assert all("offset" not in r.url.params for r in requests), "outside the finder it is ignored"


@pytest.mark.asyncio
async def test_facet_cardinality_cannot_authorize_closure_of_an_unread_posting():
    """Equal facet counts do not identify the missing requisition."""
    adapter, _ = _adapter({0: _body(ROWS, total=len(ROWS) + 1, typed=len(ROWS))})
    jobs = await _jobs(adapter)

    assert len(jobs) == len(ROWS)
    assert not adapter.drift.listing_complete
    assert adapter.drift.records_dropped == 1


@pytest.mark.asyncio
async def test_a_small_facet_shortfall_is_lossy_and_never_counts_against_the_source():
    from tracker.connectors.recipes.outcome import (
        RESETS_ABSENCE,
        SourceOutcome,
        classify_source_outcome,
    )

    adapter, _ = _adapter({
        offset: _body(_rows(min(200, 937 - offset), start=offset), total=938, typed=937)
        for offset in range(0, 937, 200)
    })
    jobs = await _jobs(adapter)
    assert len(jobs) == 937 and not adapter.drift.listing_complete
    outcome = classify_source_outcome({
        "scanned": len(jobs), "records_dropped": adapter.drift.records_dropped,
        "listing_invalidated": adapter.drift.listing_invalidated, "list_complete": False,
    })
    assert outcome is SourceOutcome.LOSSY
    assert outcome not in RESETS_ABSENCE


@pytest.mark.asyncio
@pytest.mark.parametrize("typed", [None, 5])
async def test_a_shortfall_nothing_explains_invalidates(typed):
    adapter, _ = _adapter({0: _body(ROWS, total=len(ROWS) + 1, typed=typed)})
    await _jobs(adapter)
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_rows_repeating_across_pages_are_never_a_complete_listing():
    """An unstable order repeats a row and hides another: 250 declared and typed,
    249 unique. The facet total does not match, so it is loss."""
    first = _rows(200)
    second = [first[0], *_rows(49, start=200)]
    adapter, _ = _adapter({
        0: _body(first, total=250, typed=250),
        200: _body(second, total=250, typed=250),
    })
    jobs = await _jobs(adapter)
    assert len(jobs) == 249
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_hydrate_reads_the_body_workplace_and_category_never_the_recruiter():
    detail = json.loads(json.dumps(DETAIL))
    detail["items"][0]["ExternalContactName"] = "Pat Recruiter"
    detail["items"][0]["ExternalContactEmail"] = "pat@fortinet.example"
    adapter, _ = _adapter({0: _body(ROWS, total=len(ROWS), typed=len(ROWS))}, detail=detail)
    job = (await _jobs(adapter))[0]

    await adapter.hydrate(job)

    assert job.description_complete and len(job.description_html) > 1000
    assert job.workplace_type is WorkplaceType.HYBRID
    assert job.department == "Software Development"
    assert job.source_facts.employment_type_raw == "Full time"
    assert "Pat Recruiter" not in repr(job) and "pat@fortinet.example" not in repr(job)
    assert job.url.endswith("/hcmUI/CandidateExperience/en/sites/CX_2001/job/23073")


def test_the_token_is_host_and_site_and_the_checker_reads_the_declared_total():
    assert parse_tenant(TOKEN).site == "CX_2001"
    with pytest.raises(ValueError, match="host\\|site"):
        parse_tenant("edel.fa.us2.oraclecloud.com")
    assert declared_total(json.dumps(_body(ROWS, total=938, typed=937))) == 938
    assert declared_total("<html>not a board</html>") is None
