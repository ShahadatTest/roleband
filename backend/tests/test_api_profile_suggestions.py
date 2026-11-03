"""Suggestion verdict endpoints: accept is the only apply path, and it writes
through the same stores a manual worlds edit uses (persona kept in step, scope
recomputed, fail-open guarded)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from tests.factories import Upserted
from tracker.api.routers import profile as profile_router
from tracker.api.routers.profile import (
    accept_profile_suggestion,
    dismiss_profile_suggestion,
    list_profile_suggestions,
)
from tracker.db.models import AppSetting, ProfileSuggestion
from tracker.scope import projection as scope_projection
from tracker.scope.promotion import PromotionResult
from tracker.settings_store import ENABLED_DOMAINS_KEY, EXCLUDED_DOMAINS_KEY, PERSONA_PROFILE_KEY
from tracker.taxonomy.domains import all_slugs


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


@pytest.fixture(autouse=True)
def _no_promotion(monkeypatch):
    """These tests hold the axis writes over a fake session; promotion reads
    the inventory and is covered on real Postgres (`test_scope_promotion.py`)."""

    async def none(_session):
        return PromotionResult()

    monkeypatch.setattr(profile_router, "promote_after_save", none)


class _Session:
    """Serves AppSetting rows and ProfileSuggestion rows; records upserts the
    settings_store issues through execute()."""

    def __init__(self, settings_rows=None, suggestions=None):
        self.rows = dict(settings_rows or {})
        self.suggestions = {row.id: row for row in (suggestions or [])}
        self.committed = False
        # Rows are built per `get`, so none is ever held: nothing to forget.
        self.identity_map: dict = {}

    async def flush(self):
        return None

    async def get(self, model, key):
        if model is ProfileSuggestion:
            return self.suggestions.get(key)
        assert model is AppSetting
        value = self.rows.get(key)
        return AppSetting(key=key, value=value) if value is not None else None

    async def scalars(self, _stmt):
        return _Scalars(
            [r for r in self.suggestions.values() if r.status == "pending"]
        )

    async def execute(self, stmt, params=None):
        compiled = stmt.compile()
        self.rows[compiled.params["key"]] = compiled.params["value"]
        return Upserted(stmt)

    async def commit(self):
        self.committed = True


def _suggestion(sid=1, kind="world_off", world="advertising", status="pending"):
    return ProfileSuggestion(
        id=sid, kind=kind, dedupe_key=f"{kind}:{world}",
        payload={"world": world}, basis={"score": -8.0}, status=status,
    )


def test_accept_world_off_narrows_domains_and_recomputes(monkeypatch):
    recomputed = []

    async def fake_apply(session, roles, bands, tracks, locations, domains, *, excluded_domains, answers, excluded_locations, include_unstated_level):
        recomputed.append(set(domains))
        return 7

    monkeypatch.setattr(scope_projection, "apply_saved_scope_to_jobs", fake_apply)
    session = _Session(
        settings_rows={
            ENABLED_DOMAINS_KEY: {"slugs": ["ai_ml", "advertising"]},
            PERSONA_PROFILE_KEY: {
                "experience_stage": "staff", "target_stage": "principal",
                "domains": ["ai_ml", "advertising"],
            },
        },
        suggestions=[_suggestion()],
    )
    result = asyncio.run(accept_profile_suggestion(1, session))

    assert result["enabled_domain_groups"] == ["ai_ml"]
    assert result["in_scope_changed"] == 7
    assert result["suggestion"]["status"] == "accepted"
    assert recomputed == [{"ai_ml"}]
    # The persona holds no copy of the axis, so an accept leaves it alone.
    assert session.rows[PERSONA_PROFILE_KEY]["domains"] == ["ai_ml", "advertising"]
    assert session.committed


def test_accept_world_on_widens_domains(monkeypatch):
    async def fake_apply(*_args, excluded_domains, answers, excluded_locations, include_unstated_level):
        return 3

    monkeypatch.setattr(scope_projection, "apply_saved_scope_to_jobs", fake_apply)
    session = _Session(
        settings_rows={ENABLED_DOMAINS_KEY: {"slugs": ["ai_ml"]}},
        suggestions=[_suggestion(kind="world_on", world="media_entertainment")],
    )
    result = asyncio.run(accept_profile_suggestion(1, session))
    assert set(result["enabled_domain_groups"]) == {"ai_ml", "media_entertainment"}


def test_accept_world_on_lifts_a_not_interested_veto_on_that_world(monkeypatch):
    """Turning a world on while it is excluded would change nothing on the
    radar: the veto drops its roles whatever the worlds axis says."""
    recomputed = []

    async def fake_apply(*_args, excluded_domains, answers, excluded_locations, include_unstated_level):
        recomputed.append(set(excluded_domains))
        return 3

    monkeypatch.setattr(scope_projection, "apply_saved_scope_to_jobs", fake_apply)
    session = _Session(
        settings_rows={
            ENABLED_DOMAINS_KEY: {"slugs": ["ai_ml"]},
            EXCLUDED_DOMAINS_KEY: {"slugs": ["media_entertainment", "advertising"]},
        },
        suggestions=[_suggestion(kind="world_on", world="media_entertainment")],
    )
    asyncio.run(accept_profile_suggestion(1, session))
    assert session.rows[EXCLUDED_DOMAINS_KEY] == {"slugs": ["advertising"]}
    assert recomputed == [{"advertising"}]


def test_accept_refuses_to_exclude_the_last_world():
    # set_enabled_domains rewrites empty to ALL (fail-open); accepting would
    # invert the user's intent, so the endpoint must refuse instead.
    session = _Session(
        settings_rows={ENABLED_DOMAINS_KEY: {"slugs": ["advertising"]}},
        suggestions=[_suggestion()],
    )
    with pytest.raises(HTTPException) as err:
        asyncio.run(accept_profile_suggestion(1, session))
    assert err.value.status_code == 409
    # Nothing was persisted.
    assert session.rows[ENABLED_DOMAINS_KEY] == {"slugs": ["advertising"]}


def test_dismiss_changes_nothing_but_status():
    session = _Session(
        settings_rows={ENABLED_DOMAINS_KEY: {"slugs": ["ai_ml", "advertising"]}},
        suggestions=[_suggestion()],
    )
    result = asyncio.run(dismiss_profile_suggestion(1, session))
    assert result["suggestion"]["status"] == "dismissed"
    assert session.rows[ENABLED_DOMAINS_KEY] == {"slugs": ["ai_ml", "advertising"]}
    assert session.committed


@pytest.mark.parametrize("status", ["accepted", "dismissed"])
def test_verdict_endpoints_reject_already_resolved(status):
    session = _Session(suggestions=[_suggestion(status=status)])
    with pytest.raises(HTTPException) as err:
        asyncio.run(dismiss_profile_suggestion(1, session))
    assert err.value.status_code == 409


def test_verdict_endpoints_404_unknown_id():
    session = _Session()
    with pytest.raises(HTTPException) as err:
        asyncio.run(accept_profile_suggestion(99, session))
    assert err.value.status_code == 404


def test_list_serves_pending_only_by_world_slug():
    session = _Session(suggestions=[
        _suggestion(sid=1),
        _suggestion(sid=2, kind="world_on", world="media_entertainment", status="dismissed"),
    ])
    result = asyncio.run(list_profile_suggestions(session))
    assert [s["id"] for s in result["suggestions"]] == [1]
    entry = result["suggestions"][0]
    # The world is a slug the dashboard names; no English here.
    assert "display" not in entry
    assert entry["world"] in all_slugs()
    assert entry["basis"] == {"score": -8.0}


def test_accept_world_off_with_no_interests_is_a_not_interested_veto(monkeypatch):
    """Written as the walk writes "Not interested in advertising":
    with no interests the worlds set is everything, so the veto is the only
    place the answer can live, and a subject added later still arrives on."""
    async def fake_apply(*_args, excluded_domains, answers, excluded_locations, include_unstated_level):
        return 1

    monkeypatch.setattr(scope_projection, "apply_saved_scope_to_jobs", fake_apply)
    session = _Session(settings_rows={}, suggestions=[_suggestion()])
    result = asyncio.run(accept_profile_suggestion(1, session))

    assert "advertising" not in result["enabled_domain_groups"]
    # The response carries the veto, so the screen adopts it too.
    assert result["excluded_domain_groups"] == ["advertising"]
    assert session.rows[EXCLUDED_DOMAINS_KEY] == {"slugs": ["advertising"]}
    assert session.rows[ENABLED_DOMAINS_KEY] == {"hidden": ["advertising"]}


def test_accept_world_off_among_interests_drops_the_interest_without_a_veto(monkeypatch):
    async def fake_apply(*_args, excluded_domains, answers, excluded_locations, include_unstated_level):
        return 1

    monkeypatch.setattr(scope_projection, "apply_saved_scope_to_jobs", fake_apply)
    session = _Session(
        settings_rows={ENABLED_DOMAINS_KEY: {"slugs": ["ai_ml", "advertising"]}},
        suggestions=[_suggestion()],
    )
    result = asyncio.run(accept_profile_suggestion(1, session))

    assert result["enabled_domain_groups"] == ["ai_ml"]
    assert EXCLUDED_DOMAINS_KEY not in session.rows
    assert session.rows[ENABLED_DOMAINS_KEY]["slugs"] == ["ai_ml"]
