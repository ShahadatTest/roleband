"""The persona (levels and aim sentence) and the one save path that writes it."""

import asyncio

import pytest

from tests.factories import Upserted
from tracker.api.routers import settings as settings_router
from tracker.api.routers.settings import (
    IntentStatementPayload,
    SettingsPayload,
    get_profile_ep,
    put_intent_statement_ep,
    put_settings_ep,
)
from tracker.db.models import AppSetting
from tracker.scope.axes import ScopeInputError
from tracker.scope.axes import derive_stage_span as _derive_stage_span
from tracker.scope.promotion import PromotionResult
from tracker.semantic import provision

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")


@pytest.fixture(autouse=True)
def _no_promotion(monkeypatch):
    """These tests drive the save handler over a fake session; promotion reads
    the posting inventory and is held on real Postgres (`test_scope_promotion.py`)."""

    async def none(_session):
        return PromotionResult()

    monkeypatch.setattr(settings_router, "promote_after_save", none)


class _Session:
    """app_settings-backed fake: get() serves stored rows, execute() records upserts."""

    def __init__(self, rows: dict[str, dict] | None = None):
        self.rows = dict(rows or {})
        self.committed = False

    async def get(self, model, key):
        assert model is AppSetting
        value = self.rows.get(key)
        return AppSetting(key=key, value=value) if value is not None else None

    async def execute(self, stmt, params=None):
        compiled = stmt.compile()
        self.rows[compiled.params["key"]] = compiled.params["value"]
        return Upserted(stmt)

    async def commit(self):
        self.committed = True


async def _board_count(_session) -> int:
    """The Board count a save reports, stubbed beside the recompute."""
    return 40


def test_stage_span_derivation_covers_both_directions_and_single_stage():
    assert _derive_stage_span("staff", "principal") == ["staff", "principal"]
    # Stretching down (open to a step back) is equally valid.
    assert _derive_stage_span("senior", "entry") == ["entry", "mid", "senior"]
    assert _derive_stage_span("mid", "mid") == ["mid"]
    assert _derive_stage_span("intern", "director_plus") == [
        "intern", "entry", "mid", "senior", "staff", "principal", "director_plus",
    ]
    # A stored `junior` stage reads as Entry.
    assert _derive_stage_span("junior", "mid") == ["entry", "mid"]


def test_stage_span_rejects_unknown_stages():
    with pytest.raises(ScopeInputError):
        _derive_stage_span("bogus", "staff")
    with pytest.raises(ScopeInputError):
        _derive_stage_span("staff", "l6")


def _no_recompute(monkeypatch, calls=None):
    async def fake_apply(session, roles, bands, tracks, locations, domains, *, excluded_domains, answers, excluded_locations, include_unstated_level):
        if calls is not None:
            calls.append((roles, bands, tracks, locations, domains))
        return 9

    monkeypatch.setattr(settings_router, "apply_saved_scope_to_jobs", fake_apply)
    monkeypatch.setattr(settings_router, "_board_count", _board_count)


def test_one_save_path_derives_the_level_range_and_creates_the_persona(monkeypatch):
    """PUT /api/settings is the only save. Two levels make the
    seniority axis their span and create the persona, which holds the levels
    and the aim sentence and nothing of the scope."""
    calls: list = []
    _no_recompute(monkeypatch, calls)
    session = _Session()

    response = asyncio.run(put_settings_ep(
        SettingsPayload(
            enabled_role_groups=["software_engineering"],
            enabled_seniority_bands=["staff"],  # ignored: the levels decide
            enabled_role_tracks=["technical", "bogus_track"],
            enabled_location_groups=["uk"],
            experience_stage="entry",
            target_stage="senior",
        ),
        session,
    ))

    assert response["enabled_seniority_bands"] == ["entry", "mid", "senior"]
    assert response["enabled_role_tracks"] == ["technical"]
    assert response["in_scope_changed"] == 9
    assert calls[0][1] == ["entry", "mid", "senior"]
    assert session.committed is True
    assert session.rows["persona_profile"] == {
        "experience_stage": "entry", "target_stage": "senior", "intent_statement": "",
    }


def test_get_profile_reads_the_levels_and_never_a_scope_copy(monkeypatch):
    fresh = asyncio.run(get_profile_ep(_Session()))
    assert fresh == {"profile": None, "scope_configured": False, "intent_statement": ""}

    legacy = asyncio.run(get_profile_ep(_Session({
        "enabled_role_groups": {"slugs": ["software_engineering"]},
    })))
    assert legacy["profile"] is None
    assert legacy["scope_configured"] is True

    # A stored scope copy is omitted on read so it cannot diverge from settings.
    old = asyncio.run(get_profile_ep(_Session({
        "persona_profile": {
            "experience_stage": "staff", "target_stage": "principal", "crafts": ["management"],
            "disciplines": ["engineering_management"], "locations": ["uk"], "intent_statement": "",
        },
    })))
    assert old["profile"] == {"experience_stage": "staff", "target_stage": "principal", "intent_statement": ""}
    assert "customized" not in old


def test_a_save_embeds_the_intent_statement_once_and_clears_on_removal(monkeypatch):
    """The statement embeds at save into a standing vector;
    an unchanged statement must not re-embed (saves happen on routine scope
    tweaks, and each embed is a model load); removing it clears both the
    persona field and the stored vector."""
    from tracker.config import get_settings

    embeds: list[str] = []

    async def fake_embed(text: str) -> list[float]:
        embeds.append(text)
        return [0.25, 0.75]

    _no_recompute(monkeypatch)
    monkeypatch.setattr(settings_router, "embed_query", fake_embed)

    session = _Session()
    payload = dict(
        enabled_role_groups=["engineering_management"], enabled_seniority_bands=[],
        enabled_role_tracks=["management"], enabled_location_groups=["uk"],
        experience_stage="staff", target_stage="principal",
    )

    asyncio.run(put_settings_ep(
        SettingsPayload(**payload, intent_statement="  Senior product leadership in AI  "), session,
    ))
    assert embeds == ["Senior product leadership in AI"]
    assert session.rows["persona_profile"]["intent_statement"] == "Senior product leadership in AI"
    # The tier is stamped beside the model.
    assert session.rows["intent_embedding"] == {
        "statement": "Senior product leadership in AI",
        "model": get_settings().embedding_model,
        "tier": provision.resolve_tier(),
        "vector": [0.25, 0.75],
    }

    # Same statement again: no new embed call.
    asyncio.run(put_settings_ep(
        SettingsPayload(**payload, intent_statement="Senior product leadership in AI"), session,
    ))
    assert embeds == ["Senior product leadership in AI"]

    # Omitted: a routine scope save keeps the statement and its vector.
    asyncio.run(put_settings_ep(SettingsPayload(**payload), session))
    assert session.rows["persona_profile"]["intent_statement"] == "Senior product leadership in AI"
    assert session.rows["intent_embedding"]["vector"] == [0.25, 0.75]
    assert embeds == ["Senior product leadership in AI"]

    # Removed: the persona field empties and the vector record clears.
    asyncio.run(put_settings_ep(SettingsPayload(**payload, intent_statement=""), session))
    assert session.rows["persona_profile"]["intent_statement"] == ""
    assert session.rows["intent_embedding"] == {}
    assert embeds == ["Senior product leadership in AI"]


def test_put_intent_saves_the_statement_alone_and_never_touches_scope(monkeypatch):
    """Settings > Intelligence owns the aim sentence: its endpoint embeds and
    stores the statement, keeps the persona copy in step, and never writes an
    axis or recomputes scope (it ranks, it never filters)."""

    async def fail_apply(*args, **kwargs):
        raise AssertionError("the aim sentence must not recompute scope")

    embeds: list[str] = []

    async def fake_embed(text: str) -> list[float]:
        embeds.append(text)
        return [0.5, 0.5]

    monkeypatch.setattr(settings_router, "apply_saved_scope_to_jobs", fail_apply)
    monkeypatch.setattr(settings_router, "_board_count", _board_count)
    monkeypatch.setattr(settings_router, "embed_query", fake_embed)

    persona = {
        "experience_stage": "staff", "target_stage": "principal",
        "crafts": ["management"], "disciplines": ["engineering_management"],
        "locations": ["uk"], "domains": [], "intent_statement": "",
    }
    session = _Session({
        "persona_profile": dict(persona),
        "enabled_role_groups": {"slugs": ["engineering_management"]},
    })

    saved = asyncio.run(put_intent_statement_ep(
        IntentStatementPayload(intent_statement="  Frontier AI leadership "), session
    ))
    assert saved == {"intent_statement": "Frontier AI leadership"}
    assert embeds == ["Frontier AI leadership"]
    assert session.rows["intent_embedding"]["statement"] == "Frontier AI leadership"
    # Writing the aim preserves levels and removes a stored scope copy.
    assert session.rows["persona_profile"] == {
        "experience_stage": "staff", "target_stage": "principal", "intent_statement": "Frontier AI leadership",
    }
    assert session.rows["enabled_role_groups"] == {"slugs": ["engineering_management"]}
    assert session.committed

    # The profile read shows the new sentence.
    state = asyncio.run(get_profile_ep(session))
    assert state["intent_statement"] == "Frontier AI leadership"

    # Unchanged text: no second model load.
    asyncio.run(put_intent_statement_ep(
        IntentStatementPayload(intent_statement="Frontier AI leadership"), session
    ))
    assert embeds == ["Frontier AI leadership"]

    # Cleared: both copies empty, and ranking loses the vector.
    cleared = asyncio.run(put_intent_statement_ep(
        IntentStatementPayload(intent_statement="   "), session
    ))
    assert cleared == {"intent_statement": ""}
    assert session.rows["intent_embedding"] == {}
    assert session.rows["persona_profile"]["intent_statement"] == ""


def test_put_settings_carries_the_intent_statement_without_touching_axes(monkeypatch):
    """The raw fine-tune path (PUT /api/settings) can save the statement too —
    routing it through PUT /api/profile would clobber hand-tuned axes with the
    persona derivation. None = untouched; a value embeds + merges into the
    persona copy when one exists."""
    from tracker.config import get_settings

    async def fake_apply(session, roles, bands, tracks, locations, domains, *, excluded_domains, answers, excluded_locations, include_unstated_level):
        return 0

    embeds: list[str] = []

    async def fake_embed(text: str) -> list[float]:
        embeds.append(text)
        return [0.1, 0.9]

    monkeypatch.setattr(settings_router, "apply_saved_scope_to_jobs", fake_apply)
    monkeypatch.setattr(settings_router, "_board_count", _board_count)
    monkeypatch.setattr(settings_router, "embed_query", fake_embed)

    session = _Session({
        "persona_profile": {
            "experience_stage": "staff", "target_stage": "principal",
            "crafts": ["management"], "disciplines": ["engineering_management"],
            "locations": ["uk"], "domains": [], "intent_statement": "",
        },
    })
    axes = dict(
        enabled_role_groups=["engineering_management"],
        enabled_seniority_bands=["staff", "principal"],
    )

    # Omitted: nothing intent-related happens.
    asyncio.run(put_settings_ep(SettingsPayload(**axes), session))
    assert embeds == []
    assert "intent_embedding" not in session.rows

    # Provided: embeds, stores the record, and keeps the persona copy in step.
    asyncio.run(put_settings_ep(
        SettingsPayload(**axes, intent_statement="Frontier AI leadership"), session
    ))
    assert embeds == ["Frontier AI leadership"]
    assert session.rows["intent_embedding"] == {
        "statement": "Frontier AI leadership",
        "model": get_settings().embedding_model,
        "tier": provision.resolve_tier(),
        "vector": [0.1, 0.9],
    }
    assert session.rows["persona_profile"]["intent_statement"] == "Frontier AI leadership"
    # The persona keeps its levels and the aim; a stored scope copy is dropped
    # on write.
    assert session.rows["persona_profile"] == {
        "experience_stage": "staff", "target_stage": "principal", "intent_statement": "Frontier AI leadership",
    }
