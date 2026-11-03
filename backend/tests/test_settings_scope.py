"""Persisted taxonomy scope stays canonical and tolerates damaged JSON rows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from sqlalchemy.dialects import postgresql

from tests.factories import Upserted
from tracker import settings_store
from tracker.config import all_location_group_slugs, default_enabled_location_groups
from tracker.db.models import AppSetting
from tracker.db.queries.scope import job_scope_expr
from tracker.levels import all_band_slugs, default_enabled_bands
from tracker.semantic import provision
from tracker.taxonomy.domains import all_slugs as all_domain_slugs
from tracker.taxonomy.roles import all_slugs, default_enabled_slugs
from tracker.taxonomy.tracks import all_track_slugs, default_enabled_tracks


@dataclass
class _Row:
    value: object


class FakeSession:
    def __init__(self, expected_key: str, row: _Row | None = None):
        self.expected_key = expected_key
        self.row = row
        self.executed = []

    async def get(self, model, key):
        assert model is AppSetting
        assert key == self.expected_key
        return self.row

    async def execute(self, stmt):
        self.executed.append(stmt)
        return Upserted(stmt)


@pytest.mark.parametrize(
    "getter,key,defaults,valid",
    [
        (
            settings_store.get_enabled_roles,
            settings_store.ENABLED_ROLES_KEY,
            default_enabled_slugs,
            all_slugs,
        ),
        (
            settings_store.get_enabled_bands,
            settings_store.ENABLED_BANDS_KEY,
            default_enabled_bands,
            all_band_slugs,
        ),
        (
            settings_store.get_enabled_tracks,
            settings_store.ENABLED_TRACKS_KEY,
            default_enabled_tracks,
            all_track_slugs,
        ),
        (
            settings_store.get_enabled_locations,
            settings_store.ENABLED_LOCATIONS_KEY,
            default_enabled_location_groups,
            all_location_group_slugs,
        ),
    ],
)
def test_enabled_taxonomy_defaults_and_filters_damaged_rows(getter, key, defaults, valid):
    assert asyncio.run(getter(FakeSession(key))) == set(defaults())

    valid_slug = valid()[0]
    stored = FakeSession(
        key,
        _Row({"slugs": [valid_slug, "unknown", None, {"not": "hashable"}, ["nested"]]}),
    )
    assert asyncio.run(getter(stored)) == {valid_slug}

    malformed = FakeSession(key, _Row({"slugs": valid_slug}))
    assert asyncio.run(getter(malformed)) == set(defaults())


@pytest.mark.parametrize(
    "setter,key,all_valid",
    [
        (settings_store.set_enabled_roles, settings_store.ENABLED_ROLES_KEY, all_slugs),
        (settings_store.set_enabled_bands, settings_store.ENABLED_BANDS_KEY, all_band_slugs),
        (settings_store.set_enabled_tracks, settings_store.ENABLED_TRACKS_KEY, all_track_slugs),
        (
            settings_store.set_enabled_locations,
            settings_store.ENABLED_LOCATIONS_KEY,
            all_location_group_slugs,
        ),
    ],
)
def test_set_enabled_taxonomy_canonicalizes_and_upserts(setter, key, all_valid):
    taxonomy_order = all_valid()
    requested = [taxonomy_order[-1], "bogus", taxonomy_order[0], taxonomy_order[-1]]
    expected = [taxonomy_order[0], taxonomy_order[-1]]
    session = FakeSession(key)

    assert asyncio.run(setter(session, requested)) == expected
    assert len(session.executed) == 1
    params = session.executed[0].compile().params
    assert params["key"] == key
    # `seen` is the whole list the user was choosing among, so a category the
    # taxonomy adds later is new to them until their next save.
    assert params["value"] == {"slugs": expected, "seen": taxonomy_order}


def test_job_scope_expression_and_combines_role_band_track_and_location():
    sql = str(
        job_scope_expr(
            ["software_engineering"], ["director_plus"], ["technical"], ["uk", "singapore"],
            ["ai_ml"], excluded_domains=[],
        ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )

    assert "jobs.level_band IN ('director_plus')" in sql
    assert "jobs.family IN ('software_engineering')" in sql
    assert "jobs.track IN ('technical')" in sql
    # Locations gate by overlap with the stored matches, not mere non-emptiness.
    assert "jobs.location_groups && " in sql
    assert "singapore" in sql and "uk" in sql
    assert "array_length" not in sql
    # Domains gate by overlap too, but fail-open: NULL (pre-axis) and
    # empty (classified, honestly unknown) rows must pass a narrowed axis.
    assert "jobs.domains && " in sql
    assert "ai_ml" in sql
    assert "jobs.domains IS NULL" in sql
    assert "cardinality" in sql


def test_job_scope_expression_domain_axis_is_optional_narrowing():
    # An empty enabled set adds NO domain clause — "no narrowing", never
    # "match nothing". The inverse of every other axis, and deliberate: with
    # fail-open-unknown, empty-fails-classified would be an inverse filter.
    sql = str(
        job_scope_expr(
            ["software_engineering"], ["staff"], ["technical"], ["uk"], [], excluded_domains=[]
        ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "domains" not in sql
    assert sql != "false"


def test_job_scope_expression_empty_axis_matches_nothing():
    empty_cases = [
        ([], ["staff"], ["technical"], ["uk"]),
        (["software_engineering"], [], ["technical"], ["uk"]),
        (["software_engineering"], ["staff"], [], ["uk"]),
        (["software_engineering"], ["staff"], ["technical"], []),
    ]
    for roles, bands, tracks, locations in empty_cases:
        sql = str(
            job_scope_expr(roles, bands, tracks, locations, ["ai_ml"], excluded_domains=[]).compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        assert sql == "false", (roles, bands, tracks, locations)


def test_enabled_domains_default_to_all_and_empty_reads_as_all():
    # No row → every world (the axis narrows only by explicit choice).
    assert asyncio.run(
        settings_store.get_enabled_domains(FakeSession(settings_store.ENABLED_DOMAINS_KEY))
    ) == set(all_domain_slugs())
    # A stored subset is respected.
    stored = FakeSession(settings_store.ENABLED_DOMAINS_KEY, _Row({"slugs": ["ai_ml"]}))
    assert asyncio.run(settings_store.get_enabled_domains(stored)) == {"ai_ml"}
    # A stored EMPTY set reads as all — with fail-open-unknown an
    # empty include-set would block classified rows while passing unclassified
    # ones, an inverse filter no user can ask for. Self-healing on read.
    empty = FakeSession(settings_store.ENABLED_DOMAINS_KEY, _Row({"slugs": []}))
    assert asyncio.run(settings_store.get_enabled_domains(empty)) == set(all_domain_slugs())


def test_set_enabled_domains_refuses_to_persist_empty():
    session = FakeSession(settings_store.ENABLED_DOMAINS_KEY)
    assert asyncio.run(settings_store.set_enabled_domains(session, [])) == all_domain_slugs()
    params = session.executed[0].compile().params
    # Stored as what the user HID, so a world added later is on for
    # everyone who never decided about it.
    assert params["value"] == {"hidden": []}
    # Bogus-only input is the same as empty after canonicalization.
    session2 = FakeSession(settings_store.ENABLED_DOMAINS_KEY)
    assert asyncio.run(
        settings_store.set_enabled_domains(session2, ["bogus"])
    ) == all_domain_slugs()
    # A real subset persists as that subset, in declaration order.
    session3 = FakeSession(settings_store.ENABLED_DOMAINS_KEY)
    assert asyncio.run(
        settings_store.set_enabled_domains(session3, ["cloud_infra", "ai_ml", "bogus"])
    ) == ["ai_ml", "cloud_infra"]


def test_job_scope_expression_applies_learned_company_exclusions():
    """The SQL half of `rule_excluded`: same verbatim,
    case-insensitive, per-company, per-field semantics — drift between the two
    gates would make a saved rule lie on one surface."""
    exclusions = frozenset({("amazon", "department", "fulfillment & operations management")})
    sql = str(
        job_scope_expr(
            ["product_management"], ["director_plus"], ["management"], ["united_states"],
            [], exclusions, excluded_domains=[],
        ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "NOT" in sql
    assert "jobs.company = 'amazon'" in sql
    assert "lower(trim(jobs.department)) = 'fulfillment & operations management'" in sql
    # A team rule reads the team column, not department.
    team_sql = str(
        job_scope_expr(
            ["product_management"], ["director_plus"], ["management"], ["united_states"],
            [], frozenset({("google", "team", "ads")}), excluded_domains=[],
        ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "lower(trim(jobs.team)) = 'ads'" in team_sql
    # No rules -> no exclusion clause at all. (The level axis may still say
    # "IS NOT DISTINCT FROM" for a posting that states no level.)
    clean = str(
        job_scope_expr(
            ["product_management"], ["director_plus"], ["management"], ["united_states"],
            [], frozenset(), excluded_domains=[],
        ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "jobs.company" not in clean
    assert "NOT (" not in clean


# --------------------------------------------------------------------------- #
# Intent-statement embedding record
# --------------------------------------------------------------------------- #


def test_intent_embedding_absent_or_malformed_reads_as_none():
    key = settings_store.INTENT_EMBEDDING_KEY
    assert asyncio.run(settings_store.get_intent_embedding(FakeSession(key))) is None
    # Cleared record ({}), blank statement, and a non-numeric vector all read
    # as absent rather than raising.
    for value in (
        {},
        {"statement": "  ", "model": "all-MiniLM-L6-v2", "vector": [0.1]},
        {"statement": "ai leadership", "model": "all-MiniLM-L6-v2", "vector": ["x"]},
        {"statement": "ai leadership", "model": "all-MiniLM-L6-v2", "vector": []},
    ):
        session = FakeSession(key, _Row(value))
        assert asyncio.run(settings_store.get_intent_embedding(session)) is None


def test_intent_embedding_from_a_different_model_reads_as_none():
    # A statement vector from an old model lives in a different space than
    # jobs.embedding — serving it would rank against noise. Stale = absent.
    session = FakeSession(
        settings_store.INTENT_EMBEDDING_KEY,
        _Row({"statement": "ai leadership", "model": "some-old-model", "vector": [0.1, 0.2]}),
    )
    assert asyncio.run(settings_store.get_intent_embedding(session)) is None


def test_intent_embedding_from_a_different_tier_reads_as_none():
    """fp32 and int8 are the same model in *nearly* the same space. After a
    tier switch the corpus is re-embedded, so a statement
    vector from the old artifact would rank against a seam — stale = absent,
    the same contract a model change already had."""
    from tracker.config import get_settings

    other = "int8" if provision.resolve_tier() == "fp32" else "fp32"
    session = FakeSession(
        settings_store.INTENT_EMBEDDING_KEY,
        _Row({
            "statement": "ai leadership",
            "model": get_settings().embedding_model,
            "tier": other,
            "vector": [0.1, 0.2],
        }),
    )
    assert asyncio.run(settings_store.get_intent_embedding(session)) is None


def test_intent_embedding_without_a_tier_still_reads(monkeypatch):
    """Older records carry no tier and were produced at whatever
    the machine auto-detected. Gating them out would silently drop direction
    ranking for every existing user at upgrade — a missing tier matches."""
    from tracker.config import get_settings

    session = FakeSession(
        settings_store.INTENT_EMBEDDING_KEY,
        _Row({
            "statement": "ai leadership",
            "model": get_settings().embedding_model,
            "vector": [0.1, 0.2],
        }),
    )
    assert asyncio.run(settings_store.get_intent_embedding(session)) is not None


def test_intent_embedding_round_trip_and_empty_statement_clears():
    from tracker.config import get_settings

    model = get_settings().embedding_model
    tier = provision.resolve_tier()
    session = FakeSession(settings_store.INTENT_EMBEDDING_KEY)
    asyncio.run(settings_store.set_intent_embedding(session, " ai leadership ", [0.5, 0.5]))
    (stmt,) = session.executed
    value = stmt.compile().params["value"]
    assert value == {
        "statement": "ai leadership", "model": model, "tier": tier, "vector": [0.5, 0.5],
    }

    good = FakeSession(settings_store.INTENT_EMBEDDING_KEY, _Row(value))
    assert asyncio.run(settings_store.get_intent_embedding(good)) == {
        "statement": "ai leadership", "model": model, "vector": [0.5, 0.5],
    }

    # Removing the statement clears the record (stored as {}, reads as None).
    clearing = FakeSession(settings_store.INTENT_EMBEDDING_KEY)
    asyncio.run(settings_store.set_intent_embedding(clearing, "", []))
    (clear_stmt,) = clearing.executed
    assert clear_stmt.compile().params["value"] == {}


# --------------------------------------------------------------------------- #
# The worlds axis stores what was HIDDEN
# --------------------------------------------------------------------------- #


class _StoredSetting:
    """One `app_settings` row, for the reader."""

    def __init__(self, value):
        self.value = value


class _ReadSession:
    def __init__(self, value):
        self._row = None if value is None else _StoredSetting(value)

    async def get(self, _model, _key):
        return self._row


def test_a_world_added_later_is_on_for_everyone_who_never_hid_anything(monkeypatch):
    """The whole reason the axis stores the complement. Under an enabled-set, a
    new world is absent from every stored answer and arrives OFF — switched off
    by a choice nobody made, and invisible while it happens."""
    from tracker import settings_store as store

    # A user who hid one world, stored before `worlds_split` existed.
    session = _ReadSession({"hidden": ["advertising"]})
    monkeypatch.setattr(store, "all_domain_slugs", lambda: [*all_domain_slugs(), "worlds_split"])

    enabled = asyncio.run(store.get_enabled_domains(session))
    assert "worlds_split" in enabled, "a world nobody decided about is on"
    assert "advertising" not in enabled, "and their decision is kept"


def test_the_legacy_enabled_set_is_still_read_as_one():
    """Rows written before the migration keep their meaning until it runs."""
    from tracker import settings_store as store

    session = _ReadSession({"slugs": ["ai_ml", "cloud_infra"]})
    assert asyncio.run(store.get_enabled_domains(session)) == {"ai_ml", "cloud_infra"}


def test_an_absent_or_malformed_row_still_means_every_world():
    from tracker import settings_store as store

    for value in (None, {"slugs": "not-a-list"}, {}):
        session = _ReadSession(value)
        assert asyncio.run(store.get_enabled_domains(session)) == set(all_domain_slugs()), value


# --------------------------------------------------------------------------- #
# A subject added later follows the saved intent
# --------------------------------------------------------------------------- #


class _RoundTripSession:
    """Keeps the one row `set_enabled_domains` writes and serves it back."""

    def __init__(self):
        self.value = None

    async def execute(self, stmt):
        self.value = stmt.compile().params["value"]
        return Upserted(stmt)

    async def get(self, _model, _key):
        return None if self.value is None else _StoredSetting(self.value)


def _saved_then_grown(monkeypatch, enabled, excluded):
    from tracker import settings_store as store

    session = _RoundTripSession()
    asyncio.run(store.set_enabled_domains(session, enabled, excluded=excluded))
    monkeypatch.setattr(store, "all_domain_slugs", lambda: [*all_domain_slugs(), "quantum_new"])
    return asyncio.run(store.get_enabled_domains(session))


def test_a_subject_added_later_stays_out_of_interested_only_in(monkeypatch):
    """"Interested in AI" is a short list. A subject nobody named is not in
    it; stored as the complement, it would arrive on and widen the radar."""
    enabled = _saved_then_grown(monkeypatch, ["ai_ml"], excluded=[])
    assert enabled == {"ai_ml"}


def test_interests_beside_a_veto_still_keep_a_later_subject_out(monkeypatch):
    enabled = _saved_then_grown(monkeypatch, ["ai_ml", "cloud_infra"], excluded=["advertising"])
    assert enabled == {"ai_ml", "cloud_infra"}


def test_a_subject_added_later_arrives_under_not_interested_in_only(monkeypatch):
    """Only "not interested in advertising": the worlds set is everything the
    veto leaves, and a later subject nobody said no to belongs in it."""
    everything_else = [slug for slug in all_domain_slugs() if slug != "advertising"]
    enabled = _saved_then_grown(monkeypatch, everything_else, excluded=["advertising"])
    assert "quantum_new" in enabled
    assert "advertising" not in enabled


def test_a_subject_added_later_arrives_when_nothing_was_said(monkeypatch):
    enabled = _saved_then_grown(monkeypatch, all_domain_slugs(), excluded=[])
    assert "quantum_new" in enabled
