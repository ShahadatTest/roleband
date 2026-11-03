"""`levels.pay`: how each company builds an offer, as code.

What these pin: a no-bonus company and an unchecked company are different answers;
the policy percentages agree with the measured per-level splits (the table is not
allowed to contradict the data it summarises); and the package stops inventing a
bonus for companies that pay none.
"""

from __future__ import annotations

from datetime import datetime

from tracker.analytics.comp_package import build_job_package
from tracker.levels.ladder import rung_for_band
from tracker.levels.model import BONUS_NONE, BONUS_PCT_OF_BASE
from tracker.levels.pay import (
    PAY_POLICIES,
    bonus_ratio_for,
    describe,
    policy_for,
    stated_by,
    vesting_for,
)
from tracker.profiles.resolve import Claim, resolve_field
from tracker.schema import LevelBand

# Per-level base and bonus values for the policy agreement check.
_MEASURED = {
    ("google", LevelBand.STAFF): (272333, 58614),  # L6 base, bonus
    ("microsoft", LevelBand.PRINCIPAL): (248000, 36600),  # 67
    ("amazon", LevelBand.PRINCIPAL): (282000, 0),
    ("anthropic", LevelBand.SENIOR): (316000, 0),
    ("openai", LevelBand.SENIOR): (275257, 0),
}


def test_no_bonus_is_zero_and_unverified_is_none():
    assert bonus_ratio_for("amazon", LevelBand.PRINCIPAL) == 0.0
    assert bonus_ratio_for("netflix", "staff") == 0.0
    assert bonus_ratio_for("apple", LevelBand.SENIOR) is None  # not checked -> next estimator
    assert bonus_ratio_for("not-a-company", "senior") is None
    # A pct company at a band the policy does not table is also None, not 0.
    assert policy_for("google").bonus_rule == BONUS_PCT_OF_BASE
    assert bonus_ratio_for("google", LevelBand.ENTRY) is None


def test_policy_percentages_agree_with_measured_splits():
    """A policy that contradicts the measured bonus/base ratio is wrong somewhere. The
    tolerance is the realised-vs-target gap (rating multipliers below 1.0, proration).
    Six points covers that gap; it is not a licence for a wrong table."""
    for (company, band), (base, bonus) in _MEASURED.items():
        policy = policy_for(company)
        realised = bonus / base
        if policy.bonus_rule == BONUS_NONE:
            assert realised == 0.0, (company, band)
            continue
        target = rung_for_band(company, band).bonus_target
        assert target is not None, (company, band)
        lo, hi = target
        assert lo - 0.06 <= realised <= hi + 0.06, (company, band, round(realised, 3), (lo, hi))


def test_verified_policy_keeps_its_checked_date_without_source_ids():
    from tracker.levels.pay import profile_offer

    policy = policy_for("google")
    assert policy.is_verified
    assert describe("google")["verified"] is True
    assert profile_offer("google")["verified_on"] == policy.verified.isoformat()


def test_vesting_is_read_from_the_policy_table():
    assert vesting_for("amazon") == "5/15/40/40"
    assert vesting_for("google") == "38/32/20/10"  # new-hire grants since ~2023
    assert vesting_for("jane-street") is None  # unverified stays absent, never a default


def test_describe_renders_unverified_as_none_not_zero():
    d = describe("jane-street")
    assert d["verified"] is False
    assert d["bonus_rule"] is None and d["vesting"] is None
    a = describe("amazon")
    assert a["bonus_rule"] == BONUS_NONE
    assert a["vesting"] == "5/15/40/40" and a["sign_on_bridges_vesting"] is True


def test_package_does_not_invent_a_bonus_for_a_no_bonus_company():
    """Amazon director_plus with no measured row gets no bonus, never comp_split's flat 12%."""
    pkg = build_job_package(
        company="amazon",
        band="director_plus",
        family="product_management",
        comp_low=900000,
        comp_median=1000000,
        comp_high=1100000,
        comp_provenance="seed",
        disclosed={
            "disclosed": True,
            "base_min": 250000,
            "base_max": 350000,
            "currency": "USD",
            "pay_basis": "base",
            "pay_period": "year",
            "bonus_pct": None,
            "snippet": "…",
            "confidence": "high",
        },
        baselines={},
    )
    assert pkg["split_source"] == "heuristic"
    assert {c["kind"] for c in pkg["components"]} == {"base", "equity"}
    assert pkg["policy"]["vesting"] == "5/15/40/40"


def test_package_uses_the_policy_bonus_where_no_split_is_measured():
    pkg = build_job_package(
        company="google",
        band="staff",
        family="product_management",
        comp_low=400000,
        comp_median=500000,
        comp_high=600000,
        comp_provenance="seed",
        disclosed={
            "disclosed": True,
            "base_min": 200000,
            "base_max": 200000,
            "currency": "USD",
            "pay_basis": "base",
            "pay_period": "year",
            "bonus_pct": None,
            "snippet": "…",
            "confidence": "high",
        },
        baselines={},
    )
    bonus = next(c for c in pkg["components"] if c["kind"] == "bonus")
    assert bonus["low"] == round(200000 * 0.225)  # L6 target 20-25%, midpoint
    assert bonus["provenance"] == "estimated"


# --- who states a fact ------------------------------------------ #


def test_each_fact_says_whether_the_employer_states_it_or_it_is_estimated():
    assert stated_by("google", "bonus_rule") == "employer"  # its postings print "+ N% bonus target"
    assert stated_by("google", "vesting") == "estimated"  # no Google document states 38/32/20/10
    assert stated_by("amazon", "vesting") == "estimated"
    assert stated_by("amazon", "annual_refresh") == "employer"  # 10-K: grants at the annual review
    assert stated_by("microsoft", "vesting") == "employer"  # 10-K: "vest ratably"
    assert stated_by("microsoft", "bonus_rule") == "estimated"  # employees and the press report it
    assert stated_by("anthropic", "annual_refresh") == "employer"  # its posting names the program
    assert stated_by("nvidia", "bonus_rule") == "estimated"
    assert describe("google")["estimated"] == ["equity_rule", "vesting", "annual_refresh"]
    assert describe("mongodb")["estimated"] == []


def test_the_verification_run_corrects_and_adds_only_well_supported_facts():
    assert vesting_for("google") == "38/32/20/10"
    assert policy_for("nvidia").bonus_rule == BONUS_NONE
    assert vesting_for("openai") == "25/25/25/25"  # quarterly, no cliff
    # Below the bar (score 1.0 or a single template): not shipped.
    assert vesting_for("nvidia") is None
    assert vesting_for("anthropic") is None


def _claim(source, value, day):
    return Claim("vesting_schedule", value, source, datetime(2026, 10, day))


def test_a_reported_fact_outranks_an_old_claim_under_a_source_no_longer_ranked():
    # A claim under a source the core does not rank stays (append-only). A
    # reported or employer claim must win over it, whatever the date.
    stale = _claim("acme.legacy", "33/33/22/12", 9)
    assert resolve_field([stale, _claim("estimated", "38/32/20/10", 1)], datetime(2026, 10, 9)).value == "38/32/20/10"
    assert resolve_field([_claim("estimated", "a", 9), _claim("employer", "b", 1)], datetime(2026, 10, 9)).value == "b"


# --- searched, nothing found ------------------------------------ #


def test_unknown_is_an_answer_with_a_date_never_a_value():
    from tracker.levels.completeness import answered

    jane = policy_for("jane-street")
    assert "bonus_rule" in jane.unknown and "vesting" in jane.unknown
    # The scoreboard counts it: the company was searched and says nothing.
    assert answered("bonus_rule", "jane-street") and answered("vesting", "jane-street")
    # An unverified value supplies no policy fact to pay math or the package.
    assert jane.bonus_rule == "unverified" and vesting_for("jane-street") is None
    assert bonus_ratio_for("jane-street", LevelBand.SENIOR) is None
    assert describe("jane-street")["unknown"] == ["bonus_rule", "equity_rule", "vesting", "annual_refresh"]
    assert describe("jane-street")["verified"] is False  # nothing found is not a checked policy


def test_trading_firms_with_no_stock_answer_equity_none_as_reported():
    # Reported per-level pay shows ~$0 stock at every level and postings name no equity.
    for firm in ("two-sigma", "drw", "optiver", "susquehanna-international-group"):
        assert policy_for(firm).equity_rule == "none" and policy_for(firm).stated_by("equity_rule") == "estimated"
    # Firms whose reported pay shows stock stay unknown, never none.
    assert "equity_rule" in policy_for("jane-street").unknown
    assert "equity_rule" in policy_for("hudson-river-trading").unknown


# --- one-year grants: company profile only ----------------------- #


def test_a_grant_term_reaches_the_company_profile_never_a_job():
    from tracker.levels.completeness import answered
    from tracker.levels.pay import profile_vesting

    # Coinbase and Stripe grant equity one year at a time; Netflix's options vest when granted.
    assert profile_vesting("coinbase") == ("one_year_grants", "employer")
    assert profile_vesting("stripe") == ("one_year_grants", "estimated")
    assert profile_vesting("netflix") == ("vested_at_grant", "employer")
    # A job's package reads no multi-year fraction for them: listings are unchanged.
    for company in ("coinbase", "stripe", "netflix"):
        assert vesting_for(company) is None and describe(company)["vesting"] is None
        assert answered("vesting", company)
    # A stated schedule outranks the one-year-grant marker on the profile.
    assert profile_vesting("google") == ("38/32/20/10", "estimated")
    assert profile_vesting("asana") is None  # one-year grants rest on two forum snippets: below the bar


# --- the company profile's offer facts (`profile_offer`) ----------------------


def test_profile_offer_separates_stated_searched_and_not_researched(monkeypatch):
    """Three answers that must not collapse into one dash: a stated fact with who
    states it, a fact searched for and not found, and a company never researched."""
    from datetime import date

    from tracker.levels.model import PayPolicy
    from tracker.levels.pay import profile_offer

    monkeypatch.setitem(PAY_POLICIES, "acme", PayPolicy(
        "acme",
        bonus_rule=BONUS_NONE,
        equity_rule="unverified",
        base_cap_usd=200000,
        verified=date(2026, 10, 9),
        estimated=("base_cap_usd",),
        unknown=("equity_rule", "annual_refresh", "vesting"),
    ))
    assert profile_offer("acme") == {
        "verified_on": "2026-10-09",
        "facts": [
            {"fact": "equity_rule", "value": None, "stated_by": None},
            {"fact": "bonus_rule", "value": "none", "stated_by": "employer"},
            {"fact": "annual_refresh", "value": None, "stated_by": None},
            # Recorded only where it holds: false is not "searched and not found".
            {"fact": "base_cap_usd", "value": 200000, "stated_by": "estimated"},
        ],
        "unknown_fields": ["vesting_schedule"],
    }
    assert profile_offer("never-researched") is None


def test_a_grant_term_answers_the_vesting_row(monkeypatch):
    from tracker.levels.model import PayPolicy
    from tracker.levels.pay import profile_offer

    monkeypatch.setitem(PAY_POLICIES, "acme", PayPolicy("acme", grant_term="one_year", unknown=("vesting",)))
    assert profile_offer("acme")["unknown_fields"] == []
