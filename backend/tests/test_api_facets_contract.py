"""The similar-postings and facets routes' response contract.

`tracker/api/schemas/jobs.py` declares what `/api/jobs/{job_id}/similar` and
`/api/facets` send. These tests hold it over real HTTP against
`tests/facets_contract_seed.py`:

1. **Shapes and the scope vocabulary**: the shapes forbid unknown keys; each
   scope the contract names is one the route accepts, and another is refused.
2. **Facets**: an empty radar offers the taxonomies and nothing else; visible
   tracked companies by display name, tracked locations that have roles, worlds
   that have roles; counts of open, in-scope, visible roles per value; hiding a
   company removes it everywhere.
3. **Similar postings**: neighbours most similar first as list rows with their
   rounded score, per scope and limit; a hidden company's neighbours dropped; no
   neighbours answered as an empty list.
4. **Drift**: a builder that adds, drops or mistypes a key fails the response.

`pin_jobs_clock` fixes `days_open`; `no_escape` guards every test.
"""

from __future__ import annotations

from typing import get_args

import pytest
import pytest_asyncio
from fastapi.exceptions import ResponseValidationError

from tests.api_errors import said
from tests.facets_contract_seed import SeededBoard, pin_jobs_clock, seed_board
from tests.skills_contract_seed import hide_company
from tracker.api.routers import jobs as router
from tracker.api.schemas import jobs as contract
from tracker.taxonomy.domains import DOMAIN_GROUPS
from tracker.taxonomy.roles import ROLE_GROUPS
from tracker.taxonomy.tracks import TRACKS

NEW_SHAPES = (contract.SimilarJob, contract.SimilarJobsResponse, contract.FacetOption,
              contract.LocationFacetOption, contract.FacetCounts, contract.FacetsResponse)
VISIBLE_COUNTS = {
    "company": {"anthropic": 1, "google": 3, "hidden-co": 1, "openai": 1},
    "level_band": {"principal": 1, "senior": 1, "staff": 4},
    "level_confidence": {"confirmed": 5, "unconfirmed": 1},
    "family": {"engineering_management": 1, "product_management": 3, "program_management": 1},
    "track": {"management": 1, "product_program": 4, "technical": 1},
    "workplace_type": {"hybrid": 1, "onsite": 4, "remote": 1},
    "location_group": {"silicon_valley": 4, "united_states": 5, "new_york": 1, "london": 1},
    "domain": {"ai_ml": 2, "logistics_fulfillment": 1, "security_privacy": 1, "unclassified": 2},
}


@pytest_asyncio.fixture
async def clock(monkeypatch, no_escape):
    pin_jobs_clock(monkeypatch)


@pytest_asyncio.fixture
async def seeded(api_client, db_session, clock) -> SeededBoard:
    return await seed_board(db_session)


@pytest_asyncio.fixture
async def hidden(db_session, seeded) -> SeededBoard:
    await hide_company(db_session)
    return seeded


def _fields(model) -> list[str]:
    return list(model.model_fields)


async def _get(api_client, path: str, status: int = 200) -> dict:
    response = await api_client.get(path)
    assert response.status_code == status, response.text
    return response.json()


def _world(slug: str) -> dict:
    """A world option: its slug is the key and the client names it."""
    assert slug in {g.slug for g in DOMAIN_GROUPS}
    return {}


# --------------------------------------------------------------------------- #
# 1. Shapes and the scope vocabulary
# --------------------------------------------------------------------------- #


def test_the_new_shapes_forbid_unknown_keys_and_a_neighbour_is_a_list_row_with_a_score():
    assert [m.__name__ for m in NEW_SHAPES if m.model_config.get("extra") != "forbid"] == []
    assert _fields(contract.SimilarJob) == [*_fields(contract.JobRow), "score"]


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", get_args(contract.SimilarityScope))
async def test_each_scope_the_contract_names_is_one_the_route_accepts(api_client, seeded, scope):
    body = await _get(api_client, f"/api/jobs/{seeded.jobs['cloud']}/similar?scope={scope}")
    assert body["scope"] == scope


@pytest.mark.asyncio
async def test_any_other_scope_is_refused(api_client, seeded):
    assert said(await _get(api_client, f"/api/jobs/{seeded.jobs['cloud']}/similar?scope=nearby", status=400)) == {
        "detail": "scope must be within|cross|all",
    }


# --------------------------------------------------------------------------- #
# 2. Facets
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_an_empty_radar_offers_the_taxonomies_and_nothing_else(api_client, clock):
    assert await _get(api_client, "/api/facets") == {
        "companies": {},
        # Slugs only: the dashboard names them from its catalog.
        "families": {g.slug: {} for g in ROLE_GROUPS},
        "tracks": {t.slug: {} for t in TRACKS},
        "location_groups": {},
        "domains": {},
        "total": 0,
        "counts": {field: {} for field in _fields(contract.FacetCounts)},
    }


@pytest.mark.asyncio
async def test_facets_offer_visible_companies_tracked_locations_with_roles_and_worlds_with_roles(api_client, seeded):
    body = await _get(api_client, "/api/facets")
    assert list(body) == _fields(contract.FacetsResponse)
    # By display name. A company the user stopped following is off the Board,
    # so the filter does not offer it.
    assert list(body["companies"].items()) == [
        ("anthropic", {"display": "Anthropic"}), ("google", {"display": "Google"}),
        ("hidden-co", {"display": "Hidden Co"}), ("openai", {"display": "OpenAI"}),
    ]
    # The UK is tracked but no role names it; London has a role but is not tracked.
    assert body["location_groups"] == {
        "silicon_valley": {"display": "Silicon Valley", "parent": "united_states"},
        "new_york": {"display": "New York", "parent": "united_states"},
        "united_states": {"display": "United States", "parent": "north_america"},
    }
    assert all(list(option) == _fields(contract.LocationFacetOption) for option in body["location_groups"].values())
    # Taxonomy order, then the bucket for roles that name no world.
    assert list(body["domains"].items()) == [
        ("logistics_fulfillment", _world("logistics_fulfillment")), ("security_privacy", _world("security_privacy")),
        ("ai_ml", _world("ai_ml")), ("unclassified", {}),
    ]
    assert (len(body["families"]), len(body["tracks"])) == (len(ROLE_GROUPS), len(TRACKS))


@pytest.mark.asyncio
async def test_facets_count_open_in_scope_visible_roles_per_value(api_client, seeded):
    body = await _get(api_client, "/api/facets")
    assert list(body["counts"]) == _fields(contract.FacetCounts)
    # Never the closed or out-of-scope role; a role with no family is no key.
    assert body["counts"] == VISIBLE_COUNTS
    assert body["total"] == sum(body["counts"]["company"].values()) == 6


@pytest.mark.asyncio
async def test_hiding_a_company_removes_it_from_every_option_and_count(api_client, hidden):
    body = await _get(api_client, "/api/facets")
    assert "hidden-co" not in body["companies"] and "security_privacy" not in body["domains"]
    assert body["total"] == 5
    assert body["counts"] == {
        **VISIBLE_COUNTS,
        "company": {"anthropic": 1, "google": 3, "openai": 1},
        "level_band": {"principal": 1, "senior": 1, "staff": 3},
        "level_confidence": {"confirmed": 4, "unconfirmed": 1},
        "family": {"engineering_management": 1, "product_management": 3},
        "track": {"management": 1, "product_program": 3, "technical": 1},
        "workplace_type": {"hybrid": 1, "onsite": 3, "remote": 1},
        "location_group": {"silicon_valley": 3, "united_states": 4, "new_york": 1, "london": 1},
        "domain": {"ai_ml": 2, "logistics_fulfillment": 1, "unclassified": 2},
    }


# --------------------------------------------------------------------------- #
# 3. Similar postings
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_similar_postings_come_most_similar_first_as_list_rows_with_a_rounded_score(api_client, seeded):
    j = seeded.jobs
    body = await _get(api_client, f"/api/jobs/{j['cloud']}/similar")
    assert list(body) == _fields(contract.SimilarJobsResponse)
    assert body["scope"] == "cross"
    assert [(item["id"], item["score"]) for item in body["items"]] == [
        (j["gpt"], 0.8812), (j["vault"], 0.8655), (j["claude"], 0.6123),
    ]
    assert all(list(item) == _fields(contract.SimilarJob) for item in body["items"])
    first = body["items"][0]
    assert {k: first[k] for k in ("company", "title", "status", "first_seen", "days_open")} == {
        "company": "openai", "title": "Staff Product Manager, gpt", "status": "open",
        "first_seen": "2026-07-10T15:00:00Z", "days_open": 10,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        # `closed` closed after the table was built and `lonely` has no vector:
        # neither is offered, and neither takes a slot.
        ("scope=within", ["maps"]),
        ("scope=all&limit=3", ["gpt", "vault", "maps"]),
        ("scope=cross&limit=1", ["gpt"]),
    ],
    ids=["same_company", "both_scopes_limited", "one"],
)
async def test_similar_postings_narrow_by_scope_and_limit(api_client, seeded, query, expected):
    j = seeded.jobs
    body = await _get(api_client, f"/api/jobs/{j['cloud']}/similar?{query}")
    assert [item["id"] for item in body["items"]] == [j[key] for key in expected]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected"),
    [("", ["gpt", "claude"]), ("?scope=all&limit=3", ["gpt", "maps", "claude"])],
    ids=["cross", "hidden_take_no_slot"],
)
async def test_a_hidden_companys_neighbours_drop_out_and_take_no_slot(api_client, hidden, query, expected):
    j = hidden.jobs
    body = await _get(api_client, f"/api/jobs/{j['cloud']}/similar{query}")
    assert [item["id"] for item in body["items"]] == [j[key] for key in expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("posting", ["lonely", "unknown"])
async def test_a_posting_without_neighbours_answers_an_empty_list(api_client, seeded, posting):
    job_id = seeded.jobs.get(posting, 999999)
    assert await _get(api_client, f"/api/jobs/{job_id}/similar") == {"scope": "cross", "items": []}


# --------------------------------------------------------------------------- #
# 4. Drift
# --------------------------------------------------------------------------- #


def _row_adding(real):
    return lambda job, **kwargs: {**real(job, **kwargs), "unmodelled": True}


def _days_open_in_words(real):
    return lambda job, **kwargs: {**real(job, **kwargs), "days_open": "ten days"}


def _options_adding(real):
    async def drifted(session):
        return {slug: {**option, "logo": None} for slug, option in (await real(session)).items()}

    return drifted


def _options_without_display(real):
    async def drifted(session):
        return {slug: {} for slug in await real(session)}

    return drifted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "drift", "path"),
    [
        ("serialize_job", _row_adding, "/api/jobs/{cloud}/similar"),
        ("serialize_job", _days_open_in_words, "/api/jobs/{cloud}/similar"),
        ("_visible_company_options", _options_adding, "/api/facets"),
        ("_visible_company_options", _options_without_display, "/api/facets"),
    ],
    ids=["neighbour_key_added", "days_open_in_words", "company_option_key_added", "company_display_dropped"],
)
async def test_a_builder_that_drifts_fails_the_response(api_client, seeded, monkeypatch, name, drift, path):
    monkeypatch.setattr(router, name, drift(getattr(router, name)))
    with pytest.raises(ResponseValidationError):
        await api_client.get(path.format(**seeded.jobs))
