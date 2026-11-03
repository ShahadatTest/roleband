"""Jibe career-site listing and posting fields.

The contracts, each on what a seeker would get wrong if it broke:

* **A row is a posting at every place it names**, with the body's three parts,
  the tenant's own posting URL (never Jibe's host), and "remote" read from the
  tenant's location label.
* **Complete means the stated total was reached.** Rows repeating across pages,
  or a page stating no total, invalidate; a posting in two languages counts
  twice toward the total but is yielded once.
* **The walk asks for 100 a page and stops at the total.**
* **The token checker reads the board's own count and employer.**

"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest

from tracker.connectors import build_adapter
from tracker.connectors.listing.jibe import declared_total, jobs_url, stated_employer
from tracker.platform.ratelimit import RateLimiter
from tracker.schema import EmploymentType, WorkplaceType

FIX = Path(__file__).parent / "fixtures/listings/jibe"
GITHUB = json.loads((FIX / "page1.json").read_text())
BOOKING = json.loads((FIX / "booking_page1.json").read_text())


def _page(source: dict, rows: list, total: int | None) -> dict:
    page = {**source, "jobs": rows}
    if total is None:
        page.pop("totalCount")
    else:
        page["totalCount"] = total
    return page


def _adapter(pages: dict[int, dict], company="github", token="www.github.careers"):
    asked: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(dict(request.url.params))
        page = int(request.url.params["page"])
        return httpx.Response(200, json=pages.get(page, {**GITHUB, "jobs": []}))

    adapter = build_adapter(company, "jibe", board_token=token)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    return adapter, asked


async def _jobs(adapter):
    return [job async for job in adapter.fetch()]


@pytest.mark.asyncio
async def test_a_row_is_a_posting_with_its_body_page_and_place():
    adapter, _ = _adapter({1: GITHUB})
    jobs = {j.req_id: j for j in await _jobs(adapter)}
    raw = next(r["data"] for r in GITHUB["jobs"] if r["data"]["req_id"] == "5721")
    job = jobs["5721"]

    assert job.title == "Senior Software Engineer"
    # Jibe's canonical names its own host (githubinc.jibeapply.com); the
    # posting is the tenant's, on the careers host.
    assert raw["meta_data"]["canonical_url"].startswith("https://githubinc.jibeapply.com/")
    assert job.url == "https://www.github.careers/jobs/5721"
    assert job.locations == ["United States"]
    assert job.workplace_type is WorkplaceType.REMOTE, "'US Remote' is remote"
    assert job.department == "Engineering"
    assert job.posted_at is not None and job.posted_at.date().isoformat() == "2026-09-21"
    assert job.source_facts.employment_type_normalized is EmploymentType.FULL_TIME
    # All three parts of the body, in order.
    body = job.description_html
    parts = [body.find(raw[k][:200]) for k in ("description", "responsibilities", "qualifications")]
    assert all(p >= 0 for p in parts) and parts == sorted(parts), parts
    assert job.description_complete

    sf = jobs["5626"]
    assert sf.locations == ["San Francisco, California"]
    assert sf.workplace_type is WorkplaceType.UNKNOWN, "an office label is not remote"


@pytest.mark.asyncio
async def test_every_place_a_row_names_once_and_the_tenant_canonical_url():
    adapter, _ = _adapter({1: BOOKING}, company="booking", token="jobs.booking.com")
    jobs = {j.req_id: j for j in await _jobs(adapter)}

    lisbon = jobs["29990"]
    assert lisbon.locations == ["Lisbon, Portugal", "Faro, Portugal", "Porto, Portugal"]
    assert [p.is_primary for p in lisbon.source_facts.locations] == [True, False, False]
    # Booking's canonical is on its careers host, so it is the posting URL.
    assert jobs["30271"].url == "https://jobs.booking.com/booking/jobs/30271?lang=en-us"
    assert jobs["30271"].workplace_type is WorkplaceType.UNKNOWN, "'Amsterdam Campus' is not remote"

    github, _ = _adapter({1: GITHUB})
    doubled = next(j for j in await _jobs(github) if j.req_id == "5645")
    assert doubled.locations == ["United States"], "'United States; United States' is one place"


@pytest.mark.asyncio
async def test_the_declared_total_reached_is_complete_and_the_walk_stops_there():
    rows = BOOKING["jobs"]
    adapter, asked = _adapter(
        {1: _page(BOOKING, rows[:3], 5), 2: _page(BOOKING, rows[3:], 5)}, company="booking", token="jobs.booking.com",
    )
    jobs = await _jobs(adapter)

    assert len(jobs) == 5 and adapter.drift.listing_complete and adapter.drift.alerts == []
    assert asked == [{"page": "1", "limit": "100"}, {"page": "2", "limit": "100"}]


@pytest.mark.asyncio
async def test_rows_repeating_across_pages_are_never_complete():
    rows = BOOKING["jobs"]
    adapter, _ = _adapter(
        {1: _page(BOOKING, rows[:3], 5), 2: _page(BOOKING, [rows[2], rows[3]], 5)},
        company="booking", token="jobs.booking.com",
    )
    jobs = await _jobs(adapter)
    assert len(jobs) == 4 and not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_page_stating_no_total_invalidates():
    adapter, _ = _adapter({1: _page(GITHUB, GITHUB["jobs"], None)})
    jobs = await _jobs(adapter)
    assert len(jobs) == 5 and not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_posting_in_two_languages_counts_twice_and_is_yielded_once():
    rows = GITHUB["jobs"]
    german = copy.deepcopy(rows[0])
    german["data"]["language"] = "de-de"
    adapter, _ = _adapter({1: _page(GITHUB, [*rows, german], 6)})
    jobs = await _jobs(adapter)

    assert len(jobs) == 5
    assert adapter.drift.listing_complete, "the second language is the same posting, not a loss"


def test_the_checker_reads_the_boards_own_count_and_employer():
    assert declared_total(json.dumps(GITHUB)) == 5
    assert declared_total(json.dumps({"jobs": []})) is None
    assert stated_employer(json.dumps(GITHUB)) == "GitHub, Inc."
    # Booking's board carries its parent brand too; the employer is the one
    # most rows name (fixture: 4 Booking.com, 1 Booking Holdings) — not the
    # first row's.
    holdings_first = sorted(BOOKING["jobs"], key=lambda r: r["data"]["hiring_organization"] != "Booking Holdings")
    assert holdings_first[0]["data"]["hiring_organization"] == "Booking Holdings"
    assert stated_employer(json.dumps({**BOOKING, "jobs": holdings_first})) == "Booking.com"
    assert stated_employer("not json") is None


def test_the_token_is_the_careers_host():
    assert jobs_url("www.github.careers") == "https://www.github.careers/api/jobs"
    for bad in ("", "www.github.careers/careers-home", "jobs.ea.com|en_US/careers"):
        with pytest.raises(ValueError, match="careers host"):
            jobs_url(bad)
