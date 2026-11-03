"""SmartRecruiters: the board route, the walled API route, and the switch.

The contracts, each asserted on what a user would get wrong if it broke:

* **The board walk is complete or says it is not.** Every location group must
  list the postings it states; a group the more-route cannot complete, or fewer
  group pages than the board declared, invalidates the listing (closure
  withheld). Our own page ceiling is truncation, never blamed on the source.
* **The route follows the board.** A board that left SmartRecruiters moves the
  company to the API route; a board published again moves it back. The run
  that detects the move collects nothing (`unattempted`), carries the route
  out, and the pipeline records it: new adapter, old binding retired, a fresh
  binding with closure withheld.
* **The API route is walled.** An unconsented company sends nothing there, and
  a company that moved onto it is shown as walled (its consent dialog), not as
  an unwalled board.

Board fixtures are trimmed real pages (Roland Berger). API
fixtures follow SmartRecruiters' documented Posting API shape: the route is
robots-walled, and nothing was collected from it for this test.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.test_description_hydration import _SCOPE, _NoComp
from tracker import company_discovery
from tracker.company_store import CompanyError, record_route
from tracker.connectors import ADAPTER_REGISTRY, RateLimiterPool, RouteMoved, build_adapter
from tracker.connectors.recipes.outcome import classify_source_outcome
from tracker.db.models import ScrapeRun, SourceBinding, TrackedCompany
from tracker.platform.drift import SchemaDriftDetector
from tracker.platform.ratelimit import RateLimiter
from tracker.schema import WorkplaceType
from tracker.source_policy import CollectionPolicyDenied
from tracker.source_review import SOURCE_REVIEWS
from tracker.workflows import pipeline, post_passes
from tracker.workflows.collection import collect_source
from tracker.workflows.collection_types import empty_stats

FIX = Path(__file__).parent / "fixtures" / "listings"
INDEX = json.loads((FIX / "smartrecruiters" / "page1.json").read_text())["html"]
GROUPS1 = (FIX / "smartrecruiters" / "groups_page1.html").read_text()
MORE1 = (FIX / "smartrecruiters" / "more_amsterdam_page1.html").read_text()
POSTING = (FIX / "smartrecruiters" / "posting_744000148176189.html").read_text()
#: Talan, a board grouped by DEPARTMENT: "Agile" (1 posting, no
#: more-link) and "Architecture" (11: 9 shown + 2 on its more-page).
DEPT_INDEX = (FIX / "smartrecruiters" / "department_index.html").read_text()
DEPT_MORE = (FIX / "smartrecruiters" / "department_more_architecture.html").read_text()
API_PAGE = json.loads((FIX / "smartrecruiters_api" / "page1.json").read_text())
API_DETAIL = json.loads((FIX / "smartrecruiters_api" / "posting_744000150000001.json").read_text())
API_CONSENT = SOURCE_REVIEWS["smartrecruiters_api"].wall_fingerprint


def _wire(adapter, handler):
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    # The adapter's own default headers, as `__aenter__` sets them: the posting
    # host negotiates on `Accept`, so a bare client would hide that.
    adapter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(record), follow_redirects=True, headers=adapter.default_headers(),
    )
    adapter._limiter = RateLimiter(0)
    return adapter, requests


def _board_handler(*, groups1=GROUPS1, more1=MORE1, index=INDEX):
    def handle(request: httpx.Request) -> httpx.Response:
        path, page = request.url.path, request.url.params.get("page")
        if request.url.host == "jobs.smartrecruiters.com":
            # The live posting host negotiates: a client preferring JSON gets
            # an undocumented JSON form, not the microdata page.
            if request.headers.get("accept", "").startswith("application/json"):
                return httpx.Response(200, json={"jobTitle": "x", "postedBy": {"name": "someone"}})
            return httpx.Response(200, text=POSTING)
        if path.endswith("/api/groups"):
            return httpx.Response(200, text=groups1 if page == "1" else "")
        if path.endswith("/api/more"):
            return httpx.Response(200, text=more1 if page == "1" else "")
        return httpx.Response(200, text=index)

    return handle


def _moved_away(request: httpx.Request) -> httpx.Response:
    if request.url.host == "careers.smartrecruiters.com":
        return httpx.Response(301, headers={"Location": "https://wise.jobs/"})
    if request.url.host == "wise.jobs":
        return httpx.Response(200, text="<html><body>Wise careers</body></html>")
    raise AssertionError(f"unexpected request {request.url}")


def _api_handler(page=API_PAGE):
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host in ("careers.smartrecruiters.com", "wise.jobs"):
            return _moved_away(request)
        if request.url.path.endswith("/postings"):
            offset = request.url.params.get("offset")
            return httpx.Response(200, json=page if offset == "0" else {**page, "content": []})
        return httpx.Response(200, json=API_DETAIL)

    return handle


def _board(**kw):
    return _wire(build_adapter("roland-berger", "smartrecruiters", board_token="RolandBerger"), _board_handler(**kw))


def _api(handler=None, consent=API_CONSENT):
    adapter = build_adapter("wise", "smartrecruiters_api", board_token="Wise")
    adapter.collection_consent = consent
    return _wire(adapter, handler or _api_handler())


async def _fetch(adapter):
    return [job async for job in adapter.fetch()]


# --------------------------------------------------------------------------- #
# The board walk
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_the_board_walk_lists_every_group_completely():
    adapter, requests = _board()
    jobs = await _fetch(adapter)

    # 2 + 3 + 19 (9 shown + 10 on its more-page) + 7 + 1.
    assert len(jobs) == 32 and len({j.req_id for j in jobs}) == 32
    amsterdam = [j for j in jobs if j.locations == ["Amsterdam, Netherlands"]]
    assert len(amsterdam) == 19
    assert adapter.drift.listing_complete and adapter.drift.alerts == []
    more = [r for r in requests if r.url.path.endswith("/api/more")]
    # data-page=0 repeats what the group showed, so paging starts at 1; page 2
    # is never asked because the group was complete after page 1.
    assert [(r.url.params["value"], r.url.params["page"]) for r in more] == [("Amsterdam, NL", "1")]
    assert all(j.description_complete is False for j in jobs), "the body is on the posting page"


@pytest.mark.asyncio
@pytest.mark.parametrize(("index", "groups1"), [
    (INDEX.replace('data-groups-pages="2"', 'data-groups-pages="3"'), GROUPS1),
    (INDEX, ""),
], ids=["overstated-pages", "missing-group-page"])
async def test_fewer_group_pages_than_declared_invalidates_unknown_loss(index, groups1):
    adapter, _ = _board(index=index, groups1=groups1)
    jobs = await _fetch(adapter)

    expected = set(re.findall(r"https://jobs.smartrecruiters.com/RolandBerger/(\d+)", index + groups1 + MORE1))
    assert {job.req_id for job in jobs} == expected
    assert not adapter.drift.listing_complete
    assert adapter.drift.listing_invalidated
    assert adapter.drift.records_dropped == 0


@pytest.mark.asyncio
async def test_more_group_pages_than_the_board_declares_loses_nothing():
    """A board can serve more group pages than it declares. Every posting served
    is read, so the listing is complete, not "fewer group pages than it
    declared"."""
    adapter, _ = _board(index=INDEX.replace('data-groups-pages="2"', 'data-groups-pages="1"'))
    jobs = await _fetch(adapter)

    assert len(jobs) == 32 and adapter.drift.listing_complete


def _no_more_links(html: str) -> str:
    """The same page with every group's "Show more jobs" link removed."""
    import re
    return re.sub(r'<a [^>]*class="[^"]*js-more[^"]*"[^>]*>.*?</a>', "", html, flags=re.S)


@pytest.mark.asyncio
async def test_a_board_grouped_by_department_places_each_posting_where_it_prints_its_place():
    """Some SmartRecruiters boards group by department. A group's heading is
    then a department, and each posting prints its OWN place where a location
    board prints employment. Filing "Architecture" as the place and "Paris,
    France" as the employment would leave no radar able to keep one."""
    adapter, requests = _wire(build_adapter("talan", "smartrecruiters", board_token="Talan"),
                              _board_handler(index=DEPT_INDEX, groups1="", more1=DEPT_MORE))
    jobs = await _fetch(adapter)

    assert len(jobs) == 12 and adapter.drift.listing_complete
    assert sorted({place for j in jobs for place in j.locations}) == [
        "Lille, France", "Luxembourg, Luxembourg", "Lyon, France", "Paris, France", "Rennes, France"]
    assert sum(j.locations == ["Paris, France"] for j in jobs) == 7
    assert {j.source_facts.employment_type_raw for j in jobs} == {None}
    more = [r for r in requests if r.url.path.endswith("/api/more")]
    assert [(r.url.params["type"], r.url.params["value"]) for r in more] == [("department", "1601815")]


@pytest.mark.asyncio
async def test_with_no_more_link_a_place_in_the_description_still_reads_as_the_place():
    """A board whose groups all fit on the page says nothing of its grouping:
    a description that is no employment label is the posting's place."""
    adapter, _ = _wire(build_adapter("talan", "smartrecruiters", board_token="Talan"),
                       _board_handler(index=_no_more_links(DEPT_INDEX), groups1=""))
    jobs = await _fetch(adapter)

    agile = [j for j in jobs if j.title.startswith("Product Owner")]
    assert [j.locations for j in agile] == [["Paris, France"]]
    assert not any("Architecture" in j.locations or "Agile" in j.locations for j in jobs)


def _groups(*groups):
    from tracker.connectors.listing.smartrecruiters import _Group, _Posting
    return [
        _Group(label=label, stated=len(details), postings={
            f"{label}-{i}": _Posting(posting_id=f"{label}-{i}", title="t", url="u", detail=d)
            for i, d in enumerate(details)
        })
        for label, details in groups
    ]


@pytest.mark.parametrize("groups,expected", [
    # Real boards whose groups all fit on the page (no more-link):
    ((("Agen, France", ["Temps plein"]), ("Alès, France", ["Temps plein"])), "location"),   # Conforama
    ((("IT", ["Makati City, Philippines", "Taguig, Philippines"]),
      ("Non IT", ["Bonifacio Global City, Philippines"])), "department"),   # "IT" reads as Italy
    ((("Amsterdam, Netherlands", [None]), ("Astana, Kazakhstan", [None])), "location"),     # Santen
    ((("Agile", [None]), ("Architecture", [None])), "location"),   # No grouping evidence.
])
def test_a_board_without_more_links_is_grouped_by_what_reads_as_a_place(groups, expected):
    from tracker.connectors.listing.smartrecruiters import board_grouping

    assert board_grouping(_groups(*groups)) == expected


@pytest.mark.parametrize("declared", ["location", "department"])
def test_a_more_link_declares_the_grouping_whatever_the_page_reads_like(declared):
    """The board's own `data-type` wins over our reading of its text."""
    from tracker.connectors.listing.smartrecruiters import board_grouping

    looks_by_department = _groups(("Agile", ["Paris, France"]), ("Architecture", ["Lyon, France"]))
    looks_by_department[1].more = ("/x/api/more", declared, "1", 1)
    assert board_grouping(looks_by_department) == declared


def test_a_more_link_naming_no_type_leaves_the_grouping_to_the_page():
    """A link without `data-type` is not the board saying "location": read as
    one, a department board takes its headings for places."""
    from tracker.connectors.listing.smartrecruiters import board_grouping, parse_groups

    html = (FIX / "smartrecruiters" / "department_index.html").read_text()
    untyped = parse_groups(html.replace(' data-type="department"', ""))
    assert any(group.more is not None for group in untyped), "the fixture keeps its more-link"
    assert board_grouping(untyped) == "department"
    # Control: the board's own word still decides when it gives one.
    assert board_grouping(parse_groups(html)) == "department"
    assert board_grouping(parse_groups(html.replace('data-type="department"', 'data-type="location"'))) == "location"


@pytest.mark.asyncio
async def test_with_no_more_link_an_employment_label_still_marks_a_location_board():
    """The other side: on a location board the description is employment, and
    the group heading stays the place."""
    adapter, _ = _board(index=_no_more_links(INDEX), groups1=_no_more_links(GROUPS1))
    jobs = await _fetch(adapter)

    aachen = [j for j in jobs if j.locations == ["Aachen, Germany"]]
    assert aachen and {j.source_facts.employment_type_raw for j in aachen} == {"Intern"}


@pytest.mark.asyncio
async def test_a_place_the_caller_does_not_want_is_left_unread_and_counted():
    """The directory scan's hook: Amsterdam's more-page is never
    asked, its 9 shown postings are still listed, and the 10 unread are counted
    as unread by choice, not reported as the board's loss."""
    adapter, requests = _board()
    adapter.wanted_place = lambda label: label != "Amsterdam, Netherlands"
    jobs = await _fetch(adapter)

    assert not [r for r in requests if r.url.path.endswith("/api/more")]
    assert len(jobs) == 22 and adapter.unread_by_choice == 10
    assert len([j for j in jobs if j.locations == ["Amsterdam, Netherlands"]]) == 9
    assert adapter.drift.listing_complete and adapter.drift.alerts == []


@pytest.mark.asyncio
async def test_a_wanted_place_is_read_in_full():
    adapter, requests = _board()
    adapter.wanted_place = lambda label: label == "Amsterdam, Netherlands"
    jobs = await _fetch(adapter)

    assert len([r for r in requests if r.url.path.endswith("/api/more")]) == 1
    assert len(jobs) == 32 and adapter.unread_by_choice == 0


@pytest.mark.asyncio
async def test_a_group_whose_more_route_runs_dry_counts_what_it_never_served():
    """The group states its size, so the shortfall is a known number of
    postings: closure is withheld, and the loss is counted rather than voiding
    the whole board, so the outcome can weigh it against what was read."""
    adapter, _ = _board(more1="")
    jobs = await _fetch(adapter)

    assert len(jobs) == 22, "what was listed is kept"
    assert not adapter.drift.listing_complete, "10 unseen Amsterdam postings must withhold closure"
    assert (adapter.drift.records_dropped, adapter.drift.listing_invalidated) == (10, False)
    assert any("fewer postings than it states" in str(a) and a.get("missing") == 10 for a in adapter.drift.alerts)


@pytest.mark.asyncio
async def test_a_route_one_posting_short_of_its_group_loses_exactly_one():
    """What a board like Talan's does on every read: the more-route runs dry one
    posting before the count its group states."""
    one_short = re.sub(r'<li class="opening-job.*?</li>', "", MORE1, count=1, flags=re.S)
    adapter, _ = _board(more1=one_short)
    jobs = await _fetch(adapter)

    assert len(jobs) == 31
    assert (adapter.drift.records_dropped, adapter.drift.listing_invalidated) == (1, False)
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_group_page_that_does_not_answer_invalidates_the_listing():
    """The control: a page that failed may have held any of the rest."""
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/more"):
            return httpx.Response(503, text="", headers={"Retry-After": "0"})
        return _board_handler()(request)

    adapter, requests = _wire(build_adapter("roland-berger", "smartrecruiters", board_token="RolandBerger"), handle)
    await _fetch(adapter)
    assert adapter.drift.listing_invalidated and not adapter.drift.listing_complete
    assert sum(r.url.path.endswith("/api/more") for r in requests) == 5, "asked again before giving the page up"


@pytest.mark.parametrize(
    ("scanned", "short", "outcome"),
    [
        (498, 5, "lossy"),
        (528, 2, "lossy"),
        (525, 6, "degraded"),
    ],
    ids=["talan-5-of-503", "talan-2-of-530", "talan-6-of-531"],
)
def test_a_board_a_few_postings_short_is_read_in_full_until_the_drop_ratio(scanned, short, outcome):
    """Talan's reads as recorded: groups a handful of postings short of what
    they state, nothing else wrong. Under the record-drop ratio that is a full
    read (`lossy`, closure still withheld); over it the board has changed shape."""
    drift = SchemaDriftDetector("smartrecruiters:talan")
    drift.records_unaccounted(short, "group lists fewer postings than it states", group="Consulting")
    stats = {
        **empty_stats(),
        "scanned": scanned,
        "records_dropped": drift.records_dropped,
        "listing_invalidated": drift.listing_invalidated,
        "list_complete": drift.listing_complete,
    }
    assert classify_source_outcome(stats).value == outcome
    assert stats["list_complete"] is False


@pytest.mark.asyncio
async def test_our_page_ceiling_is_truncation_never_the_sources_loss():
    adapter, _ = _board()
    adapter.page_budget = lambda key, seed: 0 if key == "more" else seed
    jobs = await _fetch(adapter)

    assert len(jobs) == 22
    assert adapter.truncated, "a bound we chose ran out"
    assert adapter.drift.listing_complete and adapter.drift.alerts == [], "and it is not blamed on the board"


# --------------------------------------------------------------------------- #
# Continuing a read our host cut
# --------------------------------------------------------------------------- #


class FakeBoard:
    """A SmartRecruiters location board shaped as the live site serves one:
    groups in heading order, six to a
    group page, nine postings shown per group, ten to a more-page, and a
    heading that can repeat (AECOM: two "Arlington, VA" groups side by side,
    told apart only by their more-route value). Groups can come and go between
    reads, and the connection can drop at any request. Groups are keyed by
    their more-route value, which is their heading unless given."""

    PER_PAGE, SHOWN, MORE = 6, 9, 10

    def __init__(self, groups: dict[str, list[str]], token: str = "Fake"):
        self.token = token
        self.groups: dict[str, list[tuple[str, str]]] = {}
        self.headings: dict[str, str] = {}
        self._next = 744000100000000
        for label, titles in groups.items():
            self.add(label, titles)
        self.requests: list[httpx.Request] = []
        #: Drops the connection from the first request this says yes to.
        self.cut: Callable[[httpx.Request], bool] | None = None
        self.down = False

    def add(self, value: str, titles: list[str], heading: str | None = None) -> None:
        postings = []
        for title in titles:
            self._next += 1
            postings.append((str(self._next), title))
        self.groups[value] = postings
        self.headings[value] = heading or value

    def list_also(self, value: str, under: str) -> None:
        """List `value`'s first posting under another group: one posting at two places."""
        self.groups[under] = [*self.groups[under], self.groups[value][0]]

    def labels(self) -> list[str]:
        """Every group's value, in the board's order."""
        return sorted(self.groups, key=lambda value: (self.headings.get(value, value), value))

    def ids(self, labels=None) -> set[str]:
        return {pid for label in (labels or self.labels()) for pid, _ in self.groups[label]}

    def page_labels(self, number: int) -> list[str]:
        return self.labels()[number * self.PER_PAGE:(number + 1) * self.PER_PAGE]

    def _links(self, postings) -> str:
        from html import escape
        return "".join(
            f'<li class="opening-job"><a href="https://jobs.smartrecruiters.com/{self.token}/{pid}-x"'
            f' class="link--block details js-job-ad-link"><h4 class="details-title job-title">{escape(title)}</h4>'
            f'<p class="details-desc job-desc"><span class="margin--right--s">Full-time</span></p></a></li>'
            for pid, title in postings
        )

    def _section(self, value: str) -> str:
        from html import escape
        from urllib.parse import quote
        postings = self.groups[value]
        more = (
            f'<a data-page="0" data-value="{quote(value)}" data-type="location" data-more="/{self.token}/api/more"'
            f' class="link details-desc js-more">Show more jobs</a>'
            if len(postings) > self.SHOWN else ""
        )
        heading = escape(self.headings.get(value, value))
        return (
            f'<section data-qty="{len(postings)}" class="openings-section opening opening--grouped js-group">'
            f'<header class="opening-header"><ul><li><h3 class="opening-title title">{heading}</h3></li></ul>'
            f'</header><ul class="opening-jobs">{self._links(postings[:self.SHOWN])}</ul>{more}</section>'
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.cut is not None and self.cut(request):
            self.down = True
        if self.down:
            raise httpx.ConnectError("network is unreachable", request=request)
        path, page = request.url.path, int(request.url.params.get("page") or 0)
        if path.endswith("/api/groups"):
            return httpx.Response(200, text="".join(self._section(label) for label in self.page_labels(page)))
        if path.endswith("/api/more"):
            postings = self.groups.get(request.url.params["value"], [])
            first = self.SHOWN + (page - 1) * self.MORE
            return httpx.Response(200, text=self._links(postings[first:first + self.MORE]))
        pages = -(-len(self.groups) // self.PER_PAGE)
        return httpx.Response(200, text=(
            f'<html><head><meta property="og:title" content="Careers at {self.token}"></head><body>'
            f'<div data-groups-pages="{pages}">{"".join(self._section(label) for label in self.page_labels(0))}'
            "</div></body></html>"
        ))

    def group_pages_asked(self, since: int = 0) -> list[int]:
        return [int(r.url.params["page"]) for r in self.requests[since:] if r.url.path.endswith("/api/groups")]

    def more_values_asked(self, since: int = 0) -> list[str]:
        return [r.url.params["value"] for r in self.requests[since:] if r.url.path.endswith("/api/more")]


#: 24 cities over four group pages; some need more-pages, AECOM-style.
CITIES = [
    "Aachen, Germany", "Amsterdam, Netherlands", "Athens, Greece", "Austin, TX", "Barcelona, Spain",
    "Berlin, Germany", "Boston, MA", "Brussels, Belgium", "Chicago, IL", "Dallas, TX", "Denver, CO",
    "Dublin, Ireland", "Frankfurt, Germany", "Geneva, Switzerland", "Hamburg, Germany",
    "Helsinki, Finland", "Houston, TX", "Lisbon, Portugal", "London, UK", "Lyon, France",
    "Madrid, Spain", "Milan, Italy", "Munich, Germany", "Oslo, Norway",
]


@pytest.mark.asyncio
async def test_an_unknown_missing_page_is_not_a_negligible_single_record_drop():
    board = FakeBoard({city: [f"Engineer {i}" for i in range(20)] for city in CITIES[:7]})

    def handle(request):
        response = board.handle(request)
        if not request.url.path.endswith(("/api/groups", "/api/more")):
            return httpx.Response(200, text=response.text.replace('data-groups-pages="2"', 'data-groups-pages="3"'))
        return response

    adapter, _ = _wire(build_adapter("aecom", "smartrecruiters", board_token=board.token), handle)
    jobs = await _fetch(adapter)
    assert len(jobs) == 140
    assert {job.req_id for job in jobs} == board.ids()
    assert adapter.drift.listing_invalidated
    assert adapter.drift.records_dropped == 0
    assert classify_source_outcome({
        **empty_stats(), "scanned": len(jobs), "list_complete": adapter.drift.listing_complete,
        "records_dropped": adapter.drift.records_dropped, "listing_invalidated": adapter.drift.listing_invalidated,
    }).value == "degraded"


def _fake_board() -> FakeBoard:
    sizes = [3, 25, 1, 12, 2, 31, 4, 9, 14, 1, 2, 22, 5, 1, 17, 3, 2, 11, 40, 2, 6, 1, 19, 3]
    return FakeBoard({city: [f"Project Manager {i}" for i in range(n)] for city, n in zip(CITIES, sizes, strict=True)})


def _reader(board: FakeBoard, resume_from=None):
    adapter, _ = _wire(build_adapter("fake", "smartrecruiters", board_token=board.token), board.handle)
    adapter.max_retries = 0  # a dropped connection fails the request at once
    adapter.resume_from = resume_from
    return adapter


async def _read_until_cut(board: FakeBoard, resume_from=None):
    adapter = _reader(board, resume_from)
    with pytest.raises(httpx.ConnectError):
        await _fetch(adapter)
    board.down, board.cut = False, None
    return adapter


def _asks_group_page(number):
    return lambda r: r.url.path.endswith("/api/groups") and r.url.params.get("page") == str(number)


@pytest.mark.asyncio
async def test_a_read_cut_holds_the_place_after_the_last_page_it_finished():
    board = _fake_board()
    board.cut = _asks_group_page(2)

    adapter = await _read_until_cut(board)

    held = adapter.resume_point
    assert held.at == {
        "page": 1, "grouping": "location",
        "groups": [[city, sorted(board.ids([city]))] for city in CITIES[6:12]],
    }
    assert held.listed == board.ids(CITIES[:12]), "every posting on pages 0 and 1, each group complete"


@pytest.mark.asyncio
async def test_a_continued_read_reads_on_from_just_after_the_last_label_it_finished():
    board = _fake_board()
    board.list_also("Amsterdam, Netherlands", under="Frankfurt, Germany")   # pages 0 and 2
    board.cut = _asks_group_page(2)
    first = await _read_until_cut(board)
    asked = len(board.requests)

    second = _reader(board, first.resume_point)
    jobs = await _fetch(second)

    assert second.resumed and second.drift.listing_complete, second.drift.alerts
    assert {j.req_id for j in jobs} == board.ids(CITIES[12:]), "only what the first part never read"
    assert first.resume_point.listed | {j.req_id for j in jobs} == board.ids()
    # Page 2 is asked first (a group added before the place would have pushed
    # it there), then page 1 to find it, then on to the end; never page 0 again.
    assert board.group_pages_asked(asked) == [2, 1, 3, 4]
    assert set(board.more_values_asked(asked)) == {c for c in CITIES[12:] if len(board.groups[c]) > board.SHOWN}
    assert not set(board.more_values_asked(asked)) & set(CITIES[:12])


@pytest.mark.asyncio
async def test_a_group_added_before_the_place_pushes_it_onto_the_next_page_and_nothing_is_read_twice():
    board = _fake_board()
    board.cut = _asks_group_page(2)
    first = await _read_until_cut(board)
    board.add("Abu Dhabi, UAE", ["Project Manager"])   # before every label the first part read
    asked = len(board.requests)

    second = _reader(board, first.resume_point)
    jobs = await _fetch(second)

    assert second.resumed and second.drift.listing_complete
    assert {j.req_id for j in jobs} == board.ids(CITIES[12:])
    # 25 groups now: five pages, the place on page 2 (the page read anyway).
    assert board.group_pages_asked(asked) == [2, 3, 4, 5]


@pytest.mark.asyncio
async def test_a_group_gone_before_the_place_leaves_it_on_its_page_and_the_next_one_is_not_skipped():
    board = _fake_board()
    board.cut = _asks_group_page(2)
    first = await _read_until_cut(board)
    del board.groups["Athens, Greece"]                # Frankfurt slides back onto page 1
    asked = len(board.requests)

    second = _reader(board, first.resume_point)
    jobs = await _fetch(second)

    assert second.resumed and second.drift.listing_complete
    assert {j.req_id for j in jobs} == board.ids(CITIES[12:]), "Frankfurt is read from page 1"
    assert board.group_pages_asked(asked) == [2, 1, 3, 4]


@pytest.mark.asyncio
async def test_a_group_under_the_same_heading_as_the_last_one_finished_is_still_read():
    """AECOM lists two groups headed "Arlington, VA" side by side. Across a
    page boundary, a heading alone would take the second
    for the finished first, skip it, and still call the board read whole."""
    board = _fake_board()
    board.add("Dublin, Ireland, IE", ["Project Manager"] * 3, heading="Dublin, Ireland")  # first on page 2
    board.cut = _asks_group_page(2)
    first = await _read_until_cut(board)
    asked = len(board.requests)

    second = _reader(board, first.resume_point)
    jobs = await _fetch(second)

    assert second.resumed and second.drift.listing_complete
    assert {j.req_id for j in jobs} == board.ids(["Dublin, Ireland, IE", *CITIES[12:]])
    assert board.group_pages_asked(asked) == [2, 1, 3, 4, 5]


@pytest.mark.asyncio
async def test_a_place_that_has_moved_out_of_reach_reads_the_board_from_its_start():
    board = _fake_board()
    board.cut = _asks_group_page(2)
    first = await _read_until_cut(board)
    for city in CITIES[:12]:                           # every label the first part finished is gone
        del board.groups[city]

    second = _reader(board, first.resume_point)
    jobs = await _fetch(second)

    assert not second.resumed and second.drift.listing_complete
    assert {j.req_id for j in jobs} == board.ids(), "a fresh read of the board as it is now"


@pytest.mark.asyncio
async def test_a_continued_read_is_complete_only_if_its_own_part_lists_what_each_group_states():
    board = _fake_board()
    board.cut = _asks_group_page(2)
    first = await _read_until_cut(board)
    board.MORE = 0                                     # more-pages now come back empty

    second = _reader(board, first.resume_point)
    await _fetch(second)

    assert second.resumed and not second.drift.listing_complete


@pytest.mark.asyncio
async def test_a_part_that_was_already_incomplete_leaves_no_place_to_continue_from():
    """Continued, the union would inherit a loss the second part cannot see."""
    board = _fake_board()
    original = board.handle

    def amsterdam_short(request):
        if request.url.path.endswith("/api/more") and request.url.params["value"] == "Amsterdam, Netherlands":
            board.requests.append(request)
            return httpx.Response(200, text="")
        return original(request)

    board.handle = amsterdam_short
    board.cut = _asks_group_page(2)
    adapter = _reader(board)
    with pytest.raises(httpx.ConnectError):
        await _fetch(adapter)

    assert adapter.resume_point is None


@pytest.mark.asyncio
async def test_cut_again_before_the_place_is_found_the_read_still_holds_it():
    board = _fake_board()
    board.cut = _asks_group_page(2)
    first = await _read_until_cut(board)

    board.cut = _asks_group_page(2)
    second = await _read_until_cut(board, first.resume_point)

    assert second.resume_point == first.resume_point and not second.resumed


@pytest.mark.asyncio
async def test_a_continued_read_stops_at_the_same_page_ceiling_as_a_fresh_one():
    """The ceiling bounds the page index, not the pages this part asked for:
    cut there, it is our bound (`truncated`), never the board's loss."""
    board = _fake_board()
    board.cut = _asks_group_page(2)
    first = await _read_until_cut(board)

    second = _reader(board, first.resume_point)
    second.page_budget = lambda key, seed: 3 if key == "groups" else seed
    await _fetch(second)

    assert second.resumed and second.truncated
    assert second.drift.listing_complete, "pages we never asked for are not blamed on the board"


@pytest.mark.asyncio
async def test_the_collector_never_continues_a_read():
    """A read stitched from two moments is no closure evidence: the collection
    path never sets `resume_from`, so its reads start at page one."""
    board = _fake_board()
    adapter, _ = _wire(build_adapter("fake", "smartrecruiters", board_token=board.token), board.handle)

    jobs = await _fetch(adapter)

    assert adapter.resume_from is None and not adapter.resumed
    assert {j.req_id for j in jobs} == board.ids() and board.group_pages_asked() == [1, 2, 3, 4]


# --------------------------------------------------------------------------- #
# The switch
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_board_that_left_smartrecruiters_moves_the_company_to_the_api_route():
    adapter, requests = _wire(build_adapter("wise", "smartrecruiters", board_token="Wise"), _moved_away)
    with pytest.raises(RouteMoved) as raised:
        await _fetch(adapter)
    assert raised.value.route == "smartrecruiters_api"
    assert isinstance(raised.value, CollectionPolicyDenied), "local decision: unattempted, health untouched"
    assert "wise.jobs" in raised.value.access.reason
    assert [r.url.host for r in requests] == ["careers.smartrecruiters.com", "wise.jobs"]


@pytest.mark.asyncio
async def test_the_api_route_moves_back_when_the_board_is_published():
    adapter, requests = _api(handler=_board_handler())
    with pytest.raises(RouteMoved) as raised:
        await _fetch(adapter)
    assert raised.value.route == "smartrecruiters"
    assert all(r.url.host != "api.smartrecruiters.com" for r in requests), "the walled route is not touched"


@pytest.mark.asyncio
async def test_an_unconsented_company_sends_nothing_to_the_walled_api_route():
    adapter, requests = _api(consent=None)
    with pytest.raises(PermissionError, match="walled"):
        async with adapter:
            pass
    assert requests == []


@pytest.mark.asyncio
async def test_the_api_route_lists_postings_against_its_declared_total():
    adapter, _ = _api()
    jobs = await _fetch(adapter)

    assert [j.req_id for j in jobs] == [p["id"] for p in API_PAGE["content"]]
    principal = jobs[2]
    assert principal.locations == ["Austin, TX, United States"]
    assert principal.workplace_type is WorkplaceType.REMOTE
    assert principal.department == "Engineering" and principal.raw_level == "Director"
    assert principal.url == "https://jobs.smartrecruiters.com/Wise/744000150000003"
    assert adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_fewer_unique_postings_than_total_found_is_never_complete():
    adapter, _ = _api(handler=_api_handler({**API_PAGE, "totalFound": 4}))
    jobs = await _fetch(adapter)
    assert [job.req_id for job in jobs] == [posting["id"] for posting in API_PAGE["content"]]
    assert not adapter.drift.listing_complete
    assert adapter.drift.records_dropped == 4 - len(jobs)
    assert not adapter.drift.listing_invalidated


# --------------------------------------------------------------------------- #
# A listing read inside the refresh window keeps the page's place
# --------------------------------------------------------------------------- #

PAGE_PLACE = "Santa Clara, California, United States"
READ = "744000148176189"  # listed in "Amsterdam, Netherlands"


async def _listed(known):
    adapter, _ = _board()
    adapter.known_places = known
    return next(j for j in await _fetch(adapter) if j.req_id == READ)


@pytest.mark.asyncio
async def test_a_listing_read_keeps_the_place_its_page_stated():
    """`hydrate` prepends the page's place, and a rescan inside
    `description_refresh_days` skips hydrate. The listing's places must not
    replace the stored ones and withdraw the page's place, which hides a
    posting from a scope that only the page's place matches."""
    job = await _listed({READ: (PAGE_PLACE, "Amsterdam, Netherlands")})
    assert job.locations == [PAGE_PLACE, "Amsterdam, Netherlands"]
    # The observation records what the listing said, nothing added.
    assert [p.label for p in job.source_facts.locations] == ["Amsterdam, Netherlands"]


@pytest.mark.asyncio
async def test_a_place_the_listing_adds_joins_and_a_case_change_adds_nothing():
    job = await _listed({READ: (PAGE_PLACE,)})
    assert job.locations == [PAGE_PLACE, "Amsterdam, Netherlands"]
    job = await _listed({READ: (PAGE_PLACE, "AMSTERDAM, NETHERLANDS")})
    assert job.locations == [PAGE_PLACE, "AMSTERDAM, NETHERLANDS"]


@pytest.mark.asyncio
async def test_a_posting_with_no_recent_page_read_lists_its_listing_places():
    job = await _listed({})
    assert job.locations == ["Amsterdam, Netherlands"]


# --------------------------------------------------------------------------- #
# Hydration
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_board_posting_is_hydrated_from_its_page_microdata():
    adapter, _ = _board()
    jobs = await _fetch(adapter)
    job = next(j for j in jobs if j.req_id == "744000148176189")

    await adapter.hydrate(job)

    assert job.description_complete and "Company Description" in job.description_html
    assert job.posted_at == datetime(2026, 9, 8, 9, 0, 1, 255000, tzinfo=UTC)
    assert job.workplace_type is WorkplaceType.ONSITE
    place = job.source_facts.locations[0]
    assert (place.locality, place.region, place.country) == ("Amsterdam", "North Holland", "Netherlands")
    assert place.label == "Amsterdam, North Holland, Netherlands", "a PLACE, never the typed address"
    assert job.source_facts.employment_type_raw == "Full-time"


@pytest.mark.asyncio
async def test_an_api_posting_is_hydrated_from_its_sections():
    adapter, _ = _api()
    job = (await _fetch(adapter))[0]

    await adapter.hydrate(job)

    assert job.description_html.count("<h2>") == 4
    assert "lead three payments teams" in job.description_html
    assert job.url == API_DETAIL["postingUrl"]


# --------------------------------------------------------------------------- #
# Collection carries the route out; the store records it
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_collection_reports_a_moved_route_as_unattempted_with_no_error():
    adapter, _ = _wire(build_adapter("wise", "smartrecruiters", board_token="Wise"), _moved_away)
    result = await collect_source(
        "wise", {"adapter": "smartrecruiters", "board_token": "Wise"}, _SCOPE, _NoComp(),
        max_list=None, hydrate=False, limiter_pool=RateLimiterPool(),
        adapter_factory=lambda *a, **kw: adapter,
    )
    assert result.route == "smartrecruiters_api"
    assert result.stats["unattempted"] is True and result.stats["errors"] == []
    assert not result.list_complete


def _tracked(slug: str, adapter: str, **over) -> TrackedCompany:
    fields = {
        "slug": slug, "display": slug.title(), "adapter": adapter, "board_token": "Tok",
        "careers_url": f"https://{slug}.example/careers", "status": "active", "enabled": True,
        "visible": True, "source": "catalog", "role_catalog_status": "pending",
    }
    return TrackedCompany(**{**fields, **over})


@pytest.mark.asyncio
async def test_record_route_rebinds_with_closure_withheld(db_session):
    db_session.add(_tracked("servicenow", "smartrecruiters"))
    await db_session.flush()
    db_session.add(SourceBinding(
        company_slug="servicenow", connector_kind="adapter", connector_id="smartrecruiters",
        status="stable", closure_capability="authoritative",
    ))
    await db_session.flush()

    assert await record_route(db_session, "servicenow", "smartrecruiters_api") is True

    row = await db_session.get(TrackedCompany, "servicenow")
    assert row.adapter == "smartrecruiters_api"
    bindings = (await db_session.scalars(
        select(SourceBinding).where(SourceBinding.company_slug == "servicenow").order_by(SourceBinding.id)
    )).all()
    old, new = bindings
    assert old.status == "retired" and old.retired_at is not None
    assert "smartrecruiters -> smartrecruiters_api" in old.notes
    assert new.connector_id == "smartrecruiters_api" and new.status == "stable"
    assert new.closure_capability == "none", "the new route closes nothing until validated"
    # Idempotent: already there.
    assert await record_route(db_session, "servicenow", "smartrecruiters_api") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["greenhouse", "no-such-adapter"])
async def test_record_route_refuses_a_move_across_families(db_session, route):
    db_session.add(_tracked("servicenow", "smartrecruiters"))
    await db_session.flush()
    with pytest.raises(CompanyError, match="not routes of one family"):
        await record_route(db_session, "servicenow", route)
    assert (await db_session.get(TrackedCompany, "servicenow")).adapter == "smartrecruiters"


def test_a_company_that_moved_onto_the_api_route_is_shown_walled():
    moved = _tracked("servicenow", "smartrecruiters_api")
    assert company_discovery.company_wall("servicenow", moved) is SOURCE_REVIEWS["smartrecruiters_api"]
    assert not company_discovery.is_curated("servicenow", moved)
    # On the board route, as the catalog declares, nothing walls it.
    assert company_discovery.company_wall("servicenow", _tracked("servicenow", "smartrecruiters")) is None
    # A stored adapter from ANOTHER family never overrides the declared one.
    assert company_discovery.company_wall("servicenow", _tracked("servicenow", "google")) is None
    # Wise is catalogued on the API route: walled from the start.
    assert company_discovery.company_wall("wise") is SOURCE_REVIEWS["smartrecruiters_api"]


# --------------------------------------------------------------------------- #
# End to end through the pipeline
# --------------------------------------------------------------------------- #


@pytest.fixture
def isolated_pipeline(db_session, monkeypatch):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    @asynccontextmanager
    async def session_scope():
        async with factory() as session:
            yield session
            await session.commit()

    class Compensation:
        def __init__(self, *_providers) -> None:
            pass

        async def resolve(self, _context):
            return None, []

        def reset(self, _providers, *, fingerprint):
            self.fingerprint = fingerprint

        async def aclose(self):
            pass

    monkeypatch.setattr(pipeline, "session_scope", session_scope)
    monkeypatch.setattr(pipeline, "CompResolver", Compensation)
    monkeypatch.setattr(post_passes, "POST_PASSES", ())


@pytest.mark.asyncio
async def test_the_pipeline_moves_the_company_and_the_next_run_waits_for_consent(
    db_session, isolated_pipeline, monkeypatch
):
    requests: list[httpx.Request] = []

    class Moved(ADAPTER_REGISTRY["smartrecruiters"]):
        async def __aenter__(self):
            await super().__aenter__()
            self._client = httpx.AsyncClient(
                transport=httpx.MockTransport(lambda r: (requests.append(r), _moved_away(r))[1]),
                follow_redirects=True,
            )
            self._limiter = RateLimiter(0)
            return self

    monkeypatch.setitem(ADAPTER_REGISTRY, "smartrecruiters", Moved)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _refuse)
    db_session.add(_tracked("wise", "smartrecruiters", board_token="Wise"))
    await db_session.commit()

    await pipeline.run_pipeline(companies=["wise"], hydrate=False)

    await db_session.refresh(row := await db_session.get(TrackedCompany, "wise"))
    assert row.adapter == "smartrecruiters_api"
    run = (await db_session.scalars(select(ScrapeRun).order_by(ScrapeRun.id.desc()))).first()
    assert run.per_source["wise"]["outcome"] == "unattempted"
    assert run.per_source["wise"]["errors"] == []

    # The next run is on the walled route, and the user has not consented.
    before = len(requests)
    await pipeline.run_pipeline(companies=["wise"], hydrate=False)
    run = (await db_session.scalars(select(ScrapeRun).order_by(ScrapeRun.id.desc()))).first()
    assert "walled" in run.per_source["wise"]["policy_reason"]
    assert len(requests) == before, "nothing is sent for an unconsented walled company"


async def _refuse(*_args, **_kwargs):
    raise AssertionError("a pipeline test reached the network")
