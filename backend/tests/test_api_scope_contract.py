"""The scope, settings and profile routes' response contract.

`tracker/api/schemas/scope.py` declares what these routes send. A model that
agrees only with itself proves nothing, so these tests hold it to its sources:

1. **The vocabularies**: a location's `kind` against the taxonomy table, and the
   refresh status against every branch the handler can take.
2. **The routes over real HTTP** against seeded Postgres rows
   (`tests/scope_contract_seed.py`): each shape's exact keys, what the values
   mean, saves read back by a later request, and rejected input leaving the
   stored state exactly as it was.
3. **Drift in both directions**: a key a serializer adds or drops without its
   model fails the response instead of vanishing from, or defaulting in, it.
"""

from __future__ import annotations

from typing import get_args

import pytest
import pytest_asyncio
from fastapi.exceptions import ResponseValidationError
from sqlalchemy import select

from tests.api_errors import said
from tests.scope_contract_seed import (
    CURRENT_PERSONA,
    LEGACY_PERSONA,
    T0,
    SeededScope,
    _job,
    seed_scope_contract,
    store_intent_record,
    store_persona,
)
from tracker.api.routers import settings as settings_router
from tracker.api.schemas import scope as contract
from tracker.db.models import Job, RoleCatalog
from tracker.levels import LEVELS
from tracker.taxonomy.domains import all_slugs as all_domain_slugs
from tracker.taxonomy.locations import LOCATION_GROUPS

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")

_AXES = set(contract.ScopeAxes.model_fields)

# --------------------------------------------------------------------------- #
# 1. Vocabularies
# --------------------------------------------------------------------------- #


def test_location_kind_is_the_set_the_taxonomy_uses():
    # Plus "city": a GeoNames city is not in the fixed table, only in the
    # gazetteer, and appears when tracked or searched.
    assert set(get_args(contract.LocationKind)) == {
        group.get("kind", "country") for group in LOCATION_GROUPS.values()
    } | {"city"}


# --------------------------------------------------------------------------- #
# 2. The routes over HTTP
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def seeded(db_session, monkeypatch) -> SeededScope:
    async def no_model(_text):
        return [0.25, 0.5]  # no model weights in tests: a fixed vector stands in

    monkeypatch.setattr(settings_router, "embed_query", no_model)
    return await seed_scope_contract(db_session)


def _fields(model) -> set[str]:
    return set(model.model_fields)


@pytest.mark.asyncio
async def test_the_catalog_sends_every_key_of_every_shape(api_client, seeded):
    response = await api_client.get("/api/scope/catalog")
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body) == _fields(contract.ScopeCatalogResponse)
    assert set(body["settings"]) == _AXES
    for key, model in [
        ("domains", contract.ScopeDomain), ("locations", contract.ScopeLocation),
        ("levels", contract.ScopeLevel), ("tracks", contract.ScopeTrack),
        ("categories", contract.ScopeCategory), ("companies", contract.ScopeCatalogCompany),
    ]:
        assert body[key], key
        assert all(set(item) == _fields(model) for item in body[key]), key
    groups = [group for category in body["categories"] for group in category["groups"]]
    assert all(set(group) == _fields(contract.ScopeRoleGroup) for group in groups)

    # A decoder cell holds exactly one of its two keys, never a null for the other.
    cells = {
        (level["slug"], company): cell
        for level in body["levels"] for company, cell in level["decoder"].items()
    }
    assert all(len(cell) == 1 for cell in cells.values())
    assert set(cells[("senior", "google")]) == {"company_wide"}
    # Google's L8 is Principal Engineer for an engineer, Director for everyone
    # else: that band's cell is per track.
    assert set(cells[("principal", "google")]) == {"per_track"}
    assert set(cells[("senior", "apple")]) == {"per_track"}
    assert not any(company == "acme" for _, company in cells), "a company with no ladder has no cell"


@pytest.mark.asyncio
async def test_the_catalog_means_what_it_says(api_client, seeded):
    body = (await api_client.get("/api/scope/catalog")).json()

    companies = {row["slug"]: row for row in body["companies"]}
    assert companies["google"]["role_catalog_scanned_at"] == "2026-07-01T12:00:00Z"
    assert companies["acme"]["role_catalog_status"] == "partial"
    assert companies["pending_co"]["role_catalog_scanned_at"] is None
    # One company is not ready, so joint impact is off and track counts fall
    # back to open jobs, which skip the hidden company.
    assert body["joint_counts_ready"] is False
    assert {t["slug"]: t["count"] for t in body["tracks"]}["technical"] == 2

    groups = {g["slug"]: g for c in body["categories"] for g in c["groups"]}
    software = groups["software_engineering"]
    assert software["band_counts"] == {"senior": 1, "staff": 2, "principal": 1}
    # Google and Apple split their levels by track; Acme's product row predates
    # the split, so its group's joint cannot price an answer that names it.
    assert software["joint_complete"] is True
    assert groups["product_management"]["joint_complete"] is False
    assert body["unclassified_domain_count"] == 1

    locations = {loc["slug"]: loc for loc in body["locations"]}
    assert locations["uk"]["count"] == 2, "the hidden company's open job is not counted"
    # Every kind but "city": a city is listed only once tracked (see below).
    assert {loc["kind"] for loc in body["locations"]} == set(get_args(contract.LocationKind)) - {"city"}
    assert {company for loc in body["locations"] for company in loc["uncovered_by"]} == {"apple"}


@pytest.mark.asyncio
async def test_settings_answer_with_the_axes_and_a_save_is_read_back(api_client, db_session, seeded):
    defaults = (await api_client.get("/api/settings")).json()
    assert set(defaults) == _AXES
    assert defaults["enabled_domain_groups"] == all_domain_slugs()

    saved = await api_client.put("/api/settings", json={
        "enabled_role_groups": ["product_management", "software_engineering"],
        "enabled_seniority_bands": ["principal", "staff"],
        "enabled_role_tracks": ["technical"],
        "enabled_location_groups": ["uk", "silicon_valley"],
        "enabled_domain_groups": ["ai_ml"],
        "intent_statement": "Platform leadership",
    })
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert set(body) == _AXES | {"in_scope_changed", "on_board", "promoted", "promotion_pending"}, "passengers are never echoed"
    assert body["enabled_seniority_bands"] == ["staff", "principal"], "taxonomy order, not request order"
    assert body["in_scope_changed"] == 1
    acme = await db_session.scalar(select(Job.in_scope).where(Job.dedupe_key == "acme:ops"))
    assert acme is False, "a product_program role left a technical-only scope"

    read_back = (await api_client.get("/api/settings")).json()
    assert read_back == {key: body[key] for key in _AXES}
    assert (await api_client.get("/api/scope/catalog")).json()["settings"] == read_back

    # Axes a request omits stay as they were; stage markers derive the seniority span.
    partial = (await api_client.put("/api/settings", json={
        "enabled_role_groups": ["software_engineering"],
        "enabled_seniority_bands": ["entry"],
        "experience_stage": "senior",
        "target_stage": "staff",
    })).json()
    assert partial["enabled_seniority_bands"] == ["senior", "staff"]
    assert partial["enabled_location_groups"] == read_back["enabled_location_groups"]
    assert partial["enabled_domain_groups"] == ["ai_ml"]


STOCKHOLM, GOTHENBURG = "city_2673730", "city_2711537"


@pytest.mark.asyncio
async def test_a_tracked_city_is_a_place_like_any_other(api_client, db_session, seeded):
    """A GeoNames city saved as scope is kept, listed with its
    parent and its parent's coverage, gates jobs like any group, and is the
    only city the joint carries."""
    db_session.add_all([
        _job("google", "sthlm", locations=["Stockholm, Sweden"],
             location_groups=["sweden", "europe", STOCKHOLM]),
        _job("google", "gbg", locations=["Gothenburg, Sweden"],
             location_groups=["sweden", "europe", GOTHENBURG]),
        RoleCatalog(
            role_group="data_science", company="google", count=2,
            band_counts={"staff": 2}, band_track_counts={"staff": {"technical": 2}},
            examples=["Staff Data Scientist"], domain_counts={"ai_ml": 2},
            domain_examples={"ai_ml": ["Applied AI"]}, updated_at=T0,
            scope_cells=[
                {"band": "staff", "track": "technical", "locations": ["europe", "sweden", STOCKHOLM],
                 "domains": ["ai_ml"], "count": 1},
                {"band": "staff", "track": "technical", "locations": ["europe", "sweden", GOTHENBURG],
                 "domains": ["ai_ml"], "count": 1},
            ],
        ),
    ])
    await db_session.commit()

    saved = (await api_client.put("/api/settings", json={
        "enabled_role_groups": ["software_engineering", "data_science"],
        "enabled_seniority_bands": ["staff"],
        "enabled_location_groups": [STOCKHOLM, "uk", "city_0", "city_nowhere"],
    })).json()
    # Taxonomy order, then cities; a slug that names no city is dropped.
    assert saved["enabled_location_groups"] == ["uk", STOCKHOLM]
    assert (await api_client.get("/api/settings")).json()["enabled_location_groups"] == ["uk", STOCKHOLM]

    in_scope = dict((await db_session.execute(
        select(Job.dedupe_key, Job.in_scope).where(Job.dedupe_key.in_(["google:sthlm", "google:gbg"]))
    )).all())
    assert in_scope == {"google:sthlm": True, "google:gbg": False}, "the city gates; Sweden is not tracked"

    body = (await api_client.get("/api/scope/catalog")).json()
    locations = {loc["slug"]: loc for loc in body["locations"]}
    assert locations[STOCKHOLM] == {
        "slug": STOCKHOLM, "display": "Stockholm", "default_enabled": False, "selected": True,
        "count": 1, "kind": "city", "parent": "sweden",
        "uncovered_by": locations["sweden"]["uncovered_by"], "prominent": True,
        # Chosen by search, never a taxonomy category that can be "new".
        "new": False,
    }
    assert GOTHENBURG not in locations, "an untracked city is not listed"
    cells = body["scope_cells"]
    assert cells["cities"] == [STOCKHOLM]
    # The untracked city is stripped from its cell rather than growing a set.
    assert sorted(map(sorted, cells["location_sets"])) == sorted(
        [sorted(["europe", "sweden", STOCKHOLM]), ["europe", "sweden"]]
    )


@pytest.mark.asyncio
async def test_the_place_search_answers_with_its_contract(api_client, seeded):
    body = (await api_client.get("/api/scope/places", params={"q": "stockholm"})).json()
    assert set(body) == _fields(contract.PlaceSearchResponse)
    assert all(set(place) == _fields(contract.PlaceResult) for place in body["places"])
    assert body["places"][0] == {
        "slug": STOCKHOLM, "display": "Stockholm", "kind": "city", "parent": "sweden",
        "context": "Sweden", "matched_by": None,
    }
    union = (await api_client.get("/api/scope/places", params={"q": "eu"})).json()["unions"]
    assert set(union[0]) == _fields(contract.UnionResult) and len(union[0]["members"]) == 27
    assert (await api_client.get("/api/scope/places", params={"q": ""})).status_code == 422


#: A save naming the persona's levels and aim (the one save path).
PERSONA_SAVE = {
    "enabled_role_groups": CURRENT_PERSONA["disciplines"], "enabled_seniority_bands": [],
    "enabled_role_tracks": CURRENT_PERSONA["crafts"], "enabled_location_groups": CURRENT_PERSONA["locations"],
    "enabled_domain_groups": CURRENT_PERSONA["domains"],
    "experience_stage": CURRENT_PERSONA["experience_stage"], "target_stage": CURRENT_PERSONA["target_stage"],
    "intent_statement": CURRENT_PERSONA["intent_statement"],
}
PERSONA = {key: CURRENT_PERSONA[key] for key in ("experience_stage", "target_stage", "intent_statement")}


async def _state(api_client) -> tuple[dict, dict]:
    return (await api_client.get("/api/settings")).json(), (await api_client.get("/api/profile")).json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "change", "detail"),
    [
        ("/api/settings", {"experience_stage": "staff"}, "experience_stage and target_stage travel together"),
        ("/api/settings", {"experience_stage": "l6", "target_stage": "staff"}, "unknown experience_stage: 'l6'"),
        ("/api/settings", {"experience_stage": "staff", "target_stage": "vp"}, "unknown target_stage: 'vp'"),
    ],
    ids=["settings_half_stage_pair", "settings_unknown_stage", "settings_unknown_target"],
)
async def test_rejected_input_leaves_the_stored_scope_and_persona_intact(
    api_client, seeded, path, change, detail
):
    """`put_settings_ep` writes the role axis before it validates the stages, so
    this holds only because a request that raises is never committed."""
    await api_client.put("/api/settings", json=PERSONA_SAVE)
    before = await _state(api_client)
    request = {**before[0], "enabled_role_groups": ["product_management"], **change}

    response = await api_client.put(path, json=request)

    assert response.status_code == 422
    assert said(response.json()) == {"detail": detail}
    assert await _state(api_client) == before


@pytest.mark.asyncio
async def test_profile_states_send_their_own_keys(api_client, db_session, seeded):
    assert (await api_client.get("/api/profile")).json() == {
        "profile": None, "scope_configured": False, "intent_statement": "",
    }

    await api_client.put("/api/settings", json={
        "enabled_role_groups": ["software_engineering"], "enabled_seniority_bands": ["staff"],
    })
    await store_intent_record(db_session, "A statement saved without a persona")
    profileless = (await api_client.get("/api/profile")).json()
    assert profileless == {
        "profile": None, "scope_configured": True,
        "intent_statement": "A statement saved without a persona",
    }

    await api_client.put("/api/settings", json=PERSONA_SAVE)
    current = (await api_client.get("/api/profile")).json()
    assert set(current) == _fields(contract.ProfileStateResponse)
    # The levels and the aim, nothing of the scope.
    assert current["profile"] == PERSONA
    assert current["intent_statement"] == CURRENT_PERSONA["intent_statement"]

    # A persona an older writer stored with the scope copied in and no aim
    # line: only its levels are read, and the aim falls back to the record.
    await store_persona(db_session, {**LEGACY_PERSONA, "left_by_an_older_writer": True})
    legacy = (await api_client.get("/api/profile")).json()
    assert legacy["profile"] == {"experience_stage": "staff", "target_stage": "principal"}
    assert legacy["intent_statement"] == CURRENT_PERSONA["intent_statement"], "falls back to the intent record"


@pytest.mark.asyncio
async def test_the_one_save_path_moves_the_levels_and_keeps_the_aim(api_client, seeded):
    saved = await api_client.put("/api/settings", json=PERSONA_SAVE)
    assert saved.status_code == 200, saved.text
    assert saved.json()["enabled_seniority_bands"] == ["staff", "principal"]
    assert (await api_client.get("/api/profile")).json()["profile"] == PERSONA

    # A save that names new levels and no aim moves the levels only: the aim
    # is Settings > Intelligence's, and a scope save must not erase it.
    await api_client.put("/api/settings", json={
        **{k: v for k, v in PERSONA_SAVE.items() if k != "intent_statement"},
        "enabled_role_tracks": ["management"], "experience_stage": "senior", "target_stage": "senior",
    })
    after = (await api_client.get("/api/profile")).json()
    assert after["profile"] == {**PERSONA, "experience_stage": "senior", "target_stage": "senior"}
    assert "customized" not in after
    assert [level.slug for level in LEVELS if level.slug == "senior"] == ["senior"]
    assert (await api_client.put("/api/profile", json=CURRENT_PERSONA)).status_code == 405


@pytest.mark.asyncio
async def test_refresh_sends_the_keys_of_its_branch_and_no_others(api_client, seeded, monkeypatch):
    async def lock_held(_session, _key):
        return False

    real_lock = settings_router.try_advisory_lock
    monkeypatch.setattr(settings_router, "try_advisory_lock", lock_held)
    deferred = (await api_client.post("/api/scope/refresh")).json()
    monkeypatch.setattr(settings_router, "try_advisory_lock", real_lock)
    async def busy(_session, **_kw):
        return False

    async def free(_session, **_kw):
        return True

    monkeypatch.setattr(settings_router.job_requests, "ring_role_discovery", busy)
    running = (await api_client.post("/api/scope/refresh")).json()
    monkeypatch.setattr(settings_router.job_requests, "ring_role_discovery", free)
    started = (await api_client.post("/api/scope/refresh")).json()

    # The status is the code; the dashboard words it.
    assert deferred == {"status": "deferred"}
    assert running == {"status": "already_running"}
    assert started == {"status": "started", "max_list": 600}
    assert {deferred["status"], running["status"], started["status"]} == set(
        get_args(contract.ScopeRefreshStatus)
    )

    # The places being answered reach the scan, unknown ones dropped.
    spawned = []

    async def record(_session, **kw):
        spawned.append(kw)
        return True

    monkeypatch.setattr(settings_router.job_requests, "ring_role_discovery", record)
    await api_client.post("/api/scope/refresh", json={"locations": ["singapore", "not_a_place"]})
    await api_client.post("/api/scope/refresh")
    assert [call["locations"] for call in spawned] == [["singapore"], []]


@pytest.mark.asyncio
async def test_rules_answer_with_their_contract(api_client, seeded):
    listed = (await api_client.get("/api/scope/rules")).json()
    assert listed == {"rules": [{
        "id": seeded.rule_id, "company": "acme", "kind": "department",
        "value": "Operations", "created_at": "2026-07-01T12:00:00Z",
    }]}

    rule = {"company": "google", "kind": "team", "value": "Ads Sales"}
    created = await api_client.post("/api/scope/rules", json=rule)
    assert created.status_code == 200, created.text
    body = created.json()
    assert set(body) == _fields(contract.ScopeRuleCreateResponse)
    assert set(body["rule"]) == _fields(contract.ScopeRule)
    assert body["created"] is True and isinstance(body["in_scope_changed"], int)

    existing = await api_client.post("/api/scope/rules", json={**rule, "value": " ads sales "})
    assert existing.status_code == 200
    assert existing.json() == {
        "rule": body["rule"], "created": False, "in_scope_changed": 0,
        "promoted": 0, "promotion_pending": False,
    }

    deleted = (await api_client.delete(f"/api/scope/rules/{seeded.rule_id}")).json()
    assert set(deleted) == {"deleted", "in_scope_changed", "promoted", "promotion_pending"} and deleted["deleted"] is True
    assert [r["id"] for r in (await api_client.get("/api/scope/rules")).json()["rules"]] == [
        body["rule"]["id"]
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body", "status", "detail"),
    [
        ("POST", "/api/scope/rules", {"company": "nobody", "kind": "team", "value": "x"}, 404,
         "unknown company: 'nobody'"),
        ("POST", "/api/scope/rules", {"company": "acme", "kind": "team", "value": "   "}, 422,
         "rule value must be non-empty"),
        ("DELETE", "/api/scope/rules/999999", None, 404, "rule not found"),
    ],
)
async def test_errors_keep_their_status_and_detail(api_client, seeded, method, path, body, status, detail):
    response = await api_client.request(method, path, json=body)
    assert response.status_code == status
    assert said(response.json()) == {"detail": detail}


# --------------------------------------------------------------------------- #
# 3. Drift
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "path", "drift"),
    [
        ("_serialize_rule", "/api/scope/rules", lambda row: {**row, "surprise": 1}),
        ("_serialize_rule", "/api/scope/rules", lambda row: {k: v for k, v in row.items() if k != "kind"}),
        ("build_scope_catalog", "/api/scope/catalog", lambda body: {**body, "surprise": 1}),
        ("build_scope_catalog", "/api/scope/catalog",
         lambda body: {k: v for k, v in body.items() if k != "joint_counts_ready"}),
    ],
    ids=["rule_adds_a_key", "rule_drops_a_key", "catalog_adds_a_key", "catalog_drops_a_key"],
)
async def test_serializer_drift_fails_the_response_instead_of_reshaping_it(
    api_client, seeded, monkeypatch, target, path, drift
):
    real = getattr(settings_router, target)
    if target == "build_scope_catalog":
        async def drifted(*args, **kwargs):
            return drift(await real(*args, **kwargs))
    else:
        def drifted(*args, **kwargs):
            return drift(real(*args, **kwargs))
    monkeypatch.setattr(settings_router, target, drifted)

    with pytest.raises(ResponseValidationError):
        await api_client.get(path)
