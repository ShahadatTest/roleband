"""The profile suggestion routes' response contract.

`tracker/api/schemas/profile_suggestions.py` declares what these routes send.
These tests hold it to its sources:

1. **The vocabularies**: `kind` and `status` against the CHECK constraints the
   table enforces, and `kind` against what inference can raise.
2. **The routes over real HTTP** against seeded Postgres rows
   (`tests/profile_suggestions_contract_seed.py`): each shape's exact keys, a
   basis returned exactly as stored, an accept read back through the worlds
   axis, the persona and the roles it moves, and every refused verdict leaving
   all of that exactly as it was.
3. **Drift**: a key the serializer adds or drops without its model fails the
   response. A stored basis is JSONB, so a key it carries beyond the model
   reaches the client, and a key it lacks fails the response.

`no_escape` guards every seeded test: an accept recomputes scope in SQL and must
reach nothing beyond the scratch database.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import get_args

import pytest
import pytest_asyncio
from fastapi.exceptions import ResponseValidationError
from sqlalchemy import select, update

from tests.api_errors import said
from tests.profile_suggestions_contract_seed import (
    EXCLUDED_WORLDS,
    PERSONA,
    SeededSuggestions,
    seed_profile_suggestions,
    settings_body,
)
from tracker.api.routers import profile as profile_router
from tracker.api.schemas import profile_suggestions as contract
from tracker.db.models import Job, ProfileSuggestion
from tracker.taxonomy.domains import all_slugs as all_worlds
from tracker.user_profile.inference import SUGGESTION_KINDS

#: `PUT /api/settings` starts the directory scan when the set is followed.
pytestmark = pytest.mark.usefixtures("no_escape")

# --------------------------------------------------------------------------- #
# 1. Vocabularies
# --------------------------------------------------------------------------- #


def _admitted(constraint_name: str) -> set[str]:
    [constraint] = [
        c for c in ProfileSuggestion.__table__.constraints if constraint_name in str(c.name)
    ]
    return set(re.findall(r"'([^']+)'", str(constraint.sqltext)))


def test_kind_and_status_are_the_values_the_table_admits():
    assert set(get_args(contract.SuggestionKind)) == _admitted("ck_profile_suggestion_kind")
    assert set(get_args(contract.SuggestionStatus)) == _admitted("ck_profile_suggestion_status")
    assert set(get_args(contract.SuggestionKind)) == set(SUGGESTION_KINDS)


# --------------------------------------------------------------------------- #
# 2. The routes over HTTP
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def seeded(db_session, api_client, no_escape) -> SeededSuggestions:
    ids = await seed_profile_suggestions(db_session)
    saved = await api_client.put("/api/settings", json=settings_body(PERSONA))
    assert saved.status_code == 200, saved.text
    return ids


def _fields(model) -> set[str]:
    return set(model.model_fields)


def _url(suggestion_id: int, verdict: str) -> str:
    return f"/api/profile/suggestions/{suggestion_id}/{verdict}"


async def _in_scope(db_session) -> list[str]:
    return list(await db_session.scalars(
        select(Job.req_id).where(Job.in_scope.is_(True)).order_by(Job.req_id)
    ))


async def _resolutions(db_session) -> dict[int, tuple[str, datetime | None]]:
    rows = await db_session.execute(
        select(ProfileSuggestion.id, ProfileSuggestion.status, ProfileSuggestion.resolved_at)
    )
    return {row.id: (row.status, row.resolved_at) for row in rows}


async def _state(api_client, db_session) -> dict:
    """Everything a verdict could move: what a client reads back, and each row's resolution."""
    return {
        "suggestions": (await api_client.get("/api/profile/suggestions")).json(),
        "worlds": (await api_client.get("/api/settings")).json()["enabled_domain_groups"],
        "profile": (await api_client.get("/api/profile")).json(),
        "in_scope": await _in_scope(db_session),
        "resolutions": await _resolutions(db_session),
    }


def _worlds_without(*left_out: str) -> list[str]:
    return [world for world in all_worlds() if world not in left_out]


@pytest.mark.asyncio
async def test_the_list_sends_pending_suggestions_oldest_first_with_each_basis_as_stored(
    api_client, db_session, seeded
):
    response = await api_client.get("/api/profile/suggestions")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == _fields(contract.ProfileSuggestionListResponse)

    rows = body["suggestions"]
    assert [row["id"] for row in rows] == [seeded.early, seeded.narrow, seeded.widen], (
        "resolved rows are never listed; created_at orders, and id breaks the tie"
    )
    assert all(set(row) == _fields(contract.ProfileSuggestionRow) for row in rows)
    assert all(set(row["basis"]) == _fields(contract.ProfileSuggestionBasis) for row in rows)

    stored = dict((await db_session.execute(select(ProfileSuggestion.id, ProfileSuggestion.basis))).all())
    assert {row["id"]: row["basis"] for row in rows} == {
        seeded.early: stored[seeded.early], seeded.narrow: stored[seeded.narrow], seeded.widen: stored[seeded.widen],
    }

    by_id = {row["id"]: row for row in rows}
    narrow, widen, early = by_id[seeded.narrow], by_id[seeded.widen], by_id[seeded.early]
    assert {key: narrow[key] for key in ("kind", "world", "status", "created_at")} == {
        "kind": "world_off", "world": "advertising",
        "status": "pending", "created_at": "2026-07-01T13:00:00Z",
    }
    assert (widen["kind"], widen["world"]) == ("world_on", "media_entertainment")
    assert (widen["basis"]["sectors"], widen["basis"]["intent_matched"]) == (["gaming"], True)
    assert early["basis"]["background"] == 1 and early["created_at"] == "2026-07-01T12:00:00Z"
    assert isinstance(narrow["basis"]["score"], float) and narrow["basis"]["score"] < 0


@pytest.mark.asyncio
async def test_no_pending_suggestion_is_an_empty_list(api_client, db_session, no_escape):
    assert (await api_client.get("/api/profile/suggestions")).json() == {"suggestions": []}


@pytest.mark.asyncio
async def test_accepting_a_narrowing_moves_the_axis_the_persona_and_the_roles(
    api_client, db_session, seeded
):
    assert await _in_scope(db_session) == ["ads-1", "ads-2", "ai-1", "unclassified-1"]

    response = await api_client.post(_url(seeded.narrow, "accept"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == _fields(contract.ProfileSuggestionAcceptResponse)
    assert set(body["suggestion"]) == _fields(contract.ProfileSuggestionRow)
    assert (body["suggestion"]["id"], body["suggestion"]["status"]) == (seeded.narrow, "accepted")

    narrowed = _worlds_without(*EXCLUDED_WORLDS, "advertising")
    assert body["enabled_domain_groups"] == narrowed, "the axis as saved, in taxonomy order"
    assert body["in_scope_changed"] == 2, "both advertising roles left scope"

    assert await _in_scope(db_session) == ["ai-1", "unclassified-1"]
    assert (await api_client.get("/api/settings")).json()["enabled_domain_groups"] == narrowed
    # The persona holds no copy of the axis to keep in step.
    profile = (await api_client.get("/api/profile")).json()
    assert profile["profile"] == {"experience_stage": "staff", "target_stage": "principal", "intent_statement": ""}
    listed = (await api_client.get("/api/profile/suggestions")).json()["suggestions"]
    assert [row["id"] for row in listed] == [seeded.early, seeded.widen]
    status, resolved_at = (await _resolutions(db_session))[seeded.narrow]
    assert status == "accepted" and resolved_at is not None


@pytest.mark.asyncio
async def test_accepting_a_widening_brings_that_world_back_into_scope(api_client, db_session, seeded):
    body = (await api_client.post(_url(seeded.widen, "accept"))).json()
    assert body["suggestion"]["status"] == "accepted"
    assert body["enabled_domain_groups"] == _worlds_without("payments_fintech")
    assert body["in_scope_changed"] == 1
    assert await _in_scope(db_session) == ["ads-1", "ads-2", "ai-1", "media-1", "unclassified-1"]


@pytest.mark.asyncio
async def test_accepting_without_a_persona_moves_the_axis_and_creates_no_persona(
    api_client, db_session, no_escape
):
    seeded = await seed_profile_suggestions(db_session)
    body = (await api_client.post(_url(seeded.narrow, "accept"))).json()
    assert set(body) == _fields(contract.ProfileSuggestionAcceptResponse)
    assert body["enabled_domain_groups"] == _worlds_without("advertising")
    assert (await api_client.get("/api/profile")).json()["profile"] is None


@pytest.mark.asyncio
async def test_refusing_to_exclude_the_last_world_leaves_everything_as_it_was(
    api_client, db_session, seeded
):
    await api_client.put("/api/settings", json=settings_body({**PERSONA, "domains": ["advertising"]}))
    before = await _state(api_client, db_session)

    refused = await api_client.post(_url(seeded.narrow, "accept"))
    assert (refused.status_code, said(refused.json())) == (409, {"detail": "cannot exclude the last tracked world"})
    assert await _state(api_client, db_session) == before
    assert before["resolutions"][seeded.narrow] == ("pending", None)


@pytest.mark.asyncio
async def test_a_dismissal_resolves_the_row_and_moves_nothing_else(api_client, db_session, seeded):
    before = await _state(api_client, db_session)

    response = await api_client.post(_url(seeded.narrow, "dismiss"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == _fields(contract.ProfileSuggestionDismissResponse)
    assert set(body["suggestion"]) == _fields(contract.ProfileSuggestionRow)
    assert (body["suggestion"]["id"], body["suggestion"]["status"]) == (seeded.narrow, "dismissed")

    after = await _state(api_client, db_session)
    assert after["suggestions"]["suggestions"] == [
        row for row in before["suggestions"]["suggestions"] if row["id"] != seeded.narrow
    ]
    assert (after["worlds"], after["profile"], after["in_scope"]) == (
        before["worlds"], before["profile"], before["in_scope"],
    )
    status, resolved_at = after["resolutions"].pop(seeded.narrow)
    assert status == "dismissed" and resolved_at is not None
    before["resolutions"].pop(seeded.narrow)
    assert after["resolutions"] == before["resolutions"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "row", "status", "detail"),
    [
        ("accept", "accepted", 409, "already accepted"),
        ("dismiss", "accepted", 409, "already accepted"),
        ("accept", "dismissed", 409, "already dismissed"),
        ("dismiss", "dismissed", 409, "already dismissed"),
        ("accept", None, 404, "unknown suggestion"),
        ("dismiss", None, 404, "unknown suggestion"),
    ],
)
async def test_a_refused_verdict_keeps_its_status_and_detail_and_changes_nothing(
    api_client, db_session, seeded, verdict, row, status, detail
):
    before = await _state(api_client, db_session)
    response = await api_client.post(_url(getattr(seeded, row) if row else 999_999, verdict))
    assert response.status_code == status
    assert said(response.json()) == {"detail": detail}
    assert await _state(api_client, db_session) == before


# --------------------------------------------------------------------------- #
# 3. Drift
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "verdict", "drift"),
    [
        ("GET", None, lambda row: {**row, "surprise": 1}),
        ("GET", None, lambda row: {key: value for key, value in row.items() if key != "world"}),
        ("POST", "accept", lambda row: {**row, "surprise": 1}),
        ("POST", "dismiss", lambda row: {key: value for key, value in row.items() if key != "created_at"}),
    ],
    ids=["list_row_adds_a_key", "list_row_drops_a_key", "accept_row_adds_a_key", "dismiss_row_drops_a_key"],
)
async def test_serializer_drift_fails_the_response_instead_of_reshaping_it(
    api_client, seeded, monkeypatch, method, verdict, drift
):
    real = profile_router._serialize_suggestion
    monkeypatch.setattr(profile_router, "_serialize_suggestion", lambda row: drift(real(row)))

    with pytest.raises(ResponseValidationError):
        await api_client.request(
            method, _url(seeded.narrow, verdict) if verdict else "/api/profile/suggestions"
        )


async def _store_basis(db_session, suggestion_id: int, basis: dict) -> None:
    await db_session.execute(
        update(ProfileSuggestion).where(ProfileSuggestion.id == suggestion_id).values(basis=basis)
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_a_stored_basis_key_the_model_does_not_name_still_reaches_the_client(
    api_client, db_session, seeded
):
    listed = (await api_client.get("/api/profile/suggestions")).json()["suggestions"]
    basis = next(row["basis"] for row in listed if row["id"] == seeded.narrow)
    await _store_basis(db_session, seeded.narrow, {**basis, "recency_weight": 0.5})

    listed = (await api_client.get("/api/profile/suggestions")).json()["suggestions"]
    assert next(row["basis"] for row in listed if row["id"] == seeded.narrow) == {**basis, "recency_weight": 0.5}


@pytest.mark.asyncio
async def test_a_stored_basis_missing_a_key_the_client_reads_fails_the_response(
    api_client, db_session, seeded
):
    listed = (await api_client.get("/api/profile/suggestions")).json()["suggestions"]
    basis = next(row["basis"] for row in listed if row["id"] == seeded.narrow)
    await _store_basis(db_session, seeded.narrow, {k: v for k, v in basis.items() if k != "background"})

    with pytest.raises(ResponseValidationError):
        await api_client.get("/api/profile/suggestions")
