"""Avature portal listing and labelled detail blocks.

The contracts, each on what a seeker would get wrong if it broke:

* **Cards parse to postings**: title, detail link, the id from the link, and
  the labelled subtitle spans (place, department, worker type).
* **Complete means the stated total was reached.** Unique ids below the stated
  total — rows repeating across pages — or a page stating no total invalidates.
* **Detail blocks are read by label**: `Work Model` is the workplace, the
  "Locations:" line is the fuller place, and only UNLABELLED blocks become the
  description (Role ID, Worker Type and the like never leak into it).

"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import httpx
import pytest

from tracker.connectors import build_adapter
from tracker.connectors.listing.avature import (
    declared_total,
    parse_cards,
    parse_detail,
    parse_tenant,
)
from tracker.enrich.classify import location_groups_for
from tracker.platform.ratelimit import RateLimiter
from tracker.schema import WorkplaceType

FIX = Path(__file__).parent / "fixtures/listings/avature"
PAGE = json.loads((FIX / "page1.json").read_text())["html"]
DETAIL = (FIX / "detail_216202.html").read_text()
TOKEN = "jobs.ea.com|en_US/careers"


def _with_total(page: str, total: int | None) -> str:
    if total is None:
        return re.sub(r'aria-label="\d+ results"', "", page)
    return re.sub(r'aria-label="\d+ results"', f'aria-label="{total} results"', page)


def _adapter(pages: dict[int, str]):
    def handle(request: httpx.Request) -> httpx.Response:
        if "/JobDetail/" in request.url.path:
            return httpx.Response(200, text=DETAIL)
        return httpx.Response(200, text=pages.get(int(request.url.params["jobOffset"]), "<html></html>"))

    adapter = build_adapter("electronic-arts", "avature", board_token=TOKEN)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    return adapter


async def _jobs(adapter):
    return [job async for job in adapter.fetch()]


def test_cards_parse_to_postings():
    cards = parse_cards(PAGE)
    assert len(cards) == 20 and declared_total(PAGE) == 20
    first = cards[0]
    assert (first.posting_id, first.title) == ("214164", "Director, PE Shared Services")
    assert (first.location, first.department, first.worker_type) == (
        "Hyderabad, India", "People Experience & Workplaces", "Regular Employee",
    )
    assert first.url.endswith("/JobDetail/Director-PE-Shared-Services/214164")


@pytest.mark.asyncio
async def test_the_declared_total_reached_is_complete():
    adapter = _adapter({0: PAGE})
    jobs = await _jobs(adapter)
    assert len(jobs) == 20 and adapter.drift.listing_complete and adapter.drift.alerts == []
    assert jobs[0].department == "People Experience & Workplaces"


@pytest.mark.asyncio
async def test_rows_repeating_across_pages_are_never_complete():
    """40 stated; page 2 repeats page 1 — 20 unique."""
    adapter = _adapter({0: _with_total(PAGE, 40), 20: _with_total(PAGE, 40)})
    jobs = await _jobs(adapter)
    assert len(jobs) == 20 and not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_page_stating_no_total_invalidates():
    adapter = _adapter({0: _with_total(PAGE, None)})
    await _jobs(adapter)
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_detail_blocks_are_read_by_label():
    detail = parse_detail(DETAIL)
    assert detail.locations == ["Hyderabad, Telangana, India"]
    assert detail.workplace is WorkplaceType.HYBRID
    assert detail.department == "EA Mobile - Slingshot Games (India)"
    assert "Technical Director" in detail.description_html
    # The VALUES of labelled blocks (Post To, Worker Type) and the locations
    # line are facts, not description.
    for leaked in ("External careers site, Internal careers site", "Regular Employee", "Locations:"):
        assert leaked not in detail.description_html, f"{leaked!r} is a labelled fact, not description"

    adapter = _adapter({0: PAGE})
    job = (await _jobs(adapter))[0]
    await adapter.hydrate(job)
    assert job.locations == ["Hyderabad, Telangana, India"] and job.description_complete


def test_the_token_is_host_and_portal():
    tenant = parse_tenant(TOKEN)
    assert tenant.search_url() == "https://jobs.ea.com/en_US/careers/SearchJobs/"
    with pytest.raises(ValueError, match="host\\|portal"):
        parse_tenant("jobs.ea.com")


# --- Synopsys: the same family, another tenant's layout --------- #

SYN_PAGE = json.loads((FIX / "synopsys_page1.json").read_text())["html"]
SYN_DETAIL = (FIX / "synopsys_detail_18605.html").read_text()
SYN_TOKEN = "synopsys.avature.net|careers"


def _syn_adapter(pages: dict[int, str]):
    asked: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if "/JobDetail/" in request.url.path:
            return httpx.Response(200, text=SYN_DETAIL)
        offset = int(request.url.params["jobOffset"])
        asked.append(offset)
        return httpx.Response(200, text=pages.get(offset, "<html></html>"))

    adapter = build_adapter("synopsys", "avature", board_token=SYN_TOKEN)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    return adapter, asked


def _syn_page(cards: slice, total: int) -> str:
    """The real page cut to some of its cards, stating `total`."""
    articles = re.findall(r'<article class="article article--result".*?</article>', SYN_PAGE, re.S)
    head, tail = SYN_PAGE.split(articles[0], 1)[0], SYN_PAGE.rsplit(articles[-1], 1)[1]
    return _with_total(head + "".join(articles[cards]) + tail, total)


def test_a_tenant_chooses_its_card_spans():
    cards = parse_cards(SYN_PAGE)
    assert len(cards) == 6 and declared_total(SYN_PAGE) == 6
    first = cards[0]
    assert (first.posting_id, first.title) == ("18605", "ZeBu Application Engineer")
    assert first.worker_type == "Employee", "Synopsys' hireType span"
    assert first.posted_at is not None and first.posted_at.date().isoformat() == "2026-09-02"
    assert first.location is None, "Synopsys' card states no place; the detail does"


@pytest.mark.asyncio
async def test_the_walk_advances_by_the_cards_a_page_returned():
    """Synopsys serves 6 a page whatever `jobRecordsPerPage` asks: stepping
    by our 20 would skip 14 of every 20 postings."""
    adapter, asked = _syn_adapter({0: _syn_page(slice(0, 3), 6), 3: _syn_page(slice(3, 6), 6)})
    jobs = await _jobs(adapter)

    assert asked == [0, 3]
    assert len(jobs) == 6 and adapter.drift.listing_complete and adapter.drift.alerts == []


@pytest.mark.asyncio
async def test_a_labelled_description_is_the_description_and_fields_are_the_place():
    detail = parse_detail(SYN_DETAIL)
    assert detail.locations == ["Shanghai, China"]
    assert detail.department == "Engineering"
    assert detail.posted_at is not None and detail.posted_at.date().isoformat() == "2026-09-02"
    assert detail.workplace is WorkplaceType.UNKNOWN, "'Remote Eligible: No' says nothing of the office"
    # The body sits under the label "Job Description and Requirements"; the
    # boilerplate after it is unlabelled. Both are description, nothing else.
    assert "Synopsys is uniquely positioned" in detail.description_html
    assert "want talented people of every background" in detail.description_html
    for leaked in ("Applications Engineering", "Remote Eligible", "Job Subcategory"):
        assert leaked not in detail.description_html, f"{leaked!r} is a labelled fact"

    remote = parse_detail(re.sub(
        r'(Remote Eligible\s*</div>\s*<div class="article__content__view__field__value">\s*)No',
        r"\1Yes", SYN_DETAIL,
    ))
    assert remote.workplace is WorkplaceType.REMOTE

    adapter, _ = _syn_adapter({0: SYN_PAGE})
    job = (await _jobs(adapter))[0]
    await adapter.hydrate(job)
    assert job.locations == ["Shanghai, China"] and job.department == "Engineering" and job.description_complete


@pytest.mark.asyncio
async def test_an_empty_page_ends_the_walk_short_of_the_total():
    """12 stated, 6 served: the empty page is the end (not 200 more requests),
    and the listing is incomplete."""
    adapter, asked = _syn_adapter({0: _syn_page(slice(0, 6), 12)})
    jobs = await _jobs(adapter)

    assert asked == [0, 6]
    assert len(jobs) == 6 and not adapter.drift.listing_complete


# --- The OpenRoles shape ---

TS_TOKEN = "careers.twosigma.com|careers|openroles"
TS_PAGE = json.loads((FIX / "twosigma_page1.json").read_text())["html"]
TS_DETAIL = (FIX / "twosigma_detail_14291.html").read_text()


def _ts_adapter(pages: dict[int, httpx.Response | str]):
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        if "/JobDetail/" in request.url.path:
            return httpx.Response(200, text=TS_DETAIL)
        assert request.url.path == "/careers/OpenRoles/", request.url.path
        page = pages.get(int(request.url.params["jobOffset"]), "<html></html>")
        return page if isinstance(page, httpx.Response) else httpx.Response(200, text=page)

    adapter = build_adapter("two-sigma", "avature", board_token=TS_TOKEN)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    return adapter, asked


def test_the_shape_is_declared_in_the_token_never_guessed():
    assert parse_tenant(TS_TOKEN).search_url() == "https://careers.twosigma.com/careers/OpenRoles/"
    assert not parse_tenant(TS_TOKEN).counted and parse_tenant(TOKEN).counted
    with pytest.raises(ValueError):
        parse_tenant("careers.twosigma.com|careers|guess")


def test_openroles_cards_carry_the_place_and_department_never_the_grade():
    cards = parse_cards(TS_PAGE, "openroles")
    assert len(cards) == 10 and declared_total(TS_PAGE) is None
    first = cards[0]
    assert (first.posting_id, first.location, first.department, first.worker_type) == (
        "14291", "United States - NY New York", "Engineering", None)
    assert all(c.location for c in cards)
    assert all(c.location is None for c in parse_cards(TS_PAGE)), "the search shape reads labelled spans only"


@pytest.mark.asyncio
async def test_an_uncounted_board_ending_on_its_empty_page_is_complete():
    adapter, asked = _ts_adapter({0: TS_PAGE})
    jobs = await _jobs(adapter)
    assert len(jobs) == 10 and adapter.drift.listing_complete
    assert jobs[0].locations == ["United States - NY New York"]
    # Pages overlap by one row: the second page is read from offset 9.
    assert [u.split("jobOffset=")[1] for u in asked] == ["0", "9"]


@pytest.mark.asyncio
async def test_a_lost_page_on_an_uncounted_board_is_never_complete():
    adapter, _ = _ts_adapter({0: TS_PAGE, 9: httpx.Response(500)})
    adapter.settings = adapter.settings.model_copy(update={"scraper_max_retries": 0})
    jobs = await _jobs(adapter)
    assert len(jobs) == 10 and not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_the_description_is_what_follows_the_facts():
    adapter, _ = _ts_adapter({0: TS_PAGE})
    job = (await _jobs(adapter))[0]
    await adapter.hydrate(job)
    text = re.sub(r"<[^>]+>", " ", job.description_html or "")
    assert text.lstrip().startswith("Two Sigma is a leading quantitative")
    assert "AI Fluency: Program Manager" not in text[:200], "the repeated title is not description"
    assert "$165,000" in text, "the pay statement stays in the description for pay detection"
    assert job.department == "Engineering" and job.locations == ["United States - NY New York"]


@pytest.mark.asyncio
async def test_the_checker_reports_an_uncounted_tenant_as_serving_roles_not_a_size():
    from scripts.check_catalog_tokens import Probe, check_probe

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200 if "OpenRoles" in request.url.path else 404, text=TS_PAGE)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await check_probe(client, Probe("two-sigma", "avature", TS_TOKEN, "test"))
    assert (result["state"], result["count"], result.get("capped")) == ("live", 10, True)


# --- The walled TLS route ---

TSMC_FIX = Path(__file__).parent / "fixtures/listings/avature_tls"
TSMC_PAGE = json.loads((TSMC_FIX / "page1.json").read_text())["html"]
TSMC_DETAIL = (TSMC_FIX / "detail_430.html").read_text()


def test_a_query_string_posting_id_and_the_us_posted_date_are_read():
    cards = parse_cards(TSMC_PAGE)
    assert len(cards) == 10
    card = next(c for c in cards if c.posting_id == "430")
    assert (card.location, card.worker_type) == ("Taiwan", "Temporary")
    assert card.posted_at is not None and card.posted_at.date().isoformat() == "2026-04-16"
    assert "jobId=430" in card.url


def test_labelled_responsibilities_and_qualifications_are_the_description_not_facts():
    detail = parse_detail(TSMC_DETAIL)
    text = re.sub(r"<[^>]+>", " ", detail.description_html or "")
    assert "Job Responsibilities" in text and "Job Qualifications" in text
    assert "Taiwan Semiconductor Manufacturing Company Limited" not in text, "a fact, not text"
    assert detail.department == "Accessibility Inclusion"
    assert detail.posted_at is not None and detail.posted_at.date().isoformat() == "2026-04-16"


def test_the_walled_route_is_refused_without_consent_and_tiered_with_it():
    from tracker.source_policy import collection_access
    from tracker.source_review import SOURCE_REVIEWS, FetchTier

    refused = collection_access("avature_tls", company="tsmc")
    assert refused.denied and refused.walled
    consent = SOURCE_REVIEWS["avature_tls"].wall_fingerprint
    allowed = collection_access("avature_tls", company="tsmc", consent=consent)
    assert not allowed.denied and allowed.tier is FetchTier.TLS_FINGERPRINT
    assert collection_access("avature", company="electronic-arts").tier is FetchTier.IDENTIFIED


@pytest.mark.asyncio
async def test_no_request_leaves_without_consent():
    from tracker.source_policy import CollectionPolicyDenied

    asked = []
    adapter = build_adapter("tsmc", "avature_tls", board_token="careers.tsmc.com|en_US/careers")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: asked.append(r) or httpx.Response(200)))
    with pytest.raises(CollectionPolicyDenied):
        await _jobs(adapter)
    assert asked == []


# --- overlapping pages on an uncounted board ---


def _ts_pages(rows: list[str], per_page: int = 3) -> str:
    """A synthetic OpenRoles page per offset, from the real page's article markup."""
    article = re.findall(r'<article class="article article--result".*?</article>', TS_PAGE, re.S)[0]
    head, tail = TS_PAGE.split(article, 1)[0], TS_PAGE.rsplit(
        re.findall(r'<article class="article article--result".*?</article>', TS_PAGE, re.S)[-1], 1)[1]
    first_id = re.search(r"/(\d+)\"", article).group(1)
    cards = "".join(article.replace(first_id, rid) for rid in rows)
    return head + cards + tail


class _MovingBoard:
    """A board whose rows change between requests, served by offset."""

    def __init__(self, rows, per_page=3):
        self.rows, self.per_page, self.asked = list(rows), per_page, []

    def page(self, offset):
        return _ts_pages(self.rows[offset: offset + self.per_page]) if offset < len(self.rows) else "<html></html>"


def _moving_adapter(board, on_request=None):
    def handle(request):
        offset = int(request.url.params["jobOffset"])
        board.asked.append(offset)
        if on_request:
            on_request(board, len(board.asked))
        return httpx.Response(200, text=board.page(offset))

    adapter = build_adapter("two-sigma", "avature", board_token=TS_TOKEN)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    return adapter


@pytest.mark.asyncio
async def test_a_posting_closed_mid_walk_cannot_hide_its_neighbour():
    """Rows move UP between pages; without overlap row 4 would slip past unread."""
    board = _MovingBoard([str(i) for i in range(1, 10)])

    def close_row_one_after_first_page(board, n):
        if n == 2:
            board.rows.remove("1")  # served page 1 already; the list shifts up

    adapter = _moving_adapter(board, close_row_one_after_first_page)
    ids = [job.req_id for job in await _jobs(adapter)]
    assert set(ids) >= {str(i) for i in range(2, 10)}, ids
    assert adapter.drift.listing_complete
    assert board.asked[:3] == [0, 2, 1], "the lost anchor sent the walk one row back"


@pytest.mark.asyncio
async def test_a_posting_added_mid_walk_is_read_once():
    board = _MovingBoard([str(i) for i in range(1, 10)])

    def add_after_first_page(board, n):
        if n == 2:
            board.rows.insert(0, "0")

    adapter = _moving_adapter(board, add_after_first_page)
    ids = [job.req_id for job in await _jobs(adapter)]
    assert len(ids) == len(set(ids)) and set(ids) >= {str(i) for i in range(1, 10)}
    assert adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_shift_the_walk_cannot_reconcile_gives_up_closure():
    board = _MovingBoard([str(i) for i in range(1, 30)])

    def churn(board, n):
        if n >= 2:
            board.rows = [str(int(r) + 100) for r in board.rows]  # every row replaced

    adapter = _moving_adapter(board, churn)
    await _jobs(adapter)
    assert not adapter.drift.listing_complete


# --- The capped listing shape ---

DT_TOKEN = "apply.deloitte.com|en_US/careers|capped"
DT_PAGE = json.loads((FIX / "deloitte_page1.json").read_text())["html"]
DT_DETAIL = (FIX / "deloitte_detail_368640.html").read_text()


def _dt_adapter(known_places=None, detail_status=200):
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        if "/JobDetail/" in request.url.path:
            return httpx.Response(detail_status, text=DT_DETAIL if detail_status == 200 else "")
        page = DT_PAGE if request.url.params["jobOffset"] == "0" else "<html></html>"
        return httpx.Response(200, text=page)

    adapter = build_adapter("deloitte", "avature", board_token=DT_TOKEN)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    adapter.known_places = known_places or {}
    return adapter, asked


def test_999_plus_is_a_display_cap_never_a_count():
    from tracker.connectors.listing.avature import capped_total

    assert capped_total(DT_PAGE) is None
    assert capped_total('<article data-total="412">') == 412


@pytest.mark.asyncio
async def test_a_multiple_locations_card_is_placed_from_its_posting_page():
    adapter, asked = _dt_adapter()
    jobs = {job.req_id: job for job in await _jobs(adapter)}
    assert len(jobs) == 10 and adapter.drift.listing_complete
    assert jobs["368605"].locations == ["Rosslyn, Virginia, United States"]
    assert jobs["368640"].locations == ["Atlanta, Georgia, United States", "New York, New York, United States"]
    assert jobs["368640"].description_complete and "internship" in jobs["368640"].description_html
    assert jobs["368605"].department is None, "a legal entity is not a department"
    details = [u for u in asked if "/JobDetail/" in u]
    assert len(details) == 3, "one read per generic card, none for a placed one"
    # The card states no date; the page read to place it does (`datePosted`),
    # and hydration, which skips a page already read, cannot add it later.
    posted = date(2026, 9, 25)
    assert jobs["368640"].posted_at.date() == posted
    assert jobs["368640"].source_facts.first_published_at.date() == posted
    assert jobs["368605"].posted_at is None, "a card placed without its page stays undated"
    await adapter.hydrate(jobs["368640"])
    assert len([u for u in asked if "/JobDetail/" in u]) == 3, "hydration does not read it twice"
    assert jobs["368640"].posted_at.date() == posted


@pytest.mark.asyncio
async def test_places_read_recently_are_reused_without_a_request():
    known = {rid: ("Austin, Texas, United States",) for rid in ("368640", "368569", "368546")}
    adapter, asked = _dt_adapter(known)
    jobs = {job.req_id: job for job in await _jobs(adapter)}
    assert jobs["368569"].locations == ["Austin, Texas, United States"]
    assert not [u for u in asked if "/JobDetail/" in u]


@pytest.mark.asyncio
async def test_a_multiple_locations_card_whose_page_is_unreadable_stays_as_listed():
    # A failed read is not a page that names no place: the card keeps its
    # listed label, in its facts too, rather than being cleared as if the page
    # had said so. The failure is a note keyed by req: the row WAS built and
    # yielded, so it adds nothing to the keys closure reads as present (no
    # bare req id).
    adapter, asked = _dt_adapter(detail_status=404)
    jobs = {job.req_id: job for job in await _jobs(adapter)}
    generic = ("368640", "368569", "368546")
    assert len([u for u in asked if "/JobDetail/" in u]) == 3
    for rid in generic:
        assert jobs[rid].locations == ["Multiple Locations"]
        assert [p.label for p in jobs[rid].source_facts.locations] == ["Multiple Locations"]
        assert not jobs[rid].description_complete
    assert jobs["368605"].locations == ["Rosslyn, Virginia, United States"]
    unreadable = [a for a in adapter.drift.alerts if a["message"] == "posting page unreadable"]
    assert sorted(a["req"] for a in unreadable) == sorted(generic)
    assert adapter.drift.present_only == set()
    assert len(jobs) == 10 and adapter.drift.listing_complete


@pytest.mark.asyncio
@pytest.mark.parametrize(("read", "expected"), [
    (["Austin, Texas"], ["Austin, Texas"]),
    ([], []),  # read, and the page names no place: the generic label goes
    (None, ["Multiple Locations"]),  # not read: nothing is known, the row stays
])
async def test_only_a_page_that_was_read_can_clear_a_generic_place(read, expected):
    adapter, _ = _dt_adapter()
    job = next(j for j in await _jobs(_dt_adapter(detail_status=404)[0]) if j.req_id == "368569")
    assert job.locations == ["Multiple Locations"]

    async def page(_job):
        return read

    await adapter.place_from_page(job, page, clear_listed_place=True)
    assert job.locations == expected
    assert [p.label for p in job.source_facts.locations] == expected


@pytest.mark.asyncio
async def test_a_multiple_locations_card_the_role_gate_drops_costs_no_request():
    # Only an admitted generic card needs a detail request for its places;
    # fetching rejected cards wastes the listing budget.
    adapter, asked = _dt_adapter()
    gated: list[str] = []

    def gate(job):
        gated.append(job.req_id)
        return job.req_id == "368640"

    adapter.place_gate = gate
    jobs = {job.req_id: job for job in await _jobs(adapter)}

    assert len(jobs) == 10 and adapter.drift.listing_complete
    assert sorted(gated) == ["368546", "368569", "368640"], "asked only about generic cards"
    details = [u for u in asked if "/JobDetail/" in u]
    assert len(details) == 1 and details[0].endswith("/368640")
    assert jobs["368640"].locations == ["Atlanta, Georgia, United States", "New York, New York, United States"]
    assert jobs["368569"].locations == ["Multiple Locations"]
    assert jobs["368605"].locations == ["Rosslyn, Virginia, United States"]


# --- The folder listing shape ---

BAIN_TOKEN = "careers.bain.com|jobs|folder"
BAIN_PAGE = json.loads((FIX / "bain_page1.json").read_text())["html"]
BAIN_DETAIL = (FIX / "bain_detail_106191.html").read_text()


def _bain_page(total: int, *, sortable: bool = True) -> str:
    page = BAIN_PAGE.replace("of 266", f"of {total}")
    return page if sortable else page.replace('aria-label="Sort jobs by Posted date"', 'aria-label="Sort jobs"')


def _bain_adapter(default: str, sorted_pages: dict[int, str]):
    asked: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if "/FolderDetail/" in request.url.path:
            return httpx.Response(200, text=BAIN_DETAIL)
        params = dict(request.url.params)
        asked.append(params)
        offset = int(params["folderOffset"])
        if "folderSort" not in params:
            return httpx.Response(200, text=default if offset == 0 else "<html></html>")
        return httpx.Response(200, text=sorted_pages.get(offset, "<html></html>"))

    adapter = build_adapter("bain-company", "avature", board_token=BAIN_TOKEN)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    return adapter, asked


def test_a_folder_portal_is_counted_and_probed_on_its_own_parameters():
    tenant = parse_tenant(BAIN_TOKEN)
    assert tenant.counted
    assert tenant.probe_url() == (
        "https://careers.bain.com/jobs/SearchJobs/?folderRecordsPerPage=10&folderOffset=0"
    )
    assert parse_tenant(TOKEN).probe_url().endswith("SearchJobs/?jobRecordsPerPage=20&jobOffset=0")


def test_folder_cards_carry_every_city_as_a_place():
    cards = parse_cards(BAIN_PAGE, "folder")
    assert len(cards) == 10 and declared_total(BAIN_PAGE) == 266
    assert (cards[0].posting_id, cards[0].location) == ("109068", "New Delhi")
    assert [c.location for c in cards if c.posting_id == "109508"] == ["New York, San Francisco"]
    assert all(c.location is None for c in parse_cards(BAIN_PAGE)), "the search shape reads labelled spans only"


@pytest.mark.asyncio
async def test_the_walk_is_sorted_by_the_portals_posted_date_column():
    """The default order hides a posting, so it is read once only to learn the
    column; every counted page is then asked for newest first."""
    adapter, asked = _bain_adapter(_bain_page(10), {0: _bain_page(10)})
    jobs = await _jobs(adapter)
    assert "folderSort" not in asked[0]
    assert all(a.get("folderSort") == "schemaField_3_194_3" and a["folderSortDirection"] == "DESC"
               for a in asked[1:])
    assert len(jobs) == 10 and adapter.drift.listing_complete
    intern = next(j for j in jobs if j.req_id == "109508")
    assert intern.locations == ["New York", "San Francisco"]
    assert "united_states" in location_groups_for(intern.locations)


@pytest.mark.asyncio
async def test_a_folder_walk_short_of_its_stated_total_closes_nothing():
    adapter, _ = _bain_adapter(_bain_page(11), {0: _bain_page(11)})
    jobs = await _jobs(adapter)
    assert len(jobs) == 10 and not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_folder_portal_without_the_sort_walks_its_default_order_and_says_so():
    adapter, asked = _bain_adapter(_bain_page(10, sortable=False), {})
    jobs = await _jobs(adapter)
    assert all("folderSort" not in a for a in asked)
    assert len(jobs) == 10
    assert any("posted-date sort" in a["message"] for a in adapter.drift.alerts)


def test_a_folder_posting_reads_its_work_area_and_posted_date():
    detail = parse_detail(BAIN_DETAIL, "folder")
    assert detail.department == "Technology & Engineering"
    assert detail.posted_at is not None and detail.posted_at.date().isoformat() == "2026-06-01"
    assert "great place to work" in (detail.description_html or "").lower()
    for fact in ("Permanent Full-Time", "106191"):
        assert fact not in (detail.description_html or ""), f"{fact!r} is a labelled fact, not description"


@pytest.mark.asyncio
async def test_a_placed_card_keeps_the_places_a_page_read_named():
    """Only a generic card ("Multiple Locations") asks the page, so a card that
    names its own place never reached that branch and its single label replaced
    what a page read had named. Locations fail closed, so the posting drops out
    of a scope its page places matched. Fail-first: the card's one place.

    368605 is a placed card: the test above asserts it costs no detail read."""
    known = {"368605": ("Rosslyn, Virginia, United States", "Boston, Massachusetts, United States")}
    adapter, asked = _dt_adapter(known_places=known)
    jobs = {job.req_id: job for job in await _jobs(adapter)}

    assert not [u for u in asked if "368605" in u], "a placed card must still cost no request"
    assert jobs["368605"].locations == [
        "Rosslyn, Virginia, United States", "Boston, Massachusetts, United States",
    ]
