"""Pure-logic tests for compensation aggregation (no DB).

Pins the percentile/histogram math and the ordering/coverage rules behind the
Statistics "Compensation" sub-tab.
"""

from __future__ import annotations

from tracker.analytics.comp_stats import (
    COMP_MIN_ROLES,
    SKILL_CELL_MIN,
    _histogram,
    _percentile,
    build_comp_stats,
    build_disclosed_bands,
    rank_skill_comp,
)


def test_percentile_linear_interpolation_matches_percentile_cont():
    vals = [300_000, 600_000, 800_000, 1_000_000]  # sorted
    # p50 interpolates the two middle values, like Postgres percentile_cont.
    assert _percentile(vals, 0.50) == 700_000
    assert _percentile(vals, 0.25) == 525_000  # 0.75 between 300k and 600k
    assert _percentile(vals, 0.0) == 300_000
    assert _percentile(vals, 1.0) == 1_000_000
    assert _percentile([], 0.5) is None
    assert _percentile([420_000], 0.9) == 420_000


def test_histogram_aligns_to_nice_step_and_counts_every_value():
    vals = [0, 50_000, 100_000, 150_000, 200_000, 250_000, 300_000, 350_000, 400_000]
    bins = _histogram(vals)
    # range 400k over ~8 target bins -> 50k nice step, aligned at 0.
    assert bins[0]["lo"] == 0
    assert bins[0]["hi"] - bins[0]["lo"] == 50_000
    assert sum(b["count"] for b in bins) == len(vals)  # nothing dropped
    # Max value falls in the last bin, not off the end.
    assert bins[-1]["count"] >= 1


def test_histogram_handles_degenerate_and_empty():
    assert _histogram([]) == []
    one = _histogram([500_000])
    assert one == [{"lo": 500_000, "hi": 500_000, "count": 1}]


def _fixture():
    # (company, level_band, family, comp_median); one null-comp row.
    return [
        ("google", "staff", "swe", 600_000),
        ("google", "senior", "swe", 300_000),
        ("openai", "principal", "ml_ai_research", 1_000_000),  # out of level order on purpose
        ("openai", "staff", "ml_ai_research", 800_000),
        ("meta", "senior", "pm", None),  # counted in coverage, excluded from math
    ]


def test_coverage_counts_all_open_but_excludes_null_comp():
    s = build_comp_stats(_fixture(), total_open=5)
    assert s["coverage"] == {"with_comp": 4, "total_open": 5, "pct": 0.8}
    assert s["overall"]["p50"] == 700_000
    assert s["overall"]["min"] == 300_000 and s["overall"]["max"] == 1_000_000


def test_by_level_is_ordered_by_seniority_not_input_order():
    s = build_comp_stats(_fixture(), total_open=5, min_roles=1)
    assert [x["level_band"] for x in s["by_level"]] == ["senior", "staff", "principal"]
    staff = next(x for x in s["by_level"] if x["level_band"] == "staff")
    assert staff["count"] == 2 and staff["p50"] == 700_000  # 600k & 800k


def test_by_company_and_family_ranked_by_median_desc():
    s = build_comp_stats(_fixture(), total_open=5, min_roles=1)
    assert [x["company"] for x in s["by_company"]] == ["openai", "google"]
    # pm only had a null-comp row, so it must not appear as a family group.
    fams = [x["family"] for x in s["by_family"]]
    assert fams == ["ml_ai_research", "swe"]
    assert "pm" not in fams


def test_a_group_below_the_minimum_is_not_listed_and_the_minimum_is_stated():
    # One Operations role priced at $1.1M must not top "pay by discipline".
    rows = [("apple", "staff", "pm", 500_000)] * 5 + [("openai", "staff", "ops", 1_100_000)]
    s = build_comp_stats(rows, total_open=6)
    assert s["min_roles"] == COMP_MIN_ROLES == 5
    assert [f["family"] for f in s["by_family"]] == ["pm"]
    assert [c["company"] for c in s["by_company"]] == ["apple"]
    assert [lv["count"] for lv in s["by_level"]] == [6]
    # The whole still counts every role: the gate is on groups, not the market.
    assert s["overall"]["count"] == 6 and s["overall"]["max"] == 1_100_000


def _market(cells):
    """`(level, family, comp)` rows: `cells` maps (level, family) to its comps."""
    return [(lv, fam, c) for (lv, fam), comps in cells.items() for c in comps]


def test_a_skill_premium_compares_roles_at_the_same_level_and_discipline():
    # Every Director role pays $1M and every Staff role $500K; Python is named by
    # Directors only. Against the market median it read as a $500K premium; at
    # its own level it pays exactly what everyone does.
    market = _market({("director_plus", "pm"): [1_000_000] * 10, ("staff", "pm"): [500_000] * 30})
    rows = [("python", "director_plus", "pm", 1_000_000)] * 10 + [("cuda", "staff", "pm", 500_000)] * 10
    ranked = {r["term"]: r for r in rank_skill_comp(rows, market, min_jobs=5)}
    assert ranked["python"]["premium"] == 0
    assert ranked["python"]["p50"] == 1_000_000
    assert ranked["cuda"]["premium"] == 0


def test_a_skill_that_better_payers_ask_for_earns_its_premium_and_one_that_lesser_payers_do_loses():
    staff = [400_000] * 10 + [600_000] * 10  # the cell's median is $500K
    market = _market({("staff", "eng"): staff, ("senior", "eng"): [300_000] * 6 + [350_000] * 6})
    rows = (
        [("cuda", "staff", "eng", 600_000)] * 6  # +$100K in Staff
        + [("cuda", "senior", "eng", 350_000)] * 4  # +$25K in Senior
        + [("cpp", "staff", "eng", 400_000)] * 5  # -$100K
    )
    ranked = rank_skill_comp(rows, market, min_jobs=5)
    assert [r["term"] for r in ranked] == ["cuda", "cpp"]
    cuda, cpp = ranked
    assert cuda["count"] == 10 and cuda["premium"] == round((6 * 100_000 + 4 * 25_000) / 10)
    assert cpp["premium"] == -100_000


def test_a_skill_premium_rests_only_on_cells_with_enough_roles():
    market = _market({("staff", "eng"): [500_000] * 10, ("principal", "eng"): [700_000] * 3})
    # Two roles in Staff (below SKILL_CELL_MIN) and a principal cell below CELL_MIN.
    rows = [("rust", "staff", "eng", 900_000)] * (SKILL_CELL_MIN - 1) + [("rust", "principal", "eng", 900_000)] * 20
    assert rank_skill_comp(rows, market, min_jobs=1) == []
    # With enough roles in a counted cell it appears, on those roles alone.
    more = rows + [("rust", "staff", "eng", 600_000)] * 2
    [rust] = rank_skill_comp(more, market, min_jobs=1)
    assert rust["count"] == SKILL_CELL_MIN + 1 and rust["premium"] == 250_000  # median 750K over 500K


def test_past_the_limit_the_list_keeps_the_top_and_the_bottom():
    market = _market({("staff", "eng"): [500_000] * 10})
    rows = [(f"s{i}", "staff", "eng", 500_000 + i * 10_000) for i in range(6) for _ in range(3)]
    ranked = rank_skill_comp(rows, market, min_jobs=3, limit=4)
    assert [r["term"] for r in ranked] == ["s5", "s4", "s1", "s0"]


def test_empty_input_yields_null_overall():
    s = build_comp_stats([], total_open=0)
    assert s["overall"] is None
    assert s["histogram"] == []
    assert s["by_level"] == [] and s["by_company"] == []
    assert s["coverage"]["pct"] == 0.0


# --- Employer-disclosed bands -------------------------------------------------
# A posting states a band per (company, level), not a salary per role: Google hangs
# several requisitions off one band. These pin the band-as-unit contract and the
# basis guard -- base pay and total comp may never share an axis.

def _band_row(
    company="google", band="staff", lo=240_000, hi=334_000, basis="base",
    currency="USD", period="year",
):
    return (company, band, lo, hi, basis, currency, period)


def test_disclosed_bands_collapse_reqs_onto_one_band():
    out = build_disclosed_bands([_band_row()] * 18)
    assert len(out["bands"]) == 1, "18 reqs on one posted band must not become 18 entries"
    assert out["bands"][0]["reqs"] == 18
    assert out["reqs"] == 18


def test_disclosed_bands_keep_same_band_from_different_companies_apart():
    out = build_disclosed_bands(
        [_band_row(company="google"), _band_row(company="deepmind")]
    )
    assert len(out["bands"]) == 2, "identical numbers from two employers are two bands"
    assert out["companies"] == 2


def test_disclosed_bands_exclude_non_base_and_report_them():
    """The category error this whole payload exists to prevent.

    `unclear` = the posting gave a range but never said if it bundles bonus/equity.
    `total` = a different quantity (including Netflix's employee-elected cash/options
    amount). Neither can sit on a base-pay axis,
    and neither may be dropped silently.
    """
    out = build_disclosed_bands(
        [
            _band_row(basis="base"),
            _band_row(company="netflix", lo=440_000, hi=725_000, basis="total"),
            _band_row(company="netflix", lo=440_000, hi=725_000, basis="total"),
            _band_row(company="openai", lo=300_000, hi=500_000, basis="total"),
        ]
    )
    assert [b["company"] for b in out["bands"]] == ["google"]
    assert out["excluded"] == {
        "unclear": 0, "total": 3, "not_usd": 0, "not_yearly": 0, "implausible": 0,
    }


def test_disclosed_bands_keep_other_currencies_off_the_dollar_axis():
    """A euro or rupee base band is not a dollar band: plotted as-is, INR
    6,612,600 set the axis ceiling. Nothing is converted, so it is counted
    and left out, and a band stored with no currency is a dollar band."""
    out = build_disclosed_bands(
        [
            _band_row(company="mews", lo=90_000, hi=120_000, currency="EUR"),
            _band_row(company="google-in", lo=4_000_000, hi=6_612_600, currency="INR"),
            _band_row(company="figma", lo=180_000, hi=240_000, currency=None),
            _band_row(),
        ]
    )
    assert sorted(b["company"] for b in out["bands"]) == ["figma", "google"]
    assert out["excluded"]["not_usd"] == 2


def test_disclosed_bands_never_annualize_hourly_or_monthly_pay():
    """The axis is yearly. An hourly or monthly band, or a stored period its
    size contradicts ("$600,000 / hr" reads unclear), is counted, not drawn."""
    out = build_disclosed_bands(
        [
            _band_row(company="intern", lo=50, hi=70, period="hour"),
            _band_row(company="contract", lo=12_000, hi=15_000, period="month"),
            _band_row(company="typo", lo=600_000, hi=700_000, period="hour"),
            _band_row(company="nodate", lo=200_000, hi=260_000, period=None),
            _band_row(),
        ]
    )
    assert sorted(b["company"] for b in out["bands"]) == ["google", "nodate"]
    assert out["excluded"]["not_yearly"] == 3


def test_disclosed_bands_drop_placeholder_postings():
    """Anthropic prints a literal "Annual Salary: $1-$2 USD" on some reqs.

    The extraction is right (the span is verbatim) -- the posting is junk. It must
    not be allowed to set the axis floor.
    """
    out = build_disclosed_bands([_band_row(company="anthropic", lo=1, hi=2), _band_row()])
    assert [b["company"] for b in out["bands"]] == ["google"]
    assert out["excluded"]["implausible"] == 1


def test_disclosed_bands_order_by_seniority_then_pay():
    out = build_disclosed_bands(
        [
            _band_row(band="principal", lo=262_000, hi=365_000),
            _band_row(band="senior", lo=174_000, hi=253_000),
            _band_row(band="staff", lo=219_000, hi=306_000),
            _band_row(band="staff", lo=262_000, hi=365_000),
        ]
    )
    assert [(b["level_band"], b["high"]) for b in out["bands"]] == [
        ("senior", 253_000),
        ("staff", 365_000),
        ("staff", 306_000),
        ("principal", 365_000),
    ]


def test_disclosed_bands_truncation_keeps_the_busiest_and_says_so():
    rows = [_band_row(lo=100_000 + i * 1_000, hi=200_000 + i * 1_000) for i in range(5)]
    rows += [_band_row(lo=900_000, hi=950_000)] * 9  # the band most reqs sit on
    out = build_disclosed_bands(rows, limit=3)
    assert out["truncated"] is True
    assert len(out["bands"]) == 3
    assert max(b["reqs"] for b in out["bands"]) == 9


def test_disclosed_bands_empty_input():
    out = build_disclosed_bands([])
    assert out["bands"] == [] and out["reqs"] == 0 and out["truncated"] is False


# --- order of input never orders the output --------------------------------- #
# Tied family medians and tied company-level bands must not retain input
# order: explicit tiebreakers keep equivalent reads deterministic.


def test_families_whose_median_ties_list_in_the_same_order_however_rows_arrive():
    rows = [("acme", "senior", fam, 300_000) for fam in ("data_science", "infrastructure_sre") for _ in range(5)]
    forward = build_comp_stats(rows, total_open=10)["by_family"]
    backward = build_comp_stats(list(reversed(rows)), total_open=10)["by_family"]
    assert [d["family"] for d in forward] == [d["family"] for d in backward] == ["data_science", "infrastructure_sre"]


def test_bands_sharing_level_top_and_company_list_in_the_same_order_however_rows_arrive():
    rows = [_band_row(lo=172_400, hi=334_000), _band_row(lo=173_800, hi=334_000)]
    forward = build_disclosed_bands(rows)["bands"]
    backward = build_disclosed_bands(list(reversed(rows)))["bands"]
    assert forward == backward
    assert [b["low"] for b in forward] == [172_400, 173_800]


def test_the_bands_a_limit_keeps_do_not_depend_on_arrival_order():
    rows = [_band_row(company=c) for c in ("c", "a", "b")]
    kept = {b["company"] for b in build_disclosed_bands(rows, limit=2)["bands"]}
    assert kept == {b["company"] for b in build_disclosed_bands(list(reversed(rows)), limit=2)["bands"]}
    assert kept == {"a", "b"}
