"""Accenture's Workday board, for the countries its own search cannot answer.

The contracts, each on what a seeker would get wrong if it broke:

* **The exact country filter, never the word search.** A board query sends the
  country's `locationCountry` facet id, read from the board's own first answer,
  and an empty `searchText`; the word search returns postings that only mention
  the country.
* **A row is placed where the board says.** The rows name no `locationsText`;
  the place is the bullet after the id. The filter matches a posting with any
  place in the country, so a primary place elsewhere ("Copenhagen" under
  Sweden) is kept apart from the country, never joined to it.
* **Complete per country, or not at all.** Ids equal to the board's total is
  complete; a total at the 2,000 window, or an unreadable country list, is not.
  A country the list leaves out has no roles: complete and empty.
* **One posting, once.** The board's ids are the own search's, so a posting on
  both is yielded once.
* **Text from the detail, for board rows only.** Own-search rows carry their
  text inline and are never sent to the board.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from tracker.connectors import build_adapter
from tracker.connectors.listing.accenture import (
    ACCENTURE_LOCATION_QUERIES,
    BOARD,
    OWN_SEARCH_QUERIES,
    BoardCountry,
    OwnSearch,
    board_country_facets,
)
from tracker.platform.ratelimit import RateLimiter
from tracker.taxonomy.countries import COUNTRIES

FIXTURES = Path(__file__).parent / "fixtures/listings/accenture"
FACETS = json.loads((FIXTURES / "board_facets.json").read_text())
SWEDEN_PAGE = json.loads((FIXTURES / "board_sweden_page1.json").read_text())
DETAIL = json.loads((FIXTURES / "board_detail.json").read_text())
OWN_PAGE = json.loads((FIXTURES / "page1.json").read_text())
SWEDEN_ID = "6a800a4736884df5826858d435650f45"
JOBS_URL = BOARD.cxs + "/jobs"


def _country_list(**extra):
    return {**FACETS, **extra}


def _board_rows(n, start):
    return [
        {"title": f"Role {i}", "externalPath": f"/job/Stockholm/Role_R0099{start + i:04d}",
         "postedOn": "Posted Today", "bulletFields": [f"R0099{start + i:04d}", "Stockholm"]}
        for i in range(n)
    ]


def _adapter(*, board=None, own=None, facets=None, groups=("sweden",), board_only=("sweden",)):
    """Sweden is answered by the own search in production; the tests read it
    from the board instead, because the captured board page is Sweden's."""
    sent: list[httpx.Request] = []
    board = board or {0: SWEDEN_PAGE, 20: {"total": 38, "jobPostings": _board_rows(18, 0)}}

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        url = str(request.url)
        if url == JOBS_URL:
            body = json.loads(request.content)
            if not body["appliedFacets"]:
                return facets or httpx.Response(200, json=_country_list())
            return httpx.Response(200, json=board.get(body["offset"], {"total": 38, "jobPostings": []}))
        if url.startswith(BOARD.cxs + "/job/"):
            return httpx.Response(200, json=DETAIL)
        form = dict(httpx.QueryParams(request.content.decode()))
        page = (own or {}).get(form["jobCountry"])
        return httpx.Response(200, json=page or {**OWN_PAGE, "data": [], "totalHits": {"total": 0}})

    adapter = build_adapter("accenture", "accenture", location_groups=list(groups))
    adapter.location_queries = {
        **ACCENTURE_LOCATION_QUERIES, **{slug: [BoardCountry(slug)] for slug in board_only},
    }
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    return adapter, sent


def _board_bodies(sent):
    return [json.loads(r.content) for r in sent if str(r.url) == JOBS_URL]


async def _jobs(adapter):
    return [job async for job in adapter.fetch()]


@pytest.mark.asyncio
async def test_a_board_country_is_asked_by_its_exact_filter_from_the_boards_own_list():
    adapter, sent = _adapter()
    jobs = await _jobs(adapter)

    bodies = _board_bodies(sent)
    assert bodies[0] == {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
    assert [(b["appliedFacets"], b["offset"], b["searchText"]) for b in bodies[1:]] == [
        ({"locationCountry": [SWEDEN_ID]}, 0, ""), ({"locationCountry": [SWEDEN_ID]}, 20, ""),
    ]
    assert len(jobs) == 38 and adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_board_row_names_its_place_and_the_country_apart():
    adapter, _ = _adapter()
    by_id = {job.req_id: job for job in await _jobs(adapter)}

    stockholm = by_id["R00363247"]
    assert stockholm.locations == ["Stockholm", "Sweden"]
    assert stockholm.url == BOARD.posting_url(SWEDEN_PAGE["jobPostings"][0]["externalPath"])
    assert not stockholm.description_complete and stockholm.raw_level is None
    # Primary place in Denmark, a second place in Sweden: never "Copenhagen, Sweden".
    assert by_id["R00361460"].locations == ["Copenhagen", "Sweden"]
    # "Location Negotiable" holds the place slot and names no place.
    assert by_id["R00294116"].locations == ["Sweden"]
    # The path's "-1" suffix is not part of the id.
    assert "R00363445" in by_id


@pytest.mark.asyncio
async def test_a_board_country_at_the_window_is_not_a_count():
    adapter, _ = _adapter(board={0: {**SWEDEN_PAGE, "total": 2000}})
    await _jobs(adapter)
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_fewer_board_rows_than_its_total_is_never_complete():
    adapter, _ = _adapter(board={0: SWEDEN_PAGE})  # 20 rows of a stated 38
    await _jobs(adapter)
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_an_unreadable_country_list_is_never_complete():
    adapter, sent = _adapter(facets=httpx.Response(200, text="<html>maintenance</html>"), groups=("sweden", "uk"),
                             own={"United Kingdom": {**OWN_PAGE, "data": OWN_PAGE["data"][:2], "totalHits": {"total": 2}}})
    jobs = await _jobs(adapter)
    assert len(jobs) == 2, "the own search's countries still collect"
    assert not adapter.drift.listing_complete
    assert len(_board_bodies(sent)) == 1, "no country is asked without its filter"


@pytest.mark.asyncio
async def test_a_country_the_list_leaves_out_has_no_roles():
    uk_rows = OWN_PAGE["data"][:2]
    adapter, sent = _adapter(groups=("iceland", "uk"), board_only=("iceland",),
                             own={"United Kingdom": {**OWN_PAGE, "data": uk_rows, "totalHits": {"total": 2}}})
    jobs = await _jobs(adapter)
    assert len(jobs) == 2 and adapter.drift.listing_complete
    assert len(_board_bodies(sent)) == 1, "only the country list was read"


def test_a_board_country_we_cannot_place_is_named():
    body = json.loads(json.dumps(FACETS))
    body["facets"][0]["values"][0]["values"].append({"descriptor": "Atlantis", "id": "x", "count": 3})
    ids, unknown = board_country_facets(body)
    assert unknown == ["Atlantis"]
    # Workday's own spellings resolve to our countries.
    assert ids["sweden"] == SWEDEN_ID
    assert {"china", "hong_kong", "united_states", "czechia", "turkey"} <= set(ids)
    # The city facet beside it is not read as countries.
    assert not set(ids) & {"stockholm", "london"}


@pytest.mark.asyncio
async def test_an_unplaceable_board_country_is_noted_in_the_scan():
    body = json.loads(json.dumps(FACETS))
    body["facets"][0]["values"][0]["values"].append({"descriptor": "Atlantis", "id": "x", "count": 3})
    adapter, _ = _adapter(facets=httpx.Response(200, json=body))
    await _jobs(adapter)
    notes = [a for a in adapter.drift.alerts if a["message"] == "board names countries we cannot place"]
    assert notes and notes[0]["names"] == ["Atlantis"]


@pytest.mark.asyncio
async def test_a_posting_on_both_surfaces_is_yielded_once():
    shared = {**OWN_PAGE["data"][0], "requisitionId": "R00363247"}
    adapter, _ = _adapter(groups=("sweden", "uk"),
                          own={"United Kingdom": {**OWN_PAGE, "data": [shared], "totalHits": {"total": 1}}})
    jobs = await _jobs(adapter)
    assert [j.req_id for j in jobs].count("R00363247") == 1
    assert len(jobs) == 38 and adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_hydrate_reads_board_rows_from_the_detail_and_leaves_own_rows_alone():
    uk_rows = OWN_PAGE["data"][:1]
    adapter, sent = _adapter(groups=("sweden", "uk"),
                             own={"United Kingdom": {**OWN_PAGE, "data": uk_rows, "totalHits": {"total": 1}}})
    jobs = {job.req_id: job for job in await _jobs(adapter)}
    board_job, own_job = jobs["R00363247"], jobs[uk_rows[0]["requisitionId"]]
    own_text = own_job.description_html

    before = len(sent)
    await adapter.hydrate(own_job)
    assert len(sent) == before and own_job.description_html == own_text

    await adapter.hydrate(board_job)
    assert str(sent[-1].url) == BOARD.cxs + SWEDEN_PAGE["jobPostings"][0]["externalPath"]
    assert board_job.description_complete
    assert board_job.description_html == DETAIL["jobPostingInfo"]["jobDescription"]
    assert board_job.posted_at == datetime.fromisoformat("2026-10-19").replace(tzinfo=board_job.posted_at.tzinfo)
    assert board_job.locations == ["Stockholm", "Sweden"]


@pytest.mark.asyncio
async def test_hydrate_from_the_url_alone():
    """The description backfill rebuilds a stored posting from its url."""
    adapter, sent = _adapter()
    job = next(j for j in await _jobs(adapter) if j.req_id == "R00363247")
    job.detail_payload = None
    await adapter.hydrate(job)
    assert job.description_complete


def test_every_country_but_india_is_declared():
    declared = set(ACCENTURE_LOCATION_QUERIES)
    assert "india" not in declared, "India answers each surface's window, not a count"
    assert {c.slug for c in COUNTRIES} - {"india"} <= declared


def test_the_own_search_answers_every_country_it_has_a_recipe_for():
    assert all(ACCENTURE_LOCATION_QUERIES[slug] == terms for slug, terms in OWN_SEARCH_QUERIES.items())
    assert ACCENTURE_LOCATION_QUERIES["france"] == [BoardCountry("france")]
    assert ACCENTURE_LOCATION_QUERIES["germany"] == [OwnSearch("Deutschland", "de-de", "de")]
