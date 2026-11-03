"""Radancy TalentBrew sitemap listing and JSON-LD posting pages.

The contracts, each on what a seeker would get wrong if it broke:

* **The sitemap is the board**: every posting URL it names is requested, and
  the id is the URL's last segment.
* **A posting page becomes a posting** from its JSON-LD — title, place, posted
  date and the whole description, with every office of a multi-office posting.
* **A listed id is never lost**: an unreadable page keeps its id present (so
  closure does not close a live posting), and a 404 is a posting that closed
  between the two requests.
* **Three fields are never read**: the hiring manager's name (`workHours`), the
  tenant's grade as an employment type, and the office's street address.

"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tracker.connectors import build_adapter
from tracker.connectors.extract.payload import job_posting
from tracker.connectors.listing.radancy import posting_id, sitemap_links, sitemap_url
from tracker.connectors.listing.sitemap_board import places_of
from tracker.platform.ratelimit import RateLimiter
from tracker.schema import EmploymentType

FIX = Path(__file__).parent / "fixtures/listings/radancy"
SITEMAP = json.loads((FIX / "page1.json").read_text())["html"]
POSTING = (FIX / "job_100980904800.html").read_text()
MULTI = (FIX / "job_multi_location.html").read_text()
URLS = sitemap_links(SITEMAP)[0]


def _adapter(pages: dict[str, httpx.Response] | None = None, sitemap: str = SITEMAP):
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url)
        if url.endswith("sitemap.xml"):
            return httpx.Response(200, text=sitemap)
        if pages is not None and url in pages:
            return httpx.Response(pages[url].status_code, text=pages[url].text)
        return httpx.Response(200, text=POSTING)

    adapter = build_adapter("arm", "radancy", board_token="careers.arm.com")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    return adapter, asked


async def _jobs(adapter):
    return [job async for job in adapter.fetch()]


def test_the_sitemap_is_the_board():
    jobs, children = sitemap_links(SITEMAP)
    assert len(jobs) == 4 and children == []
    assert posting_id(jobs[0]) == "100980904800"
    assert posting_id("https://careers.arm.com/category/software-engineering-jobs/33099/8081696/1") is None
    assert sitemap_url("careers.arm.com") == "https://careers.arm.com/sitemap.xml"
    with pytest.raises(ValueError, match="careers host"):
        sitemap_url("careers.arm.com/search-jobs")


@pytest.mark.asyncio
async def test_every_listed_posting_is_requested_and_becomes_a_posting():
    adapter, asked = _adapter()
    jobs = await _jobs(adapter)

    assert asked == [sitemap_url("careers.arm.com"), *URLS]
    assert len(jobs) == 4 and adapter.drift.listing_complete and adapter.drift.alerts == []
    job = jobs[0]
    assert job.req_id == "100980904800"
    assert job.title == "Principal Software Engineer– AI Networking"
    assert job.locations == ["Sophia Antipolis, France"]
    assert job.posted_at is not None and job.posted_at.date().isoformat() == "2026-09-22"
    assert job.description_complete and len(job.description_html) > 1000
    assert job.url == URLS[0]


def test_every_office_of_a_posting_without_its_street():
    posting = job_posting(MULTI)
    places = places_of(posting)
    assert [p.label for p in places] == ["Cambridge, United Kingdom", "Manchester, England, United Kingdom"]
    assert [p.is_primary for p in places] == [True, False]
    street = posting["jobLocation"][0]["address"]["streetAddress"]
    assert "Fulbourn Road" in street, "the fixture really does carry a street"
    for place in places:
        assert "Fulbourn" not in (place.label or "")


@pytest.mark.asyncio
async def test_the_hiring_manager_and_the_grade_never_reach_a_posting():
    """Arm's JSON-LD puts the hiring manager in `workHours` and its own grade
    in `employmentType`. Neither is a fact about the job we may store."""
    posting = job_posting(POSTING)
    assert posting["workHours"] == "Steven Capper" and posting["employmentType"] == "Established"

    adapter, _ = _adapter()
    job = (await _jobs(adapter))[0]

    blob = json.dumps({
        "title": job.title, "url": job.url, "locations": job.locations,
        "department": job.department, "description": job.description_html,
        "raw": job.source_facts.employment_type_raw,
    })
    assert "Steven Capper" not in blob
    assert job.source_facts.employment_type_raw is None
    assert job.source_facts.employment_type_normalized is EmploymentType.UNKNOWN


@pytest.mark.asyncio
async def test_a_listed_id_that_will_not_read_is_kept_present():
    """The id was listed, so closure must not close it — only this run's copy
    is missing."""
    # A posting page that carries no JSON-LD reads exactly like a
    # transient failure does: the id is present, the row is not built.
    adapter, _ = _adapter({URLS[1]: httpx.Response(200, text="<html><body>maintenance</body></html>")})
    jobs = await _jobs(adapter)

    assert len(jobs) == 3
    assert adapter.drift.listing_complete, "the board was enumerated; one page failed"
    assert posting_id(URLS[1]) in adapter.drift.present_only


@pytest.mark.asyncio
async def test_a_posting_gone_since_the_sitemap_is_not_a_loss():
    adapter, _ = _adapter({URLS[2]: httpx.Response(404, text="gone")})
    jobs = await _jobs(adapter)

    assert len(jobs) == 3 and adapter.drift.listing_complete
    assert posting_id(URLS[2]) not in adapter.drift.present_only


@pytest.mark.asyncio
async def test_a_sitemap_that_names_no_posting_invalidates():
    adapter, _ = _adapter(sitemap='<?xml version="1.0"?><urlset><url><loc>https://careers.arm.com/</loc></url></urlset>')
    jobs = await _jobs(adapter)
    assert jobs == [] and not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_posting_listed_twice_is_fetched_once():
    """A sitemap that repeats a URL must not cost a second request, nor yield
    the posting twice."""
    entry = f"<loc>{URLS[0]}</loc>"
    assert SITEMAP.count(entry) == 1
    adapter, asked = _adapter(sitemap=SITEMAP.replace(entry, f"{entry}</url><url>{entry}"))
    jobs = await _jobs(adapter)

    assert asked.count(URLS[0]) == 1
    assert [j.req_id for j in jobs].count("100980904800") == 1 and len(jobs) == 4


@pytest.mark.asyncio
async def test_a_board_past_our_ceiling_is_cut_by_us(monkeypatch):
    """One request per posting is this family's cost, so the scan is bounded.
    A board past the ceiling is OUR bound — `truncated`, non-authoritative —
    never the source's fault, and never a licence to close what we skipped."""
    adapter, asked = _adapter()
    monkeypatch.setattr(type(adapter), "max_jobs", 2)
    jobs = await _jobs(adapter)

    assert len(jobs) == 2 and adapter.truncated
    assert len([u for u in asked if "/job/" in u]) == 2, "the postings past the ceiling are not fetched"


@pytest.mark.asyncio
async def test_postings_whose_url_title_fits_the_user_are_read_first():
    """The URL names the title, so matching pages can reach the Board first.
    Ordering must not reduce completeness: every listed page is still read."""
    from tracker.enrich.enricher import ScopeFilter, annotate, passes_filters

    scope = ScopeFilter(
        enabled_bands=frozenset({"staff"}),
        enabled_roles=frozenset({"ml_ai_research"}),
        enabled_tracks=frozenset({"management"}),
        enabled_locations=frozenset({"uk"}),
        enabled_domains=frozenset(),
    )
    adapter, asked = _adapter()
    adapter.place_gate = lambda raw: passes_filters(annotate(raw), scope, read_place=False)

    jobs = await _jobs(adapter)

    manager = "https://careers.arm.com/job/cambridge/staff-software-engineer-and-line-manager-machine-learning-c-and-vulkan/33099/100974823776"
    assert asked[1] == manager, "the one posting this user wants is read first"
    assert sorted(asked[1:]) == sorted(URLS), "and every listed posting is still read"
    assert len(jobs) == 4 and adapter.drift.listing_complete


def test_the_url_names_the_title_and_city_for_ordering_only():
    from tracker.connectors.listing.radancy import url_title

    assert url_title(URLS[0]) == ("principal software engineer ai networking", "sophia antipolis")
    assert url_title("https://careers.arm.com/category/software-engineering-jobs/33099/8081696/1") is None
