"""Scope catalog API exposes joint counts and explicit inventory state."""

import asyncio
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import TextClause

from tests.factories import Upserted
from tracker.api.job_requests import role_discovery_argv
from tracker.api.routers import settings as settings_router
from tracker.api.routers.settings import SettingsPayload, put_settings_ep
from tracker.config import all_location_group_slugs, default_enabled_location_groups
from tracker.db.models import AppSetting, RoleCatalog, TrackedCompany
from tracker.levels.ladder import stage_decoder
from tracker.scope.catalog import build_scope_catalog
from tracker.scope.promotion import PromotionResult
from tracker.supervisor.registry import job
from tracker.taxonomy.domains import all_slugs as all_domain_slugs

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


class _Scalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return list(self.rows)

    def one(self):
        [row] = self.rows
        return row


def _reads_the_catalog(stmt) -> bool:
    return not isinstance(stmt, TextClause) and stmt.column_descriptions[0].get("entity") is RoleCatalog


class FakeSession:
    def __init__(self):
        self.tracked = TrackedCompany(
            slug="acme",
            display="Acme",
            adapter="greenhouse",
            status="active",
            enabled=True,
            visible=True,
            source="catalog",
            role_catalog_status="ready",
        )
        self.catalog = RoleCatalog(
            role_group="software_engineering",
            company="acme",
            count=3,
            # Stored "junior" keys remain readable as Entry: every
            # reader takes its "junior" keys as Entry.
            band_counts={"junior": 2, "staff": 1},
            band_track_counts={
                "junior": {"technical": 2},
                "staff": {"technical": 1},
            },
            scope_cells=[
                # Two junior postings that differ only in their worlds, and one
                # staff posting in two places — enough shape that interning has
                # something to collapse and something to keep apart.
                {
                    "band": "junior",
                    "track": "technical",
                    "locations": ["uk"],
                    "domains": [],
                    "count": 1,
                },
                {
                    "band": "junior",
                    "track": "technical",
                    "locations": ["uk"],
                    "domains": ["ai_ml"],
                    "count": 1,
                },
                {
                    "band": "staff",
                    "track": "technical",
                    "locations": ["silicon_valley", "united_states"],
                    "domains": ["ai_ml"],
                    "count": 1,
                },
            ],
            examples=["Junior Software Engineer", "Staff Software Engineer"],
        )

    settings = {
        "enabled_role_groups": {"slugs": ["software_engineering"]},
        "enabled_seniority_bands": {"slugs": ["staff"]},
        "enabled_role_tracks": {"slugs": ["management", "technical"]},
        "enabled_location_groups": {"slugs": ["silicon_valley", "uk"]},
    }

    async def get(self, model, key):
        assert model is AppSetting
        return AppSetting(key=key, value=self.settings[key]) if key in self.settings else None

    def catalog_rows(self) -> list[RoleCatalog]:
        return [self.catalog]

    def _columns(self, row: RoleCatalog) -> tuple:
        """A row as the catalog read selects it: its JSON columns as text."""
        return (
            row.role_group, row.company, row.count,
            *(json.dumps(value) for value in (
                row.band_counts, row.band_track_counts, row.scope_cells,
                row.domain_counts or {}, row.domain_examples or {},
            )),
        )

    async def execute(self, stmt, params=None):
        # The catalog's version moves with its rows, as `role_catalog`'s does
        # with every write, so a read after a change never reuses the counts.
        if isinstance(stmt, TextClause) and "FROM role_catalog" in str(stmt):
            rows = [self._columns(row) for row in self.catalog_rows()]
            return _Scalars([(len(rows), 1, json.dumps(rows, sort_keys=True))])
        if _reads_the_catalog(stmt):
            return _Scalars([self._columns(row) for row in self.catalog_rows()])
        return await self.answer(stmt, params)

    async def answer(self, stmt, params=None):
        # The four opt-in axes arrive in one read.
        if not isinstance(stmt, TextClause) and "FROM app_settings" in str(stmt):
            return _Scalars(list(self.settings.items()))
        # The decoder contains reference companies only:
        # additional ladders must not expand it.
        if not isinstance(stmt, TextClause) and "company_comp_level" in str(stmt):
            raise AssertionError("the level decoder reads the reference ladders only, never company_comp_level")
        # The known-job location counts come from a raw unnest query; anything
        # else would be the live track-count fallback, which joint inventory
        # must not need.
        if isinstance(stmt, TextClause):
            assert "unnest(location_groups)" in str(stmt)
            return _Scalars([("silicon_valley", 4), ("uk", 7), ("singapore", 2)])
        raise AssertionError("joint inventory should not fall back to live job counts")

    async def scalars(self, stmt):
        entity = stmt.column_descriptions[0].get("entity")
        if entity is TrackedCompany:
            return _Scalars([self.tracked])
        raise AssertionError(f"unexpected select entity: {entity}")


async def _board_count(_session) -> int:
    """The Board count a save reports, stubbed beside the recompute."""
    return 40


def test_level_decoder_is_the_reference_companies_only():
    """The level-band decoder names FAANG, OpenAI and Anthropic, and no other
    company, however many have a reviewed ladder. Additional ladders must not
    expand this table; the fake refuses that read."""
    payload = asyncio.run(build_scope_catalog(FakeSession(), []))
    companies = {company for level in payload["levels"] for company in level["decoder"]}
    assert companies == {"google", "meta", "apple", "amazon", "netflix", "openai", "anthropic"}
    # Reviewed ladders outside the reference set still exist, and stay out.
    assert {"microsoft", "nvidia", "jane-street"} <= set(stage_decoder())
    assert companies.isdisjoint({"microsoft", "nvidia", "jane-street"})
    staff = next(level for level in payload["levels"] if level["slug"] == "staff")
    # Amazon has no Staff rung: the cell is absent, never borrowed from a
    # neighbouring rung.
    assert "amazon" not in staff["decoder"]
    assert staff["decoder"]["google"] == {"company_wide": "L6"}
    senior = next(level for level in payload["levels"] if level["slug"] == "senior")
    assert senior["decoder"]["amazon"] == {"company_wide": "L6"}
    assert senior["decoder"]["google"] == {"company_wide": "L5"}


def test_scope_catalog_returns_all_taxonomy_and_joint_counts():
    payload = asyncio.run(build_scope_catalog(FakeSession(), []))

    assert payload["settings"] == {
        "enabled_role_groups": ["software_engineering"],
        "enabled_seniority_bands": ["staff"],
        "enabled_role_tracks": ["management", "technical"],
        "enabled_location_groups": ["silicon_valley", "uk"],
        # Nothing stored → the worlds axis defaults to every domain.
        "enabled_domain_groups": all_domain_slugs(),
        # Nothing stored → nobody said "not interested in" anything.
        "excluded_domain_groups": [],
        # No answers stored → read off the two flat axes: each saved track,
        # holding the saved families.
        "role_answers": [
            {"track": "management", "roles": ["software_engineering"]},
            {"track": "technical", "roles": ["software_engineering"]},
        ],
        # Nothing stored -> no place excepted.
        "excluded_location_groups": [],
        # Never set -> the default: roles whose level isn't stated are in.
        "include_unstated_level": True,
    }
    # The domains axis is explicit too: every world, saved state, inventory.
    domains = {entry["slug"]: entry for entry in payload["domains"]}
    assert set(domains) == set(all_domain_slugs())
    assert all(entry["selected"] for entry in payload["domains"])
    assert payload["unclassified_domain_count"] == 0
    # The locations axis is explicit: every group, its saved state, and known-job counts.
    locations = {entry["slug"]: entry for entry in payload["locations"]}
    assert set(locations) == set(all_location_group_slugs())
    assert locations["uk"]["selected"] is True and locations["uk"]["count"] == 7
    assert locations["singapore"]["selected"] is False and locations["singapore"]["count"] == 2
    assert locations["silicon_valley"]["default_enabled"] is True
    # Nested-tree shape for the client: three levels, metro -> country ->
    # region. Every country has a region parent; only regions are top-level
    # (and `gulf` nests under `middle_east`, so even that is not flat).
    assert locations["silicon_valley"]["kind"] == "metro"
    assert locations["silicon_valley"]["parent"] == "united_states"
    assert locations["united_states"]["kind"] == "country"
    assert locations["united_states"]["parent"] == "north_america"
    assert locations["uk"]["parent"] == "europe"
    assert locations["europe"]["kind"] == "region"
    assert locations["europe"]["parent"] is None
    assert locations["uae"]["parent"] == "gulf"
    assert locations["gulf"]["parent"] == "middle_east"
    technology = next(c for c in payload["categories"] if c["slug"] == "technology")
    software = next(g for g in technology["groups"] if g["slug"] == "software_engineering")
    # The seeded row's legacy "junior" reads as Entry: never dropped.
    assert software["band_counts"] == {"entry": 2, "staff": 1}
    assert software["total"] == 3
    assert software["joint_complete"] is True
    assert software["band_track_counts"] == {
        "entry": {"technical": 2},
        "staff": {"technical": 1},
    }
    assert payload["joint_counts_ready"] is True
    # The full-market career ladder: every stage first-class.
    assert [level["slug"] for level in payload["levels"]] == [
        "intern", "entry", "mid", "senior", "staff", "principal", "director_plus",
    ]
    # Slugs only: the dashboard names each stage from its catalog.
    assert all("display" not in level for level in payload["levels"])
    assert payload["companies"][0]["role_catalog_status"] == "ready"
    # Track axis: every kind is explicit; counts come from the pre-gate inventory.
    tracks = {t["slug"]: t for t in payload["tracks"]}
    assert set(tracks) == {"management", "product_program", "technical", "business_customer"}
    assert tracks["management"]["selected"] is True and tracks["management"]["count"] == 0
    assert tracks["product_program"]["selected"] is False and tracks["product_program"]["count"] == 0
    assert tracks["technical"]["count"] == 3
    # Each track carries its realistic seniority gate so the wizard can disable
    # the rest (management has no intern/new-grad/mid rung; a business IC tops out
    # at principal; technical spans the full ladder).
    assert tracks["management"]["allowed_bands"] == ["senior", "staff", "principal", "director_plus"]
    assert tracks["business_customer"]["allowed_bands"][0] == "intern"
    assert tracks["business_customer"]["allowed_bands"][-1] == "principal"
    assert tracks["technical"]["allowed_bands"] == [
        "intern", "entry", "mid", "senior", "staff", "principal", "director_plus",
    ]


def test_legacy_catalog_keeps_counts_visible_but_disables_joint_impact():
    class LegacySession(FakeSession):
        def __init__(self):
            super().__init__()
            self.catalog.band_track_counts = {}

        async def answer(self, stmt, params=None):
            if isinstance(stmt, TextClause):
                return await super().answer(stmt, params)
            if "company_comp_level" in str(stmt):
                return _Scalars([])
            return _Scalars([("management", 5), ("technical", 3)])

    payload = asyncio.run(build_scope_catalog(LegacySession(), []))

    assert payload["joint_counts_ready"] is False
    software = next(
        group
        for category in payload["categories"]
        for group in category["groups"]
        if group["slug"] == "software_engineering"
    )
    assert software["total"] == 3
    assert software["band_track_counts"] == {}
    # Its roles have levels and no track split, so the group's joint cannot
    # price an answer that names it.
    assert software["joint_complete"] is False
    assert {track["slug"]: track["count"] for track in payload["tracks"]}["management"] == 5


class _FallbackSession(FakeSession):
    """Answers the live-job fallback the catalog uses when joint counts are
    not ready, so a test can observe which path it took."""

    async def answer(self, stmt, params=None):
        if isinstance(stmt, TextClause):
            return await super().answer(stmt, params)
        if "company_comp_level" in str(stmt):
            return _Scalars([])
        return _Scalars([("technical", 3)])


def test_a_scanned_catalog_reset_to_pending_holds_joint_impact_until_refreshed():
    """A followed company whose catalog WAS scanned and is due a rescan: its
    counts are stale, so the joint impact waits for the refresh."""
    from datetime import UTC, datetime

    session = _FallbackSession()
    session.tracked.role_catalog_status = "pending"
    session.tracked.role_catalog_scanned_at = datetime(2026, 9, 1, tzinfo=UTC)

    payload = asyncio.run(build_scope_catalog(session, []))

    assert payload["joint_counts_ready"] is False
    software = next(
        group
        for category in payload["categories"]
        for group in category["groups"]
        if group["slug"] == "software_engineering"
    )
    assert software["total"] == 0


def test_a_followed_company_never_scanned_does_not_hold_everyones_counts():
    """A Workday company is scanned only by a sync the user starts; until then it has no rows to be incomplete
    about, and must not blank the counts for every other company."""
    session = FakeSession()
    session.tracked.role_catalog_status = "pending"
    session.tracked.role_catalog_scanned_at = None

    payload = asyncio.run(build_scope_catalog(session, []))

    assert payload["joint_counts_ready"] is True
    [company] = payload["companies"]
    assert (company["role_catalog_status"], company["role_catalog_scanned_at"]) == ("pending", None)


def test_a_company_nobody_follows_never_holds_the_counts():
    """Unfollowed companies with capped (`partial`) catalogs must not hide the
    joint counts from a user who follows none of them."""
    from datetime import UTC, datetime

    session = FakeSession()
    session.tracked.enabled = False
    session.tracked.role_catalog_status = "partial"
    session.tracked.role_catalog_scanned_at = datetime(2026, 9, 1, tzinfo=UTC)

    assert asyncio.run(build_scope_catalog(session, []))["joint_counts_ready"] is True

    session.tracked.enabled = True  # the same catalog, followed, still holds them
    assert asyncio.run(build_scope_catalog(_with(session), []))["joint_counts_ready"] is False


def test_every_count_is_over_the_companies_the_user_follows():
    """The walk's 100% is the roles the radar can show:
    a company switched off in Settings adds nothing to the joint, the level
    counts or the family counts, though its catalog is still stored."""
    session = FakeSession()
    followed = asyncio.run(build_scope_catalog(session, []))
    assert followed["scope_cells"]["cells"]
    assert sum(level["count"] for level in followed["levels"]) == 3

    session.tracked.enabled = False
    unfollowed = asyncio.run(build_scope_catalog(_with(session), []))
    assert unfollowed["scope_cells"]["cells"] == []
    assert sum(level["count"] for level in unfollowed["levels"]) == 0
    assert all(
        group["total"] == 0
        for category in unfollowed["categories"]
        for group in category["groups"]
    )


def _with(session: FakeSession) -> FakeSession:
    fallback = _FallbackSession()
    fallback.tracked, fallback.catalog = session.tracked, session.catalog
    return fallback


def test_settings_payload_requires_both_scope_axes():
    parsed = SettingsPayload(
        enabled_role_groups=["software_engineering"],
        enabled_seniority_bands=["staff"],
    )
    assert parsed.enabled_seniority_bands == ["staff"]


def test_scope_refresh_uses_catalog_only_discovery_command():
    args = [*job("role_discovery").command, *role_discovery_argv(["google", "openai"], max_list=600)]

    assert args[1:4] == ["-m", "tracker.supervisor.entries", "role_discovery"]
    assert "tracker.daily" not in args and "scan" not in args
    assert args[args.index("--company") + 1 : args.index("--max-list")] == ["google", "openai"]
    assert args[args.index("--max-list") + 1] == "600"
    assert "--location" not in args


def test_scope_refresh_passes_the_answered_places_to_discovery():
    args = role_discovery_argv(None, max_list=600, locations=["uk", "city_2643743"])
    assert args[args.index("--location") + 1:] == ["uk", "city_2643743"]


class _PutSession:
    def __init__(self):
        self.executed = []
        self.committed = False

    async def execute(self, stmt, params=None):
        self.executed.append(stmt)
        return Upserted(stmt)

    async def get(self, model, key):
        assert model is AppSetting
        return None  # no stored row → axis defaults

    async def commit(self):
        self.committed = True


def test_saving_scope_recomputes_existing_job_visibility(monkeypatch):
    calls = []

    async def fake_apply(session, roles, bands, tracks, locations, domains, *, excluded_domains, answers, excluded_locations, include_unstated_level):
        calls.append((session, roles, bands, tracks, locations, domains))
        return 17

    session = _PutSession()
    monkeypatch.setattr(settings_router, "apply_saved_scope_to_jobs", fake_apply)
    monkeypatch.setattr(settings_router, "_board_count", _board_count)

    response = asyncio.run(
        put_settings_ep(
            SettingsPayload(
                enabled_role_groups=["software_engineering"],
                enabled_seniority_bands=["director_plus"],
                enabled_role_tracks=["technical"],
                enabled_location_groups=["uk"],
            ),
            session,
        )
    )

    assert response == {
        "enabled_role_groups": ["software_engineering"],
        "enabled_seniority_bands": ["director_plus"],
        "enabled_role_tracks": ["technical"],
        "enabled_location_groups": ["uk"],
        # Omitted from the payload → axis reads back its default (all worlds).
        "enabled_domain_groups": all_domain_slugs(),
        "excluded_domain_groups": [],
        "role_answers": [{"track": "technical", "roles": ["software_engineering"]}],
        "excluded_location_groups": [],
        "include_unstated_level": True,
        "in_scope_changed": 17,
        # What the Board holds after the save, beside what changed.
        "on_board": 40,
        # Promotion is stubbed here: nothing added, nothing waiting.
        "promoted": 0,
        "promotion_pending": False,
    }
    # Scope recompute received the track, location, and domain axes too.
    assert calls == [
        (
            session, ["software_engineering"], ["director_plus"], ["technical"], ["uk"],
            sorted(all_domain_slugs()),
        )
    ]
    assert session.committed is True


def test_saving_scope_without_locations_leaves_the_axis_untouched(monkeypatch):
    calls = []

    async def fake_apply(session, roles, bands, tracks, locations, domains, *, excluded_domains, answers, excluded_locations, include_unstated_level):
        calls.append(locations)
        return 0

    session = _PutSession()
    monkeypatch.setattr(settings_router, "apply_saved_scope_to_jobs", fake_apply)
    monkeypatch.setattr(settings_router, "_board_count", _board_count)

    response = asyncio.run(
        put_settings_ep(
            SettingsPayload(
                enabled_role_groups=["software_engineering"],
                enabled_seniority_bands=["staff"],
                enabled_role_tracks=["technical"],
            ),
            session,
        )
    )

    # Older clients that omit the axis keep the stored value (defaults here).
    assert response["enabled_location_groups"] == default_enabled_location_groups()
    assert calls == [sorted(default_enabled_location_groups())]


# --------------------------------------------------------------------------- #
# Stage markers on the raw save. The stage dimmer is the only seniority control
# the product has, so a stored band set that contradicts the persona is
# corruption, not a choice: `["staff"]` against a principal->director_plus
# persona would push every principal role collected out of scope.
# --------------------------------------------------------------------------- #

_PERSONA = {
    "experience_stage": "staff",
    "target_stage": "staff",
    "crafts": ["management"],
    "disciplines": ["engineering_management"],
    "locations": ["north_america"],
    "domains": ["ai_ml"],
    "intent_statement": "leadership in AI",
}


class _PersonaPutSession(_PutSession):
    """A `_PutSession` that already holds a persona profile."""

    def __init__(self, persona=None):
        super().__init__()
        self.persona = persona

    async def get(self, model, key):
        assert model is AppSetting
        if key == "persona_profile" and self.persona is not None:
            return AppSetting(key=key, value=self.persona)
        return None


def _persona_put(session, monkeypatch, **payload_fields):
    written = []

    async def fake_apply(session, roles, bands, tracks, locations, domains, *, excluded_domains, answers, excluded_locations, include_unstated_level):
        return 0

    async def fake_set_persona(session, profile):
        written.append(profile)
        return profile

    monkeypatch.setattr(settings_router, "apply_saved_scope_to_jobs", fake_apply)
    monkeypatch.setattr(settings_router, "_board_count", _board_count)
    # Patch the router where the handler looks up the store function.
    monkeypatch.setattr(settings_router, "set_persona_profile", fake_set_persona)
    response = asyncio.run(
        put_settings_ep(
            SettingsPayload(
                enabled_role_groups=["software_engineering"],
                enabled_role_tracks=["technical"],
                enabled_location_groups=["uk"],
                **payload_fields,
            ),
            session,
        )
    )
    return response, written


def test_stages_on_a_raw_save_derive_the_seniority_axis(monkeypatch):
    session = _PersonaPutSession(_PERSONA)

    response, written = _persona_put(
        session,
        monkeypatch,
        # The contradiction above. The span wins: the axis is
        # not an independent claim once the markers are named.
        enabled_seniority_bands=["staff"],
        experience_stage="principal",
        target_stage="director_plus",
    )

    assert response["enabled_seniority_bands"] == ["principal", "director_plus"]
    # The markers move on the persona, which holds only the levels and the aim
    # a stored scope copy is dropped on write.
    assert written == [{
        "experience_stage": "principal", "target_stage": "director_plus",
        "intent_statement": _PERSONA["intent_statement"],
    }]


def test_a_raw_save_without_stages_leaves_the_persona_alone(monkeypatch):
    session = _PersonaPutSession(_PERSONA)

    response, written = _persona_put(
        session, monkeypatch, enabled_seniority_bands=["senior", "staff"]
    )

    # No markers sent -> the axis is the client's raw claim.
    assert response["enabled_seniority_bands"] == ["senior", "staff"]
    assert written == []


def test_a_raw_save_refuses_half_a_stage_pair(monkeypatch):
    for half in ({"experience_stage": "principal"}, {"target_stage": "principal"}):
        with pytest.raises(HTTPException) as raised:
            _persona_put(
                _PersonaPutSession(_PERSONA),
                monkeypatch,
                enabled_seniority_bands=["staff"],
                **half,
            )
        assert raised.value.status_code == 422


def test_a_raw_save_refuses_an_unknown_stage(monkeypatch):
    with pytest.raises(HTTPException) as raised:
        _persona_put(
            _PersonaPutSession(_PERSONA),
            monkeypatch,
            enabled_seniority_bands=["staff"],
            experience_stage="staff",
            target_stage="vice_regent",
        )

    assert raised.value.status_code == 422
    assert "vice_regent" in str(raised.value.detail)


# --------------------------------------------------------------------------- #
# The scope joint on the wire. Every other count in this payload is
# a marginal; this is the only shape a client can apply the whole gate to, so
# what it must prove is that interning is lossless and that "ready" answers
# staleness rather than coverage.
# --------------------------------------------------------------------------- #


def _decode(cells: dict) -> list[dict]:
    """Undo the interning, the way a client must."""
    return [
        {
            "role": cells["roles"][role],
            "band": cells["bands"][band],
            "track": cells["tracks"][track],
            "locations": cells["location_sets"][location],
            "domains": cells["domain_sets"][domain],
            "count": count,
        }
        for role, band, track, location, domain, count in cells["cells"]
    ]


def test_the_scope_joint_survives_interning_unchanged():
    session = FakeSession()
    cells = asyncio.run(build_scope_catalog(session, []))["scope_cells"]

    assert cells["ready"] is True
    assert _decode(cells) == [
        {
            "role": "software_engineering",
            "band": band,
            "track": track,
            "locations": locations,
            "domains": domains,
            "count": count,
        }
        for band, track, locations, domains, count in sorted(
            (
                # The seeded row's legacy "junior" cells, read as Entry.
                ("entry", "technical", ["uk"], [], 1),
                ("entry", "technical", ["uk"], ["ai_ml"], 1),
                ("staff", "technical", ["silicon_valley", "united_states"], ["ai_ml"], 1),
            ),
            key=lambda row: (
                cells["bands"].index(row[0]),
                cells["tracks"].index(row[1]),
                cells["location_sets"].index(row[2]),
                cells["domain_sets"].index(row[3]),
            ),
        )
    ]
    # The cells account for every posting the marginals do.
    assert sum(row["count"] for row in _decode(cells)) == session.catalog.count
    # A dictionary entry exists once, however many cells point at it.
    assert cells["location_sets"].count(["uk"]) == 1
    # The empty domain set is a real entry, not an omission: it is the
    # fail-open case, and a client that cannot see it re-implements the gate
    # wrongly.
    assert [] in cells["domain_sets"]


def test_the_joint_reports_which_companies_it_covers():
    session = FakeSession()
    cells = asyncio.run(build_scope_catalog(session, []))["scope_cells"]

    assert cells["companies"] == ["acme"]
    assert cells["missing_companies"] == []
    assert cells["stale_companies"] == []


def test_a_catalog_row_written_before_the_joint_reads_not_ready():
    """Staleness, not coverage: postings we hold but cannot place."""
    session = FakeSession()
    session.catalog.scope_cells = []
    cells = asyncio.run(build_scope_catalog(session, []))["scope_cells"]

    assert cells["ready"] is False
    assert cells["cells"] == []
    # Named, so the wait has something to point at rather than a bare false.
    assert cells["stale_companies"] == ["acme"]
    assert cells["companies"] == []


def test_an_empty_company_does_not_make_the_joint_stale():
    """A board with no postings has nothing to place, so it is not a gap."""
    session = FakeSession()
    session.catalog.scope_cells = []
    session.catalog.band_counts = {}
    session.catalog.count = 0
    cells = asyncio.run(build_scope_catalog(session, []))["scope_cells"]

    assert cells["ready"] is False  # no cells anywhere is still nothing to show
    assert cells["cells"] == []
    assert cells["stale_companies"] == []


class _OneStaleOneUnfollowed(FakeSession):
    """Acme is counted; Stripe is followed but its catalog predates the joint;
    Initech is tracked but not followed and never scanned."""

    def __init__(self):
        super().__init__()
        self.stripe = TrackedCompany(
            slug="stripe", display="Stripe", adapter="greenhouse", status="active", enabled=True,
            visible=True, source="catalog", role_catalog_status="ready",
        )
        self.initech = TrackedCompany(
            slug="initech", display="Initech", adapter="greenhouse", status="active", enabled=False,
            visible=True, source="catalog", role_catalog_status="pending",
        )
        self.stale = RoleCatalog(
            role_group="software_engineering", company="stripe", count=4,
            band_counts={"staff": 4}, band_track_counts={"staff": {"technical": 4}}, scope_cells=[],
            examples=[],
        )

    async def answer(self, stmt, params=None):
        # A stale company still sends the marginal track counts to the live
        # jobs query; nothing here depends on it.
        if not isinstance(stmt, TextClause) and "FROM jobs" in str(stmt):
            return _Scalars([])
        return await super().answer(stmt, params)

    def catalog_rows(self) -> list[RoleCatalog]:
        return [self.catalog, self.stale]

    async def scalars(self, stmt):
        entity = stmt.column_descriptions[0].get("entity")
        if entity is TrackedCompany:
            return _Scalars([self.tracked, self.stripe, self.initech])
        raise AssertionError(f"unexpected select entity: {entity}")


def test_one_stale_company_is_named_and_left_out_instead_of_blanking_every_count():
    """One followed company whose catalog predates the joint must not set
    ready=false for everyone and leave the walk with no counts at all. Its
    cells are left out anyway, so the joint of the others is exact; the screen
    names the one that is not counted."""
    cells = asyncio.run(build_scope_catalog(_OneStaleOneUnfollowed(), []))["scope_cells"]

    assert cells["ready"] is True
    assert cells["companies"] == ["acme"]
    assert cells["stale_companies"] == ["stripe"]
    assert sum(row["count"] for row in _decode(cells)) == 3  # Acme's three; none of Stripe's


def test_missing_companies_are_followed_companies_only():
    """`missing_companies` answers "which of MY companies are not counted".
    Listing every tracked row makes it hundreds long, mostly unfollowed, and
    useless to name on screen."""
    cells = asyncio.run(build_scope_catalog(_OneStaleOneUnfollowed(), []))["scope_cells"]
    assert cells["missing_companies"] == []


def test_a_category_added_since_the_last_save_is_marked_new(monkeypatch):
    """The user saved their locations before `singapore` existed: it
    arrives OFF and marked new; every category they were shown is not new, and
    a save that records `seen` clears the mark."""
    import json as _json

    from tracker.taxonomy import slug_history

    real = _json.loads(slug_history._PATH.read_text())["axes"]
    real["locations"]["baseline"] = [s for s in real["locations"]["baseline"] if s != "singapore"]
    real["locations"]["added"] = {"singapore": "2026-10-01"}
    monkeypatch.setattr(slug_history, "_axes", lambda: real)

    payload = asyncio.run(build_scope_catalog(FakeSession(), []))
    locations = {entry["slug"]: entry for entry in payload["locations"]}
    assert (locations["singapore"]["new"], locations["singapore"]["selected"]) == (True, False)
    assert [slug for slug, entry in locations.items() if entry["new"]] == ["singapore"]
    # The other axes are untouched but for the Intern rung, added since.
    assert [level["slug"] for level in payload["levels"] if level["new"]] == ["intern"]

    session = FakeSession()
    session.settings = {
        **session.settings,
        "enabled_location_groups": {"slugs": ["silicon_valley", "uk"], "seen": list(locations)},
    }
    after_save = asyncio.run(build_scope_catalog(session, []))
    assert not any(entry["new"] for entry in after_save["locations"])


# --------------------------------------------------------------------------- #
# Cities the draft names before saving. The stored
# cells keep every city a posting names and the read keeps only the named
# ones, so naming a city in the read prices it at once.
# --------------------------------------------------------------------------- #

LONDON = "city_2643743"


class _LondonSession(FakeSession):
    """Acme's one staff posting in London also names the city."""

    def __init__(self):
        super().__init__()
        self.catalog.scope_cells = [
            {"band": "staff", "track": "technical", "locations": ["uk", LONDON], "domains": [], "count": 2},
        ]
        self.catalog.band_counts = {"staff": 2}
        self.catalog.band_track_counts = {"staff": {"technical": 2}}
        self.catalog.count = 2


def test_an_unsaved_city_named_in_the_read_is_priced_at_once():
    unnamed = asyncio.run(build_scope_catalog(_LondonSession(), []))
    assert LONDON not in unnamed["scope_cells"]["cities"]
    assert all(LONDON not in row["locations"] for row in _decode(unnamed["scope_cells"]))

    named = asyncio.run(build_scope_catalog(_LondonSession(), [], extra_cities=[LONDON]))
    cells = named["scope_cells"]
    assert LONDON in cells["cities"]
    assert [row["locations"] for row in _decode(cells)] == [["uk", LONDON]]
    assert LONDON in {location["slug"] for location in named["locations"]}, "the tree lists it too"
    # Naming a city prices it; it saves nothing.
    assert LONDON not in named["settings"]["enabled_location_groups"]


def test_only_known_cities_are_read_from_the_request():
    catalog = asyncio.run(build_scope_catalog(
        _LondonSession(), [], extra_cities=["uk", "city_999999999", "not a place"],
    ))
    assert catalog["scope_cells"]["cities"] == []
    assert [row["locations"] for row in _decode(catalog["scope_cells"])] == [["uk"]]
