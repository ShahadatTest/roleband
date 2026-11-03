"""The scope screens' counts from the posting inventory.

- J1 the entries built from inventory rows equal the entries the scan's own
  tally builds for the same listing, cell for cell (one tally function);
- J3 gone rows, unfollowed, hidden and adapter-less companies and rows a
  learned exclusion matches never count;
- J5 a company with rows and no complete read is `partial`, counts only
  its recent rows, and a capped reconcile or a discovery probe is never a
  complete read; a company never read is `missing`; one read before but not
  within the freshness window is `stale`, with when it was last read;
  the Profile and the Companies screen read one rule;
- J9 under the inventory source the catalog's joint, marginals and place
  counts come from those rows, with no `jobs` fallback;
- J7 the answer stays inside its byte budget at a projected size, and its CPU
  time grows in step with the listing, not faster.
"""

from __future__ import annotations

import gc
import itertools
import json
import statistics
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, update

from tracker.config import get_settings
from tracker.db.inventory_store import write_inventory
from tracker.db.models import (
    CompanyScopeRule,
    PostingInventory,
    ScrapeRun,
    ScrapeSourceRun,
    SourceBinding,
    TrackedCompany,
)
from tracker.enrich.enricher import annotate
from tracker.enrich.inventory import inventory_row
from tracker.schema import RawJob
from tracker.scope.catalog import build_scope_catalog
from tracker.scope.catalog_store import catalog_rows
from tracker.scope.inventory_joint import inventory_counts
from tracker.taxonomy.role_catalog import CatalogTallies, add_to_catalog

NOW = datetime.now(UTC)
COMPANY = "anthropic"

TITLES = (
    "Staff Software Engineer", "Senior Engineering Manager", "Principal Product Manager",
    "Senior Data Scientist", "Staff Security Engineer, Detection", "Account Executive",
    "Director of Finance", "Barista", "Senior Technical Program Manager",
    "Staff Machine Learning Engineer, Ads",
)
PLACES = (["London, UK"], ["New York, NY"], ["Berlin, Germany"], ["Remote, US"], ["Multiple Locations"])
TEAMS = (None, "Ads", "Payments")


def _population(company: str = COMPANY) -> list[RawJob]:
    return [
        RawJob(company=company, req_id=f"r{i}", title=title, url=f"https://jobs.example.test/{i}",
               locations=list(places), team=team)
        for i, (title, places, team) in enumerate(itertools.product(TITLES, PLACES, TEAMS))
    ]


def _raw(req: str, title: str = "Staff Software Engineer", places=("London, UK",), company=COMPANY, team=None) -> RawJob:
    return RawJob(company=company, req_id=req, title=title, url=f"https://jobs.example.test/{req}",
                  locations=list(places), team=team)


def _company(slug: str = COMPANY, **overrides) -> TrackedCompany:
    fields = dict(slug=slug, display=slug.title(), adapter="greenhouse", status="active", enabled=True,
                  visible=True, source="catalog")
    return TrackedCompany(**{**fields, **overrides})


async def _store(db_session, raws: list[RawJob], *, company: str = COMPANY, seen_at: datetime = NOW) -> None:
    run = ScrapeRun(status="running")
    db_session.add(run)
    await db_session.flush()
    rows = {raw.dedupe_key(): inventory_row(raw, annotate(raw)) for raw in raws}
    await write_inventory(
        db_session, run_id=run.id, company=company, binding_id=None, rows=rows,
        seen_keys=set(rows), authoritative=False, now=seen_at, touch_hours=12,
    )
    await db_session.commit()


async def _read(db_session, company: str = COMPANY, *, scan_mode="reconcile", capped=False,
                complete=True, errors=(), inventory_written=True, at: datetime = NOW) -> None:
    """One source run as `run_persistence._finish_source` records it."""
    binding = SourceBinding(company_slug=company, connector_kind="greenhouse", connector_id=company)
    run = ScrapeRun(status="ok")
    db_session.add_all([binding, run])
    await db_session.flush()
    stats = {"capped": capped, "errors": list(errors)}
    if inventory_written:
        stats["inventory_rows"] = 1
    db_session.add(ScrapeSourceRun(
        run_id=run.id, binding_id=binding.id, company_slug=company, provider_key=company,
        scan_mode=scan_mode, outcome="ok", started_at=at, finished_at=at,
        list_complete=complete, errors=list(errors), stats=stats,
    ))
    await db_session.commit()


def _comparable(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: row["role_group"])


@pytest.mark.asyncio
async def test_inventory_entries_are_the_scans_own_tally_cell_for_cell(db_session):
    """J1: the same listing, tallied by the scan and rebuilt from the inventory."""
    population = _population()
    db_session.add(_company())
    await db_session.commit()
    await _store(db_session, population)
    await _read(db_session)

    scanned: CatalogTallies = {}
    for raw in population:
        add_to_catalog(scanned, raw, annotate(raw))
    counts = await inventory_counts(db_session, [_company()], [])
    rebuilt = [
        {key: value for key, value in vars(entry).items() if key != "company"}
        for entry in counts.entries
    ]
    assert _comparable(rebuilt) == _comparable(catalog_rows(scanned))
    assert sum(row["count"] for row in rebuilt) > 0
    assert counts.counted == {COMPANY} and counts.partial == set() and counts.missing == set()


@pytest.mark.asyncio
async def test_what_the_board_can_never_show_is_never_counted(db_session):
    """J3."""
    db_session.add_all([
        _company(), _company("paused", enabled=False), _company("hushed", visible=False),
        _company("adapterless", status="pending"),
    ])
    db_session.add(CompanyScopeRule(company=COMPANY, kind="team", value="Ads"))
    await db_session.commit()
    await _store(db_session, [_raw("keep"), _raw("gone"), _raw("ads", team="Ads")])
    await db_session.execute(update(PostingInventory).where(PostingInventory.req_id == "gone").values(gone_at=NOW))
    for slug in ("paused", "hushed", "adapterless"):
        await _store(db_session, [_raw(f"{slug}-1", company=slug)], company=slug)
        await _read(db_session, slug)
    await _read(db_session)
    await db_session.commit()

    tracked = [_company(), _company("paused", enabled=False), _company("hushed", visible=False),
               _company("adapterless", status="pending")]
    counts = await inventory_counts(db_session, tracked, ["hushed"])
    assert {entry.company for entry in counts.entries} == {COMPANY}
    assert sum(entry.count for entry in counts.entries) == 1, "only 'keep': not the gone row, not the Ads team"


@pytest.mark.asyncio
async def test_a_row_from_an_older_taxonomy_is_skipped_not_fatal(db_session):
    """A band or track the code does not know (until the reclassify pass
    rewrites the row) must not take the whole count down."""
    db_session.add(_company())
    await db_session.commit()
    await _store(db_session, [_raw("keep"), _raw("old-band"), _raw("old-track")])
    await db_session.execute(update(PostingInventory).where(PostingInventory.req_id == "old-band").values(level_band="retired_band"))
    await db_session.execute(update(PostingInventory).where(PostingInventory.req_id == "old-track").values(track="retired_track"))
    await _read(db_session)

    counts = await inventory_counts(db_session, [_company()], [])
    assert sum(entry.count for entry in counts.entries) == 1


@pytest.mark.asyncio
async def test_a_company_without_a_complete_read_is_partial_and_counts_only_recent_rows(db_session):
    """J5. Capped reads only add rows, so without a complete read an old
    row may be long closed: it waits for the company's first complete read."""
    tracked = [_company(), _company("stripe"), _company("openai")]
    db_session.add_all(tracked)
    await db_session.commit()
    await _store(db_session, [_raw("recent")])
    await _store(db_session, [_raw("old")], seen_at=NOW - timedelta(days=30))
    # Neither a probe, a capped reconcile, an errored one, one with an
    # incomplete listing nor one whose inventory write failed is a complete read.
    await _read(db_session, scan_mode="discovery")
    await _read(db_session, capped=True)
    await _read(db_session, errors=["HTTP 500"])
    await _read(db_session, complete=False)
    await _read(db_session, inventory_written=False)
    await _store(db_session, [_raw("s1", company="stripe")], company="stripe", seen_at=NOW - timedelta(days=30))

    counts = await inventory_counts(db_session, tracked, [])
    # Stripe was read, a month ago, and not since: named with that read.
    assert counts.not_counted() == {"openai": "missing", COMPANY: "partial", "stripe": "stale"}
    assert set(counts.last_read) == {"stripe"}
    assert sum(entry.count for entry in counts.entries) == 1, "only the recent row"

    # A complete read: it reads every listed row again, so "old" is current.
    await _store(db_session, [_raw("recent"), _raw("old")])
    await _read(db_session)
    counts = await inventory_counts(db_session, tracked, [])
    assert counts.not_counted() == {"openai": "missing", "stripe": "stale"}
    assert sum(entry.count for entry in counts.entries) == 2, "a complete read vouches for every row it read"


@pytest.mark.asyncio
async def test_a_row_no_scan_read_within_the_freshness_window_never_counts(db_session):
    """The rows that count are exactly the rows a save promotes. Promotion
    admits only rows read within `inventory_promotion_fresh_hours`, so counting
    every live row after a complete read would let the Walk promise roles a
    save would not add."""

    from tracker.scope.promotion import candidates_stmt
    from tracker.settings_store import set_enabled_bands, set_enabled_locations, set_enabled_roles

    tracked = [_company()]
    db_session.add_all(tracked)
    await db_session.commit()
    fresh_hours = get_settings().inventory_promotion_fresh_hours
    await _store(db_session, [_raw("read-now")])
    await _store(db_session, [_raw("read-before")], seen_at=NOW - timedelta(hours=fresh_hours + 2))
    await _read(db_session)
    await set_enabled_roles(db_session, ["software_engineering"])
    await set_enabled_bands(db_session, ["staff"])
    await set_enabled_locations(db_session, ["uk"])
    await db_session.commit()

    counts = await inventory_counts(db_session, tracked, [])
    promoted = (await db_session.scalars(await candidates_stmt(db_session))).all()

    assert sum(entry.count for entry in counts.entries) == 1
    assert [row.req_id for row in promoted] == ["read-now"]


@pytest.mark.asyncio
async def test_a_company_whose_reads_stopped_is_named_with_its_last_read(db_session):
    """Counting only fresh rows, a company whose scans stop for longer than the
    freshness window counts nothing. It must not stay "counted", or the count
    shrinks and nothing says why."""
    fresh_hours = get_settings().inventory_promotion_fresh_hours
    stopped = NOW - timedelta(hours=fresh_hours + 24)
    tracked = [_company(), _company("stripe"), _company("openai"), _company("figma"), _company("notion")]
    db_session.add_all(tracked)
    await db_session.commit()
    # Read in full, then the scans stopped.
    await _store(db_session, [_raw("swe")], seen_at=stopped)
    await _read(db_session, at=stopped)
    # Controls: read in full now; an empty board read in full now; one whose
    # last full read is old but whose rows a later read listed now (partial
    # reads keep it current); one never read.
    await _store(db_session, [_raw("s1", company="stripe")], company="stripe")
    await _read(db_session, "stripe")
    await _read(db_session, "figma")
    await _read(db_session, "notion", at=stopped)
    await _store(db_session, [_raw("n1", company="notion")], company="notion")

    counts = await inventory_counts(db_session, tracked, [])

    assert counts.not_counted() == {COMPANY: "stale", "openai": "missing"}
    assert counts.last_read == {COMPANY: stopped}
    assert counts.counted == {"stripe", "figma", "notion"}
    assert {entry.company for entry in counts.entries} == {"stripe", "notion"}


@pytest.mark.asyncio
async def test_the_catalog_counts_from_the_inventory_when_switched(db_session, monkeypatch):
    """J9: the joint, the marginals and the place counts are one set of rows;
    no `jobs` fallback, and a partial company is named on the wire."""
    db_session.add_all([_company(), _company("stripe")])
    await db_session.commit()
    await _store(db_session, [
        _raw("swe"), _raw("em", title="Senior Engineering Manager"),
        _raw("unplaced", places=("Multiple Locations",)),
        _raw("unsorted", title="Clinical Specialist, Mental Health"),
    ])
    await _read(db_session)
    await _store(db_session, [_raw("s1", company="stripe", places=("New York, NY",))], company="stripe")

    monkeypatch.setattr(get_settings(), "scope_counts_source", "inventory")
    catalog = await build_scope_catalog(db_session, [])
    cells = catalog["scope_cells"]
    assert cells["ready"] is True and catalog["joint_counts_ready"] is True
    assert sum(cell[-1] for cell in cells["cells"]) == 3
    assert cells["companies"] == [COMPANY, "stripe"]
    assert (cells["partial_companies"], cells["missing_companies"], cells["stale_companies"]) == (["stripe"], [], [])
    assert cells["unplaced"] == 1
    places = {location["slug"]: location["count"] for location in catalog["locations"]}
    assert (places["uk"], places["united_states"]) == (2, 1)
    # "Senior Engineering Manager" names a manager rank we cannot place at a
    # company with no ladder: its cell is counted apart from the
    # rungs, under the level key the Walk's switch reads.
    assert sum(level["count"] for level in catalog["levels"]) == 2
    unplaced_level = cells["bands"].index("unstated")
    assert sum(cell[-1] for cell in cells["cells"] if cell[1] == unplaced_level) == 1

    monkeypatch.setattr(get_settings(), "scope_counts_source", "catalog")
    assert (await build_scope_catalog(db_session, []))["scope_cells"]["cells"] == [], (
        "the catalog source reads role_catalog, which nothing wrote here"
    )


@pytest.mark.asyncio
async def test_the_companies_screen_names_a_partial_company_under_the_same_rule(api_client, db_session, monkeypatch):
    db_session.add_all([_company(), _company("stripe")])
    await db_session.commit()
    await _store(db_session, [_raw("swe"), _raw("unsorted", title="Clinical Specialist, Mental Health")])
    await _read(db_session)
    await _store(db_session, [_raw("s1", company="stripe")], company="stripe")
    monkeypatch.setattr(get_settings(), "scope_counts_source", "inventory")

    body = (await api_client.get("/api/companies/open-counts")).json()
    assert body["not_counted"] == {"stripe": "partial"}
    assert body["unsorted"] == {COMPANY: 1}
    assert body["last_read"] == {}
    catalog = (await api_client.get("/api/scope/catalog")).json()
    assert catalog["scope_cells"]["partial_companies"] == ["stripe"]


@pytest.mark.asyncio
async def test_the_companies_screen_says_when_a_stopped_company_was_last_read(api_client, db_session, monkeypatch):
    """Stale on the wire: the reason and the time, from the one rule the Profile
    reads too; the catalog source names no read time."""
    fresh_hours = get_settings().inventory_promotion_fresh_hours
    stopped = NOW - timedelta(hours=fresh_hours + 24)
    db_session.add(_company())
    await db_session.commit()
    await _store(db_session, [_raw("swe")], seen_at=stopped)
    await _read(db_session, at=stopped)
    monkeypatch.setattr(get_settings(), "scope_counts_source", "inventory")

    body = (await api_client.get("/api/companies/open-counts")).json()
    assert body["not_counted"] == {COMPANY: "stale"}
    assert datetime.fromisoformat(body["last_read"][COMPANY]) == stopped
    catalog = (await api_client.get("/api/scope/catalog")).json()
    assert (catalog["scope_cells"]["stale_companies"], catalog["scope_cells"]["companies"]) == ([COMPANY], [])

    monkeypatch.setattr(get_settings(), "scope_counts_source", "catalog")
    assert (await api_client.get("/api/companies/open-counts")).json()["last_read"] == {}


async def _seed_live_rows(db_session, companies: list[str], per_company: int) -> None:
    db_session.add_all([_company(slug) for slug in companies])
    await db_session.commit()
    samples = [inventory_row(raw, annotate(raw)) for raw in _population("x")]
    rows = []
    for n in range(len(companies) * per_company):
        company = companies[n % len(companies)]
        sample = samples[n % len(samples)]
        rows.append({
            "dedupe_key": f"{company}:{n}", "company": company, "req_id": str(n), "title": sample.title,
            "url": "https://jobs.example.test", "department": None, "team": sample.team, "raw_level": None,
            "locations": list(sample.locations), "workplace_type": "unknown", "posted_at": None,
            "level_band": sample.level_band, "level_confidence": sample.level_confidence,
            "family": sample.family, "track": sample.track, "location_groups": list(sample.location_groups),
            "domains": list(sample.domains), "content_hash": "x", "first_seen_at": NOW, "last_seen_at": NOW,
            "last_seen_run_id": None, "gone_at": None,
        })
    for start in range(0, len(rows), 1000):
        await db_session.execute(insert(PostingInventory), rows[start:start + 1000])
    await db_session.commit()


async def _cpu_to_build(db_session) -> tuple[float, dict]:
    """The median of three warm builds, in this process's CPU seconds. The
    first read after fresh inserts pays for a cold table; the screen reads a
    warm one. Each build starts from a collected heap, so a garbage
    collection the inserts left due is not billed to it."""
    await build_scope_catalog(db_session, [])
    spent = []
    for _ in range(3):
        gc.collect()
        started = time.process_time()
        catalog = await build_scope_catalog(db_session, [])
        spent.append(time.process_time() - started)
    return statistics.median(spent), catalog


@pytest.mark.asyncio
async def test_the_answer_stays_inside_its_budget_at_a_projected_size(db_session, monkeypatch):
    """J7: 50,000 live rows across 100 companies (the projected full coverage),
    against a quarter of that with the same rows per company."""
    monkeypatch.setattr(get_settings(), "scope_counts_source", "inventory")
    companies = [f"co{i:03d}" for i in range(100)]
    await _seed_live_rows(db_session, companies[:25], per_company=500)
    small, _ = await _cpu_to_build(db_session)
    await _seed_live_rows(db_session, companies[25:], per_company=500)
    full, catalog = await _cpu_to_build(db_session)

    size = len(json.dumps(catalog["scope_cells"], default=str))
    assert size < 250 * 1024, f"joint is {size} B"
    assert sum(cell[-1] for cell in catalog["scope_cells"]["cells"]) > 0
    # Four times the rows and companies costs about four times the CPU. A pass
    # that re-scans every row per company, or any other quadratic pass, costs
    # about sixteen. The ratio is the budget because CPU time per row
    # differs several times between a laptop and a shared CI runner, while
    # both sizes run on the same machine.
    assert full < 8 * small, f"4x the listing took {full / small:.1f}x the CPU ({small:.2f} s, {full:.2f} s)"
    # A constant slowdown, such as a query per row, keeps the ratio; this
    # ceiling, far above any machine's normal cost, still stops it.
    assert full < 20.0, f"built in {full:.2f} s of CPU"
