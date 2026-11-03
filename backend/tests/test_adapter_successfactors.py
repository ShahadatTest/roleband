"""SAP SuccessFactors career sites, on EY's real pages.

The contracts, each on what a seeker would get wrong if it broke:

* **A place's country is read by position and written by name.** The codes
  collide with US states (IN, IL, CA, AR) and with each other (HR is Haryana
  and Croatia), so matched as text an Indian posting would read as Indiana.
* **Complete means the stated total was reached**, counted in unique ids.
* **A "+N more" row is placed from its page** when the role gate admits it,
  reusing places already read; otherwise it keeps its first place.
* **A walk that stops short closes nothing**, and a token naming the wrong
  site is a failed read, never an empty board.

"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from tracker.connectors import build_adapter
from tracker.connectors.listing.successfactors import (
    declared_total,
    parse_detail,
    parse_rows,
    parse_tenant,
    row_place,
)
from tracker.enrich.classify import location_groups_for
from tracker.platform.ratelimit import RateLimiter
from tracker.taxonomy.locations import countries_for

FIX = Path(__file__).parent / "fixtures/listings/successfactors"
PAGE = json.loads((FIX / "page1.json").read_text())["html"]
DETAIL = (FIX / "detail_1431618233.html").read_text()
TOKEN = "careers.ey.com|ey"
TENANT = parse_tenant(TOKEN)


def _page(total: int) -> str:
    return PAGE.replace("of <b>8551", f"of <b>{total}")


def _adapter(pages: dict[int, str], *, gate=None, known=None, detail_status=200):
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if "/job/" in request.url.path:
            asked.append(request.url.path)
            return httpx.Response(detail_status, text=DETAIL if detail_status == 200 else "")
        return httpx.Response(200, text=pages.get(int(request.url.params["startrow"]), "<html></html>"))

    adapter = build_adapter("ey", "successfactors", board_token=TOKEN)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    if gate is not None:
        adapter.place_gate = gate
    if known is not None:
        adapter.known_places = known
    return adapter, asked


async def _jobs(adapter):
    try:
        return [job async for job in adapter.fetch()]
    finally:
        await adapter._client.aclose()


@pytest.mark.parametrize("raw,label,country", [
    ("Pune, MH, IN, 411006", "Pune, India", "india"),            # IN is also Indiana
    ("Tel Aviv, IL, 6706703", "Tel Aviv, Israel", "israel"),      # IL is also Illinois
    ("Calgary, AB, CA, T2P 1M4", "Calgary, Canada", "canada"),     # CA is also California
    ("CABA, B, AR, 1001", "CABA, Argentina", "argentina"),        # AR is also Arkansas
    ("Gurugram, HR, IN, 122003", "Gurugram, India", "india"),     # HR is also Croatia
    ("New York, NY, US, 10001-8604", "New York, NY, United States", "united_states"),
    ("SG, 048583", "Singapore", "singapore"),
    ("PY", "Paraguay", "paraguay"),
    ("Baku, AZ, AZ1010", "Baku, Azerbaijan", "azerbaijan"),       # AZ is also Arizona
    ("New Delhi, National Capital Territory, IN, 110037", "New Delhi, National Capital Territory, India", "india"),
])
def test_a_place_names_its_country_by_position_never_by_matching_codes(raw, label, country):
    assert row_place(raw) == label
    assert countries_for([label]) == {country}, "exactly its own country"


def test_rows_parse_to_postings_with_places_and_their_more_marker():
    rows = parse_rows(PAGE, TENANT)
    assert len(rows) == 25 and declared_total(PAGE) == 8551
    first = rows[0]
    assert (first.posting_id, first.title, first.place, first.more) == (
        "1431366233", "Senior Consultant - Financial Due Diligence (M&A)", "Prague 1 - Nove Mesto, Czechia", False,
    )
    assert first.url.startswith("https://careers.ey.com/ey/job/")
    milano = rows[2]
    assert (milano.place, milano.more) == ("Milano, Italy", True)
    assert all(location_groups_for([r.place]) for r in rows), "every fixture place classifies"


@pytest.mark.asyncio
async def test_the_stated_total_reached_is_complete():
    adapter, asked = _adapter({0: _page(25)}, gate=lambda _job: False)
    jobs = await _jobs(adapter)
    assert len(jobs) == 25 and adapter.drift.listing_complete and adapter.drift.alerts == []
    assert asked == [], "a row the role gate drops is never placed"


@pytest.mark.asyncio
async def test_short_of_the_stated_total_closes_nothing():
    adapter, _ = _adapter({0: _page(30)}, gate=lambda _job: False)
    jobs = await _jobs(adapter)
    assert len(jobs) == 25 and not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_more_row_is_placed_from_its_page_or_from_places_already_read():
    known = {"1410456533": ["Rome, Italy"]}
    adapter, asked = _adapter({0: _page(25)}, known=known)
    jobs = {job.req_id: job for job in await _jobs(adapter)}
    more = {"1410456533", "1421011033", "1410352633", "1410454233"}
    # Three read (all the fixture's page), one reused; single-place rows never.
    assert len(asked) == 3
    assert jobs["1410456533"].locations == ["Rome, Italy"]
    placed = jobs["1421011033"]
    assert len(placed.locations) == 81 and placed.description_complete
    assert all(not jobs[k].description_complete for k in jobs if k not in more)


@pytest.mark.asyncio
async def test_a_more_row_whose_page_is_unreadable_keeps_its_first_place():
    # 404: the posting closed between the listing and its page (a 5xx is the
    # transport's retry, not this). The first place is a real place, and the
    # posting is still shown there.
    adapter, asked = _adapter({0: _page(25)}, detail_status=404)
    jobs = {job.req_id: job for job in await _jobs(adapter)}
    assert len(asked) == 4
    milano = jobs["1410456533"]
    assert milano.locations == ["Milano, Italy"]
    assert [loc.label for loc in milano.source_facts.locations] == ["Milano, Italy"]
    assert not milano.description_complete
    unreadable = [a for a in adapter.drift.alerts if a["message"] == "posting page unreadable"]
    assert {a["req"] for a in unreadable} == {"1410456533", "1421011033", "1410352633", "1410454233"}
    assert adapter.drift.listing_complete, "a posting page is not the listing"


def test_the_posting_page_states_every_place_and_its_date():
    detail = parse_detail(DETAIL)
    assert len(detail.places) == 81 and detail.places[0] == "Rochester, NY, United States"
    assert all(countries_for([p]) == {"united_states"} for p in detail.places)
    assert detail.posted_at is not None and detail.posted_at.date().isoformat() == "2026-09-26"
    assert detail.employer == "EY"
    assert "EY" in (detail.description_html or "")


def test_the_token_is_host_and_site():
    assert TENANT.probe_url() == (
        "https://careers.ey.com/ey/search/?q=&sortColumn=referencedate&sortDirection=desc&startrow=0"
    )
    with pytest.raises(ValueError):
        parse_tenant("careers.ey.com")


@pytest.mark.parametrize("raw,label,country", [
    ("Boston, MA", "Boston, MA", "united_states"),              # MA is also Morocco
    ("Indianapolis, IN", "Indianapolis, IN", "united_states"),  # IN is also India
    ("Los Angeles, CA", "Los Angeles, CA", "united_states"),    # CA is also Canada
    ("San José, CR", "San José, Costa Rica", "costa_rica"),     # CR is no state: a country
])
def test_a_bare_state_code_is_never_read_as_a_country(raw, label, country):
    """A tenant may print "City, ST" with no country and no postcode.
    The code then has no position to read as a country, so the row is kept as
    written and the taxonomy places it; read by matching codes, a whole US
    board would land on Moroccan, Indian and Canadian radars and off every US one."""
    assert row_place(raw) == label
    assert countries_for([label]) == {country}


@pytest.mark.asyncio
async def test_a_single_place_row_keeps_the_places_a_page_read_named():
    """Only a `more` row asks the page, so a row whose card names one place
    never reached that branch and the card's label replaced what a page read
    had named. Locations fail closed, so the posting drops out of a scope its
    page places matched. Fail-first: the card's one place comes back."""
    known = {"1431366233": ["Prague 1 - Nove Mesto, Czechia", "Brno, Czechia"]}
    adapter, asked = _adapter({0: _page(25)}, known=known)
    jobs = {job.req_id: job for job in await _jobs(adapter)}

    assert "1431366233" not in asked, "a single-place row must still cost no request"
    assert jobs["1431366233"].locations == [
        "Prague 1 - Nove Mesto, Czechia", "Brno, Czechia",
    ]
    # The observation records what the listing said, not what we held.
    assert [loc.label for loc in jobs["1431366233"].source_facts.locations] == [
        "Prague 1 - Nove Mesto, Czechia",
    ]


def _second_page(total: int) -> str:
    """The fixture page as the board's next 25 rows: the same rows under other ids."""
    return re.sub(r"(/job/[^\"?#]*?/)(\d+)/", lambda m: f"{m.group(1)}9{m.group(2)}/", _page(total))


@pytest.mark.asyncio
async def test_a_two_page_walk_reaches_the_stated_total_and_is_complete():
    adapter, _ = _adapter({0: _page(50), 25: _second_page(50)}, gate=lambda _job: False)
    jobs = await _jobs(adapter)
    assert len(jobs) == 50 == len({job.req_id for job in jobs})
    assert adapter.drift.listing_complete and adapter.drift.alerts == []


@pytest.mark.asyncio
async def test_a_page_that_comes_back_empty_mid_walk_closes_nothing():
    # The second page answers with no rows: the walk stops 25 short of the
    # stated total, and the 25 it never read must not be closed.
    adapter, _ = _adapter({0: _page(50)}, gate=lambda _job: False)
    jobs = await _jobs(adapter)
    assert len(jobs) == 25
    assert not adapter.drift.listing_complete
    assert adapter.drift.records_dropped == 25


@pytest.mark.asyncio
async def test_a_page_that_fails_mid_walk_invalidates_the_listing():
    def handle(request: httpx.Request) -> httpx.Response:
        if int(request.url.params["startrow"]) == 0:
            return httpx.Response(200, text=_page(50))
        return httpx.Response(404, text="")

    adapter = build_adapter("ey", "successfactors", board_token=TOKEN)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    adapter.place_gate = lambda _job: False
    jobs = await _jobs(adapter)
    assert len(jobs) == 25
    assert not adapter.drift.listing_complete
    assert adapter.drift.listing_invalidated
    assert adapter.drift.alerts[0]["message"] == "search page failed"
    assert adapter.drift.alerts[0]["page"] == 1


@pytest.mark.asyncio
async def test_a_token_naming_the_wrong_site_is_a_failure_never_an_empty_board():
    # A wrong site path answers 200 with a page that has no results table.
    wrong = "<html><body><h1>Welcome to our careers site</h1></body></html>"
    adapter, _ = _adapter({0: wrong})
    assert await _jobs(adapter) == []
    assert not adapter.drift.listing_complete
    assert not adapter.drift.empty_proven, "nothing here proves the board lists nothing"
    messages = {a["message"] for a in adapter.drift.alerts}
    assert "empty job list" in messages


@pytest.mark.parametrize("raw", ["Springfield, QQ, 12345", "Atlantis, Deep, QQ, 0000"])
def test_a_place_with_no_known_country_code_is_placed_in_no_country(raw):
    # QQ is no country: the label is kept as written and the taxonomy places
    # it nowhere, rather than reading a neighbouring field as the country.
    label = row_place(raw)
    assert label is not None and "QQ" in label
    assert countries_for([label]) == set()
    assert location_groups_for([label]) == []
