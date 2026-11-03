"""Shopify's streamed careers listing, in both shapes the page streams.

The contracts, each on what a seeker would get wrong if it broke:

* **The stream is the listing**: every streamed posting is read, including
  postings absent from the rendered HTML; a page with no stream invalidates.
* **Either shape is the listing**: a page streaming `roles` summaries is read
  as completely as one streaming Ashby records, and the posting page fills in
  the date and employment type a summary does not state.
* **Nobody's name or email is kept**: the rows carry the hiring team, and
  nothing of it may reach a stored posting.
* **Every posting is placed**, with "Americas" read by the region rule, and a
  location id the table cannot resolve is never guessed.
* **An unlisted posting is not read**; a list with nothing listed is an empty
  board, never a failed read; a posting streamed twice is one posting.

"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict

import httpx
import pytest

from tests.contracts.conftest import fixture_dir, load_fixture
from tracker.connectors import build_adapter
from tracker.connectors.extract.turbo_stream import decode_turbo_stream, loader_data
from tracker.connectors.listing.shopify import location_label, role_place
from tracker.enrich.classify import location_groups_for
from tracker.platform.ratelimit import RateLimiter
from tracker.schema import EmploymentType, WorkplaceType

PAGE = load_fixture("shopify", "page1.json")["html"]
ROLES = load_fixture("shopify", "roles.json")["html"]
POSTING = (fixture_dir("shopify") / "posting_ef12f6c3.html").read_text()
PEOPLE = ("Given", "Family", "person@example.com", "Internal job title", "hiringTeam", "Hiring Manager")


def _adapter(page: str = PAGE, posting: str = POSTING, status: int = 200):
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=page if request.url.path == "/careers" else posting)

    adapter = build_adapter("shopify", "shopify")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    return adapter


async def _jobs(adapter):
    try:
        return [job async for job in adapter.fetch()]
    finally:
        await adapter._client.aclose()


@pytest.mark.asyncio
async def test_the_streamed_postings_are_the_listing_not_the_rendered_html():
    adapter = _adapter()
    jobs = await _jobs(adapter)
    assert len(jobs) == 114 == len({j.req_id for j in jobs})
    assert PAGE.count('href="/careers/') < 114, "the HTML renders only some of them"
    assert adapter.drift.listing_complete and adapter.drift.alerts == []
    first = next(j for j in jobs if j.req_id == "69bdefc2-b2f5-4277-996b-7b677bcf1c0a")
    assert first.title == "Account Executive, SMB, German-speaking"
    assert first.url == ("https://www.shopify.com/careers/"
                         "account-executive-smb-german-speaking_69bdefc2-b2f5-4277-996b-7b677bcf1c0a")
    assert first.department == "Commercial" and first.workplace_type is WorkplaceType.REMOTE
    assert first.source_facts.employment_type_normalized is EmploymentType.FULL_TIME
    assert first.locations == ["Ireland", "United Kingdom"], "primary, then secondary"


@pytest.mark.asyncio
async def test_no_persons_name_or_email_reaches_a_posting():
    stream = json.dumps(decode_turbo_stream(PAGE), default=str)
    assert all(word in stream for word in ("person@example.com", "Hiring Manager")), "the fixture carries them"
    for job in await _jobs(_adapter()):
        stored = json.dumps(asdict(job), default=str)
        leaked = [word for word in PEOPLE if word in stored]
        assert not leaked, f"{job.req_id} carries {leaked}"
        assert job.detail_payload is None, "no raw row is handed onward"


@pytest.mark.asyncio
async def test_every_posting_is_placed_the_americas_by_the_region_rule():
    jobs = await _jobs(_adapter())
    assert sum(j.locations == ["Americas"] for j in jobs) == 87
    assert all(location_groups_for(j.locations) for j in jobs)
    americas = next(j for j in jobs if j.locations == ["Americas"])
    groups = location_groups_for(americas.locations)
    assert {"united_states", "canada", "brazil"} <= set(groups) and "germany" not in groups


def test_a_city_location_is_written_with_its_region_and_country():
    assert location_label({"name": "Bellevue", "address": {"postalAddress": {
        "addressLocality": "Bellevue", "addressRegion": "Washington", "addressCountry": "United States",
    }}}) == "Bellevue, Washington, United States"
    assert location_label({"name": "Americas", "address": {"postalAddress": {"addressCountry": "Americas"}}}) == "Americas"
    assert location_label({"name": "EMEA", "address": None}) == "EMEA"


@pytest.mark.asyncio
@pytest.mark.parametrize("page,status", [
    ("<html><body>no stream</body></html>", 200),
    (PAGE, 503),
])
async def test_a_page_that_is_not_the_listing_invalidates(page, status):
    adapter = _adapter(page=page, status=status)
    adapter.settings = adapter.settings.model_copy(update={"scraper_max_retries": 0})
    assert await _jobs(adapter) == []
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_hydrate_reads_the_description_from_the_posting_page():
    adapter = _adapter()
    job = next(j for j in await _jobs(adapter) if j.req_id.startswith("ef12f6c3"))
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, text=POSTING)))
    try:
        await adapter.hydrate(job)
    finally:
        await adapter._client.aclose()
    assert job.description_complete and job.description_html.startswith("<h2>About Shop</h2>")


def test_the_stream_decoder_reads_shared_values_and_sentinels():
    # Index 0 is the root; "_N" keys and values are indices, -5 is undefined,
    # -7 null, and "Shop" is one slot read twice.
    table = [{"_1": 2, "_3": -5, "_4": 5}, "name", "Shop", "missing", "list", [2, 2, -7]]
    page = ("<script>window.__reactRouterContext.streamController.enqueue("
            + json.dumps(json.dumps(table)) + ");</script>")
    assert decode_turbo_stream(page) == {"name": "Shop", "missing": None, "list": ["Shop", "Shop", None]}
    assert decode_turbo_stream("<html></html>") is None
    assert loader_data(POSTING, "($locale)/careers/$posting")["jobPosting"]["title"] == "Affiliate Marketing Lead, Shop"


ROUTE = "($locale)/careers"


def _encode(root: object) -> str:
    """A careers page streaming `root`, in the table form the decoder reads.

    A dict or list met twice is written once and referenced by index, so a
    value that contains itself encodes as the cycle the page would carry."""
    table: list[object] = []
    placed: dict[int, int] = {}

    def put(value: object) -> int:
        if value is None:
            return -7
        if isinstance(value, (dict, list)) and id(value) in placed:
            return placed[id(value)]
        index = len(table)
        table.append(None)
        if isinstance(value, dict):
            placed[id(value)] = index
            table[index] = {f"_{put(key)}": put(item) for key, item in value.items()}
        elif isinstance(value, list):
            placed[id(value)] = index
            table[index] = [put(item) for item in value]
        else:
            table[index] = value
        return index

    put(root)
    return ("<script>window.__reactRouterContext.streamController.enqueue("
            + json.dumps(json.dumps(table)) + ");</script>")


def _listing(edit) -> str:
    """The real fixture's listing, changed by `edit(rows, locations)`, re-streamed."""
    data = copy.deepcopy(loader_data(PAGE, ROUTE))
    edit(data["jobPostingsWithJobs"], data["atsLocations"])
    return _encode({"loaderData": {ROUTE: data}})


def _posting(rows: list, req: str) -> dict:
    return next(row["jobPosting"] for row in rows if row["jobPosting"]["id"] == req)


FIRST = "69bdefc2-b2f5-4277-996b-7b677bcf1c0a"


def test_the_encoder_round_trips_the_fixture():
    # The edits below are only as good as the re-streamed page they produce.
    assert loader_data(_listing(lambda _rows, _locs: None), ROUTE) == loader_data(PAGE, ROUTE)


@pytest.mark.asyncio
async def test_an_unlisted_posting_is_not_read_and_does_not_cost_closure():
    page = _listing(lambda rows, _locs: _posting(rows, FIRST).update(isListed=False))
    adapter = _adapter(page=page)
    jobs = await _jobs(adapter)
    assert FIRST not in {job.req_id for job in jobs} and len(jobs) == 113
    assert adapter.drift.listing_complete and adapter.drift.alerts == []


@pytest.mark.asyncio
async def test_a_list_with_nothing_listed_proves_the_board_empty_and_closes_nothing():
    def unlist(rows, _locs):
        for row in rows:
            row["jobPosting"]["isListed"] = False

    adapter = _adapter(page=_listing(unlist))
    assert await _jobs(adapter) == []
    assert adapter.drift.empty_proven and not adapter.drift.listing_complete
    assert adapter.drift.alerts == [], "an empty board is not a failed read"


@pytest.mark.asyncio
async def test_an_empty_posting_list_is_the_same_empty_board():
    adapter = _adapter(page=_listing(lambda rows, _locs: rows.clear()))
    assert await _jobs(adapter) == []
    assert adapter.drift.empty_proven and not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_location_ids_the_table_cannot_resolve_are_never_guessed():
    def orphan(rows, _locs):
        _posting(rows, FIRST)["locationIds"] = {"primaryLocationId": "no-such-place",
                                                "secondaryLocationIds": ["nor-this"]}

    adapter = _adapter(page=_listing(orphan))
    jobs = {job.req_id: job for job in await _jobs(adapter)}
    posting = _posting(loader_data(PAGE, ROUTE)["jobPostingsWithJobs"], FIRST)
    # Falls back to the posting's own stated place, and invents nothing else.
    assert jobs[FIRST].locations == [posting["locationName"].strip()]
    assert adapter.drift.listing_complete

    def orphan_unnamed(rows, locs):
        orphan(rows, locs)
        _posting(rows, FIRST)["locationName"] = None

    jobs = {job.req_id: job for job in await _jobs(_adapter(page=_listing(orphan_unnamed)))}
    assert jobs[FIRST].locations == [], "unplaced, so no scope can match it by accident"


@pytest.mark.asyncio
async def test_a_posting_streamed_twice_is_one_posting():
    page = _listing(lambda rows, _locs: rows.append(copy.deepcopy(next(
        row for row in rows if row["jobPosting"]["id"] == FIRST))))
    adapter = _adapter(page=page)
    jobs = await _jobs(adapter)
    assert [job.req_id for job in jobs].count(FIRST) == 1 and len(jobs) == 114
    assert adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_value_that_contains_itself_decodes_and_never_reaches_a_posting():
    def loop(rows, locs):
        posting = _posting(rows, FIRST)
        posting["teamName"] = posting           # a read field pointing back at its record
        locs[0]["address"]["self"] = locs[0]    # and a cycle inside the location table

    page = _listing(loop)
    decoded = _posting(loader_data(page, ROUTE)["jobPostingsWithJobs"], FIRST)
    assert decoded["teamName"] is decoded, "the page really streams the cycle"
    adapter = _adapter(page=page)
    jobs = {job.req_id: job for job in await _jobs(adapter)}
    assert len(jobs) == 114 and adapter.drift.listing_complete
    first = jobs[FIRST]
    assert first.department is None, "a non-text team is not a team"
    json.dumps(asdict(first), default=str)  # no cycle survives into the posting


# --------------------------------------------------------------------------- #
# The `roles` shape
# --------------------------------------------------------------------------- #

ROLE = "8b0403e4-137a-4f29-8f88-254c2ac0a716"


def _roles(edit) -> str:
    """The real `roles` fixture, changed by `edit(roles)`, re-streamed."""
    data = copy.deepcopy(loader_data(ROLES, ROUTE))
    edit(data["roles"])
    return _encode({"loaderData": {ROUTE: data}})


@pytest.mark.asyncio
async def test_a_page_streaming_roles_is_read_as_the_whole_listing():
    adapter = _adapter(page=ROLES)
    jobs = await _jobs(adapter)
    assert len(jobs) == 121 == len({j.req_id for j in jobs})
    assert ROLES.count('href="/careers/') < 121, "the HTML renders only some of them"
    assert adapter.drift.listing_complete and adapter.drift.alerts == []
    role = next(j for j in jobs if j.req_id == ROLE)
    assert role.title == "Account Executive, SMB Existing Business"
    assert role.url == f"https://www.shopify.com/careers/account-executive-smb-existing-business_{ROLE}"
    assert role.locations == ["Ireland", "United Kingdom"], "in the page's order, prefix gone"
    assert role.workplace_type is WorkplaceType.REMOTE and role.department == "Sales"
    assert all(location_groups_for(j.locations) for j in jobs), "every role is placed"


def test_a_role_place_splits_the_workplace_from_the_place():
    assert role_place("Remote - Hong Kong") == ("Hong Kong", WorkplaceType.REMOTE)
    assert role_place("Hybrid - Toronto") == ("Toronto", WorkplaceType.HYBRID)
    assert role_place("On-site - Ottawa") == ("Ottawa", WorkplaceType.ONSITE)
    # A place named with a hyphen is not a workplace prefix.
    assert role_place("Saint-Laurent") == ("Saint-Laurent", WorkplaceType.UNKNOWN)
    assert role_place("Remote") == ("Remote", WorkplaceType.UNKNOWN)


@pytest.mark.asyncio
async def test_a_role_in_two_workplaces_states_none():
    def mixed(roles):
        role = next(r for r in roles if r["id"] == ROLE)
        role["locations"] = ["Remote - Ireland", "Hybrid - London"]

    jobs = {j.req_id: j for j in await _jobs(_adapter(page=_roles(mixed)))}
    assert jobs[ROLE].workplace_type is WorkplaceType.UNKNOWN
    assert jobs[ROLE].locations == ["Ireland", "London"]


@pytest.mark.asyncio
async def test_hydrate_fills_what_a_role_summary_does_not_state():
    def ef12(roles):
        roles[0].update(id="ef12f6c3-0000-4000-8000-000000000000", title="Affiliate Marketing Lead, Shop",
                        locations=["Americas"])

    adapter = _adapter(page=_roles(ef12))
    job = next(j for j in await _jobs(adapter) if j.req_id.startswith("ef12f6c3"))
    assert job.posted_at is None and job.workplace_type is WorkplaceType.UNKNOWN
    assert job.source_facts.employment_type_normalized is EmploymentType.UNKNOWN
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, text=POSTING)))
    try:
        await adapter.hydrate(job)
    finally:
        await adapter._client.aclose()
    record = loader_data(POSTING, "($locale)/careers/$posting")["jobPosting"]
    assert job.description_complete
    assert job.posted_at is not None and job.posted_at.date().isoformat() == record["publishedDate"]
    assert job.source_facts.first_published_at == job.posted_at
    assert job.source_facts.employment_type_normalized is EmploymentType.FULL_TIME
    assert job.workplace_type is not WorkplaceType.UNKNOWN


@pytest.mark.asyncio
async def test_hydrate_keeps_what_the_listing_already_stated():
    adapter = _adapter()
    job = next(j for j in await _jobs(adapter) if j.req_id.startswith("ef12f6c3"))
    stated = (job.posted_at, job.workplace_type, job.source_facts)
    other = POSTING.replace('"publishedDate"', '"publishedDateX"')
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, text=other)))
    try:
        await adapter.hydrate(job)
    finally:
        await adapter._client.aclose()
    assert (job.posted_at, job.workplace_type, job.source_facts) == stated


@pytest.mark.asyncio
async def test_a_role_list_of_unreadable_rows_is_a_failed_read():
    adapter = _adapter(page=_roles(lambda roles: [r.update(id=None) for r in roles]))
    assert await _jobs(adapter) == []
    assert not adapter.drift.listing_complete and not adapter.drift.empty_proven
