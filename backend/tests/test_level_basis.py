"""A posting that states no level is never read as Mid.

`read_level` says what decided a band; basis `none` keeps `mid` for sorting
only. Every gate then asks the user's switch instead of that `mid`: the Python
gate the pipeline runs, the SQL gate over `jobs` and over `posting_inventory`,
and the browser's cell gate. All of them read one fixture,
`fixtures/level_basis_gate.json`, which `dashboard/src/features/scope/
scopeCells.test.ts` reads too, so the server and the browser cannot disagree
about the same posting.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from tracker.db.inventory_store import write_inventory
from tracker.db.models import Job, PostingInventory, ScrapeRun
from tracker.db.queries.scope import job_scope_expr
from tracker.db.repo import apply_saved_scope_to_jobs
from tracker.enrich.enricher import Annotation, ScopeFilter, passes_filters
from tracker.enrich.inventory import InventoryRow
from tracker.enrich.level_mapper import read_level
from tracker.levels import INCLUDE_UNSTATED_LEVEL_DEFAULT
from tracker.schema import LevelBand, LevelBasis, LevelConfidence, RawJob, RoleTrack
from tracker.taxonomy.domains import all_slugs as all_domains
from tracker.taxonomy.role_answers import parse_answers
from tracker.taxonomy.role_catalog import add_to_catalog, count_level
from tracker.taxonomy.tracks import allowed_bands_for

#: `PUT /api/settings` starts the directory scan when the set is followed.
pytestmark = pytest.mark.usefixtures("no_escape")

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "level_basis_gate.json").read_text())
POSTINGS = {p["id"]: p for p in FIXTURE["postings"]}
SCOPES = FIXTURE["scopes"]
TRACKS = ["technical", "management"]
FAMILIES = ["software_engineering", "engineering_management"]
T0 = datetime(2026, 10, 2, tzinfo=UTC)


def _raw(company: str, title: str, raw_level: str | None = None) -> RawJob:
    return RawJob(company=company, req_id="x", title=title, url="u", locations=["Seattle, WA"],
                  raw_level=raw_level)


# --- what decided the band -------------------------------------------------- #


@pytest.mark.parametrize(
    "company,title,raw_level,band,basis",
    [
        ("microsoft", "Software Engineer", "IC4", LevelBand.SENIOR, LevelBasis.STATED),
        ("amazon", "Sr. Technical Program Manager", None, LevelBand.SENIOR, LevelBasis.COMPANY),
        ("openai", "Senior Software Engineer", None, LevelBand.SENIOR, LevelBasis.GENERIC),
        ("google", "Research Intern, PhD", None, LevelBand.INTERN, LevelBasis.GENERIC),
        # A bare title states no level.
        ("google", "Research Scientist, DeepMind", None, LevelBand.MID, LevelBasis.NONE),
        ("apple", "Software Engineer", None, LevelBand.MID, LevelBasis.NONE),
    ],
)
def test_the_reading_says_what_decided_the_band(company, title, raw_level, band, basis):
    reading = read_level(_raw(company, title, raw_level))
    assert (reading.band, reading.basis) == (band, basis)


def test_an_ambiguous_title_is_a_level_we_cannot_place_not_one_never_stated():
    # "Product Manager" names a role, not a rung: the generic senior is our
    # guess. It is unmapped, which the gate treats like a posting
    # that states nothing, but it is not that claim: the card says "level not
    # mapped", never "level not stated". The band stays for sorting.
    reading = read_level(_raw("google", "Product Manager"))
    assert reading.confidence is LevelConfidence.UNCONFIRMED
    assert (reading.band, reading.basis) == (LevelBand.SENIOR, LevelBasis.UNMAPPED)


# --- one fixture, every gate ------------------------------------------------ #


def test_the_fixture_ranges_are_the_taxonomy_ranges():
    for track, bands in FIXTURE["track_bands"].items():
        assert bands == allowed_bands_for(track), track


def _annotation(posting: dict) -> Annotation:
    basis = LevelBasis(posting["basis"]) if posting["basis"] else None
    return Annotation(
        band=LevelBand(posting["band"]), confidence=LevelConfidence.CONFIRMED,
        family=posting["family"], location_groups=["uk"], track=RoleTrack(posting["track"]),
        domains=[], basis=basis if basis is not None else LevelBasis.GENERIC,
    )


def _filter(scope: dict) -> ScopeFilter:
    return ScopeFilter(
        enabled_bands=frozenset(scope["bands"]), enabled_roles=frozenset(FAMILIES),
        enabled_tracks=frozenset(TRACKS), enabled_locations=frozenset({"uk"}),
        enabled_domains=frozenset(), answers=_answers(scope),
        include_unstated_level=scope["include_unstated_level"],
    )


def _answers(scope: dict):
    return parse_answers(scope["answers"]) if scope["answers"] is not None else None


@pytest.mark.parametrize("scope", SCOPES, ids=[s["name"] for s in SCOPES])
def test_the_python_gate_admits_the_fixture(scope):
    admitted = {pid for pid, p in POSTINGS.items() if passes_filters(_annotation(p), _filter(scope))}
    assert admitted == set(scope["passes"])


def test_the_catalog_counts_an_unstated_posting_apart_from_mid():
    tallies: dict = {}
    for pid, posting in POSTINGS.items():
        ann = _annotation(posting)
        assert count_level(ann) == posting["cell_band"], pid
        add_to_catalog(tallies, RawJob(company="acme", req_id=pid, title=pid, url="u"), ann)
    counts = tallies["software_engineering"].band_counts
    assert counts["unstated"] == 1 and counts["mid"] == 2


def _job(pid: str, posting: dict) -> Job:
    return Job(
        company="acme", req_id=pid, dedupe_key=f"acme:{pid}", title=pid,
        url=f"https://careers.example.test/acme/{pid}", locations=["London, UK"],
        location_groups=["uk"], domains=[], workplace_type="onsite", level_band=posting["band"],
        level_confidence="confirmed", level_basis=posting["basis"], family=posting["family"],
        track=posting["track"], comp_currency="USD", status="open", in_scope=False,
        first_seen=T0, last_seen=T0, description_sections=[],
    )


def _gate_args(scope: dict) -> tuple[tuple, dict]:
    axes = (FAMILIES, scope["bands"], TRACKS, ["uk"], all_domains())
    return axes, {
        "excluded_domains": [], "answers": _answers(scope), "excluded_locations": [],
        "include_unstated_level": scope["include_unstated_level"],
    }


@pytest.mark.asyncio
async def test_the_sql_gate_over_jobs_admits_the_fixture_and_never_writes_null(db_session):
    db_session.add_all(_job(pid, p) for pid, p in POSTINGS.items())
    await db_session.commit()
    for scope in SCOPES:
        axes, keywords = _gate_args(scope)
        await apply_saved_scope_to_jobs(db_session, *axes, **keywords)
        await db_session.commit()
        rows = dict((await db_session.execute(select(Job.req_id, Job.in_scope))).all())
        assert None not in rows.values(), scope["name"]
        assert {pid for pid, on in rows.items() if on} == set(scope["passes"]), scope["name"]


@pytest.mark.asyncio
async def test_the_sql_gate_over_inventory_admits_the_fixture(db_session):
    run = ScrapeRun(status="running")
    db_session.add(run)
    await db_session.flush()
    rows = {
        f"acme:{pid}": InventoryRow(
            dedupe_key=f"acme:{pid}", req_id=pid, title=pid, url=f"https://x/{pid}",
            department=None, team=None, raw_level=None, locations=("London, UK",),
            workplace_type="onsite", posted_at=None, level_band=p["band"],
            level_confidence="confirmed", level_basis=p["basis"], family=p["family"],
            track=p["track"], location_groups=("uk",), domains=(),
        )
        for pid, p in POSTINGS.items()
    }
    await write_inventory(
        db_session, run_id=run.id, company="acme", binding_id=None, rows=rows,
        seen_keys=set(rows), authoritative=True, now=T0, touch_hours=12.0,
    )
    await db_session.commit()
    stored = dict((await db_session.execute(select(PostingInventory.req_id, PostingInventory.level_basis))).all())
    assert stored == {pid: p["basis"] for pid, p in POSTINGS.items()}
    for scope in SCOPES:
        axes, keywords = _gate_args(scope)
        gate = job_scope_expr(*axes, model=PostingInventory, **keywords)
        admitted = set((await db_session.scalars(select(PostingInventory.req_id).where(gate))).all())
        assert admitted == set(scope["passes"]), scope["name"]


# --- the switch, saved ------------------------------------------------------ #


def test_the_switch_defaults_off_until_family_ladders_land():
    # The default is on. Flipping it is a deliberate change to this line and to the
    # fixture the dashboard reads, not a side effect.
    assert INCLUDE_UNSTATED_LEVEL_DEFAULT is True
    assert FIXTURE["include_unstated_level_default"] is INCLUDE_UNSTATED_LEVEL_DEFAULT
    assert ScopeFilter(
        enabled_bands=frozenset(), enabled_roles=frozenset(), enabled_tracks=frozenset(),
        enabled_locations=frozenset(), enabled_domains=frozenset(),
    ).include_unstated_level is True


@pytest.mark.asyncio
async def test_a_save_stores_the_switch_and_rescopes_by_it(api_client, db_session):
    db_session.add_all(_job(pid, p) for pid, p in POSTINGS.items())
    await db_session.commit()
    # Never set: the default, on.
    assert (await api_client.get("/api/settings")).json()["include_unstated_level"] is True

    body = {
        "enabled_role_groups": FAMILIES, "enabled_seniority_bands": ["senior", "principal"],
        "enabled_role_tracks": TRACKS, "enabled_location_groups": ["uk"],
        "include_unstated_level": False,
    }
    saved = await api_client.put("/api/settings", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["include_unstated_level"] is False
    in_scope = dict((await db_session.execute(select(Job.req_id, Job.in_scope))).all())
    assert {pid for pid, on in in_scope.items() if on} == {"swe_senior", "em_principal"}

    # A client that does not send the switch leaves it as saved: off stays
    # off although the default is on.
    untouched = await api_client.put(
        "/api/settings", json={k: v for k, v in body.items() if k != "include_unstated_level"}
    )
    assert untouched.json()["include_unstated_level"] is False
    assert (await api_client.get("/api/settings")).json()["include_unstated_level"] is False

    on = await api_client.put("/api/settings", json={**body, "include_unstated_level": True})
    assert on.json()["include_unstated_level"] is True
    db_session.expire_all()
    in_scope = dict((await db_session.execute(select(Job.req_id, Job.in_scope))).all())
    assert {pid for pid, on in in_scope.items() if on} == {
        "swe_senior", "swe_unstated", "em_unstated", "em_unmapped", "em_principal",
    }


@pytest.mark.asyncio
async def test_the_board_level_filter_counts_and_selects_unstated_apart_from_mid(api_client, db_session):
    # The Board's Level facet must not show every posting that names no level
    # as "Mid-level": grouping the stored band, which is Mid for sorting only,
    # would put them there.
    rows = {
        "unstated": {"band": "mid", "basis": "none"},
        "said_mid": {"band": "mid", "basis": "generic"},
        "legacy_mid": {"band": "mid", "basis": None},  # no basis stored: read as its band
        "principal": {"band": "principal", "basis": "company"},
        # A manager rank we cannot place: its guessed staff is not a
        # level, so it is counted and selected with the unplaced, never as Staff.
        "unmapped": {"band": "staff", "basis": "unmapped"},
    }
    for pid, row in rows.items():
        job = _job(pid, {**row, "family": "software_engineering", "track": "technical"})
        job.in_scope = True
        db_session.add(job)
    await db_session.commit()

    counts = (await api_client.get("/api/facets")).json()["counts"]["level_band"]
    assert counts == {"unstated": 2, "mid": 2, "principal": 1}

    async def titles(query: str) -> set[str]:
        return {row["title"] for row in (await api_client.get(f"/api/jobs?{query}")).json()["items"]}

    assert await titles("level_band=mid") == {"said_mid", "legacy_mid"}
    assert await titles("level_band=unstated") == {"unstated", "unmapped"}
    assert await titles("level_band=staff") == set()
    assert await titles("level_band=unstated&level_band=principal") == {"unstated", "unmapped", "principal"}
