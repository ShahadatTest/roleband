"""What a catalog scan could see, and what a save put on the Board.

Three numbers on the walk must not be silently short:

- A source that lists only the places it is asked for (Amazon, Apple,
  Microsoft...) is scanned under the places saved at the time, so adding
  Europe would price Europe at ~0 with no mark. The catalog records the places
  each such scan asked, so the screen can say "counted after the next scan".
- Postings with no role family or no recognised place are left out of the
  catalog, and counted per company so they leave a trace.
- The save confirmation's "N roles changed" (`in_scope_changed`) includes
  closed rows and every company. A save also answers what the Board holds.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, update

from tracker.connectors.listing.base import BaseAdapter
from tracker.db.models import Job, RoleCatalog, TrackedCompany
from tracker.enrich.enricher import Annotation
from tracker.schema import LevelBand, LevelConfidence, RawJob, RoleTrack
from tracker.scope.catalog import build_scope_catalog
from tracker.scope.catalog_store import persist_company_catalog, scanned_places
from tracker.taxonomy.role_catalog import add_to_catalog, catalog_drop_reason

#: `PUT /api/settings` starts the directory scan when the set is followed.
pytestmark = pytest.mark.usefixtures("no_escape")


def _ann(family: str | None = "software_engineering", places: list[str] | None = None) -> Annotation:
    return Annotation(
        band=LevelBand.STAFF, confidence=LevelConfidence.CONFIRMED, family=family,
        location_groups=["uk"] if places is None else places, track=RoleTrack.TECHNICAL, domains=[],
    )


def _raw(req: str) -> RawJob:
    return RawJob(company="acme", req_id=req, title="Staff Engineer", url=f"https://x.test/{req}")


def test_a_posting_the_catalog_cannot_count_is_reported_not_silently_dropped():
    tallies: dict = {}
    assert add_to_catalog(tallies, _raw("1"), _ann()) is True
    assert add_to_catalog(tallies, _raw("2"), _ann(family=None)) is False
    assert add_to_catalog(tallies, _raw("3"), _ann(places=[])) is False
    assert tallies["software_engineering"].count == 1


def test_a_dropped_posting_says_why_and_the_two_reasons_never_overlap():
    """A role with a place and no role family is unsorted, not unplaced. One
    count for both reasons makes the Companies screen say "a place we can't
    read" about roles it has placed."""
    assert catalog_drop_reason(_ann()) is None
    assert catalog_drop_reason(_ann(family=None)) == "unsorted"
    assert catalog_drop_reason(_ann(places=[])) == "unplaced"
    # Neither: the place is the first thing no answer can match.
    assert catalog_drop_reason(_ann(family=None, places=[])) == "unplaced"


class _Manifest:
    """A source that lists only the places it is asked for."""

    location_queries = {"uk": ["London"], "united_states": ["US"], "germany": ["DE"], "japan": ["JP"]}

    def __init__(self, enabled: set[str]):
        self._enabled_locations = frozenset(enabled)

    def planned_location_items(self):
        return BaseAdapter.planned_location_items(self)  # type: ignore[arg-type]


class _WholeBoard:
    location_queries = None


def test_the_places_a_scan_asked_are_what_its_manifest_ran_for_the_saved_places():
    # London is inside the UK and the UK query covers it; Germany was never asked.
    assert scanned_places(_Manifest({"london", "united_states"})) == ["uk", "united_states"]
    # A source that lists the whole board asked about no place in particular.
    assert scanned_places(_WholeBoard()) is None
    assert scanned_places(None) is None


class _Tracked:
    role_catalog_status = "pending"
    role_catalog_scanned_at = None
    role_catalog_error = None
    role_catalog_places = None
    role_catalog_unplaced = None
    role_catalog_unsorted = None


class _Session:
    def __init__(self):
        self.tracked = _Tracked()

    async def get(self, model, key):
        return self.tracked

    async def execute(self, stmt):
        return None

    def add(self, row):
        pass


def test_a_complete_scan_records_what_it_asked_and_what_it_could_not_count():
    session = _Session()
    asyncio.run(persist_company_catalog(
        session, "acme", {}, complete=True, places=["uk", "united_states"], unplaced=7, unsorted=3,
    ))
    assert session.tracked.role_catalog_places == ["uk", "united_states"]
    assert session.tracked.role_catalog_unplaced == 7
    assert session.tracked.role_catalog_unsorted == 3


T0 = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def _company(slug: str, *, enabled: bool = True, visible: bool = True, places=None, unplaced=None):
    return TrackedCompany(
        slug=slug, display=slug.title(), adapter="greenhouse", status="active", enabled=enabled,
        visible=visible, source="catalog", role_catalog_status="ready", role_catalog_scanned_at=T0,
        role_catalog_places=places, role_catalog_unplaced=unplaced,
    )


def _catalog(company: str) -> RoleCatalog:
    return RoleCatalog(
        role_group="software_engineering", company=company, count=1, band_counts={"staff": 1},
        band_track_counts={"staff": {"technical": 1}},
        scope_cells=[{"band": "staff", "track": "technical", "locations": ["uk"], "domains": [], "count": 1}],
        examples=[], domain_counts={}, domain_examples={}, updated_at=T0,
    )


@pytest.mark.asyncio
async def test_the_catalog_names_partly_scanned_followed_companies_and_their_uncounted_postings(db_session):
    db_session.add_all([
        _company("amazon", places=["united_states"], unplaced=7),
        _company("stripe", unplaced=2),  # the whole board: no places to name
        _company("apple", enabled=False, places=["uk"], unplaced=5),  # not followed
    ])
    db_session.add_all([_catalog("amazon"), _catalog("stripe"), _catalog("apple")])
    await db_session.commit()

    cells = (await build_scope_catalog(db_session, []))["scope_cells"]
    assert cells["scanned_places"] == {"amazon": ["united_states"]}
    assert cells["unplaced"] == 9


def _job(key: str, company: str, *, status: str = "open") -> Job:
    return Job(
        company=company, req_id=key, dedupe_key=f"{company}:{key}", title=key,
        url=f"https://careers.example.test/{company}/{key}", locations=["London, UK"],
        location_groups=["uk", "europe"], domains=[], workplace_type="onsite", level_band="staff",
        level_confidence="confirmed", family="software_engineering", track="technical",
        comp_currency="USD", status=status, in_scope=False, first_seen=T0, last_seen=T0,
        description_sections=[],
    )


@pytest.mark.asyncio
async def test_a_save_answers_what_the_board_holds_not_only_what_changed(api_client, db_session):
    db_session.add_all([_company("acme"), _company("hidden", visible=False)])
    db_session.add_all([
        _job("a", "acme"), _job("b", "acme"), _job("gone", "acme", status="closed"), _job("h", "hidden"),
    ])
    await db_session.commit()
    saved = await api_client.put("/api/settings", json={
        "enabled_role_groups": [], "enabled_seniority_bands": ["staff"],
        "enabled_location_groups": ["uk"], "role_answers": [{"track": "technical", "roles": "any"}],
    })
    assert saved.status_code == 200, saved.text
    body = saved.json()
    # Four rows entered scope, one closed and one at a hidden company: the
    # Board shows two.
    assert body["in_scope_changed"] == 4
    assert body["on_board"] == 2


@pytest.mark.asyncio
async def test_companies_says_which_followed_companies_the_count_leaves_out_and_their_unplaced_roles(
    api_client, db_session,
):
    """The Profile rail's statuses, shown on the company they are about:
    the same rule as the Profile's count, one company at a time."""
    stale = _catalog("oldco")
    stale.scope_cells = []  # written before the joint: its postings cannot be placed
    pending = _company("newco", unplaced=4)
    pending.role_catalog_status = "pending"
    db_session.add_all([
        _company("amazon", unplaced=7),
        _company("stripe"),
        _company("oldco", unplaced=3),
        pending,  # followed, its catalog not built yet
        _company("apple", enabled=False, unplaced=5),  # not followed: none of its business
    ])
    db_session.add_all([_catalog("amazon"), _catalog("stripe"), stale, _catalog("apple"), _catalog("newco")])
    await db_session.commit()

    body = (await api_client.get("/api/companies/open-counts")).json()
    assert body["not_counted"] == {"newco": "missing", "oldco": "stale"}
    # A pending catalog's unplaced count belongs to no count yet.
    assert body["unplaced"] == {"amazon": 7, "oldco": 3}

    cells = (await build_scope_catalog(db_session, []))["scope_cells"]
    assert cells["missing_companies"] == ["newco"] and cells["stale_companies"] == ["oldco"]


#: The catalog columns only a full catalog read needs: the cells a walk places
#: postings in, the titles a hover shows, the per-track and per-domain tallies.
_CATALOG_DETAIL = re.compile(
    r"(?:\w+_)?(scope_cells|examples|band_track_counts|domain_counts|domain_examples)(?:_\d+)?"
)


async def _read(api_client, engine, path: str) -> tuple[dict, set[str]]:
    """The answer, and which catalog detail columns its read returned."""
    seen: set[str] = set()

    def record(_conn, cursor, _statement, _parameters, _context, _executemany):
        for column in cursor.description or ():
            if match := _CATALOG_DETAIL.fullmatch(column[0]):
                seen.add(match.group(1))

    event.listen(engine.sync_engine, "after_cursor_execute", record)
    try:
        response = await api_client.get(path)
    finally:
        event.remove(engine.sync_engine, "after_cursor_execute", record)
    assert response.status_code == 200, response.text
    return response.json(), seen


async def _detail_columns_returned(api_client, engine, path: str) -> set[str]:
    return (await _read(api_client, engine, path))[1]


@pytest.mark.asyncio
async def test_the_companies_counts_read_no_catalog_detail(api_client, db_session):
    """The Companies screen asks only which followed companies are catalogued
    and which catalogs predate the joint, so it reads whether a row has cells,
    never the cells. The scope catalog is the control: it reads them."""
    stale = _catalog("oldco")
    stale.scope_cells = []
    db_session.add_all([_company("amazon"), _company("oldco")])
    db_session.add_all([_catalog("amazon"), stale])
    await db_session.commit()

    assert await _detail_columns_returned(api_client, db_session.bind, "/api/companies/open-counts") == set()
    assert "scope_cells" in await _detail_columns_returned(api_client, db_session.bind, "/api/scope/catalog")


def _software(body: dict) -> dict:
    return next(
        group for category in body["categories"] for group in category["groups"]
        if group["slug"] == "software_engineering"
    )


@pytest.mark.asyncio
async def test_a_catalog_read_with_nothing_changed_reads_no_row(api_client, db_session):
    """The counts from the rows are most of a catalog read. Between two
    catalog writes they are reused, and the answer is the same."""
    db_session.add_all([_company("amazon"), _company("stripe"), _catalog("amazon"), _catalog("stripe")])
    await db_session.commit()

    first, first_read = await _read(api_client, db_session.bind, "/api/scope/catalog")
    second, second_read = await _read(api_client, db_session.bind, "/api/scope/catalog")

    assert "scope_cells" in first_read
    assert second_read == set()
    assert second == first
    assert _software(second)["total"] == 2


@pytest.mark.asyncio
async def test_a_scan_that_replaces_a_catalog_shows_on_the_next_read(api_client, db_session):
    db_session.add_all([_company("acme"), _catalog("acme")])
    await db_session.commit()
    before, _ = await _read(api_client, db_session.bind, "/api/scope/catalog")

    tallies: dict = {}
    for req in ("1", "2", "3"):
        add_to_catalog(tallies, _raw(req), _ann())
    assert await persist_company_catalog(db_session, "acme", tallies, complete=True) == "ready"
    await db_session.commit()
    after, after_read = await _read(api_client, db_session.bind, "/api/scope/catalog")

    assert (_software(before)["total"], _software(after)["total"]) == (1, 3)
    assert "scope_cells" in after_read


@pytest.mark.asyncio
async def test_a_catalog_row_changed_in_place_shows_on_the_next_read(api_client, db_session):
    """Same rows, same ids: only the row's version says it changed."""
    db_session.add_all([_company("acme"), _catalog("acme")])
    await db_session.commit()
    await _read(api_client, db_session.bind, "/api/scope/catalog")

    await db_session.execute(
        update(RoleCatalog).where(RoleCatalog.company == "acme")
        .values(count=5, band_counts={"staff": 5}, band_track_counts={"staff": {"technical": 5}})
    )
    await db_session.commit()
    after, _ = await _read(api_client, db_session.bind, "/api/scope/catalog")

    assert _software(after)["band_counts"] == {"staff": 5}


@pytest.mark.asyncio
async def test_a_company_switched_off_leaves_the_next_read(api_client, db_session):
    """The rows are unchanged; the company they are counted for is not."""
    db_session.add_all([_company("acme"), _company("stripe"), _catalog("acme"), _catalog("stripe")])
    await db_session.commit()
    before, _ = await _read(api_client, db_session.bind, "/api/scope/catalog")

    await db_session.execute(update(TrackedCompany).where(TrackedCompany.slug == "stripe").values(enabled=False))
    await db_session.commit()
    after, _ = await _read(api_client, db_session.bind, "/api/scope/catalog")

    assert (_software(before)["total"], _software(after)["total"]) == (2, 1)
    assert after["scope_cells"]["companies"] == ["acme"]


#: The most one followed company may add to the catalog answer: its record in
#: the company list and its name among the counted ones. Counts sent again per
#: company and family were most of a 6 MB answer.
_PER_COMPANY_BYTES = 250


@pytest.mark.asyncio
async def test_the_catalog_answer_grows_by_one_record_per_company_not_one_per_family(api_client, db_session):
    families = ("software_engineering", "product_management", "data_science")

    async def follow(slugs: list[str]) -> int:
        for slug in slugs:
            db_session.add(_company(slug))
            for family in families:
                row = _catalog(slug)
                row.role_group = family
                db_session.add(row)
        await db_session.commit()
        response = await api_client.get("/api/scope/catalog")
        assert response.status_code == 200, response.text
        return len(response.content)

    few = await follow([f"co{n:02d}" for n in range(5)])
    many = await follow([f"co{n:02d}" for n in range(5, 25)])

    assert (many - few) / 20 <= _PER_COMPANY_BYTES
