"""Unit tests for the base/bonus/equity heuristic and stock-trajectory aggregation."""

from __future__ import annotations

import pytest

from tracker.analytics.comp_split import (
    BONUS_PCT,
    PARENT_TICKERS_OUTSIDE_ATLAS,
    equity_pct,
    is_public,
    parent_ticker,
    split_tc,
    ticker_for,
)
from tracker.analytics.comp_stats import build_comp_trajectory
from tracker.levels.identity import IDENTITIES
from tracker.schema import LevelBand


class TestSplitTc:
    def test_components_sum_back_to_total_exactly(self):
        for tc in (298_053, 479_251, 900_001, 1_234_567):
            parts = split_tc(tc, "google", LevelBand.STAFF)
            assert parts["base"] + parts["bonus"] + parts["equity"] == tc

    def test_bonus_is_flat_share_of_tc(self):
        parts = split_tc(1_000_000, "google", LevelBand.SENIOR)
        assert parts["bonus"] == round(1_000_000 * BONUS_PCT)

    def test_equity_share_rises_with_seniority(self):
        tc = 1_000_000
        eq = {
            band: split_tc(tc, "google", band)["equity"]
            for band in (
                LevelBand.SENIOR,
                LevelBand.STAFF,
                LevelBand.PRINCIPAL,
                LevelBand.DIRECTOR_PLUS,
            )
        }
        assert (
            eq[LevelBand.SENIOR]
            < eq[LevelBand.STAFF]
            < eq[LevelBand.PRINCIPAL]
            < eq[LevelBand.DIRECTOR_PLUS]
        )

    def test_cash_heavy_company_has_thinner_equity(self):
        # Netflix pays mostly cash: its equity slice must be below a peer's.
        nflx = split_tc(1_000_000, "netflix", LevelBand.STAFF)["equity"]
        goog = split_tc(1_000_000, "google", LevelBand.STAFF)["equity"]
        assert nflx < goog

    def test_equity_heavy_company_has_fatter_equity(self):
        # The company multiplier increases equity over the generic share;
        # the clamp must still bound director_plus at the equity cap.
        assert equity_pct("openai", LevelBand.STAFF) == pytest.approx(0.63)
        assert equity_pct("openai", LevelBand.DIRECTOR_PLUS) == pytest.approx(0.80)
        oai = split_tc(1_000_000, "openai", LevelBand.STAFF)["equity"]
        goog = split_tc(1_000_000, "google", LevelBand.STAFF)["equity"]
        assert oai > goog

    def test_equity_pct_is_clamped(self):
        assert 0.0 <= equity_pct("google", LevelBand.DIRECTOR_PLUS) <= 0.80
        assert 0.0 <= equity_pct("netflix", LevelBand.SENIOR) <= 0.80


class TestPublicRegistry:
    def test_known_public_company_has_ticker(self):
        assert is_public("google")
        assert ticker_for("google") == "GOOGL"

    def test_private_company_has_no_ticker(self):
        assert not is_public("openai")
        assert ticker_for("openai") is None

    def test_twitch_equity_tracks_parent_amazon(self):
        assert ticker_for("twitch") == "AMZN"

    def test_a_renamed_ticker_is_read_from_the_atlas(self):
        # The ticker is XYZ.
        assert ticker_for("block") == "XYZ"

    def test_an_acquired_company_tracks_its_buyer(self):
        # Grants use the parent's IBM stock.
        assert ticker_for("confluent") == "IBM"
        assert IDENTITIES["confluent"].listed is False

    def test_a_company_outside_the_atlas_reads_the_fallback_table(self):
        assert "linkedin" not in IDENTITIES
        assert ticker_for("linkedin") == "MSFT"


class TestBuildCompTrajectory:
    def _rows(self):
        # (company, level_band, family, comp_median)
        return [
            ("google", "staff", "swe", 644_000),
            ("google", "senior", "swe", 408_000),
            ("netflix", "staff", "swe", 700_000),
            ("openai", "staff", "ml_ai_research", 1_100_000),  # private
            ("apple", "senior", "swe", None),  # null comp -> skipped
            ("apple", "bogus_band", "swe", 349_000),  # undecodable band -> skipped
        ]

    def test_partitions_public_and_private(self):
        out = build_comp_trajectory(self._rows())
        pub = {e["company"] for e in out["public"]}
        priv = {e["company"] for e in out["private"]}
        assert pub == {"google", "netflix"}
        assert priv == {"openai"}

    def test_public_entries_carry_ticker(self):
        out = build_comp_trajectory(self._rows())
        goog = next(e for e in out["public"] if e["company"] == "google")
        assert goog["ticker"] == "GOOGL"
        assert goog["count"] == 2

    def test_package_reconstructs_median_tc(self):
        out = build_comp_trajectory(self._rows())
        for e in out["public"] + out["private"]:
            assert e["base"] + e["bonus"] + e["equity"] == e["median_tc"]

    def test_overall_blends_public_only(self):
        out = build_comp_trajectory(self._rows())
        # Overall count is the public postings (2 google + 1 netflix), excluding
        # the private openai role and the two skipped apple rows.
        assert out["overall"]["count"] == 3

    def test_null_and_bad_band_rows_are_skipped(self):
        out = build_comp_trajectory(self._rows())
        assert all(e["company"] != "apple" for e in out["public"] + out["private"])

    def test_empty_when_no_public_roles(self):
        out = build_comp_trajectory([("openai", "staff", "swe", 900_000)])
        assert out["overall"] is None
        assert out["public"] == []
        assert len(out["private"]) == 1

    def test_assumptions_exposed(self):
        out = build_comp_trajectory(self._rows())
        assert out["assumptions"]["bonus_pct"] == BONUS_PCT
        assert "staff" in out["assumptions"]["equity_by_band"]


class TestObservedSplitOverridesHeuristic:
    """The comp path must prefer REAL per-level splits over the heuristic."""

    def _observed(self):
        # Netflix as it actually is: 100% base, zero stock (cash election).
        return {
            ("netflix", "staff"): {"base_pct": 1.0, "stock_pct": 0.0, "bonus_pct": 0.0},
            ("google", "principal"): {
                "base_pct": 0.3476, "stock_pct": 0.5502, "bonus_pct": 0.1022,
            },
        }

    def test_observed_split_is_used_when_available(self):
        from tracker.analytics.comp_split import split_tc_observed

        p = split_tc_observed(1_000_000, "google", LevelBand.PRINCIPAL, self._observed())
        assert p["source"] == "measured"
        assert p["equity"] == 550_200  # 55.02%, the measured share
        assert p["base"] + p["bonus"] + p["equity"] == 1_000_000

    def test_falls_back_to_heuristic_when_no_observation(self):
        from tracker.analytics.comp_split import split_tc_observed

        p = split_tc_observed(1_000_000, "stripe", LevelBand.STAFF, self._observed())
        assert p["source"] == "heuristic"
        assert p["base"] + p["bonus"] + p["equity"] == 1_000_000

    def test_zero_equity_company_is_honoured_not_overridden_by_the_guess(self):
        from tracker.analytics.comp_split import split_tc, split_tc_observed

        # The heuristic invents an equity slice for Netflix...
        guessed = split_tc(1_000_000, "netflix", LevelBand.STAFF)
        assert guessed["equity"] > 0
        # ...but the observed split says zero, and the observed split must win.
        real = split_tc_observed(1_000_000, "netflix", LevelBand.STAFF, self._observed())
        assert real["equity"] == 0
        assert real["base"] == 1_000_000
        assert real["source"] == "measured"

    def test_trajectory_uses_observed_and_reports_its_source(self):
        rows = [("google", "principal", "swe", 1_000_000)]
        out = build_comp_trajectory(rows, observed=self._observed())
        goog = next(e for e in out["public"] if e["company"] == "google")
        assert goog["split_source"] == "measured"
        assert goog["equity_pct"] == pytest.approx(0.5502, abs=1e-3)

    def test_trajectory_flags_a_heuristic_group_as_estimated(self):
        rows = [("stripe", "staff", "swe", 900_000)]
        out = build_comp_trajectory(rows, observed=self._observed())
        entry = (out["public"] + out["private"])[0]
        assert entry["split_source"] == "heuristic"

    def test_trajectory_marks_a_mixed_group(self):
        rows = [
            ("google", "principal", "swe", 900_000),   # observed
            ("google", "senior", "swe", 400_000),      # not in observed -> heuristic
        ]
        out = build_comp_trajectory(rows, observed=self._observed())
        goog = next(e for e in out["public"] if e["company"] == "google")
        assert goog["split_source"] == "mixed"

    def test_under_a_plugin_only_its_own_splits_are_blended(self):
        """The heuristic is our data. While a plugin answers pay, a
        posting its rows do not split is left out, and a company with none is
        absent, never split by ours."""
        from tracker.analytics.comp_split import split_tc_observed

        assert split_tc_observed(1_000_000, "stripe", LevelBand.STAFF, self._observed(), heuristic=False) is None
        rows = [
            ("google", "principal", "swe", 900_000),   # the plugin splits it
            ("google", "senior", "swe", 400_000),      # it does not: left out
            ("stripe", "staff", "swe", 900_000),       # no split at all: absent
        ]
        out = build_comp_trajectory(rows, observed=self._observed(), heuristic=False)
        companies = {e["company"]: e for e in out["public"] + out["private"]}
        assert set(companies) == {"google"}
        assert (companies["google"]["split_source"], companies["google"]["count"]) == ("measured", 1)
        assert companies["google"]["median_tc"] == 900_000

    def test_cash_election_company_does_not_move_with_the_stock(self):
        # A cash-only split must remain flat under every stock scenario.
        rows = [("netflix", "staff", "swe", 756_250)]
        out = build_comp_trajectory(rows, observed=self._observed())
        nflx = next(e for e in out["public"] if e["company"] == "netflix")
        assert nflx["equity"] == 0
        assert nflx["equity_pct"] == 0.0
        # TC(d) = base + bonus + equity*(1+d) -> invariant in d when equity == 0.
        for d in (-0.5, 0.0, 2.0):
            projected = nflx["base"] + nflx["bonus"] + nflx["equity"] * (1 + d)
            assert projected == nflx["median_tc"]


class TestProfileIdentityOverridesHardcodedTable:
    def test_resolved_profile_makes_a_newly_listed_company_public(self):
        # The atlas says databricks is not listed; a resolved profile that says
        # it is (a human pin) must win.
        assert not is_public("databricks")
        rows = [("databricks", "staff", "swe", 650_000)]
        out = build_comp_trajectory(
            rows,
            profiles={"databricks": {"is_public": True, "ticker": "DBX2", "equity_vehicle": "rsu"}},
        )
        assert [e["company"] for e in out["public"]] == ["databricks"]
        assert out["public"][0]["ticker"] == "DBX2"

    def test_profile_can_mark_a_company_private_again(self):
        rows = [("google", "staff", "swe", 650_000)]
        out = build_comp_trajectory(
            rows, profiles={"google": {"is_public": False, "ticker": None, "equity_vehicle": None}}
        )
        assert [e["company"] for e in out["private"]] == ["google"]

    def test_equity_vehicle_is_surfaced_for_the_ui(self):
        rows = [("netflix", "staff", "swe", 756_250)]
        out = build_comp_trajectory(
            rows,
            profiles={"netflix": {"is_public": True, "ticker": "NFLX", "equity_vehicle": "cash_election"}},
        )
        assert out["public"][0]["equity_vehicle"] == "cash_election"

    def test_falls_back_to_hardcoded_table_without_profiles(self):
        rows = [("google", "staff", "swe", 650_000)]
        out = build_comp_trajectory(rows)
        assert [e["company"] for e in out["public"]] == ["google"]


class TestSubsidiaryTracksItsListedParent:
    """A subsidiary is not listed, yet its grants are its parent's stock."""

    def test_a_subsidiary_whose_own_profile_says_private_reprices_with_its_parent(self):
        # A subsidiary profile can be unlisted with an inferred options instrument.
        rows = [("google-deepmind", "staff", "ml_ai_research", 772_000), ("linkedin", "staff", "pm", 500_000)]
        out = build_comp_trajectory(
            rows,
            profiles={
                "google-deepmind": {"is_public": False, "ticker": None, "equity_vehicle": "options"},
                "linkedin": {"is_public": False, "ticker": None, "equity_vehicle": None},
            },
        )
        assert out["private"] == []
        by = {e["company"]: e for e in out["public"]}
        assert (by["google-deepmind"]["ticker"], by["google-deepmind"]["equity_vehicle"]) == ("GOOGL", "rsu")
        assert (by["linkedin"]["ticker"], by["linkedin"]["equity_vehicle"]) == ("MSFT", "rsu")
        assert by["google-deepmind"]["equity"] > 0

    def test_a_subsidiary_with_its_own_equity_stays_private(self):
        # Waymo grants its own units, not GOOGL: it is deliberately not in the map.
        assert parent_ticker("waymo") is None
        out = build_comp_trajectory(
            [("waymo", "staff", "swe", 600_000)],
            profiles={"waymo": {"is_public": False, "ticker": None, "equity_vehicle": "options"}},
        )
        assert [e["company"] for e in out["private"]] == ["waymo"]

    def test_a_grant_ticker_is_never_on_a_company_listed_itself(self):
        granted = {s for s, i in IDENTITIES.items() if i.grant_ticker}
        assert granted >= {"twitch", "zoox", "github", "google-deepmind", "hashicorp", "confluent", "wiz"}
        assert not {s for s in granted if IDENTITIES[s].listed}
        assert is_public("twitch") and ticker_for("zoox") == "AMZN"

    def test_the_fallback_table_never_restates_an_atlas_company(self):
        assert not set(PARENT_TICKERS_OUTSIDE_ATLAS) & set(IDENTITIES)
