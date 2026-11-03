"""Each query is held to the total IT declares.

amazon, google, microsoft and workday page one search per location term, and a
board states its size per term, not for the union. So the check runs per term,
over every row that term served — BEFORE the cross-term dedupe, since a posting
listed in two offices is counted in both terms' totals. A term read short of
its own total must not leave the run recorded complete and eligible to close
postings it never read.
"""

from __future__ import annotations

import json

import httpx
import pytest

from tests.scripted_boards import amazon_board, amazon_hit, google_board, results_page
from tracker.connectors.listing.base import RateLimiter
from tracker.connectors.listing.microsoft import MicrosoftAdapter
from tracker.connectors.listing.workday import WorkdayAdapter
from tracker.source_review import SOURCE_REVIEWS

# --- microsoft ---------------------------------------------------------------- #


def _microsoft(terms: dict[str, tuple[int, list[str]]]) -> MicrosoftAdapter:
    """term -> (declared count, ids served on its one page)."""

    def handler(request: httpx.Request) -> httpx.Response:
        term = request.url.params.get("location")
        count, ids = terms[term]
        rows = [{"id": i, "name": f"PM {i}"} for i in ids] if request.url.params.get("start") == "0" else []
        return httpx.Response(200, json={"data": {"count": count, "positions": rows}})

    adapter = MicrosoftAdapter("microsoft")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    return adapter


async def _terms(adapter, fetch, terms: list[str]) -> list:
    seen: set[str] = set()
    out = []
    for term in terms:
        out.extend([job async for job in fetch(term, seen)])
    return out


@pytest.mark.asyncio
async def test_a_posting_in_two_terms_counts_toward_both_totals():
    """The dedupe runs after the count: `m2` is in both terms, and each term's
    `count` includes it. Counting after the dedupe would read London 2-of-2 as
    1-of-2 and invent a loss on every multi-office posting."""
    adapter = _microsoft({"United Kingdom": (2, ["m1", "m2"]), "London": (2, ["m2", "m3"])})
    jobs = await _terms(adapter, adapter._fetch_term, ["United Kingdom", "London"])

    assert sorted(job.req_id for job in jobs) == ["m1", "m2", "m3"]
    assert adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_term_that_reads_short_is_counted_loss_not_a_broken_board():
    """The US query declares more than it serves."""
    adapter = _microsoft({"United States": (5, ["m1", "m2", "m3", "m4"])})
    await _terms(adapter, adapter._fetch_term, ["United States"])

    assert not adapter.drift.listing_complete
    assert not adapter.drift.listing_invalidated
    assert adapter.drift.records_dropped == 1
    [alert] = adapter.drift.alerts
    assert (alert["message"], alert["term"]) == ("fewer unique postings than count", "United States")


# --- workday ------------------------------------------------------------------ #


def _workday(terms: dict[str, tuple[int, list[str]]]) -> WorkdayAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        total, ids = terms[body["searchText"]]
        rows = [
            {"title": f"EM {i}", "externalPath": f"/job/X/EM_{i}", "locationsText": "US, CA, Santa Clara",
             "bulletFields": [i]}
            for i in ids
        ] if body["offset"] == 0 else []
        return httpx.Response(200, json={"total": total, "jobPostings": rows})

    adapter = WorkdayAdapter("nvidia")
    adapter.collection_consent = SOURCE_REVIEWS["workday"].wall_fingerprint
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    return adapter


async def _workday_terms(adapter, terms: list[str]) -> list:
    board = adapter._resolve()
    seen: set[str] = set()
    out = []
    for term in terms:
        out.extend([job async for job in adapter._fetch_term(board.cxs + "/jobs", board, term, seen)])
    return out


@pytest.mark.asyncio
async def test_workday_holds_each_term_to_its_total_across_overlapping_terms():
    adapter = _workday({"Santa Clara": (2, ["JR1", "JR2"]), "United States": (3, ["JR1", "JR2", "JR3"])})
    jobs = await _workday_terms(adapter, ["Santa Clara", "United States"])

    assert len(jobs) == 3
    assert adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_workday_short_term_is_counted():
    adapter = _workday({"United States": (4, ["JR1", "JR2", "JR3"])})
    await _workday_terms(adapter, ["United States"])
    assert (adapter.drift.listing_complete, adapter.drift.records_dropped) == (False, 1)


@pytest.mark.asyncio
async def test_workday_total_at_the_window_is_the_window_not_a_count():
    """CXS caps `total` at 2000 (Applied Materials' whole board declares
    exactly that). Holding a capped term to 2000 would score a 'loss' of the
    difference against a healthy board; it is our view that ended, so the run
    is `truncated` — no closure, no health change."""
    adapter = _workday({"United States": (2000, ["JR1", "JR2", "JR3"])})
    await _workday_terms(adapter, ["United States"])

    assert adapter.truncated is True
    assert adapter.drift.records_dropped == 0
    assert not adapter.drift.listing_invalidated


# --- amazon ------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_amazon_group_that_reads_short_is_counted():
    pages = {"0": {"hits": 150, "jobs": [amazon_hit(i) for i in range(100)]},
             "100": {"hits": 150, "jobs": [amazon_hit(i) for i in range(100, 148)]}}
    adapter = amazon_board(pages, [])
    jobs = [job async for job in adapter._fetch_group(("united_states", [("normalized_country_code[]", "USA")]), set())]

    assert len(jobs) == 148
    assert (adapter.drift.listing_complete, adapter.drift.records_dropped) == (False, 2)


# --- google ------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_google_is_held_to_a_total_only_where_the_page_states_one():
    short = {"1": results_page(first=1, last=20, total=25, ids=range(0, 20))}
    adapter = google_board(short, [])
    await _terms(adapter, adapter._fetch_location, ["United States"])
    assert (adapter.drift.listing_complete, adapter.drift.records_dropped) == (False, 5)

    # No "Showing .. of N rows" marker: google does not declare a total, and a
    # missing marker is not drift, so there is nothing to be held to.
    unmarked = {"1": results_page(first=1, last=20, total=25, ids=range(0, 20)).replace("Showing", "Seen")}
    adapter = google_board(unmarked, [])
    await _terms(adapter, adapter._fetch_location, ["United States"])
    assert adapter.drift.listing_complete
