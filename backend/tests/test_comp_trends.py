"""Pure-logic tests for the comp-over-time rollup slices (no DB).

Pins the grouping-sets shape behind the Statistics Compensation trend: one exact
percentile summary per grouping, computed from each group's raw values.
"""

from __future__ import annotations

from tracker.analytics.comp_stats import _percentile, build_comp_metric_rows


def _fixture():
    # (company, level_band, family, comp_median)
    return [
        ("google", "staff", "swe", 600_000),
        ("google", "senior", "swe", 300_000),
        ("openai", "staff", "ml", 800_000),
        ("openai", "principal", "ml", 1_000_000),
        ("meta", "senior", None, 400_000),   # null family -> excluded from family dim
        ("apple", "staff", "swe", None),      # null comp -> excluded everywhere
    ]


def _rows_for(rows, dim):
    return {r["key"]: r for r in rows if r["dim"] == dim}


def test_overall_slice_is_exact_over_all_comped_rows():
    rows = build_comp_metric_rows(_fixture())
    overall = _rows_for(rows, "overall")
    assert set(overall) == {""}
    o = overall[""]
    assert o["count"] == 5  # apple (null comp) excluded
    # median of [300k,400k,600k,800k,1000k]
    assert o["p50"] == _percentile([300_000, 400_000, 600_000, 800_000, 1_000_000], 0.5)
    assert o["p50"] == 600_000


def test_one_slice_per_company_level_and_nonnull_family():
    rows = build_comp_metric_rows(_fixture())
    assert set(_rows_for(rows, "company")) == {"google", "openai", "meta"}
    assert set(_rows_for(rows, "level")) == {"staff", "senior", "principal"}
    # null-family meta row is excluded from the family dim entirely.
    assert set(_rows_for(rows, "family")) == {"swe", "ml"}


def test_group_percentiles_use_that_groups_raw_values():
    rows = build_comp_metric_rows(_fixture())
    google = _rows_for(rows, "company")["google"]
    assert google["count"] == 2
    assert google["p50"] == _percentile([300_000, 600_000], 0.5)  # 450k
    staff = _rows_for(rows, "level")["staff"]
    assert staff["count"] == 2  # apple's null-comp staff row dropped
    assert staff["p50"] == _percentile([600_000, 800_000], 0.5)  # 700k
    swe = _rows_for(rows, "family")["swe"]
    assert swe["count"] == 2  # apple's null-comp swe row dropped


def test_null_comp_rows_never_appear():
    rows = build_comp_metric_rows(_fixture())
    assert "apple" not in _rows_for(rows, "company")


def test_every_slice_carries_all_percentiles():
    rows = build_comp_metric_rows(_fixture())
    for r in rows:
        assert set(r) >= {"dim", "key", "count", "p25", "p50", "p75", "p90"}


def test_empty_input_yields_no_rows():
    assert build_comp_metric_rows([]) == []
    # all-null comp also yields nothing
    assert build_comp_metric_rows([("google", "staff", "swe", None)]) == []
