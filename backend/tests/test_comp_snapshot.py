"""comp_snapshot trend recomputation is exact over any company subset.

This is the property that `comp_metrics` (stored percentiles) cannot provide and
the reason comp_snapshot stores raw values: a subset's median is not recoverable
from per-company medians, but it IS recoverable from per-company raw values.
"""

from __future__ import annotations

from tracker.analytics.comp_stats import _percentile
from tracker.analytics.comp_trends import build_comp_trend_series

_DAY = "2026-07-14"


def _rows():
    # (date, company, level_band, family, comp_values)
    return [
        (_DAY, "google", "staff", "swe", [600_000, 620_000]),
        (_DAY, "google", "senior", "swe", [300_000]),
        (_DAY, "amazon", "staff", "swe", [320_000, 340_000]),
        (_DAY, "openai", "principal", "ml", [1_000_000]),
    ]


def _p50(series, key):
    point = next(s for s in series if s["key"] == key)["points"][0]
    return point["p50"]


def test_overall_median_matches_direct_percentile_of_all_values():
    built = build_comp_trend_series(_rows(), "overall")
    all_vals = [600_000, 620_000, 300_000, 320_000, 340_000, 1_000_000]
    assert _p50(built["series"], "") == _percentile(sorted(all_vals), 0.5)


def test_hiding_a_company_yields_the_exact_subset_percentile():
    # Simulate the endpoint's hidden filter by dropping amazon's rows before build.
    visible = [r for r in _rows() if r[1] != "amazon"]
    built = build_comp_trend_series(visible, "overall")

    subset_vals = [600_000, 620_000, 300_000, 1_000_000]  # google + openai only
    exact = _percentile(sorted(subset_vals), 0.5)
    assert _p50(built["series"], "") == exact

    # And this is NOT the naive average of the visible companies' own medians —
    # the property that makes storing raw values necessary.
    google_median = _percentile(sorted([600_000, 620_000, 300_000]), 0.5)
    openai_median = 1_000_000
    naive = (google_median + openai_median) / 2
    assert exact != naive


def test_company_dim_keys_by_company_and_uses_that_companys_values():
    built = build_comp_trend_series(_rows(), "company")
    keys = {s["key"] for s in built["series"]}
    assert keys == {"google", "amazon", "openai"}
    # google combines its staff + senior raw values.
    assert _p50(built["series"], "google") == _percentile(
        sorted([600_000, 620_000, 300_000]), 0.5
    )


def test_level_and_family_dims_skip_the_empty_sentinel():
    # A snapshot row with a "" level (the "any" sentinel) must not become a series.
    rows = [(_DAY, "google", "", "swe", [500_000])]
    assert build_comp_trend_series(rows, "level")["series"] == []
    # But it still contributes to family and overall.
    assert build_comp_trend_series(rows, "family")["series"][0]["key"] == "swe"


def test_series_ranked_by_recent_p50_descending():
    built = build_comp_trend_series(_rows(), "company")
    p50s = [s["points"][-1]["p50"] for s in built["series"]]
    assert p50s == sorted(p50s, reverse=True)
