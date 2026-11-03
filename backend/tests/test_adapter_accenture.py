"""Accenture's own careers search API.

The contracts, each on what a seeker would get wrong if it broke:

* **The stable sort, paged as a form.** Every request posts `sortBy=1` (the
  relevance sort repeats rows) and advances
  `startIndex` by the page size.
* **Complete per country, or not at all.** Unique ids equal to the country's
  `totalHits` is complete; repeats, a total at the 10,000 window, or
  `overMaxHits` invalidate. A posting listed in two countries is yielded once
  but counts toward both totals.
* **Only tracked countries are asked**, with the API's own country names.

"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tracker.connectors import build_adapter
from tracker.platform.ratelimit import RateLimiter
from tracker.schema import WorkplaceType

PAGE = json.loads((Path(__file__).parent / "fixtures/listings/accenture/page1.json").read_text())
ROWS = PAGE["data"]


def _body(rows, total, over="False"):
    return {**PAGE, "data": rows, "totalHits": {"total": total, "overMaxHits": over}}


def _adapter(pages_by_country: dict[str, dict[int, dict]], groups=("united_states",)):
    forms: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode()))
        forms.append({**form, "_content_type": request.headers.get("content-type")})
        pages = pages_by_country.get(form["jobCountry"], {})
        return httpx.Response(200, json=pages.get(int(form["startIndex"]), _body([], 0)))

    adapter = build_adapter("accenture", "accenture", location_groups=list(groups))
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    return adapter, forms


async def _jobs(adapter):
    return [job async for job in adapter.fetch()]


def _rows(n, start=0):
    return [{**ROWS[i % len(ROWS)], "requisitionId": f"R{900000 + start + i}"} for i in range(n)]


@pytest.mark.asyncio
async def test_every_request_is_the_stable_sort_paged_as_a_form():
    adapter, forms = _adapter({"USA": {0: _body(_rows(100), 150), 100: _body(_rows(50, 100), 150)}})
    jobs = await _jobs(adapter)

    assert len(jobs) == 150 and adapter.drift.listing_complete
    assert [(f["startIndex"], f["sortBy"], f["jobCountry"], f["countrySite"]) for f in forms] == [
        ("0", "1", "USA", "us-en"), ("100", "1", "USA", "us-en"),
    ]
    assert all(f["_content_type"] == "application/x-www-form-urlencoded" for f in forms)


@pytest.mark.asyncio
async def test_rows_repeating_across_pages_are_never_complete():
    first = _rows(100)
    adapter, _ = _adapter({"USA": {0: _body(first, 150), 100: _body([first[0], *_rows(49, 100)], 150)}})
    jobs = await _jobs(adapter)
    assert len(jobs) == 149 and not adapter.drift.listing_complete


@pytest.mark.asyncio
@pytest.mark.parametrize(("total", "over"), [(10000, "False"), (40, "True")])
async def test_a_total_at_the_result_window_is_not_a_count(total, over):
    adapter, _ = _adapter({"USA": {0: _body(_rows(40), total, over)}})
    await _jobs(adapter)
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_posting_in_two_countries_is_yielded_once_and_counted_in_both():
    shared = _rows(3)
    adapter, forms = _adapter(
        {"USA": {0: _body(shared, 3)}, "United Kingdom": {0: _body([shared[0], *_rows(2, 50)], 3)}},
        groups=("united_states", "uk"),
    )
    jobs = await _jobs(adapter)

    assert len(jobs) == 5
    assert adapter.drift.listing_complete, "the repeat is another country's listing, not a loss"
    assert {f["jobCountry"] for f in forms} == {"USA", "United Kingdom"}


@pytest.mark.asyncio
async def test_only_tracked_countries_are_asked():
    adapter, forms = _adapter({"United Kingdom": {0: _body(_rows(2), 2)}}, groups=("uk",))
    await _jobs(adapter)
    assert {(f["jobCountry"], f["countrySite"]) for f in forms} == {("United Kingdom", "gb-en")}


@pytest.mark.asyncio
async def test_a_row_becomes_a_job_with_its_rung_place_and_page():
    adapter, _ = _adapter({"USA": {0: _body(ROWS, len(ROWS))}})
    job = next(j for j in await _jobs(adapter) if j.req_id == "R00358194")

    assert job.raw_level == "Senior Analyst"
    assert job.locations == ["San Francisco, CA"]
    assert job.workplace_type is WorkplaceType.ONSITE
    assert job.url.startswith("https://www.accenture.com/us-en/careers/jobdetails?id=R00358194_en")
    assert job.description_complete and "We Are" in job.description_html
    assert job.team is None, "businessArea is not a team"


# --- The board probe -------------------------------------------- #
# The search route answers only the adapter's form POST; a GET answers 404
# HTML, which `check_catalog_tokens` reads as a dead board. The mock answers
# that way, so a probe using GET, JSON, or an unconfigured country fails.


def _probe_transport(seen: list[httpx.Request]):
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method != "POST":
            return httpx.Response(404, text="<title>Page Not Found | Accenture</title>")
        if request.headers.get("content-type") != "application/x-www-form-urlencoded":
            return httpx.Response(400, text="bad form")
        form = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(200, json=_body(ROWS[: int(form["maxResultSize"])], 888))

    return httpx.MockTransport(handle)


@pytest.mark.asyncio
async def test_board_probe_sends_the_adapters_own_form_post():
    from scripts.check_catalog_tokens import CATALOG_ONLY, LIVE, Probe, check_probe

    seen: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_probe_transport(seen)) as client:
        result = await check_probe(client, Probe("accenture", "accenture", "accenture", CATALOG_ONLY))

    assert result["state"] == LIVE, result
    # One US row proves the route serves the board, not the board's size.
    assert result["capped"] is True and result["count"] == 1
    assert [r.method for r in seen] == ["POST"]


@pytest.mark.asyncio
async def test_board_probe_asks_what_the_adapter_asks():
    from scripts.check_catalog_tokens import board_probe_for

    adapter, forms = _adapter({"USA": {0: _body(ROWS[:2], 2)}})
    [job async for job in adapter.fetch()]
    probe = board_probe_for("accenture")
    assert probe is not None and probe.probe_body is not None

    sent = forms[0]
    expected = {k: v for k, v in sent.items() if k not in {"startIndex", "maxResultSize", "_content_type"}}
    assert {k: v for k, v in probe.probe_body.items() if k in expected} == expected
    assert set(probe.probe_body) == set(sent) - {"_content_type"}
    assert (probe.method, probe.probe_encoding) == ("POST", "form")
    assert probe.url_for("accenture") == str(adapter.board_probe.jobs_url)
