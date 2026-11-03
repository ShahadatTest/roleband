"""disclosure_snapshot trend recomputation (no DB).

Same property `test_comp_snapshot.py` pins for comp: the series is recomputed from
raw per-company cells, so hiding a company changes every historical point exactly.
Here that matters more than for percentiles — the rate is a *ratio*, and a ratio of
sums is not the mean of ratios, so storing per-company rates would give a subset
answer that is simply wrong rather than merely approximate.
"""

from __future__ import annotations

from tracker.analytics.comp_trends import build_disclosure_trend_series

D1, D2 = "2026-07-20", "2026-07-21"


def _cell(date, company, band, basis, roles, checked, bands=()):
    """(date_iso, company, level_band, pay_basis, roles, checked, bands)."""
    return (date, company, band, basis, roles, checked, list(bands))


def _band(low, high, reqs=1):
    return {"low": low, "high": high, "reqs": reqs}


def _points(built, key):
    return next(s for s in built["series"] if s["key"] == key)["points"]


def _at(built, key, date):
    return next(p for p in _points(built, key) if p["date"] == date)


def _rows():
    return [
        # google: 10 senior roles read, 6 of them on two published base bands.
        _cell(D1, "google", "senior", "base", 6, 6, [_band(200_000, 300_000, 4), _band(240_000, 340_000, 2)]),
        _cell(D1, "google", "senior", "", 4, 4),
        # netflix: states a range but never says what it bundles.
        _cell(D1, "netflix", "staff", "unclear", 2, 2, [_band(440_000, 725_000, 2)]),
        _cell(D1, "netflix", "staff", "", 2, 2),
        # meta: 6 read roles, none disclose; 3 more not yet examined.
        _cell(D1, "meta", "staff", "", 9, 6),
    ]


# --- the rate ----------------------------------------------------------------


def test_overall_rate_is_disclosed_over_checked_across_every_basis():
    built = build_disclosure_trend_series(_rows(), "overall")
    point = _at(built, "", D1)

    assert point["open"] == 23  # 6+4+2+2+9
    assert point["checked"] == 20  # meta's 3 unread roles are backlog, not silence
    assert point["disclosed"] == 8  # google's 6 base + netflix's 2 unclear
    assert point["rate"] == 0.4


def test_hiding_a_company_yields_the_exact_subset_rate_not_an_average_of_rates():
    # Simulate the endpoint's hidden filter by dropping google's cells before build.
    visible = [r for r in _rows() if r[1] != "google"]
    point = _at(build_disclosure_trend_series(visible, "overall"), "", D1)

    assert point["checked"] == 10  # netflix 4 + meta 6
    assert point["disclosed"] == 2
    assert point["rate"] == 0.2

    # And this is NOT the mean of the two visible companies' own rates — a ratio of
    # sums is not the mean of ratios, which is why the cells store raw counts and
    # the series re-divides rather than storing a per-company rate.
    netflix_rate, meta_rate = 0.5, 0.0
    assert (netflix_rate + meta_rate) / 2 == 0.25
    assert point["rate"] != 0.25


def test_company_dim_keys_by_company_and_pools_that_companys_cells():
    built = build_disclosure_trend_series(_rows(), "company")
    assert {s["key"] for s in built["series"]} == {"google", "netflix", "meta"}

    assert _at(built, "google", D1)["rate"] == 0.6  # 6 of 10 read roles
    assert _at(built, "meta", D1)["rate"] == 0.0  # read and silent: a real 0%
    assert _at(built, "meta", D1)["open"] == 9


def test_level_dim_skips_the_unclassified_sentinel():
    rows = [
        _cell(D1, "google", "senior", "base", 2, 2, [_band(200_000, 300_000, 2)]),
        _cell(D1, "google", "", "base", 5, 5, [_band(100_000, 150_000, 5)]),
    ]
    built = build_disclosure_trend_series(rows, "level")
    assert [s["key"] for s in built["series"]] == ["senior"]
    # ...but the same cells still count in full at the market grain.
    assert _at(build_disclosure_trend_series(rows, "overall"), "", D1)["open"] == 7


def test_series_with_nothing_checked_sorts_last_and_reports_no_rate():
    rows = [
        _cell(D1, "google", "senior", "", 4, 4),  # read, silent -> 0%
        _cell(D1, "openai", "senior", "", 3, 0),  # never read -> no rate
        _cell(D1, "meta", "senior", "base", 2, 2, [_band(300_000, 400_000, 2)]),
    ]
    built = build_disclosure_trend_series(rows, "company")

    assert [s["key"] for s in built["series"]] == ["meta", "google", "openai"]
    assert _at(built, "openai", D1)["rate"] is None
    assert _at(built, "google", D1)["rate"] == 0.0


# --- the bands ---------------------------------------------------------------


def test_band_medians_pool_only_within_one_pay_basis():
    built = build_disclosure_trend_series(_rows(), "overall")
    point = _at(built, "", D1)

    # Only google's two base bands: medians of [200k, 240k] and [300k, 340k].
    assert point["bands"] == 2
    assert point["low_p50"] == 220_000
    assert point["high_p50"] == 320_000
    # Netflix's 440k-725k "unclear" band is a different quantity and never enters
    # the base-pay axis — it would have dragged high_p50 to 440k.
    assert point["reqs"] == 6


def test_band_median_is_one_vote_per_band_not_per_req():
    # An employer hangs many reqs off one band, so req-weighting would report which
    # band is most reposted rather than what employers publish.
    rows = [
        _cell(D1, "google", "senior", "base", 51, 51, [_band(200_000, 300_000, 50), _band(400_000, 500_000, 1)]),
    ]
    point = _at(build_disclosure_trend_series(rows, "overall"), "", D1)

    assert point["low_p50"] == 300_000  # midpoint of the two distinct bands
    assert point["low_p50"] != 200_000  # the req-weighted answer
    assert point["bands"] == 2
    assert point["reqs"] == 51  # the req count is still carried, just not weighted with


def test_distinct_companies_publishing_the_same_band_each_get_a_vote():
    rows = [
        _cell(D1, "google", "senior", "base", 1, 1, [_band(200_000, 300_000)]),
        _cell(D1, "meta", "senior", "base", 1, 1, [_band(200_000, 300_000)]),
        _cell(D1, "amazon", "senior", "base", 1, 1, [_band(400_000, 500_000)]),
    ]
    point = _at(build_disclosure_trend_series(rows, "overall"), "", D1)
    assert point["bands"] == 3
    assert point["low_p50"] == 200_000  # median of [200k, 200k, 400k]


def test_a_date_with_no_base_band_reports_no_median_rather_than_zero():
    rows = [_cell(D1, "netflix", "staff", "unclear", 2, 2, [_band(440_000, 725_000, 2)])]
    point = _at(build_disclosure_trend_series(rows, "overall"), "", D1)

    assert point["rate"] == 1.0  # they did publish something
    assert point["bands"] == 0
    assert point["low_p50"] is None


# --- the axis ----------------------------------------------------------------


def test_series_align_on_a_shared_axis_and_null_fill_missing_days():
    rows = [
        _cell(D1, "google", "senior", "base", 2, 2, [_band(200_000, 300_000, 2)]),
        _cell(D2, "google", "senior", "base", 2, 2, [_band(210_000, 310_000, 2)]),
        _cell(D2, "meta", "staff", "", 3, 3),  # meta only appears on day 2
    ]
    built = build_disclosure_trend_series(rows, "company")

    assert built["axis"] == [D1, D2]
    assert [p["date"] for p in _points(built, "meta")] == [D1, D2]
    day1 = _at(built, "meta", D1)
    assert day1["rate"] is None and day1["open"] == 0  # absent, not zero-disclosure
    assert _at(built, "google", D2)["low_p50"] == 210_000


def test_series_headline_counts_come_from_the_latest_day():
    rows = [
        _cell(D1, "google", "senior", "base", 2, 2, [_band(200_000, 300_000, 2)]),
        _cell(D2, "google", "senior", "base", 9, 9, [_band(200_000, 300_000, 9)]),
    ]
    series = build_disclosure_trend_series(rows, "company")["series"][0]
    assert (series["checked"], series["disclosed"]) == (9, 9)


# --- the fixed cohort ---------------------------------------------


def test_the_cohort_line_holds_the_first_days_companies_while_the_market_line_moves():
    rows = [
        _cell(D1, "google", "senior", "base", 9, 10),
        _cell(D2, "google", "senior", "base", 9, 10),
        # Added on D2: reads 30 roles and states pay on none of them.
        _cell(D2, "acme", "senior", "", 30, 30),
    ]
    built = build_disclosure_trend_series(rows, "overall")
    assert built["cohort"] == {"since": D1, "companies": 1}
    assert [s["key"] for s in built["series"]] == ["", "cohort"]
    # The market fell from 90% to 22.5% only because acme arrived.
    assert (_at(built, "", D1)["rate"], _at(built, "", D2)["rate"]) == (0.9, 0.225)
    assert (_at(built, "cohort", D1)["rate"], _at(built, "cohort", D2)["rate"]) == (0.9, 0.9)


def test_a_cohort_company_missing_on_a_day_leaves_that_day_empty_not_shifted():
    rows = [
        _cell(D1, "google", "senior", "base", 9, 10),
        _cell(D2, "acme", "senior", "", 30, 30),
    ]
    built = build_disclosure_trend_series(rows, "overall")
    assert [p["date"] for p in _points(built, "cohort")] == [D1, D2]
    assert _at(built, "cohort", D2)["rate"] is None


def test_no_cohort_when_the_company_set_never_changed_or_the_grain_is_not_the_market():
    rows = [_cell(D1, "google", "senior", "base", 9, 10), _cell(D2, "google", "senior", "base", 5, 10)]
    assert build_disclosure_trend_series(rows, "overall")["cohort"] is None
    assert [s["key"] for s in build_disclosure_trend_series(rows, "overall")["series"]] == [""]
    grown = [*rows, _cell(D2, "acme", "senior", "", 3, 3)]
    assert build_disclosure_trend_series(grown, "company")["cohort"] is None
    # A company only listed, never read, does not change the set.
    unread = [*rows, _cell(D2, "acme", "senior", "", 3, 0)]
    assert build_disclosure_trend_series(unread, "overall")["cohort"] is None
