"""The job list's reads, the scope catalog and the schedule projection answer
without HTTP.

Filtering and ordering (`db/queries/jobs.py`), both Best-match orders
(`search/best_match.py`) and the scope catalog (`scope/catalog.py`) live outside
the routers so a reader can exercise them with a session and nothing else.
Two claims, each checkable:

1. **No web framework comes with them.** Each owner is imported in a fresh
   interpreter and must load neither FastAPI/Starlette nor `tracker.api`. The
   router is the control: it does load FastAPI, so an empty answer is the probe
   seeing nothing rather than the probe being blind.
2. **They keep their meaning without the router**, on real Postgres: standing
   visibility, whole-set ordering before paging, a ranking that never gates,
   the query embedder called only when a vector can matter, and the catalog's
   inventory with hidden companies left out.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.job_contract_seed import seed_job_contract
from tracker.config import get_settings
from tracker.db.models import RoleCatalog, TrackedCompany
from tracker.db.queries.jobs import browse_jobs
from tracker.scope.catalog import build_scope_catalog
from tracker.search.best_match import intent_ranking, relevance_search
from tracker.search.policy import MatchClass

BACKEND = Path(__file__).resolve().parents[1]

_PROBE = """
import importlib, json, sys
importlib.import_module(sys.argv[1])
print(json.dumps(sorted(
    name for name in sys.modules
    if name.split(".")[0] in ("fastapi", "starlette") or name.startswith("tracker.api")
)))
"""


@pytest.mark.parametrize(
    ("module", "loads_web"),
    [
        ("tracker.db.queries.jobs", False),
        ("tracker.search.best_match", False),
        ("tracker.scope.catalog", False),
        ("tracker.scope.projection", False),
        # The schedule projection behind `/api/schedule` and `/api/status`.
        ("tracker.workflows.schedule_status", False),
        # The tier-switch policy. It must also not reach UP for the process
        # facts — `tracker.api.job_requests` is L6 — which this probe would catch as
        # `tracker.api` being loaded.
        ("tracker.semantic.matching", False),
        # The skills leaderboard, which two routers build from.
        ("tracker.db.queries.skills", False),
        ("tracker.api.routers.jobs", True),
    ],
)
def test_a_read_owner_loads_no_web_framework(module, loads_web):
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, module],
        cwd=BACKEND, capture_output=True, text=True, check=True,
    )
    loaded = json.loads(result.stdout.strip().splitlines()[-1])
    assert bool(loaded) is loads_web, loaded


BROWSE = {"status": "open", "hidden": []}


async def _list(session, **page):
    return await browse_jobs(
        session, BROWSE, sort="first_seen", order="desc", **({"limit": 50, "offset": 0} | page)
    )


@pytest.mark.asyncio
async def test_the_list_read_keeps_standing_visibility_and_orders_before_paging(db_session):
    seeded = await seed_job_contract(db_session)

    page = await _list(db_session)
    ids = [job.id for job in page.jobs]

    assert set(ids) == {seeded.plain, seeded.band, seeded.repost, seeded.none_stated,
                        seeded.hourly, seeded.total}, "dismissed and closed rows stay off the board"
    assert page.total == len(ids)
    # Every seeded posting shares first_seen, so the id tiebreaker alone orders them.
    assert ids == sorted(ids, reverse=True)
    assert page.context["favorite_ids"] == {seeded.band}
    assert page.context["lineage_meta"][next(j for j in page.jobs if j.id == seeded.band).lineage_id].size == 2

    second = await _list(db_session, limit=2, offset=1)
    assert [job.id for job in second.jobs] == ids[1:3]
    assert second.total == page.total


@pytest.mark.asyncio
async def test_intent_ranking_reorders_the_same_set_and_never_gates(db_session):
    await seed_job_contract(db_session)
    listed = await _list(db_session)

    ranking = await intent_ranking(db_session, BROWSE, [0.01] * get_settings().embedding_dim, 50, 0)

    assert ranking.total == listed.total
    assert {row.job.id for row in ranking.rows} == {job.id for job in listed.jobs}
    # No seeded row has an embedding: each is unranked (sorted last), none dropped.
    assert all(row.relevance is None for row in ranking.rows)


@pytest.mark.asyncio
async def test_relevance_search_resolves_each_query_kind_without_the_router(db_session):
    seeded = await seed_job_contract(db_session)
    embedded: list[str] = []

    async def embed(text):
        embedded.append(text)
        return None  # no model weights in tests: the lexical half ranks alone

    per_textual_query = 1 if get_settings().search_semantic_enabled else 0

    identifier = await relevance_search(
        db_session, BROWSE, "https://careers.example.test/band", 50, 0, embed=embed
    )
    assert identifier.query_kind == "identifier"
    assert [row.job.id for row in identifier.rows] == [seeded.band]
    assert identifier.rows[0].matched_via == ["exact"] and identifier.related_rows == []
    assert embedded == [], "an identity is the answer, so no vector is ever built for it"

    exact = await relevance_search(
        db_session, BROWSE, "Platform Strategy Lead, Cloud", 50, 0, include_related=True, embed=embed
    )
    assert exact.query_kind == "exact_title"
    assert [row.job.id for row in exact.rows] == [seeded.none_stated]
    assert exact.rows[0].match_class == MatchClass.EXACT.value
    assert [row.job.id for row in exact.related_rows] == [seeded.hourly]
    assert exact.related_total == 1
    assert len(embedded) == per_textual_query

    exploratory = await relevance_search(db_session, BROWSE, "product manager", 50, 0, embed=embed)
    assert exploratory.query_kind == "exploratory"
    assert exploratory.rows and exploratory.total == len(exploratory.rows)
    assert all("exact" not in row.matched_via for row in exploratory.rows)
    assert {row.match_class for row in exploratory.rows} <= {m.value for m in MatchClass}
    # The context covers exactly the rows it will be serialized with.
    assert exploratory.context["favorite_ids"] <= {row.job.id for row in exploratory.rows}
    assert len(embedded) == 2 * per_textual_query


@pytest.mark.asyncio
async def test_the_scope_catalog_sums_inventory_and_leaves_hidden_companies_out(db_session):
    for slug in ("acme", "globex"):
        db_session.add(
            TrackedCompany(
                slug=slug, display=slug.title(), adapter="greenhouse", status="active",
                enabled=True, visible=True, source="catalog", role_catalog_status="ready",
            )
        )
        db_session.add(
            RoleCatalog(
                role_group="software_engineering", company=slug, count=3,
                band_counts={"junior": 2, "staff": 1},
                band_track_counts={"junior": {"technical": 2}, "staff": {"technical": 1}},
                examples=["Junior Software Engineer", "Staff Software Engineer"],
            )
        )
    await db_session.commit()

    def software(catalog: dict) -> dict:
        return next(
            group
            for category in catalog["categories"]
            for group in category["groups"]
            if group["slug"] == "software_engineering"
        )

    everyone = await build_scope_catalog(db_session, [])
    assert everyone["joint_counts_ready"] is True
    assert software(everyone)["total"] == 6
    # Rows an older scan wrote carry "junior", read as Entry.
    assert software(everyone)["band_track_counts"] == {
        "entry": {"technical": 4}, "staff": {"technical": 2},
    }

    without_globex = await build_scope_catalog(db_session, ["globex"])
    assert software(without_globex)["total"] == 3
