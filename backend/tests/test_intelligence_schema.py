"""Grounding + coercion for disclosed-salary-band extraction (pure, no DB/network).

The core invariant: a band survives ONLY if the model's snippet appears verbatim
(post-normalization) in the posting text. Everything else collapses to
disclosed=false; no band is invented. The fixture includes a Unicode dash
to exercise normalization against an ASCII hyphen.
"""

from __future__ import annotations

import pytest

from tracker.intelligence.schema import coerce_disclosed_comp, snippet_grounded
from tracker.pay_disclosure import (
    DisclosedComp,
    PayBasis,
    derive_bonus_pct,
    derive_pay_basis,
    locate_pay_span,
)
from tracker.pay_period import PayPeriod
from tracker.platform.util import normalize_text

# The fixture includes a Unicode dash and NBSP. Its OTE sentence is
# conditional on sales roles, while the posting is for a program manager.
# See test_anthropic_conditional_ote_*.
JOB1_DESC = (
    "The annual compensation range for this role is listed below.\xa0\n\n"
    "For sales roles, the range provided is the role’s On Target Earnings "
    '("OTE") range, meaning that the range includes both the sales commissions/'
    "sales bonuses target and annual base salary for the role.\n\n"
    "Annual Salary:\n$210,000—$260,000 USD\n\nLogistics\n"
)


def test_grounded_band_from_job1_is_extracted():
    raw = {
        "disclosed": True,
        "base_min": 210000,
        "base_max": 260000,
        "currency": "USD",
        "pay_basis": "total",
        "pay_period": "year",
        "source_snippet": "$210,000—$260,000 USD",
        "confidence": "high",
    }
    dc = coerce_disclosed_comp(raw, JOB1_DESC)
    assert dc.disclosed is True
    assert dc.base_min == 210000 and dc.base_max == 260000
    assert dc.currency == "USD"
    # The model said "total"; the posting's only inclusive language is the
    # "For sales roles" boilerplate, which does not apply to this role.
    assert dc.pay_basis is PayBasis.unclear
    assert dc.pay_period is PayPeriod.year


def test_snippet_dash_variant_still_grounds():
    # Posting has an em-dash; model returns an ASCII hyphen. Normalization unifies
    # both sides, so the snippet still grounds.
    raw = {
        "disclosed": True,
        "base_min": 210000,
        "base_max": 260000,
        "currency": "USD",
        "source_snippet": "$210,000-$260,000 USD",
    }
    dc = coerce_disclosed_comp(raw, JOB1_DESC)
    assert dc.disclosed is True
    assert dc.base_max == 260000


def test_ungrounded_band_is_rejected():
    # A plausible band the posting never states must NOT survive.
    raw = {
        "disclosed": True,
        "base_min": 400000,
        "base_max": 500000,
        "currency": "USD",
        "source_snippet": "$400,000-$500,000 USD",
    }
    dc = coerce_disclosed_comp(raw, JOB1_DESC)
    assert dc.disclosed is False
    assert dc.base_min is None and dc.base_max is None


def test_stitched_snippet_still_accepted_and_quote_is_rewritten():
    """A model can produce the RIGHT band but build its snippet by concatenating
    two non-adjacent sentences, so a verbatim-substring check on the model's
    snippet would reject a correct extraction. We locate the numbers in the
    posting ourselves, so the band survives and the stored quote is verbatim."""
    raw = {
        "disclosed": True,
        "base_min": 210000,
        "base_max": 260000,
        "currency": "USD",
        "pay_basis": "total",
        "pay_period": "year",
        # Not contiguous anywhere in JOB1_DESC — the model stitched it together.
        "source_snippet": (
            "The annual compensation range for this role is listed below. "
            "Annual Salary: $210,000—$260,000 USD"
        ),
    }
    dc = coerce_disclosed_comp(raw, JOB1_DESC)
    assert dc.disclosed is True
    assert dc.base_min == 210000 and dc.base_max == 260000
    # The stored quote is OURS, sliced from the posting — so it is verbatim by
    # construction, not whatever the model handed us.
    assert dc.source_snippet != raw["source_snippet"]
    assert snippet_grounded(dc.source_snippet, JOB1_DESC) is True


def test_bounds_far_apart_in_the_document_are_rejected():
    # Two numbers that exist but never co-occur in one pay statement must not be
    # assembled into a band.
    desc = "We serve 180,000 customers." + (" filler" * 80) + " Our fund raised 240,000 dollars."
    raw = {
        "disclosed": True,
        "base_min": 180000,
        "base_max": 240000,
        "source_snippet": "180,000 ... 240,000",
    }
    assert coerce_disclosed_comp(raw, desc).disclosed is False


def test_reversed_bounds_are_swapped():
    # Both numbers ARE stated in the snippet, so a reversed pair is just an
    # ordering slip and is safe to correct.
    raw = {
        "disclosed": True,
        "base_min": 260000,
        "base_max": 210000,
        "source_snippet": "$210,000—$260,000 USD",
    }
    dc = coerce_disclosed_comp(raw, JOB1_DESC)
    assert dc.base_min == 210000 and dc.base_max == 260000


def test_digit_slip_is_rejected_not_swapped():
    """A model can return base_min=1800000 for a posting stating "$180,000". The
    snippet is verbatim, so the substring gate passes, and a blind swap would
    produce a plausible-looking $240k-$1.8M band. The number must be
    corroborated by the quoted text, or the whole band is dropped."""
    desc = "The annual base salary range for this role is $180,000—$240,000 USD."
    raw = {
        "disclosed": True,
        "base_min": 1800000,  # model added a digit
        "base_max": 240000,
        "currency": "USD",
        "source_snippet": "The annual base salary range for this role is $180,000—$240,000 USD.",
    }
    dc = coerce_disclosed_comp(raw, desc)
    assert dc.disclosed is False
    assert dc.base_min is None and dc.base_max is None


def test_k_shorthand_corroborates():
    desc = "Base pay: $180K–$240K per year."
    raw = {
        "disclosed": True,
        "base_min": 180000,  # model expanded 180K -> 180000; the text supports it
        "base_max": 240000,
        "source_snippet": "$180K–$240K",
    }
    dc = coerce_disclosed_comp(raw, desc)
    assert dc.disclosed is True
    assert dc.base_min == 180000 and dc.base_max == 240000


def test_derived_value_not_stated_in_text_is_rejected():
    # Annualizing an hourly rate is inference, not disclosure.
    desc = "This role pays $100 per hour."
    raw = {
        "disclosed": True,
        "base_min": 208000,  # 100 * 2080 — never written in the posting
        "base_max": 208000,
        "source_snippet": "This role pays $100 per hour.",
    }
    assert coerce_disclosed_comp(raw, desc).disclosed is False


def test_out_of_range_value_rejected():
    raw = {
        "disclosed": True,
        "base_min": 210000,
        "base_max": 999_999_999,  # above the sanity ceiling
        "source_snippet": "$210,000—$260,000 USD",
    }
    dc = coerce_disclosed_comp(raw, JOB1_DESC)
    assert dc.disclosed is False


def test_bogus_currency_is_dropped_not_stored():
    """A model can return the literal string "CURRENCY" for this field. Validate
    against ISO codes rather than trust free text."""
    raw = {
        "disclosed": True,
        "base_min": 210000,
        "base_max": 260000,
        "currency": "CURRENCY",
        "source_snippet": "$210,000—$260,000 USD",
    }
    dc = coerce_disclosed_comp(raw, JOB1_DESC)
    assert dc.disclosed is True  # the band itself is fine
    assert dc.currency is None  # ...but the junk currency is dropped


def test_known_currency_survives():
    raw = {
        "disclosed": True,
        "base_min": 210000,
        "base_max": 260000,
        "currency": "usd",
        "source_snippet": "$210,000—$260,000 USD",
    }
    assert coerce_disclosed_comp(raw, JOB1_DESC).currency == "USD"


def test_disclosed_false_and_non_dict_are_safe():
    assert coerce_disclosed_comp({"disclosed": False}, JOB1_DESC).disclosed is False
    assert coerce_disclosed_comp(None, JOB1_DESC).disclosed is False
    assert coerce_disclosed_comp("nope", JOB1_DESC).disclosed is False


def test_snippet_without_digit_is_not_grounded():
    # "compensation" appears in the text but is not a pay reference (no digit).
    assert snippet_grounded("competitive compensation", JOB1_DESC) is False


def test_snippet_must_actually_appear():
    assert snippet_grounded("$210,000—$260,000 USD", JOB1_DESC) is True
    assert snippet_grounded("$999,000", JOB1_DESC) is False


def test_normalize_is_symmetric_for_dashes_and_nbsp():
    assert normalize_text("$210,000—$260,000\xa0USD") == normalize_text(
        "$210,000-$260,000 USD"
    )


def test_missing_bounds_rejected_even_if_grounded():
    raw = {"disclosed": True, "source_snippet": "$210,000—$260,000 USD"}
    assert coerce_disclosed_comp(raw, JOB1_DESC).disclosed is False


def test_default_model_is_empty():
    assert DisclosedComp().disclosed is False


# --- pay_basis derivation -----------------------------------------------------
#
# Bonus or equity near a band does not mean it is bundled: the text may
# state that those components are added. Basis is derived from the text,
# independently of the model label.

# Additive bonus and equity leave the range as base salary.
GOOGLE_DESC = (
    "Individual pay is determined by factors including job-related skills, "
    "experience, and relevant education or training."
    "US: $240000 - $334000 (USD) + 25% bonus target + equity + benefits"
    "Learn more aboutbenefits at Google."
)

# The posting explains that the compensation amount is employee-
# allocated between salary and stock options; it is total eligible compensation.
NETFLIX_DESC = (
    "Generally, our compensation structure consists solely of an annual salary; we do not "
    "have bonuses. You choose each year how much of your compensation you want in salary "
    "versus stock options. To determine your personal top of market compensation, we rely "
    "on market indicators and consider your specific job family, background, skills, and "
    "experience to "
    "determine your compensation in the market range. The range for this role is "
    "$440,000.00 - $725,000.00.\n"
    "Netflix provides comprehensive benefits including Health Plans, Mental Health "
    "support, a 401(k) Retirement Plan with employer match, Stock Option "
)


def test_google_additive_wording_is_base_not_total():
    """"$240000 - $334000 (USD) + 25% bonus target + equity": the bonus and equity
    are ADDED to the range, so the range is base salary, not "total"."""
    assert derive_pay_basis(GOOGLE_DESC, [240000, 334000]) is PayBasis.base


def test_google_band_coerces_to_base_despite_model_saying_total():
    raw = {
        "disclosed": True,
        "base_min": 240000,
        "base_max": 334000,
        "currency": "USD",
        "pay_basis": "total",  # what the model actually returned
        "pay_period": "year",
        "source_snippet": "US: $240000 - $334000 (USD) + 25% bonus target + equity",
    }
    dc = coerce_disclosed_comp(raw, GOOGLE_DESC)
    assert dc.disclosed is True
    assert dc.pay_basis is PayBasis.base  # derived from text, not taken from the model


def test_unconditional_inclusive_wording_is_total():
    """A real sales posting states the OTE bundle without a conditional guard."""
    desc = (
        "Annual Salary:\n$210,000—$260,000 USD\n"
        "This range includes both the sales commissions/sales bonuses target and "
        "annual base salary for the role."
    )
    assert derive_pay_basis(desc, [210000, 260000]) is PayBasis.total


def test_anthropic_conditional_ote_boilerplate_is_not_total():
    """Anthropic pastes "For sales roles, the range provided is the role's
    On Target Earnings ("OTE") range, meaning that the range includes both..." onto
    EVERY posting. Job 1 is a Program Manager, not a sales role, so the clause does not
    describe its band. Reading the marker literally mislabels every non-sales band
    "total", trading one wrong label for another."""
    assert derive_pay_basis(JOB1_DESC, [210000, 260000]) is PayBasis.unclear


def test_anthropic_conditional_guard_does_not_suppress_a_real_marker():
    """The guard must scope to its own sentence: a genuinely inclusive statement
    elsewhere in the posting still counts, even though the boilerplate is present."""
    desc = JOB1_DESC + "\nThe range above is inclusive of your target bonus.\n"
    assert derive_pay_basis(desc, [210000, 260000]) is PayBasis.total


def test_netflix_employee_election_makes_range_total_compensation():
    assert derive_pay_basis(NETFLIX_DESC, [440000, 725000]) is PayBasis.total


def test_bare_range_with_no_basis_language_is_unclear():
    desc = "The range for this role is $440,000.00 - $725,000.00."
    assert derive_pay_basis(desc, [440000, 725000]) is PayBasis.unclear


def test_explicit_base_salary_wording_is_base():
    desc = "The annual base salary range for this role is $180,000—$240,000 USD."
    assert derive_pay_basis(desc, [180000, 240000]) is PayBasis.base


def test_base_pay_colon_wording_is_base():
    desc = "Base pay: $250,800 - $376,300. This range varies by location."
    assert derive_pay_basis(desc, [250800, 376300]) is PayBasis.base


def test_inclusive_beats_additive_when_both_present():
    """"total compensation range" is decisive even though "+ equity" also appears."""
    desc = (
        "The total compensation range for this role is $300,000 - $400,000, "
        "which comprises base + equity."
    )
    assert derive_pay_basis(desc, [300000, 400000]) is PayBasis.total


def test_bonus_eligibility_sentence_marks_the_band_as_base():
    desc = (
        "Salary range: $150,000 - $200,000. You will also be eligible for an annual "
        "bonus and equity awards."
    )
    assert derive_pay_basis(desc, [150000, 200000]) is PayBasis.base


def test_marker_outside_the_stored_quote_pad_is_still_seen():
    """The stored quote keeps only ±50 chars, but markers routinely sit further out.
    Basis derivation uses a wider window, so a marker ~150 chars away still counts."""
    filler = "x" * 150
    desc = f"Base pay range: $150,000 - $200,000. {filler} In addition, you are eligible for equity."
    assert derive_pay_basis(desc, [150000, 200000]) is PayBasis.base


# Amazon's live wording, verbatim shape: the sentence that says what the band IS, then
# ~660 characters of benefits prose, then the band alone on its own line.
_AMAZON_LISTED_BELOW = (
    "The base salary range for this position is listed below. Your Amazon package will "
    "include sign-on payments and restricted stock units (RSUs). Final compensation "
    "will be determined based on factors including experience, qualifications, and "
    "location. Amazon also offers comprehensive benefits including health insurance "
    "(medical, dental, vision, prescription, Basic Life & AD&D insurance and option "
    "for Supplemental life plans, EAP, Mental Health Support, Medical Advice Line, "
    "Flexible Spending Accounts, Adoption and Surrogacy Reimbursement coverage), "
    "401(k) matching, paid time off, and parental leave. Learn more about our benefits "
    "at https://amazon.jobs/en/benefits.\n\n"
    "USA, NY, New York - 169,000.00 - 228,600.00 USD annually"
)


def test_declaration_separated_from_the_band_by_boilerplate_is_still_base():
    """The declaration and the number it declares are one statement even when a
    benefits paragraph sits between them. A fixed +-300 window reaches neither end of
    it, and would downgrade most of amazon's `base` rows to `unclear`."""
    assert derive_pay_basis(_AMAZON_LISTED_BELOW, [169000, 228600]) is PayBasis.base


def test_geographic_market_ranges_from_wording_is_base():
    """"The base pay for this position RANGES from" is an explicit base statement that
    the `base pay range` forms miss on the plural verb alone."""
    desc = (
        "Our compensation reflects the cost of labor across several US geographic "
        "markets. The base pay for this position ranges from $196,900/year in our "
        "lowest geographic market up to $340,300/year in our highest geographic market."
    )
    assert derive_pay_basis(desc, [196900, 340300]) is PayBasis.base


def test_a_product_range_that_includes_things_is_not_a_pay_range():
    """`range includes` fires on any range at all unless it names a pay component.
    Google prints "our product range includes Pixel phones" in the same block as a real
    base band; reading it as an inclusive marker relabels a correct `base` as `total`."""
    desc = (
        "Google Store is the authoritative place to buy our hardware, and our product "
        "range includes Pixel phones, Pixel Watch, Fitbit and accessories.\n\n"
        "The US base salary range for this full-time position is $192,000 - $279,000 "
        "plus bonus, equity and benefits."
    )
    assert derive_pay_basis(desc, [192000, 279000]) is PayBasis.base


def test_a_band_inclusive_of_career_levels_is_not_inclusive_of_pay():
    """Scale's wording: the range spans LEVELS, not components. Read as an inclusive
    marker it makes the band "total" — a claim the posting never makes, and one that
    stops the package being decomposed at all."""
    desc = (
        "Compensation packages at Scale for eligible roles include base salary, "
        "equity, and benefits. The range displayed on each job posting reflects the "
        "minimum and maximum target for new hire salaries and may be inclusive of "
        "several career levels; it will be determined during the interview process.\n\n"
        "$300,000 - $400,000 USD"
    )
    assert derive_pay_basis(desc, [300000, 400000]) is PayBasis.unclear
    # The same block, once the posting does declare what the band is.
    assert derive_pay_basis(
        desc.replace("$300,000", "The base salary range is $300,000"),
        [300000, 400000],
    ) is PayBasis.base


def test_on_target_earnings_for_commissionable_roles_is_conditional():
    """Databricks pastes this onto every posting, commissioned or not — the same
    guard-rail as Anthropic's OTE boilerplate, spelled `commissionable`."""
    desc = (
        "Databricks is committed to fair and equitable compensation practices. The pay "
        "range for this role is listed below and represents the expected salary range "
        "for non-commissionable roles or on-target earnings for commissionable roles.\n\n"
        "$226,000 - $285,000 USD"
    )
    assert derive_pay_basis(desc, [226000, 285000]) is PayBasis.unclear


def test_sales_positions_boilerplate_does_not_make_a_stated_base_total():
    """ServiceNow prints this under every band, product managers included. The OTE
    sentence is about sales positions; the band's own sentence says base."""
    desc = (
        "For positions in this location, we offer a base pay of $221,200 - $387,100, plus "
        "equity (when applicable), variable/incentive compensation and benefits. Sales "
        "positions generally offer a competitive On Target Earnings (OTE) incentive "
        "compensation structure."
    )
    assert derive_pay_basis(desc, [221200, 387100]) is PayBasis.base


def test_eligible_to_receive_incentives_beside_the_sales_sentence_is_base():
    """Cadence: the same sales sentence, and the extras stated as added to the band."""
    desc = (
        "The annual salary range for California is $178,500 to $331,500. You may also be "
        "eligible to receive incentive compensation: bonus, equity, and benefits. Sales "
        "positions generally offer a competitive On Target Earnings (OTE) incentive "
        "compensation structure."
    )
    assert derive_pay_basis(desc, [178500, 331500]) is PayBasis.base


def test_not_inclusive_of_equity_is_the_opposite_of_inclusive():
    """Negated inclusive wording must not be read as bundling extra components."""
    desc = (
        "The expected base pay range for this position in the San Francisco area is "
        "$176,000 - $220,000, not inclusive of potential equity offering, bonus or benefits."
    )
    assert derive_pay_basis(desc, [176000, 220000]) is PayBasis.base
    # The control: without "not", the same words still bundle the extras.
    assert derive_pay_basis(desc.replace("not inclusive", "inclusive"), [176000, 220000]) is PayBasis.total


@pytest.mark.parametrize("extras", [
    # Zipline and LinkedIn
    "The total compensation package for this role may also include: equity compensation; "
    "discretionary annual or performance bonuses; sales incentives; benefits.",
    # PayPal
    "Additional compensation for this role may include an annual performance bonus, "
    "equity, or other incentive compensation, as applicable.",
    # Brex and Amazon
    "Depending on the position offered, equity and other forms of compensation may be "
    "provided as part of a total compensation package.",
])
def test_extras_the_package_may_add_make_the_band_base(extras):
    desc = f"The pay range for this role is $195,000 - $245,000. {extras}"
    assert derive_pay_basis(desc, [195000, 245000]) is PayBasis.base
    # The control: the band alone says nothing.
    assert derive_pay_basis("The pay range for this role is $195,000 - $245,000.", [195000, 245000]) is PayBasis.unclear


@pytest.mark.parametrize("sentence", [
    "The expected salary range for this role is $240,000 - $300,000. However, the starting "
    "base pay will depend on a number of factors.",  # Brex
    "The base pay for this role will depend on where you work. $196,500 - $291,500",  # PayPal
])
def test_a_band_sentence_that_names_base_pay_is_base(sentence):
    bounds = [240000, 300000] if "240,000" in sentence else [196500, 291500]
    assert derive_pay_basis(sentence, bounds) is PayBasis.base


def test_a_band_defined_per_kind_of_role_stays_unclear_whatever_else_is_added():
    """Databricks: base for non-commissionable roles, on-target earnings for the rest.
    The package's extras hold for both kinds of role, so they do not settle it."""
    desc = (
        "The pay range for this role is listed below and represents the expected base "
        "salary range for non-commissionable roles or on-target earnings for commissionable "
        "roles. The total compensation package for this position may also include "
        "eligibility for annual performance bonus, equity, and the benefits listed above.\n\n"
        "$226,000 - $285,000 USD"
    )
    assert derive_pay_basis(desc, [226000, 285000]) is PayBasis.unclear


def test_starting_base_salary_for_non_sales_roles_or_commission_stays_unclear():
    """Palo Alto Networks names base, but only for non-sales roles."""
    desc = (
        "For candidates who receive an offer at the posted level, the starting base salary "
        "(for non-sales roles) or base salary + commission target (for sales/commissioned "
        "roles) is expected to be the annual range listed below.\n\n$185,900 - $300,675/yr"
    )
    assert derive_pay_basis(desc, [185900, 300675]) is PayBasis.unclear


def test_a_bonus_plan_for_non_sales_roles_is_not_a_band_defined_per_kind_of_role():
    """Figma says who gets a bonus, not what the band means: its base stays base."""
    desc = (
        "Figma offers equity, sales incentive compensation for most sales roles and an "
        "annual bonus plan for eligible non-sales roles.\n\nAnnual Base Salary Range:\n"
        "$258,000—$376,000 USD"
    )
    assert derive_pay_basis(desc, [258000, 376000]) is PayBasis.base


def test_basis_is_unclear_when_the_band_cannot_be_located():
    assert derive_pay_basis(GOOGLE_DESC, [999999]) is PayBasis.unclear
    assert derive_pay_basis("", [240000]) is PayBasis.unclear


def _bonus(desc: str, bounds: list[int]) -> float | None:
    """The bonus share read around the band, against the basis its own markers give."""
    return derive_bonus_pct(desc, locate_pay_span(desc, bounds), derive_pay_basis(desc, bounds))


def test_google_states_its_bonus_target_and_we_capture_it():
    """"+ 25% bonus target" is a STATED fact, not an estimate — the posting says the
    bonus is 25% of base. Capturing it turns bonus from a modelled number into a
    quoted one on every Google role."""
    assert _bonus(GOOGLE_DESC, [240000, 334000]) == 0.25


def test_bonus_pct_reaches_the_coerced_band():
    raw = {
        "disclosed": True,
        "base_min": 240000,
        "base_max": 334000,
        "currency": "USD",
        "pay_basis": "total",
        "source_snippet": "US: $240000 - $334000 (USD) + 25% bonus target + equity",
    }
    dc = coerce_disclosed_comp(raw, GOOGLE_DESC)
    assert dc.pay_basis is PayBasis.base
    assert dc.bonus_pct == 0.25


def test_a_target_written_to_two_decimals_is_read_whole():
    """Google writes some targets to two places: "+ 42.86% bonus target" is 42.86%,
    never the "86%" left after the first decimal, which the ceiling would drop."""
    desc = "US: $127000 - $184000 (USD) + 42.86% bonus target + equity + benefits"
    bounds = [127000, 184000]
    assert _bonus(desc, bounds) == 0.4286
    # Negative controls: a target is never read from inside a longer number, and
    # a share past the ceiling is still dropped however it is written.
    assert _bonus(desc.replace("42.86", "142.86"), bounds) is None
    assert _bonus(desc.replace("42.86", "66.67"), bounds) is None


def test_prose_bonus_percentage_is_captured():
    desc = (
        "The base salary range for this role is $150,000 - $200,000. You will also be "
        "eligible for an annual bonus of 15% of base salary."
    )
    assert _bonus(desc, [150000, 200000]) == 0.15


def test_no_stated_percentage_means_no_bonus_pct():
    """"+ equity + benefits" with no number: we must not invent a bonus share."""
    desc = "Base salary range: $150,000 - $200,000 (USD) + equity + benefits."
    assert _bonus(desc, [150000, 200000]) is None


def test_bonus_pct_is_none_when_the_basis_is_not_base():
    """A "25% bonus target" only means something against a BASE band. Against Anthropic's
    unclear band it would be an invented fact, so we refuse it."""
    desc = JOB1_DESC + "\nThere is also a 25% bonus target.\n"
    assert derive_pay_basis(desc, [210000, 260000]) is PayBasis.unclear
    assert _bonus(desc, [210000, 260000]) is None


def test_implausible_percentage_is_dropped_not_stored():
    """A stray percentage near the band (equity refresh, 401k match) must not be read as
    a bonus target. Anything above the sane ceiling is dropped rather than guessed."""
    desc = "Base salary range: $150,000 - $200,000, plus a bonus of 95%."
    assert _bonus(desc, [150000, 200000]) is None


def test_netflix_total_range_yields_no_bonus_pct():
    assert _bonus(NETFLIX_DESC, [440000, 725000]) is None


def test_additive_marker_from_a_distant_paragraph_does_not_leak():
    """A bonus sentence far from the band must not turn an unstated basis into "base"
    — the window is bounded, not the whole document."""
    desc = (
        "The range for this role is $440,000.00 - $725,000.00.\n\n"
        + ("Filler paragraph about the team.\n\n" * 60)
        + "Separately, our sales staff are eligible for a bonus."
    )
    assert derive_pay_basis(desc, [440000, 725000]) is PayBasis.unclear
    # ...and the ceiling holds even with no paragraph break to stop at.
    run_on = "The range for this role is $440,000.00 - $725,000.00." + (
        " filler" * 400
    ) + " Separately, our sales staff are eligible for a bonus."
    assert derive_pay_basis(run_on, [440000, 725000]) is PayBasis.unclear
