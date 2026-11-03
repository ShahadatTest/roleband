"""Our page ceiling is a bound, not drift.

A query that serves items on its last allowed page (google's US-wide query:
1999 rows = exactly 100 pages of 20), recorded as `listing exceeded page safety
limit` DRIFT, would read as `degraded` in `classify_source_outcome`; three
degraded runs quarantine the binding, and quarantine suppresses closure
indefinitely — with no exit, because the only way out (`VALIDATED_RECOVERY`)
needs an OK run the ceiling makes unreachable. A genuinely-too-small ceiling
sets the same trap. A bound WE impose must never
read as the source's pathology (the `capped`/`bounded` rule, extended to depth).
"""

from __future__ import annotations

import pytest

from tests.scripted_boards import CARD, amazon_board, amazon_hit, google_board, results_page
from tracker.connectors.listing.base import BaseAdapter
from tracker.connectors.recipes.outcome import SourceOutcome, classify_source_outcome
from tracker.schema import RawJob


class _EndlessAdapter(BaseAdapter):
    """A source whose listing never runs dry — every page serves items."""

    name = "endless"

    async def fetch(self):
        async def fetch_page(index: int, stop) -> list[dict]:
            return [{"id": f"job-{index}-{n}"} for n in range(3)]

        async for item in self.paged_listing(fetch_page, max_pages=4, term="anything"):
            yield RawJob(company=self.company, req_id=item["id"], title="t", url="u")


class _EndingAdapter(BaseAdapter):
    """A source that reaches its natural end below the ceiling."""

    name = "ending"

    async def fetch(self):
        async def fetch_page(index: int, stop) -> list[dict]:
            if index >= 2:
                return []
            return [{"id": f"job-{index}"}]

        async for item in self.paged_listing(fetch_page, max_pages=100):
            yield RawJob(company=self.company, req_id=item["id"], title="t", url="u")


@pytest.mark.asyncio
async def test_ceiling_hit_sets_truncated_and_records_no_drift():
    adapter = _EndlessAdapter("acme")
    jobs = [job async for job in adapter.fetch()]

    assert len(jobs) == 12  # every allowed page was consumed
    assert adapter.truncated is True
    # The two channels this must never touch: drift is the source's own
    # misbehavior, and listing_complete=False is derived from `truncated` by
    # the pipeline, not smuggled through the drift detector.
    assert adapter.drift.alerts == []
    assert adapter.drift.listing_complete is True


@pytest.mark.asyncio
async def test_natural_end_is_not_truncation():
    adapter = _EndingAdapter("acme")
    jobs = [job async for job in adapter.fetch()]

    assert len(jobs) == 2
    assert adapter.truncated is False
    assert adapter.drift.alerts == []


def test_truncated_stats_classify_health_inert_not_degraded():
    """The full stats dict the pipeline records for a ceiling-cut source, fed
    to the same derivation the persist loop uses. `degraded` here would
    quarantine the binding."""
    stats = {
        "scanned": 2296,
        "kept": 413,
        "errors": [],
        "capped": False,
        "bounded": False,
        "truncated": True,
        "list_complete": False,
    }
    assert classify_source_outcome(stats) is SourceOutcome.TRUNCATED


# --- google reads its own declared total ------------------------------- #


@pytest.mark.asyncio
async def test_google_stops_at_its_declared_total_without_an_extra_request():
    """Two pages, 40 rows declared. Page 2 ends exactly at the total, so the
    scan must stop THERE — no page-3 probe, no ceiling involvement, no drift.
    The last full page must not run into `max_pages` and be punished as a
    safety-limit hit."""
    pages = {
        "1": results_page(first=1, last=20, total=40, ids=range(0, 20)),
        "2": results_page(first=21, last=40, total=40, ids=range(20, 40)),
    }
    requests: list[str] = []
    adapter = google_board(pages, requests)

    jobs = [job async for job in adapter._fetch_location("United States", set())]

    # Several locations are scanned in a real fetch(); driving one keeps the geometry.
    assert len(jobs) == 40
    assert requests == ["1", "2"]  # exactly two requests, no probe
    assert adapter.truncated is False
    assert adapter.drift.alerts == []
    assert adapter.drift.listing_complete is True


@pytest.mark.asyncio
async def test_google_page_of_duplicates_does_not_end_the_scan():
    """A page whose cards were ALL seen under an earlier location must not read
    as end-of-results.

    Filtered inside `fetch_page`, such a page would return empty, `paginate`
    would stop, and the location would report `truncated=False` with a
    complete listing — which authorizes closing every posting the scan never
    reached. Multi-location roles make this reachable: a Singapore posting also
    listed in a US office is already `seen` before the Singapore query starts,
    and `location=United States` runs first.

    Geometry below: page 1 is 20 already-seen roles, page 2 holds 20 genuinely
    new ones, and the source declares 40. Stopping at page 1 loses half the
    board silently."""
    pages = {
        "1": results_page(first=1, last=20, total=40, ids=range(0, 20)),
        "2": results_page(first=21, last=40, total=40, ids=range(100, 120)),
    }
    requests: list[str] = []
    adapter = google_board(pages, requests)
    already_seen = {str(100000 + i) for i in range(0, 20)}

    jobs = [job async for job in adapter._fetch_location("Singapore", already_seen)]

    assert requests == ["1", "2"], "the duplicate page must not stop the pager"
    assert len(jobs) == 20, "page 2's genuinely new roles are collected"
    assert {j.req_id for j in jobs} == {str(100000 + i) for i in range(100, 120)}
    assert adapter.truncated is False  # it reached the declared total naturally
    assert adapter.drift.alerts == []


@pytest.mark.asyncio
async def test_google_vocabulary_carries_no_subsumed_metro():
    """No Bay metro queries: `location` unions up to five values, and the
    metros' union is identical to the US query alone (1999). With dedup after
    the pager they would not stop after one page either, so they would cost
    hundreds of pages to collect nothing."""
    from tracker.connectors.listing.google import GOOGLE_LOCATION_QUERIES

    # The manifest is generated per country, so this pins the PROPERTY rather
    # than a literal list: google's vocabulary is country-level only. A metro
    # term here is a query the country term already subsumes.
    assert not {"silicon_valley", "new_york", "pacific_northwest", "austin", "dc_metro"} & set(
        GOOGLE_LOCATION_QUERIES
    )
    assert GOOGLE_LOCATION_QUERIES["united_states"] == ["United States"]
    # `United Kingdom`, not `London, UK`: both return the identical req_ids,
    # so the city name would describe the query rather than the set it returns.
    assert GOOGLE_LOCATION_QUERIES["uk"] == ["United Kingdom"]
    assert "london" not in GOOGLE_LOCATION_QUERIES


@pytest.mark.asyncio
async def test_google_without_the_total_marker_keeps_paging_to_empty():
    """The marker is an optimization, never a requirement: without it the scan
    pages until the source runs dry and records nothing."""
    no_marker_1 = "<html><body><main><ul>" + "".join(
        CARD.format(title=f"Engineer {i}", req_id=200000 + i) for i in range(20)
    ) + "</ul></main></body></html>"
    pages = {"1": no_marker_1}
    requests: list[str] = []
    adapter = google_board(pages, requests)

    jobs = [job async for job in adapter._fetch_location("Singapore", set())]

    assert len(jobs) == 20
    assert requests == ["1", "2"]  # paged on, met the empty page, stopped
    assert adapter.truncated is False
    assert adapter.drift.alerts == []


# --- a window is not a count ------------------------------------- #


@pytest.mark.asyncio
async def test_amazon_declared_total_below_the_window_is_a_real_count():
    """The control case: `hits` under the window is trustworthy, the scan ends
    naturally, and nothing is marked truncated."""
    pages = {"0": {"hits": 150, "jobs": [amazon_hit(i) for i in range(100)]},
             "100": {"hits": 150, "jobs": [amazon_hit(i) for i in range(100, 150)]}}
    requests: list = []
    adapter = amazon_board(pages, requests)

    jobs = [job async for job in adapter._fetch_group(
        ("united_states", [("normalized_country_code[]", "USA")]), set()
    )]

    assert len(jobs) == 150
    assert adapter.truncated is False
    assert adapter.drift.alerts == []


@pytest.mark.asyncio
async def test_amazon_at_the_window_is_truncated_not_a_complete_listing(monkeypatch):
    """`hits == 10000` is the result window, and ten state facets alone sum to
    15,727 — so absence past it is OUR bound. Reporting this as complete would
    authorize closing every posting the window hides.

    The window is shrunk to 200 so the fixture can fill it exactly as the real
    source does: a saturated query serves pages right up to the edge.
    """
    from tracker.connectors.listing import amazon as amazon_module

    monkeypatch.setattr(amazon_module, "_RESULT_WINDOW", 200)
    pages = {
        "0": {"hits": 200, "jobs": [amazon_hit(i) for i in range(100)]},
        "100": {"hits": 200, "jobs": [amazon_hit(i) for i in range(100, 200)]},
    }
    requests: list = []
    adapter = amazon_board(pages, requests)

    jobs = [job async for job in adapter._fetch_group(
        ("united_states", [("normalized_country_code[]", "USA")]), set()
    )]

    assert len(jobs) == 200, "everything addressable is still collected"
    assert adapter.truncated is True
    # Truncation is OUR bound, so it never enters the source-pathology channel.
    assert adapter.drift.alerts == []


@pytest.mark.asyncio
async def test_google_declares_no_window_so_its_total_is_a_count():
    """google's 1999 is not a window. Reading it as one means SUMMING metro
    totals against the US query. Overlapping sets cannot be summed — a posting
    listed in two offices is counted twice — and measured by union the metros
    are strictly subsumed by the US query. The unfiltered board declares and
    pages past 2000, so nothing caps a google total near 2000 either.

    The cost of the wrong reading is permanent: `truncated` is health-inert AND
    closure-suppressing, so the binding could never reach the OK run that clears
    it. A source that declares a real total must be able to report a complete
    listing."""
    # All 1999, served: a query is held to the total it states, so a complete
    # listing has to actually read it (a two-page shortcut, 40 rows under
    # "of 1999", is correctly a shortfall).
    pages = {
        str(p): results_page(
            first=(p - 1) * 20 + 1, last=min(p * 20, 1999), total=1999,
            ids=range((p - 1) * 20, min(p * 20, 1999)),
        )
        for p in range(1, 101)
    }
    requests: list[str] = []
    adapter = google_board(pages, requests)

    jobs = [job async for job in adapter._fetch_location("United States", set())]

    assert len(jobs) == 1999
    assert requests == [str(p) for p in range(1, 101)]  # stops at the declared total
    assert adapter.truncated is False, "1999 is google's count, not a cap"
    assert adapter.drift.listing_complete is True
    assert adapter.drift.alerts == []


@pytest.mark.asyncio
async def test_google_saturation_still_fires_if_a_window_is_ever_measured(monkeypatch):
    """google has no window constant, but the mechanism stays. If google ever
    grows a real result cap, a total at it must read as `truncated` rather than silently claiming the tail does not exist."""
    from tracker.connectors.listing import google as google_module

    monkeypatch.setattr(google_module, "_RESULT_WINDOW", 40)
    pages = {
        "1": results_page(first=1, last=20, total=40, ids=range(0, 20)),
        "2": results_page(first=21, last=40, total=40, ids=range(20, 40)),
    }
    adapter = google_board(pages, [])

    jobs = [job async for job in adapter._fetch_location("United States", set())]

    assert len(jobs) == 40, "everything addressable is still collected"
    assert adapter.truncated is True
    assert adapter.drift.alerts == []


@pytest.mark.asyncio
async def test_google_small_query_reports_a_complete_listing():
    """The guard against over-correcting: a genuinely small query (London: 105)
    must stay `ok`, or every narrow location would suppress closure forever."""
    pages = {
        "1": results_page(first=1, last=20, total=40, ids=range(0, 20)),
        "2": results_page(first=21, last=40, total=40, ids=range(20, 40)),
    }
    adapter = google_board(pages, [])

    jobs = [job async for job in adapter._fetch_location("London, UK", set())]

    assert len(jobs) == 40
    assert adapter.truncated is False
    assert adapter.drift.alerts == []
