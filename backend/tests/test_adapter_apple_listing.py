"""Apple search listing — the soft-empty page is a flake, not the end.

jobs.apple.com intermittently answers a mid-listing page with
`{"totalRecords": 0, "searchResults": []}`; the same request repeated returns
the real page. Read as the end of the board it invalidates the run and, run
after run, quarantines the binding. A page past the real end answers the
same bytes, so these tests pin the only thing that tells them apart: position
relative to the declared total.
"""

from __future__ import annotations

import json
from collections import Counter

import httpx
import pytest

from tracker.connectors import build_adapter
from tracker.connectors.listing.apple import _SOFT_EMPTY_ATTEMPTS
from tracker.connectors.listing.base import RateLimiter
from tracker.connectors.recipes.outcome import classify_source_outcome
from tracker.platform.paging import StopReason
from tracker.schema import dedupe_key_for
from tracker.workflows.collection_types import empty_stats

_SOFT_EMPTY = {"res": {"totalRecords": 0, "searchResults": []}}


def _row(n: int) -> dict:
    return {
        "positionId": f"2006{n:05d}",
        "reqId": f"2006{n:05d}-0836",
        "postingTitle": f"Engineering Manager {n}",
        "locations": [{"name": "Cupertino"}],
        "postDateInGMT": "2026-09-20T00:00:00.000Z",
    }


def _page(page: int, total: int) -> dict:
    start = (page - 1) * 20
    rows = [_row(n) for n in range(start, min(start + 20, total))]
    return {"res": {"totalRecords": total, "searchResults": rows}}


def _adapter(answer, **build):
    """`answer(page, attempt)` returns the search body (a str is sent as-is, not
    JSON); attempts count from 0. `build` reaches `build_adapter`."""
    attempts: Counter[int] = Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.lower().endswith("csrftoken"):
            return httpx.Response(200, headers={"x-apple-csrf-token": "t"})
        page = json.loads(request.content)["page"]
        body = answer(page, attempts[page])
        attempts[page] += 1
        if isinstance(body, str):
            return httpx.Response(200, text=body, headers={"content-type": "text/html"})
        return httpx.Response(200, json=body)

    adapter = build_adapter("apple", "apple", **build)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    return adapter, attempts


async def _drain(adapter) -> list:
    return [job async for job in adapter.fetch()]


@pytest.mark.asyncio
async def test_mid_listing_soft_empty_is_retried_and_the_listing_completes():
    def answer(page: int, attempt: int) -> dict:
        if page == 2 and attempt < 2:
            return _SOFT_EMPTY
        return _page(page, 45)

    adapter, attempts = _adapter(answer)
    jobs = await _drain(adapter)

    assert len({job.req_id for job in jobs}) == 45
    assert attempts == {1: 1, 2: 3, 3: 1}
    assert adapter.drift.listing_complete
    assert [(a["message"], a["retries"]) for a in adapter.drift.alerts] == [
        ("retried transient search answers", 2)
    ]


@pytest.mark.asyncio
async def test_first_page_soft_empty_does_not_read_as_an_empty_board():
    # A page-1 soft-empty must not read as a complete, zero-row listing. The
    # declared total must come from the answer we accept.
    def answer(page: int, attempt: int) -> dict:
        if page == 1 and attempt == 0:
            return _SOFT_EMPTY
        return _page(page, 25)

    adapter, attempts = _adapter(answer)
    jobs = await _drain(adapter)

    assert len(jobs) == 25
    assert attempts == {1: 2, 2: 1}
    assert adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_persistent_soft_empty_before_the_total_still_invalidates_the_listing():
    def answer(page: int, attempt: int) -> dict:
        return _SOFT_EMPTY if page == 2 else _page(page, 45)

    adapter, attempts = _adapter(answer)
    jobs = await _drain(adapter)

    assert len(jobs) == 20
    assert attempts[2] == _SOFT_EMPTY_ATTEMPTS
    assert 3 not in attempts
    assert not adapter.drift.listing_complete
    assert any(a["message"] == "results ended before totalRecords" for a in adapter.drift.alerts)


def _recorded(adapter, scanned: int) -> str:
    """The outcome the collector records for this listing (`collect_source`)."""
    adapter.drift.settle_listing(scanned=scanned)
    return classify_source_outcome({
        **empty_stats(),
        "scanned": scanned,
        "records_dropped": adapter.drift.records_dropped,
        "listing_invalidated": adapter.drift.listing_invalidated,
        "empty_proven": adapter.drift.empty_proven,
        "list_complete": adapter.drift.listing_complete,
    }).value


@pytest.mark.asyncio
async def test_a_first_page_soft_empty_on_every_attempt_is_a_lost_listing():
    """A soft-empty first page cannot prove an empty board: the search is
    location-filtered and the response can be transient. Exhausting retries
    must record a failed listing and suppress closure."""
    adapter, attempts = _adapter(lambda _page, _attempt: _SOFT_EMPTY)
    jobs = await _drain(adapter)

    assert jobs == []
    assert attempts == {1: _SOFT_EMPTY_ATTEMPTS}
    assert adapter.drift.listing_invalidated
    assert not adapter.drift.listing_complete
    assert not adapter.drift.empty_proven
    assert [(a["message"], a["retries"]) for a in adapter.drift.alerts] == [
        ("search answered empty on every attempt", _SOFT_EMPTY_ATTEMPTS - 1)
    ]
    assert _recorded(adapter, len(jobs)) == "failed"


@pytest.mark.asyncio
async def test_a_first_page_soft_empty_that_clears_on_the_last_attempt_is_a_full_read():
    # A successful final attempt proves completeness despite earlier soft-empty pages.
    def answer(page: int, attempt: int) -> dict:
        if page == 1 and attempt < _SOFT_EMPTY_ATTEMPTS - 1:
            return _SOFT_EMPTY
        return _page(page, 25)

    adapter, attempts = _adapter(answer)
    jobs = await _drain(adapter)

    assert len(jobs) == 25
    assert attempts == {1: _SOFT_EMPTY_ATTEMPTS, 2: 1}
    assert adapter.drift.listing_complete
    assert [(a["message"], a["retries"]) for a in adapter.drift.alerts] == [
        ("retried transient search answers", _SOFT_EMPTY_ATTEMPTS - 1)
    ]
    assert _recorded(adapter, len(jobs)) == "ok"


@pytest.mark.asyncio
async def test_real_end_of_listing_is_not_retried():
    # The declared total ends the listing; no page past it is ever requested,
    # so the retry budget is never spent on the real end.
    adapter, attempts = _adapter(lambda page, _attempt: _page(page, 40))
    jobs = await _drain(adapter)

    assert len(jobs) == 40
    assert attempts == {1: 1, 2: 1}
    assert adapter.drift.listing_complete
    assert not adapter.drift.alerts


@pytest.mark.asyncio
async def test_empty_page_that_keeps_its_total_is_not_a_soft_empty():
    # Only `totalRecords: 0` marks the flake. A short board that still states its
    # total is the source's own inconsistency: invalidate at once, no retries.
    def answer(page: int, _attempt: int) -> dict:
        if page == 2:
            return {"res": {"totalRecords": 45, "searchResults": []}}
        return _page(page, 45)

    adapter, attempts = _adapter(answer)
    await _drain(adapter)

    assert attempts[2] == 1
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_non_json_search_answer_is_retried_like_a_soft_empty():
    def answer(page: int, attempt: int):
        if page == 2 and attempt == 0:
            return "\n<html>Service Unavailable</html>"
        return _page(page, 45)

    adapter, attempts = _adapter(answer)
    jobs = await _drain(adapter)

    assert len(jobs) == 45
    assert attempts[2] == 2
    assert adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_persistent_non_json_loses_the_page_instead_of_raising():
    def answer(page: int, _attempt: int):
        return "\n<html></html>" if page == 2 else _page(page, 45)

    adapter, attempts = _adapter(answer)
    jobs = await _drain(adapter)

    assert len(jobs) == 20
    assert attempts[2] == _SOFT_EMPTY_ATTEMPTS
    assert not adapter.drift.listing_complete
    lost = [a for a in adapter.drift.alerts if a["message"] == "search answered non-JSON"]
    assert lost and lost[0]["content_type"] == "text/html"


# --- Held to the declared total ---------------------------------- #


@pytest.mark.asyncio
async def test_a_board_that_loses_a_posting_mid_walk_counts_one_lost_row():
    """Row 5 closes after page 1 is read: every later row shifts up one, so
    page 2 starts at what was row 21 and row 20 is never seen. One live row
    went unread — closure is off, and the loss is counted, not a broken board."""
    def answer(page: int, _attempt: int) -> dict:
        if page == 1:
            return _page(1, 45)
        rows = [_row(n) for n in range(21, 45)][(page - 2) * 20:(page - 1) * 20]
        return {"res": {"totalRecords": 44, "searchResults": rows}}

    adapter, _ = _adapter(answer)
    jobs = await _drain(adapter)

    assert len(jobs) == 44
    assert not adapter.drift.listing_complete
    assert not adapter.drift.listing_invalidated
    assert adapter.drift.records_dropped == 1


@pytest.mark.asyncio
async def test_a_board_that_gains_a_posting_mid_walk_is_still_complete():
    """A new posting lands at the top after page 1: rows shift DOWN, page 2
    re-serves row 19, and nothing the first page declared is missed."""
    def answer(page: int, _attempt: int) -> dict:
        if page == 1:
            return _page(1, 45)
        rows = [_row(n) for n in range(19, 45)][(page - 2) * 20:(page - 1) * 20]
        return {"res": {"totalRecords": 46, "searchResults": rows}}

    adapter, _ = _adapter(answer)
    jobs = await _drain(adapter)

    assert len({job.req_id for job in jobs}) == 45
    assert adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_postings_are_counted_by_requisition_not_by_position():
    """Apple posts one position per location under several reqIds. Keyed by
    `positionId`, a full walk counts fewer "unique" rows than the board states
    and fails every run."""
    def answer(page: int, _attempt: int) -> dict:
        body = _page(page, 25)
        for row in body["res"]["searchResults"]:
            row["positionId"] = "200600000"  # one position, 25 requisitions
        return body

    adapter, _ = _adapter(answer)
    jobs = await _drain(adapter)

    assert len(jobs) == 25
    assert adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_an_unreadable_row_still_counts_toward_the_declared_total():
    """`totalRecords` counts rows the board served. A row we cannot build is
    one dropped record, and must not ALSO read as a paging shortfall."""
    def answer(page: int, _attempt: int) -> dict:
        body = _page(page, 25)
        if page == 1:
            body["res"]["searchResults"][3] = {"positionId": "2006999", "reqId": "2006999-1"}
        return body

    adapter, _ = _adapter(answer)
    jobs = await _drain(adapter)

    assert len(jobs) == 24
    assert adapter.drift.records_dropped == 1


@pytest.mark.asyncio
async def test_a_search_that_states_no_total_is_not_closure_evidence():
    adapter, _ = _adapter(lambda page, _a: {"res": {"searchResults": _page(page, 5)["res"]["searchResults"]}})
    await _drain(adapter)
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_discovery_probe_reads_down_to_the_newest_row_it_holds_and_no_further():
    """The search is newest first, so the page holding a posting we already
    have is where the probe has caught up. The row is recognized by its
    requisition, the key its posting is stored under: its position alone
    (shared by every location's requisition) matches nothing we hold."""
    held = _row(25)  # on page 2 of a board twenty pages deep

    def probe(known: str):
        return _adapter(lambda page, _a: _page(page, 400), discovery=True, known_keys={known})

    adapter, attempts = probe(dedupe_key_for("apple", held["reqId"]))
    await _drain(adapter)
    assert sorted(attempts) == [1, 2]
    assert [o.stop_reason for o in adapter.query_observations] == [StopReason.FRONTIER]

    by_position, attempts = probe(dedupe_key_for("apple", held["positionId"]))
    await _drain(by_position)
    assert sorted(attempts) == list(range(1, by_position.discovery_max_pages + 1))
    assert [o.stop_reason for o in by_position.query_observations] == [StopReason.CEILING]
