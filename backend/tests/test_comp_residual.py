"""Equity-residual measurement (`comp_residual.build_equity_residuals`).

Invariants pinned here:
  * only basis='base' annual bands from an accepted prompt version enter the
    math; everything else lands in an `excluded` counter, never silently;
  * uncertainty is a propagated RANGE (base_min..base_max, envelope across a
    group's distinct tuples), and negative implied equity is kept as signal;
  * an observed stock_pct of 0.0 (Netflix cash election) is honoured as a real
    measurement, never replaced by the heuristic;
  * the unit is the distinct band, not the req (duplicates collapse with count);
  * the residual is never framed as an estimate "error" — output keys say
    implied/residual_vs_model/consistent;
  * while a plugin answers pay (`heuristic=False`) a (company, band)
    its rows do not split is counted `unsplit`, never checked against our
    heuristic's share.
"""

import pytest

from tracker.analytics.comp_residual import build_equity_residuals, build_source_comparison
from tracker.analytics.comp_split import equity_pct
from tracker.schema import LevelBand

V = "disclosed_comp/v5"


class TestSourceComparison:
    def test_median_share_all_and_established(self):
        # Two amazon staff rows: one established (equity 130/300), one year-1 with
        # RSU not yet vesting (equity 0). eq_all median counts both; eq_estd drops
        # the zero. Model stock_pct 0.45 from the measured per-level split.
        rows = [
            ("amazon", "staff", 300_000, 130_000),
            ("amazon", "staff", 200_000, 0),
        ]
        observed = {("amazon", "staff"): {"stock_pct": 0.45}}
        out = build_source_comparison(rows, observed=observed)
        (g,) = out["groups"]
        assert g["n"] == 2 and g["n_estd"] == 1
        assert g["source_eq_share"] == pytest.approx(0.2167, abs=1e-3)  # median of 0.433 and 0.0
        assert g["source_eq_share_estd"] == pytest.approx(0.4333, abs=1e-3)
        assert g["model_stock_pct"] == 0.45
        assert g["delta_estd_vs_model"] == pytest.approx(-0.0167, abs=1e-3)
        assert out["coverage"]["observations"] == 2

    def test_none_band_and_zero_total_are_skipped(self):
        rows = [
            ("amazon", None, 300_000, 100_000),
            ("amazon", "staff", 0, 0),
        ]
        out = build_source_comparison(rows, observed={})
        assert out["groups"] == []
        assert out["coverage"]["observations"] == 0

    def test_missing_model_split_yields_null_delta(self):
        rows = [("apple", "director_plus", 900_000, 600_000)]
        out = build_source_comparison(rows, observed={})  # no measured split
        (g,) = out["groups"]
        assert g["model_stock_pct"] is None
        assert g["delta_estd_vs_model"] is None
        assert g["source_eq_share_estd"] == pytest.approx(0.6667, abs=1e-3)

    def test_groups_sorted_by_seniority_then_company(self):
        rows = [
            ("apple", "staff", 400_000, 150_000),
            ("amazon", "senior", 300_000, 100_000),
        ]
        out = build_source_comparison(rows, observed={})
        assert [(g["band"], g["company"]) for g in out["groups"]] == [
            ("senior", "amazon"),
            ("staff", "apple"),
        ]


def _row(
    company="google",
    band="staff",
    comp_median=400_000,
    base_min=150_000,
    base_max=200_000,
    currency="USD",
    basis="base",
    period="year",
    bonus_pct=0.15,
    version=V,
):
    return (company, band, comp_median, base_min, base_max, currency, basis, period, bonus_pct, version)


def _observed_google(stock_pct):
    return {("google", "staff"): {"base_pct": 0.5, "stock_pct": stock_pct, "bonus_pct": None}}


class TestResidualMath:
    def test_implied_equity_range_to_the_digit(self):
        # cash = base * 1.15 -> 172_500..230_000; implied = 400k - cash.
        out = build_equity_residuals(
            [_row()], observed=_observed_google(0.5), accepted_versions={V}
        )
        (g,) = out["groups"]
        assert g["company"] == "google" and g["band"] == "staff"
        assert g["reqs"] == 1 and g["bands"] == 1
        assert g["comp_medians"] == [400_000]
        assert g["implied_equity"] == {"low": 170_000, "mid": 198_750, "high": 227_500}
        assert g["implied_pct"]["low"] == pytest.approx(0.425, abs=1e-4)
        assert g["implied_pct"]["mid"] == pytest.approx(0.4969, abs=1e-4)
        assert g["implied_pct"]["high"] == pytest.approx(0.5688, abs=1e-4)
        assert g["bonus_source"] == "stated"
        assert g["model_source"] == "measured"
        # 0.5 sits inside [0.425, 0.56875]: the model is consistent with the data.
        assert g["consistent"] is True
        assert g["residual_vs_model_pct"] == pytest.approx(0.4969 - 0.5, abs=1e-3)

    def test_model_outside_implied_range_is_flagged_inconsistent(self):
        out = build_equity_residuals(
            [_row()], observed=_observed_google(0.35), accepted_versions={V}
        )
        (g,) = out["groups"]
        assert g["consistent"] is False
        # Implied mid (~0.497) exceeds the modeled 0.35: residual is positive.
        assert g["residual_vs_model_pct"] > 0

    def test_negative_implied_equity_is_kept_not_clamped(self):
        # The seeded estimate does not even cover stated cash: that is signal.
        out = build_equity_residuals(
            [_row(comp_median=200_000, base_min=250_000, base_max=300_000, bonus_pct=0.0)],
            observed={},
            accepted_versions={V},
        )
        (g,) = out["groups"]
        assert g["implied_equity"]["low"] == -100_000
        assert g["implied_pct"]["low"] == pytest.approx(-0.5, abs=1e-4)

    def test_group_envelope_spans_distinct_bands(self):
        rows = [
            _row(comp_median=400_000, base_min=150_000, base_max=200_000, bonus_pct=0.0),
            _row(comp_median=500_000, base_min=180_000, base_max=220_000, bonus_pct=0.0),
        ]
        out = build_equity_residuals(rows, observed={}, accepted_versions={V})
        (g,) = out["groups"]
        assert g["bands"] == 2 and g["reqs"] == 2
        assert g["comp_medians"] == [400_000, 500_000]
        # Envelope: min of lows (400k-200k)/400k, max of highs (500k-180k)/500k.
        assert g["implied_pct"]["low"] == pytest.approx(0.5, abs=1e-4)
        assert g["implied_pct"]["high"] == pytest.approx(0.64, abs=1e-4)

    def test_groups_sorted_by_seniority_then_company(self):
        rows = [
            _row(company="google", band="staff"),
            _row(company="anthropic", band="staff"),
            _row(company="google", band="senior"),
        ]
        out = build_equity_residuals(rows, observed={}, accepted_versions={V})
        order = [(g["band"], g["company"]) for g in out["groups"]]
        assert order == [("senior", "google"), ("staff", "anthropic"), ("staff", "google")]


class TestBonusFallbacks:
    def test_stated_bonus_zero_is_stated_not_fallback(self):
        out = build_equity_residuals(
            [_row(bonus_pct=0.0)], observed={}, accepted_versions={V}
        )
        (g,) = out["groups"]
        assert g["bonus_source"] == "stated"
        # No bonus: implied mid = 400k - 175k midpoint base.
        assert g["implied_equity"]["mid"] == 225_000

    def test_null_bonus_falls_back_to_observed_ratio(self):
        observed = {("google", "senior"): {"base_pct": 0.5, "stock_pct": 0.4, "bonus_pct": 0.1}}
        out = build_equity_residuals(
            [_row(band="senior", base_min=100_000, base_max=100_000, bonus_pct=None)],
            observed=observed,
            accepted_versions={V},
        )
        (g,) = out["groups"]
        assert g["bonus_source"] == "modeled"
        # bonus_r = 0.1/0.5 of base -> cash 120k -> implied 280k.
        assert g["implied_equity"]["mid"] == 280_000

    def test_null_bonus_falls_back_to_company_median_across_bands(self):
        # No stated bonus and no observed row for THIS band, but the company's
        # other observed bands carry ratios: bonus culture is company-wide.
        observed = {
            ("google", "senior"): {"base_pct": 0.5, "stock_pct": 0.4, "bonus_pct": 0.1},
            ("google", "principal"): {"base_pct": 0.4, "stock_pct": 0.5, "bonus_pct": 0.08},
        }
        out = build_equity_residuals(
            [_row(base_min=100_000, base_max=100_000, bonus_pct=None)],
            observed=observed,
            accepted_versions={V},
        )
        (g,) = out["groups"]
        assert g["bonus_source"] == "modeled"
        # median(0.1/0.5, 0.08/0.4) = 0.2 -> cash 120k -> implied 280k.
        assert g["implied_equity"]["mid"] == 280_000

    def test_null_bonus_without_any_observation_uses_flat_fallback(self):
        # The flat constant is deliberately NOT derived from the equity
        # heuristic: the model under test must not shape the cash side.
        out = build_equity_residuals(
            [_row(base_min=100_000, base_max=100_000, bonus_pct=None)],
            observed={},
            accepted_versions={V},
        )
        (g,) = out["groups"]
        assert g["bonus_source"] == "modeled"
        assert g["model_source"] == "heuristic"
        assert g["modeled_pct"] == pytest.approx(equity_pct("google", LevelBand.STAFF))
        # cash = 100k * (1 + FALLBACK_BONUS_PER_BASE 0.15) -> implied 285k.
        assert g["implied_equity"]["mid"] == 285_000


class TestNetflixGuards:
    def test_unclear_basis_never_fabricates_a_group(self):
        # All real Netflix bands are basis='unclear' — they must not enter.
        rows = [
            _row(company="netflix", band="staff", comp_median=700_000,
                 base_min=440_000, base_max=725_000, basis="unclear", bonus_pct=None)
        ]
        out = build_equity_residuals(rows, observed={}, accepted_versions={V})
        assert out["groups"] == []
        assert out["excluded"]["basis_not_base"] == 1

    def test_observed_zero_stock_pct_is_a_measurement_not_a_gap(self):
        # 0.0 must not fall through to the ~18% heuristic slice.
        observed = {("netflix", "staff"): {"base_pct": 1.0, "stock_pct": 0.0, "bonus_pct": 0.0}}
        rows = [
            _row(company="netflix", band="staff", comp_median=700_000,
                 base_min=400_000, base_max=500_000, bonus_pct=None)
        ]
        out = build_equity_residuals(rows, observed=observed, accepted_versions={V})
        (g,) = out["groups"]
        assert g["modeled_pct"] == 0.0
        assert g["model_source"] == "measured"


class TestPluginAnswersPay:
    """Our split heuristic is our data, so it models no share for a
    plugin's figure."""

    def test_a_band_the_plugin_does_not_split_is_counted_out_not_guessed(self):
        out = build_equity_residuals(
            [_row(), _row(company="meta")], observed=_observed_google(0.5), accepted_versions={V}, heuristic=False
        )
        assert [(g["company"], g["model_source"]) for g in out["groups"]] == [("google", "measured")]
        assert out["excluded"]["unsplit"] == 1
        # Counted out before the math: coverage holds only the rows it checked.
        assert out["coverage"]["used_reqs"] == 1 and out["coverage"]["companies"] == {"google": 1}

    def test_a_measured_zero_share_is_still_checked(self):
        observed = {("netflix", "staff"): {"base_pct": 1.0, "stock_pct": 0.0, "bonus_pct": 0.0}}
        out = build_equity_residuals(
            [_row(company="netflix", comp_median=700_000, base_min=400_000, base_max=500_000)],
            observed=observed, accepted_versions={V}, heuristic=False,
        )
        (g,) = out["groups"]
        assert (g["modeled_pct"], g["model_source"]) == (0.0, "measured")
        assert out["excluded"]["unsplit"] == 0

    def test_while_ours_answers_the_heuristic_still_models_the_gap(self):
        out = build_equity_residuals([_row(company="meta")], observed={}, accepted_versions={V})
        (g,) = out["groups"]
        assert g["model_source"] == "heuristic"
        assert g["modeled_pct"] == pytest.approx(equity_pct("meta", LevelBand.STAFF), abs=1e-4)
        assert out["excluded"]["unsplit"] == 0


class TestGuards:
    def test_hourly_band_is_excluded_never_annualized(self):
        out = build_equity_residuals(
            [_row(period="hour")], observed={}, accepted_versions={V}
        )
        assert out["groups"] == []
        assert out["excluded"]["not_yearly"] == 1

    def test_a_contradicted_period_is_out_and_no_period_reads_by_size(self):
        # A stored `unclear` is the parser's "the words contradict the size"
        # ("$150,000 - $200,000 per month"), not "no word": it is not a yearly
        # salary. A band
        # stored with no period at all still enters by its size.
        out = build_equity_residuals(
            [_row(period="unclear"), _row(period=None)],
            observed={},
            accepted_versions={V},
        )
        (g,) = out["groups"]
        assert g["reqs"] == 1
        assert out["excluded"]["not_yearly"] == 1

    def test_a_band_in_another_currency_never_meets_a_dollar_estimate(self):
        # A foreign-currency base cannot be compared with a USD median:
        # it is counted out, never converted; a row with
        # no stored currency is a dollar band.
        out = build_equity_residuals(
            [_row(base_min=6_612_600, base_max=9_424_500, currency="INR"),
             _row(currency="EUR"), _row(currency=None)],
            observed={},
            accepted_versions={V},
        )
        (g,) = out["groups"]
        assert g["reqs"] == 1
        assert out["excluded"]["not_usd"] == 2

    def test_total_and_unclear_basis_are_counted_out(self):
        rows = [_row(basis="total"), _row(basis="unclear")]
        out = build_equity_residuals(rows, observed={}, accepted_versions={V})
        assert out["groups"] == []
        assert out["excluded"]["basis_not_base"] == 2

    def test_stale_prompt_version_is_excluded(self):
        # A v3 label predates deterministic basis derivation.
        out = build_equity_residuals(
            [_row(version="disclosed_comp/v3")], observed={}, accepted_versions={V}
        )
        assert out["groups"] == []
        assert out["excluded"]["stale_version"] == 1

    def test_implausible_bands_are_excluded(self):
        rows = [
            _row(base_min=1, base_max=2),  # Anthropic's "$1—$2" placeholder
            _row(base_min=200_000, base_max=150_000),  # inverted
        ]
        out = build_equity_residuals(rows, observed={}, accepted_versions={V})
        assert out["groups"] == []
        assert out["excluded"]["implausible"] == 2

    def test_missing_fields_and_bogus_band_skip_silently(self):
        rows = [
            _row(comp_median=None),
            _row(base_min=None),
            _row(band="bogus_band"),
        ]
        out = build_equity_residuals(rows, observed={}, accepted_versions={V})
        assert out["groups"] == []
        assert sum(out["excluded"].values()) == 0
        assert out["coverage"]["rows"] == 3


class TestCoverage:
    def test_duplicate_reqs_collapse_to_one_band(self):
        out = build_equity_residuals(
            [_row(), _row()], observed={}, accepted_versions={V}
        )
        (g,) = out["groups"]
        assert g["bands"] == 1 and g["reqs"] == 2
        assert out["coverage"] == {
            "rows": 2,
            "used_reqs": 2,
            "distinct_bands": 1,
            "companies": {"google": 2},
        }

    def test_empty_input_is_empty_not_invented(self):
        out = build_equity_residuals([], observed={}, accepted_versions={V})
        assert out["groups"] == []
        assert out["coverage"]["rows"] == 0
        assert out["coverage"]["companies"] == {}
        assert "equity_by_band" in out["assumptions"]
