"""The job compensation package: what is cash, what is bonus, what is equity — and which
of those the employer actually stated.

The invariant that matters: a component is `stated` ONLY if the posting stated it. Base is
stated when the band is base salary; bonus is stated
only when the posting names a percentage; equity is always our estimate. And a band whose
basis the employer never declared is NEVER decomposed.

"""

from __future__ import annotations

from types import SimpleNamespace

from tracker.analytics.comp_package import (
    EQUITY_MEASURED_GRANT,
    EQUITY_RATIO,
    MARKET_CONSISTENT,
    MARKET_DIVERGES,
    NO_SPLIT_BASIS_UNCLEAR,
    NO_SPLIT_EMPLOYEE_ELECTION,
    NO_SPLIT_HOURLY,
    NO_SPLIT_NOT_US,
    NO_SPLIT_PLUGIN,
    PROV_ESTIMATED,
    PROV_STATED,
    SPLIT_CROSS_FAMILY,
    SPLIT_HEURISTIC,
    SPLIT_MEASURED,
    VERDICT_CONSISTENT,
    VERDICT_STATED_ABOVE,
    VERDICT_STATED_BELOW,
    build_job_package,
    select_baselines,
)

# A staff baseline with separately measured components.
GOOGLE_L6 = {
    "base_amount": 272333,
    "stock_amount": 331667,
    "bonus_amount": 58614,
    "base_pct": 0.411,
    "stock_pct": 0.5005,
    "bonus_pct": 0.0885,
    "source": "acme-pay",
}
# Anthropic senior: no bonus at all.
ANTHROPIC_SENIOR = {
    "base_amount": 316000,
    "stock_amount": 247325,
    "bonus_amount": 0,
    "base_pct": 0.561,
    "stock_pct": 0.439,
    "bonus_pct": 0.0,
    "source": "acme-pay",
}
# Netflix's reported observations can be all cash, but Netflix officially lets each
# employee elect cash, stock options, or a mix. Never treat this baseline as a fixed split.
NETFLIX_STAFF = {
    "base_amount": 500000,
    "stock_amount": 0,
    "bonus_amount": 0,
    "base_pct": 1.0,
    "stock_pct": 0.0,
    "bonus_pct": 0.0,
    "source": "acme-pay",
}

# Keyed the way readers key `company_comp_level`: by our taxonomy family, the
# job's own vocabulary (`reference_pay.as_taxonomy`). A fixture keyed any other
# way would not look like the data, and would prove nothing.
BASELINES = {
    ("google", "software_engineering", "staff"): GOOGLE_L6,
    ("anthropic", "software_engineering", "senior"): ANTHROPIC_SENIOR,
    ("netflix", "product_management", "staff"): NETFLIX_STAFF,
}

GOOGLE_879 = dict(
    company="google",
    band="staff",
    family="program_management",  # NOTE: no measured split for this family
    comp_low=391162,
    comp_median=460191,
    comp_high=529219,
    comp_provenance="Google L6 estimated median (technical_program_management)",
)
GOOGLE_BAND = {
    "disclosed": True,
    "base_min": 240000,
    "base_max": 334000,
    "currency": "USD",
    "pay_basis": "base",
    "pay_period": "year",
    "bonus_pct": 0.25,
    "snippet": "US: $240000 - $334000 (USD) + 25% bonus target + equity",
    "confidence": "high",
}


def _kinds(pkg):
    return {c["kind"]: c for c in pkg["components"]}


def test_stated_base_anchors_the_package():
    """Google states base $240k-$334k. That is the one hard number, so it is what the rest
    of the package is scaled from — and it is the only component marked `stated`... except
    bonus, which the posting also states as a percentage."""
    pkg = build_job_package(**GOOGLE_879, disclosed=GOOGLE_BAND, baselines=BASELINES)

    assert pkg["state"] == "band"
    assert pkg["basis"] == "base"
    c = _kinds(pkg)
    assert c["base"] == {"kind": "base", "low": 240000, "high": 334000, "provenance": PROV_STATED}
    # Bonus is 25% OF BASE because the posting says so — not a modelled share.
    assert c["bonus"]["provenance"] == PROV_STATED
    assert c["bonus"]["low"] == 60000 and c["bonus"]["high"] == 83500
    # Equity is always ours: Google never states a number.
    assert c["equity"]["provenance"] == PROV_ESTIMATED
    assert pkg["total"]["provenance"] == PROV_ESTIMATED


def test_bonus_falls_back_to_the_measured_ratio_when_unstated():
    """No "+ N% bonus target" in the posting -> bonus is scaled from Google's measured
    L6 bonus/base ratio and must be labelled estimated, not stated."""
    band = {**GOOGLE_BAND, "bonus_pct": None}
    pkg = build_job_package(**GOOGLE_879, disclosed=band, baselines=BASELINES)

    bonus = _kinds(pkg)["bonus"]
    assert bonus["provenance"] == PROV_ESTIMATED
    # 58614/272333 = 0.2152 of base.
    assert bonus["low"] == round(240000 * 58614 / 272333)


def test_cross_family_baseline_is_flagged_not_hidden():
    """The posting is program_management; the split used for scaling is software
    engineering one. That degrades the claim and the UI has to be able to say so —
    silently mixing families is how you get a plausible number that is wrong."""
    pkg = build_job_package(**GOOGLE_879, disclosed=GOOGLE_BAND, baselines=BASELINES)
    assert pkg["split_source"] == SPLIT_CROSS_FAMILY


def test_exact_family_match_is_measured():
    """The job and the baseline both speak our taxonomy (`software_engineering`).
    Two vocabularies with nothing translating between them would make this
    `cross_family` for every job in the database."""
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering"},
        disclosed=GOOGLE_BAND,
        baselines=BASELINES,
    )
    assert pkg["split_source"] == SPLIT_MEASURED


def test_measured_split_reaches_a_non_engineering_family():
    """A product manager at Google L6 is measured against Google's product-manager L6
    row, not borrowed from the SWE one. The two rows carry different equity."""
    pm_row = {**GOOGLE_L6, "stock_amount": 200000}
    baselines = {**BASELINES, ("google", "product_management", "staff"): pm_row}
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "product_management"},
        disclosed=GOOGLE_BAND,
        baselines=baselines,
    )
    assert pkg["split_source"] == SPLIT_MEASURED
    # $200,000 is the PM ladder's grant, not the SWE ladder's $331,667.
    equity = _kinds(pkg)["equity"]
    assert equity["low"] == round(200000 * 0.60)
    assert equity["high"] == round(200000 * 1.40)


def test_borrowing_prefers_the_reference_ladder_over_dict_order():
    """A job whose family has no row of its own
    (`ml_ai_research`) borrows the SWE row — deliberately, and regardless of which
    family happened to be inserted first."""
    pm_row = {**GOOGLE_L6, "stock_amount": 200000}
    baselines = {
        ("google", "product_management", "staff"): pm_row,  # first in dict order
        **BASELINES,
    }
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "ml_ai_research"},
        disclosed=GOOGLE_BAND,
        baselines=baselines,
    )
    assert pkg["split_source"] == SPLIT_CROSS_FAMILY
    assert _kinds(pkg)["equity"]["low"] == round(331667 * 0.60)


def test_a_family_with_its_own_ladder_but_no_row_at_this_band_borrows():
    """product_management maps to a real ladder; when that ladder has no row at the
    job's band the package still borrows and still says so."""
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "product_management"},
        disclosed=GOOGLE_BAND,
        baselines=BASELINES,
    )
    assert pkg["split_source"] == SPLIT_CROSS_FAMILY


def test_no_baseline_at_all_falls_back_to_the_heuristic():
    pkg = build_job_package(
        **{**GOOGLE_879, "company": "stripe"}, disclosed=GOOGLE_BAND, baselines=BASELINES
    )
    assert pkg["split_source"] == SPLIT_HEURISTIC
    assert _kinds(pkg)["base"]["provenance"] == PROV_STATED  # the stated fact survives


# --------------------------------------------------------------------------- #
# A plugin answers pay: our heuristic splits none of its figures
# --------------------------------------------------------------------------- #


def test_a_plugin_s_total_with_no_split_of_its_own_stays_whole():
    """Stripe has no row in the plugin's set at this level: the plugin's total is
    the estimate, alone, never divided by our heuristic or pay policy."""
    pkg = build_job_package(**{**GOOGLE_879, "company": "stripe"}, disclosed={"disclosed": False},
                            baselines=BASELINES, heuristic=False)
    assert pkg["components"] == [] and pkg["total"] is None
    assert pkg["split_source"] is None and pkg["equity_basis"] is None
    assert pkg["no_split_reason"] == NO_SPLIT_PLUGIN
    assert pkg["estimate"]["median"] == 460191


def test_a_stated_base_is_not_split_by_ours_under_a_plugin_without_a_split():
    pkg = build_job_package(**{**GOOGLE_879, "company": "stripe"}, disclosed=GOOGLE_BAND,
                            baselines=BASELINES, heuristic=False)
    assert pkg["components"] == [] and pkg["total"] is None
    assert pkg["no_split_reason"] == NO_SPLIT_PLUGIN
    assert pkg["stated"] == {"low": 240000, "high": 334000}


def test_a_plugin_s_own_split_still_splits_its_total():
    """The rule removes our guess, not the plugin's measurement."""
    pkg = build_job_package(**{**GOOGLE_879, "family": "software_engineering"},
                            disclosed={"disclosed": False}, baselines=BASELINES, heuristic=False)
    assert pkg["split_source"] == SPLIT_MEASURED and pkg["no_split_reason"] is None
    assert {c["kind"] for c in pkg["components"]} == {"base", "bonus", "equity"}


def test_ours_leaves_a_band_outside_us_pay_whole_and_names_our_data():
    """Our split is measured on US pay. With ours answering, a posting whose
    pay is another country's (no row measures it) is not split by our
    heuristic, and the reason is ours, never a plugin's."""
    stated = build_job_package(**GOOGLE_879, disclosed=GOOGLE_BAND, baselines={}, us_pay=False)
    assert stated["components"] == [] and stated["total"] is None and stated["split_source"] is None
    assert stated["no_split_reason"] == NO_SPLIT_NOT_US
    assert stated["policy"] is not None and stated["policy"]["verified"]

    estimated = build_job_package(**GOOGLE_879, disclosed={"disclosed": False}, baselines={}, us_pay=False)
    assert estimated["components"] == [] and estimated["no_split_reason"] == NO_SPLIT_NOT_US

    # The same posting under a plugin keeps the plugin's reasons.
    theirs = build_job_package(**GOOGLE_879, disclosed=GOOGLE_BAND, baselines={}, us_pay=False, heuristic=False)
    assert theirs["no_split_reason"] == NO_SPLIT_PLUGIN and theirs["policy"] is None


def test_our_offer_policy_rides_only_on_our_figures():
    """The policy line is ours; the card a plugin
    answers carries none of it, split or not."""
    ours = build_job_package(**GOOGLE_879, disclosed={"disclosed": False}, baselines=BASELINES)
    assert ours["policy"] is not None and ours["policy"]["verified"]
    for disclosed in ({"disclosed": False}, GOOGLE_BAND):
        theirs = build_job_package(**GOOGLE_879, disclosed=disclosed, baselines=BASELINES, heuristic=False)
        assert theirs["policy"] is None


def test_unclear_basis_is_never_decomposed():
    """THE guard-rail. Anthropic states $210k-$260k but never says whether that is base or
    total. Splitting it would require assuming it is base, an invented fact. Show the
    number, refuse to explain it."""
    pkg = build_job_package(
        company="anthropic",
        band="senior",
        family="product_management",
        comp_low=478826,
        comp_median=563325,
        comp_high=647823,
        comp_provenance="Anthropic Senior Software Engineer estimated median",
        disclosed={
            "disclosed": True,
            "base_min": 210000,
            "base_max": 260000,
            "currency": "USD",
            "pay_basis": "unclear",
            "pay_period": "year",
            "bonus_pct": None,
            "snippet": "Annual Salary: $210,000—$260,000 USD",
            "confidence": "high",
        },
        baselines=BASELINES,
    )

    assert pkg["components"] == []
    assert pkg["total"] is None
    assert pkg["no_split_reason"] == NO_SPLIT_BASIS_UNCLEAR
    # ...but the stated figure and our independent estimate are both still shown.
    assert pkg["stated"] == {"low": 210000, "high": 260000}
    assert pkg["estimate"]["median"] == 563325


def test_hourly_band_is_not_annualized():
    """Turning $100/hr into $208k is inference, not disclosure."""
    pkg = build_job_package(
        company="google",
        band="staff",
        family="software_engineering",
        comp_low=None,
        comp_median=None,
        comp_high=None,
        comp_provenance=None,
        disclosed={
            "disclosed": True,
            "base_min": 100,
            "base_max": 150,
            "currency": "USD",
            "pay_basis": "base",
            "pay_period": "hour",
            "bonus_pct": None,
            "snippet": "$100 - $150 per hour",
            "confidence": "high",
        },
        baselines=BASELINES,
    )
    assert pkg["components"] == []
    assert pkg["no_split_reason"] == NO_SPLIT_HOURLY
    assert pkg["stated"] == {"low": 100, "high": 150}


def test_zero_observed_equity_baseline_gets_no_equity_segment():
    """A zero observed component must not produce a visible sliver."""
    pkg = build_job_package(
        company="netflix",
        band="staff",
        family="product_management",
        comp_low=400000,
        comp_median=500000,
        comp_high=600000,
        comp_provenance="Netflix estimated median",
        disclosed={
            "disclosed": True,
            "base_min": 440000,
            "base_max": 725000,
            "currency": "USD",
            "pay_basis": "base",
            "pay_period": "year",
            "bonus_pct": None,
            "snippet": "The range for this role is $440,000.00 - $725,000.00.",
            "confidence": "high",
        },
        baselines=BASELINES,
    )
    assert "equity" not in _kinds(pkg)
    assert "bonus" not in _kinds(pkg)


def test_netflix_total_band_is_stated_but_employee_split_is_not_invented():
    pkg = build_job_package(
        company="netflix",
        band="staff",
        family="product_management",
        comp_low=400000,
        comp_median=500000,
        comp_high=600000,
        comp_provenance="Netflix estimated median",
        disclosed={
            "disclosed": True,
            "base_min": 440000,
            "base_max": 725000,
            "currency": "USD",
            "pay_basis": "total",
            "pay_period": "year",
            "bonus_pct": None,
            "snippet": "The range for this role is $440,000.00 - $725,000.00.",
            "confidence": "high",
        },
        baselines=BASELINES,
    )

    assert pkg["components"] == []
    assert pkg["total"] == {"low": 440000, "high": 725000, "provenance": PROV_STATED}
    assert pkg["no_split_reason"] == NO_SPLIT_EMPLOYEE_ELECTION


def test_checked_but_nothing_stated_is_estimate_only():
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering"},
        disclosed={"disclosed": False},
        baselines=BASELINES,
    )
    assert pkg["state"] == "none_stated"
    assert pkg["stated"] is None
    assert all(c["provenance"] == PROV_ESTIMATED for c in pkg["components"])
    # The estimated components must reconstruct the TC estimate they came from.
    assert pkg["total"]["low"] == 391162
    assert sum(c["low"] for c in pkg["components"]) == 391162


def test_not_yet_checked_is_distinct_from_nothing_stated():
    """Silence because we have not looked is not silence because the employer said nothing.
    The UI must be able to tell these apart."""
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering"}, disclosed=None, baselines=BASELINES
    )
    assert pkg["state"] == "unchecked"
    assert pkg["stated"] is None
    assert pkg["estimate"]["median"] == 460191


def test_no_estimate_and_no_band_is_empty_but_safe():
    pkg = build_job_package(
        company="google",
        band=None,
        family=None,
        comp_low=None,
        comp_median=None,
        comp_high=None,
        comp_provenance=None,
        disclosed=None,
        baselines={},
    )
    assert pkg["estimate"] is None
    assert pkg["components"] == []
    assert pkg["total"] is None


# --- equity as a measured grant ---------------------------------
#
# Equity is a dollar grant sized by LEVEL, from a separate budget. Scaling it off the two
# ends of a posted base band would make the grant vary with geography rather
# than level.


def test_equity_is_the_measured_grant_not_a_multiple_of_the_stated_band():
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering"},
        disclosed=GOOGLE_BAND,
        baselines=BASELINES,
    )

    assert pkg["equity_basis"] == EQUITY_MEASURED_GRANT
    equity = _kinds(pkg)["equity"]
    assert equity == {
        "kind": "equity",
        "low": round(331667 * 0.60),
        "high": round(331667 * 1.40),
        "provenance": PROV_ESTIMATED,
    }


def test_equity_does_not_move_when_only_the_base_band_widens():
    """A posting that spans more geography states a wider base band and
    is not thereby a bigger equity grant."""
    narrow = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering"},
        disclosed={**GOOGLE_BAND, "base_min": 280000, "base_max": 290000},
        baselines=BASELINES,
    )
    wide = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering"},
        disclosed={**GOOGLE_BAND, "base_min": 200000, "base_max": 400000},
        baselines=BASELINES,
    )

    assert _kinds(narrow)["equity"] == _kinds(wide)["equity"]
    # ...while base, which the employer DID state, tracks the posting exactly.
    assert _kinds(wide)["base"]["high"] - _kinds(wide)["base"]["low"] == 200000


def test_equity_falls_back_to_a_ratio_only_when_no_grant_is_measured():
    """The heuristic tier keeps the ratio estimator (there is no grant to read) and says
    which one it used, so the two are never confused."""
    pkg = build_job_package(
        company="cohere",
        band="staff",
        family="software_engineering",
        comp_low=None,
        comp_median=None,
        comp_high=None,
        comp_provenance=None,
        disclosed={**GOOGLE_BAND, "bonus_pct": None},
        baselines={},
    )

    assert pkg["split_source"] == SPLIT_HEURISTIC
    assert pkg["equity_basis"] == EQUITY_RATIO
    equity = _kinds(pkg)["equity"]
    assert equity["high"] > equity["low"]  # a share of a band IS band-shaped


def test_components_sum_to_the_headline_total():
    """A bar whose parts do not add up to the number printed above it is a bug the user
    can see. Equity is not a multiple of base, so the total cannot be re-derived
    from the base band — it is the sum of the segments."""
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering"},
        disclosed=GOOGLE_BAND,
        baselines=BASELINES,
    )

    assert sum(c["low"] for c in pkg["components"]) == pkg["total"]["low"]
    assert sum(c["high"] for c in pkg["components"]) == pkg["total"]["high"]


def test_a_no_stock_company_gets_no_equity_sliver():
    """Netflix grants no stock; anthropic pays no bonus. A zero segment must not render."""
    pkg = build_job_package(
        company="anthropic",
        band="senior",
        family="software_engineering",
        comp_low=None,
        comp_median=None,
        comp_high=None,
        comp_provenance=None,
        disclosed={**GOOGLE_BAND, "bonus_pct": None},
        baselines={("anthropic", "software_engineering", "senior"): {**ANTHROPIC_SENIOR, "stock_amount": 0}},
    )

    assert "equity" not in _kinds(pkg)
    assert "bonus" not in _kinds(pkg)
    assert pkg["total"]["low"] == 240000


# --- stated vs measured base ------------------------------------


def test_a_band_that_matches_the_measured_base_reads_consistent():
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering"},
        disclosed=GOOGLE_BAND,
        baselines=BASELINES,
    )

    assert pkg["reconciliation"] == {
        "measured_base": 272333,
        "ratio_high": round(334000 / 272333, 3),
        "verdict": VERDICT_CONSISTENT,
    }


def test_a_band_far_above_the_measured_base_says_the_level_may_be_wrong():
    """Apple's `mid` postings run $175K-$278K against a measured $171K base. The posting
    is not generous; the level is wrong."""
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering"},
        disclosed={**GOOGLE_BAND, "base_min": 240000, "base_max": 500000},
        baselines=BASELINES,
    )

    assert pkg["reconciliation"]["verdict"] == VERDICT_STATED_ABOVE
    assert pkg["reconciliation"]["ratio_high"] > 1.5


def test_a_band_far_below_the_measured_base_is_flagged_too():
    """Amazon posts `director_plus` engineering roles at about half the measured
    director base. Same defect, opposite direction, and just as wrong to render silently."""
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering"},
        disclosed={**GOOGLE_BAND, "base_min": 120000, "base_max": 150000},
        baselines=BASELINES,
    )

    assert pkg["reconciliation"]["verdict"] == VERDICT_STATED_BELOW


def test_a_borrowed_ladder_is_not_reconciled_against():
    """A cross-family row measures a DIFFERENT job family, so disagreeing with it says
    "wrong family" — which `split_source` already says. Two claims in one slot is one
    claim too many."""
    pkg = build_job_package(**GOOGLE_879, disclosed=GOOGLE_BAND, baselines=BASELINES)

    assert pkg["split_source"] == SPLIT_CROSS_FAMILY
    assert pkg["reconciliation"] == {
        "measured_base": None,
        "ratio_high": None,
        "verdict": None,
    }


def test_a_non_usd_band_is_never_reconciled_against_a_usd_median():
    """A CAD band over a USD median is not a meaningful ratio."""
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering"},
        disclosed={**GOOGLE_BAND, "currency": "CAD"},
        baselines=BASELINES,
    )

    assert pkg["reconciliation"] is None


def test_an_undecomposed_band_has_nothing_to_reconcile():
    """`unclear` is never decomposed, so there is no stated base to compare."""
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering"},
        disclosed={**GOOGLE_BAND, "pay_basis": "unclear"},
        baselines=BASELINES,
    )

    assert pkg["no_split_reason"] == NO_SPLIT_BASIS_UNCLEAR
    assert pkg["reconciliation"] is None


# --- one headline, market median as a check on it ----------------


def test_the_market_median_is_a_check_on_the_headline_not_a_second_headline():
    """Both numbers stay in the payload: one of them is the answer and the other
    is a reading on it."""
    # Google's own L6 TC: 272,333 base + 331,667 stock + 58,614 bonus.
    market_median = 662614
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering", "comp_median": market_median},
        disclosed=GOOGLE_BAND,
        baselines=BASELINES,
    )

    assert pkg["total"]["provenance"] == PROV_ESTIMATED
    assert pkg["estimate"]["median"] == market_median
    mid = (pkg["total"]["low"] + pkg["total"]["high"]) / 2
    assert pkg["market_gap"]["ratio"] == round(mid / market_median, 3)
    assert pkg["market_gap"]["verdict"] == MARKET_CONSISTENT


def test_a_headline_far_from_the_market_median_is_flagged():
    """Half again the market median for the level is not generosity, it is a wrong
    level or a wrong family — and the pair must say so rather than print two numbers
    side by side and leave the reader to notice. The bound is wide on purpose: the two
    figures are different statistics, so a tight tolerance would mislabel
    ordinary disagreement as a level or family error."""
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering", "comp_median": 200000},
        disclosed=GOOGLE_BAND,
        baselines=BASELINES,
    )

    assert pkg["market_gap"]["verdict"] == MARKET_DIVERGES
    assert pkg["market_gap"]["ratio"] > 1.5
    # ...and an ordinary disagreement between the two statistics is not a warning.
    ordinary = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering", "comp_median": 550000},
        disclosed=GOOGLE_BAND,
        baselines=BASELINES,
    )
    assert ordinary["market_gap"]["verdict"] == MARKET_CONSISTENT


def test_no_market_estimate_means_no_gap_to_report():
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering", "comp_median": None},
        disclosed=GOOGLE_BAND,
        baselines=BASELINES,
    )

    assert pkg["estimate"] is None
    assert pkg["market_gap"] is None


class _Row:
    """A `company_comp_level` row as `select_baselines` reads it."""

    def __init__(self, company_slug, family, band, level_label, base_amount, stock_amount, bonus_amount):
        self.company_slug = company_slug
        self.family = family
        self.band = band
        self.level_label = level_label
        self.base_amount = base_amount
        self.stock_amount = stock_amount
        self.bonus_amount = bonus_amount


# Microsoft's real product-manager rows: 65, 66 and 67 all band `principal`, and
# `BAND_TO_LEVEL_LABEL["microsoft"][PRINCIPAL]` is "65" — the rung the reported
# median beside the package is read at.
_MS_PRINCIPAL = [
    _Row("microsoft", "product_management", "principal", "65", 217988, 62008, 41617),
    _Row("microsoft", "product_management", "principal", "66", 234064, 81643, 45714),
    _Row("microsoft", "product_management", "principal", "67", 255144, 231273, 88386),
]


def test_a_band_with_several_rungs_uses_the_rung_the_estimate_uses():
    # The package and the estimated median beside it are compared to each other,
    # so they must read the SAME rung. Reading 67 while the median came from 65
    # creates a false market-gap signal.
    picked = select_baselines(_MS_PRINCIPAL)[("microsoft", "product_management", "principal")]
    assert picked["base_amount"] == 217988
    assert picked["stock_amount"] == 62008


def test_row_order_cannot_change_the_answer():
    # Letting whichever row Postgres returns last win would make the answer
    # depend on order: one (company, family, band) can have several candidates
    # whose base spans more than 2x.
    forward = select_baselines(_MS_PRINCIPAL)
    backward = select_baselines(list(reversed(_MS_PRINCIPAL)))
    assert forward == backward


def test_an_undeclared_band_takes_the_median_rung_not_an_extreme():
    # No BAND_TO_LEVEL_LABEL entry for this (company, band): the fallback must
    # still be deterministic, and must not hand the user the cheapest or the
    # showiest row.
    rows = [
        _Row("acme", "software_engineering", "staff", "A", 100_000, 1, 1),
        _Row("acme", "software_engineering", "staff", "B", 200_000, 2, 2),
        _Row("acme", "software_engineering", "staff", "C", 300_000, 3, 3),
    ]
    picked = select_baselines(rows)[("acme", "software_engineering", "staff")]
    assert picked["base_amount"] == 200_000
    assert select_baselines(list(reversed(rows))) == select_baselines(rows)


def test_a_single_row_band_is_untouched():
    rows = [_Row("acme", "software_engineering", "senior", "L4", 180_000, 50_000, 20_000)]
    assert select_baselines(rows) == {
        ("acme", "software_engineering", "senior"): {
            "base_amount": 180_000,
            "stock_amount": 50_000,
            "bonus_amount": 20_000,
            "provider": None,
            "as_of": None,
        }
    }


# --- a missing part is unknown, never zero ------------------------------------ #
# Our own per-level pay measures base and no grant. Read as `stock_amount or 0`, a
# base-only row would become a MEASURED split that says the company grants no
# equity.


def test_a_base_only_row_is_not_a_measured_split_and_draws_equity_from_the_next_estimator():
    base_only = {"base_amount": 272333, "stock_amount": None, "bonus_amount": None}
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "software_engineering"},
        disclosed=GOOGLE_BAND,
        baselines={("google", "software_engineering", "staff"): base_only},
    )
    assert pkg["split_source"] == SPLIT_HEURISTIC
    assert "equity" in _kinds(pkg), "an unknown grant is not a zero grant"
    assert pkg["equity_basis"] == "ratio"


def test_a_row_missing_one_part_yields_to_a_complete_row_of_another_family():
    pm_base_only = {"base_amount": 250000, "stock_amount": None, "bonus_amount": 20000}
    pkg = build_job_package(
        **{**GOOGLE_879, "family": "product_management"},
        disclosed=GOOGLE_BAND,
        baselines={**BASELINES, ("google", "product_management", "staff"): pm_base_only},
    )
    assert pkg["split_source"] == SPLIT_CROSS_FAMILY
    assert _kinds(pkg)["equity"]["low"] == round(GOOGLE_L6["stock_amount"] * 0.60)


def test_a_measured_zero_is_still_a_value():
    """Anthropic pays no bonus: 0 is measured, not missing, and stays a split."""
    pkg = build_job_package(
        company="anthropic", band="senior", family="software_engineering",
        comp_low=None, comp_median=None, comp_high=None, comp_provenance=None,
        disclosed={**GOOGLE_BAND, "bonus_pct": None},
        baselines=BASELINES,
    )
    assert pkg["split_source"] == SPLIT_MEASURED
    assert "bonus" not in _kinds(pkg)


def test_a_rung_named_another_way_is_still_the_band_s_rung():
    """The band's rung is the atlas rung, recognised by any of its spellings in
    a row's label or aliases: a source that renames the rungs and keeps the
    familiar name as an alias picks the same row. Fail-first: only the exact
    label matched, so the renamed ladder fell to the median row."""
    from tracker.analytics.comp_package import choose_rung_row
    from tracker.levels.ladder import rung_for_band
    from tracker.schema import LevelBand

    rung = rung_for_band("google", LevelBand.SENIOR)
    assert rung is not None

    def row(label, base, aliases=()):
        return SimpleNamespace(company_slug="google", family="software_engineering", band="senior",
                               level_label=label, aliases=aliases, base_amount=base)

    native = [row(rung.code, 100_000), row("L6", 200_000), row("L4", 300_000)]
    renamed = [row("X1", 100_000, (rung.code.lower(),)), row("X2", 200_000, ("L6",)), row("X0", 300_000)]
    unnamed = [row("X1", 100_000), row("X2", 200_000), row("X0", 300_000)]
    assert choose_rung_row("google", "senior", native).base_amount == 100_000
    assert choose_rung_row("google", "senior", renamed).base_amount == 100_000
    # The control: with no spelling of the rung anywhere, the median row.
    assert choose_rung_row("google", "senior", unnamed).base_amount == 200_000


def test_the_package_names_who_supplied_its_split_and_when():
    """The baseline keeps its rung row's provider and as-of date through to the
    package, so Job detail can say whose figures scaled the segments."""
    from datetime import date
    from types import SimpleNamespace

    def rung(provider, as_of, base):
        return SimpleNamespace(company_slug="google", family="software_engineering", band="staff", level_label="L6",
                               aliases=(), base_amount=base, stock_amount=200_000, bonus_amount=40_000,
                               provider=provider, as_of=as_of)

    baselines = select_baselines([rung("levels-plugin", date(2026, 10, 1), 250_000)])
    pkg = build_job_package(**{**GOOGLE_879, "family": "software_engineering"}, disclosed=GOOGLE_BAND,
                            baselines=baselines)
    assert (pkg["split_source"], pkg["split_provider"], pkg["split_as_of"]) == (
        SPLIT_MEASURED, "levels-plugin", "2026-10-01")

    heuristic = build_job_package(**{**GOOGLE_879, "company": "acme"}, disclosed=GOOGLE_BAND, baselines=baselines)
    assert (heuristic["split_provider"], heuristic["split_as_of"]) == (None, None), "no measured split, no supplier"
