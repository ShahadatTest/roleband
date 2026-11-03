"""Contracts for multi-source claim resolution, freshness, and conflict badging."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tracker.plugin_manifest import FACT_RANK_CEILING
from tracker.profiles import sources
from tracker.profiles.resolve import (
    AGING,
    CONFLICT,
    FRESH,
    MISSING,
    OK,
    STALE,
    Claim,
    company_health,
    field_health,
    freshness_of,
    resolve_all,
    resolve_field,
)

NOW = datetime(2026, 7, 14, tzinfo=UTC)
#: A plugin's claims, as it publishes them: the registry ranks them from the
#: manifest, capped at the plugin ceiling.
AGG = "acme.legacy"
RANKS = {AGG: FACT_RANK_CEILING}


def claim(field, value, source, days_ago=0):
    return Claim(
        field=field,
        value=value,
        source=source,
        observed_at=NOW - timedelta(days=days_ago),
    )


class TestTrustOrdering:
    def test_higher_trust_source_wins_over_lower(self):
        r = resolve_field(
            [claim("ticker", "RDDT", "sec_edgar"), claim("ticker", None, AGG)],
            NOW,
        )
        assert r.value == "RDDT"
        assert r.source == "sec_edgar"

    def test_manual_beats_everything_even_when_older(self):
        # The whole point of "fill it in once": a fresh scrape must not silently
        # undo a human correction.
        r = resolve_field(
            [
                claim("ticker", None, AGG, days_ago=0),
                claim("ticker", "FIG", "manual", days_ago=200),
            ],
            NOW,
        )
        assert r.value == "FIG"
        assert r.is_manual is True

    def test_same_source_prefers_more_recent(self):
        r = resolve_field(
            [
                claim("headcount", 100, AGG, days_ago=90),
                claim("headcount", 900, AGG, days_ago=1),
            ],
            NOW,
        )
        assert r.value == 900

    def test_unknown_source_gets_default_low_rank(self):
        r = resolve_field(
            [claim("ticker", "X", "some_new_feed", days_ago=1), claim("ticker", "Y", "blueprint", days_ago=9)],
            NOW,
        )
        assert r.value == "Y"  # an unranked feed sits below every listed source, however recent

    def test_a_plugin_s_claims_read_under_the_name_the_registry_gives_them(self):
        r = resolve_field(
            [claim("ticker", "RDDT", "sec_edgar"), claim("ticker", None, AGG)], NOW, RANKS, {AGG: "Acme pay data"},
        )
        assert [c["source_label"] for c in r.conflicts] == ["Acme pay data"]
        unnamed = resolve_field([claim("ticker", "RDDT", "sec_edgar"), claim("ticker", None, AGG)], NOW)
        assert [c["source_label"] for c in unnamed.conflicts] == [AGG]  # never a name the core made up

    def test_empty_claims_resolve_to_none(self):
        assert resolve_field([], NOW) is None


class TestFreshness:
    def test_recent_claim_is_fresh(self):
        assert freshness_of("headcount", NOW - timedelta(days=5), NOW) == FRESH

    def test_past_half_ttl_is_aging(self):
        # headcount TTL = 120d -> 70d is past half, under full.
        assert freshness_of("headcount", NOW - timedelta(days=70), NOW) == AGING

    def test_past_ttl_is_stale(self):
        assert freshness_of("headcount", NOW - timedelta(days=200), NOW) == STALE

    def test_ttl_is_per_field(self):
        # 200 days is stale for headcount but not for year_founded (10y TTL).
        old = NOW - timedelta(days=200)
        assert freshness_of("headcount", old, NOW) == STALE
        assert freshness_of("year_founded", old, NOW) == FRESH


class TestConflicts:
    def test_disagreeing_sources_raise_a_conflict(self):
        # A filing gives a ticker; another source still says the company is private.
        r = resolve_field(
            [claim("ticker", "RDDT", "sec_edgar"), claim("ticker", None, AGG)],
            NOW,
        )
        assert r.has_conflict
        assert r.conflicts[0]["source"] == AGG

    def test_agreeing_sources_raise_no_conflict(self):
        r = resolve_field(
            [claim("ticker", "GOOG", "sec_edgar"), claim("ticker", "GOOG", AGG)],
            NOW,
        )
        assert not r.has_conflict

    def test_formatting_difference_is_not_a_conflict(self):
        r = resolve_field(
            [claim("hq_city", "San Francisco", "manual"),
             claim("hq_city", " san francisco ", AGG)],
            NOW,
        )
        assert not r.has_conflict

    def test_small_numeric_drift_is_tolerated(self):
        # Headcount estimates always differ a little; that's not a conflict.
        r = resolve_field(
            [claim("headcount", 5000, "manual"), claim("headcount", 5200, AGG)],
            NOW,
        )
        assert not r.has_conflict

    def test_large_numeric_divergence_is_a_conflict(self):
        # A source's headcount orders of magnitude below what the user pinned.
        r = resolve_field(
            [claim("headcount", 2000, "manual"), claim("headcount", 45, AGG)],
            NOW,
        )
        assert r.has_conflict

    def test_missing_value_conflicts_only_on_hard_fields(self):
        hard = resolve_field(
            [claim("is_public", True, "sec_edgar"), claim("is_public", None, AGG)],
            NOW,
        )
        assert hard.has_conflict  # is_public is a hard field
        soft = resolve_field(
            [claim("website", "x.com", AGG), claim("website", None, "blueprint")],
            NOW,
        )
        assert not soft.has_conflict

    def test_conflict_does_not_block_the_value(self):
        r = resolve_field(
            [claim("ticker", "RDDT", "sec_edgar"), claim("ticker", None, AGG)],
            NOW,
        )
        assert r.value == "RDDT"  # still resolves; the badge is advisory


class TestHealthRollup:
    def test_all_good_is_ok(self):
        resolved = resolve_all([claim("ticker", "GOOG", AGG)], NOW)
        assert company_health(resolved, ["ticker"])["status"] == OK

    def test_absent_required_field_is_missing(self):
        h = company_health({}, ["ticker", "headcount"])
        assert h["status"] == MISSING
        assert set(h["missing"]) == {"ticker", "headcount"}

    def test_none_value_counts_as_missing(self):
        resolved = resolve_all([claim("ticker", None, AGG)], NOW)
        assert field_health(resolved.get("ticker")) == MISSING

    def test_stale_field_flags_stale(self):
        resolved = resolve_all([claim("headcount", 100, AGG, days_ago=300)], NOW)
        h = company_health(resolved, ["headcount"])
        assert h["status"] == STALE
        assert h["stale"] == ["headcount"]

    def test_conflict_outranks_stale_in_the_badge(self):
        resolved = resolve_all(
            [
                claim("headcount", 100, AGG, days_ago=300),  # stale
                claim("ticker", "RDDT", "sec_edgar"),
                claim("ticker", None, AGG),                  # conflict
            ],
            NOW,
        )
        h = company_health(resolved, ["headcount", "ticker"])
        assert h["status"] == CONFLICT

    def test_missing_outranks_conflict(self):
        resolved = resolve_all(
            [claim("ticker", "RDDT", "sec_edgar"), claim("ticker", None, AGG)],
            NOW,
        )
        h = company_health(resolved, ["ticker", "equity_vehicle"])
        assert h["status"] == MISSING

    def test_needs_review_lists_everything_actionable(self):
        resolved = resolve_all(
            [
                claim("headcount", 100, AGG, days_ago=300),
                claim("ticker", "RDDT", "sec_edgar"),
                claim("ticker", None, AGG),
            ],
            NOW,
        )
        h = company_health(resolved, ["headcount", "ticker", "equity_vehicle"])
        # missing + conflicted + stale — the manual-enrichment worklist.
        assert set(h["needs_review"]) == {"equity_vehicle", "ticker", "headcount"}


class TestSourceRegistry:
    def test_manual_outranks_every_other_source(self):
        others = [s for k, s in sources.SOURCES.items() if k != "manual"]
        assert all(sources.rank("manual") > s.rank for s in others)

    @pytest.mark.parametrize("key", ["sec_edgar", "dol_lca", "market", "employer"])
    def test_official_sources_outrank_any_plugin(self, key):
        assert sources.rank(key) > FACT_RANK_CEILING

    def test_a_plugin_at_its_ceiling_outranks_our_seed(self):
        assert FACT_RANK_CEILING > sources.rank("blueprint")

    def test_the_core_lists_no_plugin_source(self):
        assert sources.rank(AGG) == sources.DEFAULT_RANK and sources.label(AGG) == AGG


class TestManualAdjudicationClearsTheBadge:
    """A pinned value must end the conflict — otherwise the queue never drains."""

    def test_manual_field_is_ok_even_with_lingering_dissent(self):
        # The user pinned the ticker; another source still says there is none.
        resolved = resolve_all(
            [
                claim("ticker", "RDDT", "manual"),
                claim("ticker", None, AGG),
            ],
            NOW,
        )
        r = resolved["ticker"]
        assert r.is_manual
        assert r.has_conflict          # the dissent is still RECORDED...
        assert field_health(r) == OK   # ...but it is not an open problem.

    def test_company_badge_clears_once_the_human_settles_every_field(self):
        resolved = resolve_all(
            [
                claim("ticker", "RDDT", "manual"),
                claim("ticker", None, AGG),
                claim("is_public", True, "manual"),
                claim("is_public", False, AGG),
                claim("equity_vehicle", "rsu", AGG),
                claim("headcount", 2000, "manual"),
            ],
            NOW,
        )
        h = company_health(resolved, ["is_public", "ticker", "equity_vehicle", "headcount"])
        assert h["status"] == OK
        assert h["needs_review"] == []

    def test_an_unsettled_field_still_holds_the_badge(self):
        resolved = resolve_all(
            [
                claim("ticker", "RDDT", "manual"),      # settled
                claim("is_public", True, "sec_edgar"),  # still disputed
                claim("is_public", False, AGG),
            ],
            NOW,
        )
        h = company_health(resolved, ["is_public", "ticker"])
        assert h["status"] == CONFLICT
        assert h["conflicts"] == ["is_public"]

    def test_manual_value_does_not_go_stale(self):
        # The user set it deliberately; ageing it out would nag them forever.
        resolved = resolve_all([claim("headcount", 2000, "manual", days_ago=900)], NOW)
        assert field_health(resolved["headcount"]) == OK


class TestClearManualColumnSafety:
    """Every resolvable profile field can be cleared."""

    def test_every_profile_field_is_a_nullable_column(self):
        from tracker.db.models import CompanyProfile
        from tracker.profiles.store import PROFILE_FIELDS

        cols = CompanyProfile.__table__.columns
        # The columns are resolved from our sources only, so a value no source of
        # ours states must clear: a NOT NULL column would keep a stale value (an
        # outside source's `is_public`) and read it as ours. Unknown is not "no".
        # The one exception: a profile is created with the name of the company it
        # tracks (ours), so its name is never unknown.
        for f in PROFILE_FIELDS:
            assert f in cols, f"{f} is not a CompanyProfile column"
            assert cols[f].nullable is (f != "display_name"), f"{f} must be clearable"
