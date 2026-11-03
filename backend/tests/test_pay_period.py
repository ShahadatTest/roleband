"""Per hour, per month or per year: one rule for every pay source.

A rule that reads an hour word ANYWHERE in the pay text shows salaries as
hourly rates, and one that reads only commas as thousands reads Elastic's
"€104.800" as €104. Every text below is verbatim from a real posting, or the
smallest edit of one, and each is a negative control for a plausible
broken rule: words-anywhere fails Netflix, comma-only numbers fail Elastic,
size-blind reading fails the stipend and the "Hourly rate" salary.
"""

from __future__ import annotations

import pytest

from tracker.analytics.comp_package import build_job_package
from tracker.analytics.comp_residual import build_equity_residuals
from tracker.connectors.detail.ashby import AshbyDetailConnector
from tracker.pay_disclosure import extract_grounded_band
from tracker.pay_period import PayPeriod, decide_period, effective_period, size_class, size_classes


def _band(text: str):
    return extract_grounded_band(text, text)


# --------------------------------------------------------------------------- #
# Words count only next to the amount
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("text", [
    # Netflix: the benefits paragraph under the band.
    "The range for this role is $600,000.00 - $1,066,000.00. This compensation range is "
    "determined by the market. We also offer paid leave of absence programs. Full-time "
    "hourly employees accrue 35 days annually for paid time off.",
    # Illumia: a legal notice after the band.
    "Base Salary: $142,000 - $200,000 This position is classified as Exempt under the Fair "
    "Labor Standards Act (FLSA) and applicable state wage-and-hour laws.",
    # Langan: names both, so says nothing.
    "Certain US jurisdictions require us to include an estimate of salary or hourly ranges. "
    "Pay Range $96,750—$140,000 USD",
])
def test_an_hour_word_away_from_the_amount_does_not_make_a_salary_hourly(text):
    band = _band(text)
    assert band.disclosed
    assert band.pay_period is PayPeriod.year


def test_a_stray_hour_word_elsewhere_cannot_move_a_salary():
    # Netflix's text without its later "annually": the only period word left is
    # the benefits line's "hourly", two sentences away.
    band = _band(
        "The range for this role is $600,000.00 - $1,066,000.00. This compensation range "
        "is determined by the market. Full-time hourly employees accrue paid time off."
    )
    assert band.pay_period is PayPeriod.year


def test_a_word_in_the_next_sentence_does_not_cancel_the_amounts_own():
    # Cobalt, verbatim: "hourly" is in the amount's sentence, "salary" in the next.
    band = _band(
        "The hourly range for this role is $84 - $106. A candidate’s salary is "
        "determined by various factors including location and experience."
    )
    assert (band.base_min, band.base_max) == (84, 106)
    assert band.pay_period is PayPeriod.hour


def test_a_unit_next_to_the_amount_outranks_a_general_word():
    band = _band("Salary: €4,500 - €5,500 per month, depending on experience.")
    assert (band.base_min, band.base_max, band.currency) == (4500, 5500, "EUR")
    assert band.pay_period is PayPeriod.month


def test_a_word_that_contradicts_the_size_is_could_not_tell():
    band = _band("Hourly rate: $150,000 - $200,000")
    assert band.disclosed and band.pay_period is PayPeriod.unclear


def test_the_label_reaches_back_to_the_start_of_the_amounts_sentence():
    # 66 characters before the amount: a fixed 40-character lead dropped the
    # label, and a small amount with no word is no pay (no band at all,
    # where the label makes it 50-60 an hour).
    band = _band("The hourly pay range for this role in California and New York is $50 - $60")
    assert (band.base_min, band.base_max) == (50, 60)
    assert band.pay_period is PayPeriod.hour
    # Controls from real postings (google's "daily" edited to "monthly", a
    # word the rule reads): the reach stops at a line break and at a sentence
    # glued to the next. Crossing them marks these salaries `unclear` from the
    # text above the band.
    for text in (
        "Global travel insurance & emergency assistance\n\nDaily meals allowance\n\n"
        "Additional perks & programs specific to location\n\nCompensation Range\n"
        "Compensation will be paid in the range of up to $230,000 - $280,000 + Bonus.",
        "Valuable extras: identity theft protection, subsidized parking, monthly wellness, pet "
        "insurance, accident & critical illness insurance\xa0\n\nThe base pay range for this "
        "position is:\xa0$181,000\xa0to $226,000. Please note that placement",
        "billions of users interact with Google search on a monthly basis.Individual pay is "
        "determined by factors including job-related skills, experience, and relevant "
        "education or training.US: $207000 - $300000 (USD) + 20% bonus target + equity",
    ):
        assert _band(text).pay_period is PayPeriod.year, text[:40]


def test_a_schedule_next_to_a_salary_is_not_a_pay_unit():
    # A count of hours or days is a schedule. Read as a word, "hour" leaned
    # hourly (and "per week" would contradict), so the salary read "could not
    # tell".
    for text in (
        "Compensation: $150,000 - $200,000 (40 hour week)",
        "Compensation: $150,000 - $200,000 for a 40-hour role",
        "Compensation: $150,000 - $200,000, 37.5 hours per week",
        "Compensation: $150,000 - $200,000, in the office 3 days per week",
    ):
        assert _band(text).pay_period is PayPeriod.year, text
    # Control: a schedule beside a real hourly rate does not cancel its unit.
    band = _band("Pay: $50 - $60 per hour, 40 hours per week.")
    assert (band.base_min, band.base_max, band.pay_period) == (50, 60, PayPeriod.hour)


# --------------------------------------------------------------------------- #
# Small amounts are pay only when the posting says per hour or per month
# --------------------------------------------------------------------------- #


def test_a_small_amount_with_no_unit_is_not_pay():
    # Cohere: a stipend, not a $500 yearly salary.
    assert not _band("Everyone receives a $500 - $500 home office stipend to set up.").disclosed
    assert not _band("Relocation support of $2,000 - $5,000 is available.").disclosed


def test_a_small_amount_with_its_unit_is_that_rate():
    band = _band("The base pay range for this role is between $59.49 and $89.84/hr, and more")
    assert (band.base_min, band.base_max) == (59, 89)
    assert band.pay_period is PayPeriod.hour


def _read(text: str):
    band = _band(text)
    return (band.base_min, band.base_max, band.pay_period) if band.disclosed else None


def test_a_stipend_or_a_budget_never_displaces_the_salary():
    # Fails "the first stated band wins" (1,000-1,500 a month).
    assert _read(
        "Phone stipend: $1,000 - $1,500 per month. Salary range: $150,000 - $200,000."
    ) == (150_000, 200_000, PayPeriod.year)
    # Not 1,500-3,000 `unclear`: a month-sized amount whose words say yearly.
    assert _read(
        "Annual learning budget: $1,500 - $3,000 per year. Salary range: $150,000 - $200,000."
    ) == (150_000, 200_000, PayPeriod.year)
    # Not a band: no pay at all.
    assert _read("We offer a $2,000 - $5,000 annual wellness stipend.") is None

    # Controls, each failing a plausible broken fix. Real hourly and monthly
    # pay still read (a free-text rule that drops every small amount fails):
    assert _read("The rate is $50 - $60 per hour for this role.") == (50, 60, PayPeriod.hour)
    assert _read("Pay: $65/hr - $80/hr") == (65, 80, PayPeriod.hour)
    assert _read("Salary: €4,500 - €5,500 per month.") == (4_500, 5_500, PayPeriod.month)
    # and a no-word amount where month and year overlap is not certainly a
    # salary, so a signing bonus stated after a monthly salary does not
    # displace it (ranking every yearly reading first fails):
    assert _read(
        "Salary: €4,500 - €5,500 per month. Signing bonus of €10,000 - €15,000."
    ) == (4_500, 5_500, PayPeriod.month)


def test_senior_monthly_pay_above_ten_thousand_dollars_is_monthly():
    # With the month ceiling at the yearly floor (USD 10,000), each of these
    # straddles two classes and reads as no pay, or contradicts and `unclear`.
    for text, expected in (
        ("Base pay: $9,000 - $12,000 per month", (9_000, 12_000, "USD")),
        ("Salary range: S$12,000 - S$18,000 per month", (12_000, 18_000, "SGD")),
        ("Salary: £4,500 - £9,000 per month", (4_500, 9_000, "GBP")),
        ("Base pay: $10,000 - $12,000 per month", (10_000, 12_000, "USD")),
    ):
        band = _band(text)
        assert (band.base_min, band.base_max, band.currency, band.pay_period) == (
            *expected, PayPeriod.month,
        ), text
    # Controls: the month word decides only where month and year overlap. No
    # word there is still yearly, and a clearly yearly-sized amount with "per
    # month" is still a contradiction.
    assert _band("Salary: $12,000 - $15,000").pay_period is PayPeriod.year
    assert _band("Base pay: $150,000 - $200,000 per month").pay_period is PayPeriod.unclear


def test_a_day_or_week_unit_contradicts_the_size_instead_of_going_unread():
    # Unread, "per week" left a salary-sized amount to its size: yearly.
    assert _read("Salary: $150,000 - $200,000 per week") == (150_000, 200_000, PayPeriod.unclear)
    # In prose a day or week rate is never shown as hourly or monthly pay.
    assert _read("The day rate is $600 - $800 per day.") is None
    assert _read("Contract: $3,000 - $4,000 per week.") is None
    assert _read("Daily rate: €600 - €800") is None
    # Controls: how often pay is paid says nothing about what it is per.
    assert _read("Compensation: $150,000 - $200,000, paid bi-weekly") == (
        150_000, 200_000, PayPeriod.year,
    )
    assert _read("Hourly rate: $50 - $60, paid weekly") == (50, 60, PayPeriod.hour)


# --------------------------------------------------------------------------- #
# Numbers written the European way
# --------------------------------------------------------------------------- #


def test_a_dot_before_three_digits_is_a_thousands_separator():
    band = _band(
        "The typical starting salary range for this role is: €104.800—€165.700 EUR "
        "Additional Information"
    )
    assert (band.base_min, band.base_max, band.currency) == (104_800, 165_700, "EUR")
    assert band.pay_period is PayPeriod.year
    assert band.source_snippet and "€104.800" in band.source_snippet


def test_dotted_millions_and_real_decimals_both_read_right():
    assert (_band("Base: €1.250.000 - €1.500.000 annually").base_min) == 1_250_000
    # Two decimals are cents, and a k/m suffix keeps the dot a decimal point.
    assert _band("Salary: $126,900.00 - $181,400.00 annually").base_min == 126_900
    assert _band("Salary range: $1.2M - $1.5M per year").base_min == 1_200_000


@pytest.mark.parametrize("text", [
    # Dotted thousands with a dot decimal: no reading. An IndexError here
    # aborts a whole source's run from `structure_job_detail`.
    "Salary: $120.000.00 - $150.000.00 per year",
    # Dates beside a currency code: read as one number with no value.
    "Start date 01.10.2024 - 31.12.2024 EUR 600 per day",
])
def test_a_number_that_reads_as_no_value_is_no_band_never_a_crash(text):
    assert not _band(text).disclosed


# --------------------------------------------------------------------------- #
# Size classes, in every currency
# --------------------------------------------------------------------------- #


def test_size_classes_are_about_ten_times_apart_in_any_currency():
    assert size_class(15.65, 22.00, "USD") is PayPeriod.hour  # DoorDash "Base Pay:"
    assert size_class(4_500, 5_500, "EUR") is PayPeriod.month
    assert size_class(222_800, 300_000, "USD") is PayPeriod.year  # Anthropic
    # Coinbase: ₹6,612,600 is a yearly salary, not $6.6M and not "no pay".
    assert size_class(6_612_600, 9_424_500, "INR") is PayPeriod.year
    assert size_class(3, 4, "USD") is None  # "$3-4B annual logistics spend"
    assert size_class(900, 1_200, "USD") is None  # hour and month never overlap
    # Month and year DO overlap, USD 10,000 to 30,000. Senior monthly pay runs
    # that high ("S$12,000 - S$18,000 per month"), and a month ceiling at the
    # yearly floor makes $9,000 - $12,000 straddle two classes, so real monthly
    # pay reads as no pay at all.
    assert size_classes(9_000, 12_000, "USD") == (PayPeriod.month,)
    assert size_classes(12_000, 18_000, "USD") == (PayPeriod.year, PayPeriod.month)
    assert size_class(12_000, 18_000, "USD") is PayPeriod.year  # no word: yearly
    assert size_classes(150_000, 200_000, "USD") == (PayPeriod.year,)


def test_a_structured_pay_field_may_be_decided_by_size_alone():
    # A Greenhouse tier labelled "Zone 1 (Menlo Park, CA; ...)" names no period.
    assert decide_period(PayPeriod.hour, None, structured=True) is PayPeriod.hour
    assert decide_period(PayPeriod.hour, None) is None  # free text: not pay
    assert decide_period(PayPeriod.year, None) is PayPeriod.year
    assert decide_period(PayPeriod.year, PayPeriod.hour) is PayPeriod.unclear
    assert decide_period(None, PayPeriod.year) is None


# --------------------------------------------------------------------------- #
# Stored rows are checked when read: nothing is rewritten
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("stored", "low", "high", "currency", "shown"), [
    ("hour", 600_000, 1_066_000, "USD", "unclear"),  # Netflix, stored before this rule
    ("year", 104, 165, "EUR", "unclear"),  # Elastic, stored before this rule
    # A stored `unclear` is the rule's own "the words contradict the size"
    # ("Base pay: $10,000 - $12,000 per month" against a month ceiling at the
    # yearly floor):
    # never promoted to a salary to split and compare with the pay floor.
    ("unclear", 163_000, 236_000, "USD", "unclear"),
    ("unclear", 10_000, 12_000, "USD", "unclear"),
    (None, 163_000, 236_000, "USD", "year"),  # no period stored: the size reads
    ("hour", 59, 89, "USD", "hour"),
    ("month", 4_500, 5_500, "EUR", "month"),
    ("month", 12_000, 18_000, "USD", "month"),  # where month and year overlap
    ("year", 12_000, 18_000, "USD", "year"),
    ("year", 1, 2, "USD", "unclear"),  # a placeholder is no pay at any size
])
def test_a_stored_period_is_shown_only_when_its_amount_can_be_it(stored, low, high, currency, shown):
    assert effective_period(stored, low, high, currency) == shown


_ROLE = dict(
    company="netflix", band="staff", family="engineering", comp_low=None,
    comp_median=None, comp_high=None, comp_provenance=None,
)


@pytest.mark.parametrize(("period", "reason"), [
    ("hour", "hourly"), ("month", "monthly"), ("unclear", "period_unclear"),
])
def test_a_band_that_is_not_yearly_is_never_split(period, reason):
    disclosed = {
        "disclosed": True, "base_min": 150_000, "base_max": 200_000, "currency": "USD",
        "pay_basis": "base", "pay_period": period, "snippet": "Hourly rate: $150,000 - $200,000",
    }
    package = build_job_package(**_ROLE, disclosed=disclosed)
    assert package["no_split_reason"] == reason
    assert package["components"] == [] and package["total"] is None


def test_the_equity_check_counts_only_bands_whose_size_agrees_with_their_period():
    # A salary stored with no period enters as yearly. A salary stored as
    # hourly is a contradiction the stored row cannot resolve (the words are
    # not kept), and so is one stored `unclear` (its words contradicted it):
    # both stay out, and so does a tiny amount stored yearly.
    rows = [
        ("google", "staff", 400_000, 150_000, 200_000, "USD", "base", None, 0.15, "v"),
        ("google", "staff", 400_000, 150_000, 200_000, "USD", "base", "unclear", 0.15, "v"),
        ("google", "staff", 400_000, 150_000, 200_000, "USD", "base", "hour", 0.15, "v"),
        ("google", "staff", 400_000, 45, 60, "USD", "base", "year", 0.15, "v"),
    ]
    out = build_equity_residuals(rows, observed={}, accepted_versions={"v"})
    assert out["excluded"]["not_yearly"] == 3
    assert sum(group["reqs"] for group in out["groups"]) == 1


# --------------------------------------------------------------------------- #
# Ashby's structured interval goes through the same rule
# --------------------------------------------------------------------------- #


def _ashby(low, high, interval, currency="USD"):
    payload = {
        "descriptionHtml": "<p>About the role.</p>",
        "compensation": {"summaryComponents": [{
            "compensationType": "Salary", "minValue": low, "maxValue": high,
            "currencyCode": currency, "interval": interval,
        }]},
    }
    return AshbyDetailConnector().parse_payload(payload).source_disclosed_comp


def test_ashby_interval_is_checked_against_the_amount():
    assert _ashby(180_000, 220_000, "1 YEAR").pay_period == "year"
    assert _ashby(180_000, 220_000, "NONE").pay_period == "year"
    assert _ashby(45, 60, "1 HOUR").pay_period == "hour"
    assert _ashby(4_500, 5_500, "1 MONTH", "EUR").pay_period == "month"
    assert _ashby(45, 60, "1 YEAR").pay_period == "unclear"
    assert _ashby(8_000, 11_000, "1 MONTH").pay_period == "month"  # senior monthly pay


def test_an_ashby_interval_we_do_not_show_is_could_not_tell():
    for low, high, interval, unit in (
        (600, 800, "1 DAY", "per day"),  # was stored hourly by its size
        (3_000, 4_000, "1 WEEK", "per week"),  # was stored monthly
        (5_000, 6_000, "2 WEEK", "per 2 weeks"),  # was stored monthly
        (180_000, 220_000, "2 YEAR", "per 2 years"),  # a count other than one
    ):
        comp = _ashby(low, high, interval)
        assert comp.pay_period == "unclear", interval
        # The stored quote states the unit, so "could not tell" has its reason.
        assert unit in comp.source_snippet, interval
    # Control: only a missing interval lets the size decide alone.
    assert _ashby(45, 60, "NONE").pay_period == "hour"
    assert _ashby(45, 60, None).pay_period == "hour"


# --------------------------------------------------------------------------- #
# A k/m suffix is a token of its own
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("text", [
    "Salary: $150,000 - $200,000 Massachusetts residents only",  # the "M" read as millions
    "Base salary $150,000 - $200,000 MN, hybrid",
    "Pay range $150,000 to $200,000 maximum, plus equity",
    "The range is $150,000 - $200,000 Mountain View",
    "Compensation: $150,000 - $200,000 Kansas City",
])
def test_a_word_starting_with_k_or_m_after_a_band_is_not_a_suffix(text):
    """Workday prints the place after the pay. The first letter of the next
    word read as a k/m suffix, the pair failed the 10x ratio check, and the
    band was lost: a missed band, systematic for every state starting with M."""
    assert _read(text) == (150000, 200000, PayPeriod.year)


def test_a_monthly_word_after_the_band_is_the_period_not_a_suffix():
    assert _read("Pay: $12,000 - $18,000 Monthly") == (12000, 18000, PayPeriod.month)


def test_a_real_suffix_still_reads():
    assert _read("Base pay $150K - $200K per year") == (150000, 200000, PayPeriod.year)
    assert _read("Base pay $150k-$200k") == (150000, 200000, PayPeriod.year)


# --------------------------------------------------------------------------- #
# A currency code is evidence wherever it sits
# --------------------------------------------------------------------------- #


def _stated(text: str):
    band = _band(text)
    return (band.base_min, band.base_max, band.currency, band.pay_period) if band.disclosed else None


@pytest.mark.parametrize(("text", "expected"), [
    # Workday's and SAP's way: the code before the first amount, no symbol.
    ("Salary range: USD 150,000 - 200,000 per year.", (150_000, 200_000, "USD", PayPeriod.year)),
    ("Base salary: GBP 90,000 - 120,000 per annum.", (90_000, 120_000, "GBP", PayPeriod.year)),
    ("Pay range: CAD 120,000 - 150,000.", (120_000, 150_000, "CAD", PayPeriod.year)),
    # Currencies the table sizes, named by their code in the text.
    ("Salary: INR 3,000,000 - 4,500,000 per annum.", (3_000_000, 4_500_000, "INR", PayPeriod.year)),
    ("Lön: SEK 55,000 - 65,000 per month.", (55_000, 65_000, "SEK", PayPeriod.month)),
    ("Salary range 9,000,000 - 12,000,000 JPY annually.", (9_000_000, 12_000_000, "JPY", PayPeriod.year)),
    ("Base salary CHF 140,000 - 170,000.", (140_000, 170_000, "CHF", PayPeriod.year)),
])
def test_a_currency_code_before_or_after_the_amounts_is_evidence(text, expected):
    assert _stated(text) == expected


def test_an_amount_past_the_stored_ceiling_is_no_band_never_a_crash():
    """A won salary is hundreds of millions of units: inside the yearly size
    class, outside `MAX_COMP`, where building the band raises a validation
    error that would stop the pass. A
    missed band, not a crash; a won band under the ceiling still reads."""
    assert _stated("Salary: KRW 205,000,000 - 274,000,000 per year.") is None
    assert _stated("Salary: KRW 60,000,000 - 80,000,000 per year.") == (
        60_000_000, 80_000_000, "KRW", PayPeriod.year,
    )


@pytest.mark.parametrize("text", [
    # Two numbers and a dash with no money anywhere are not a band.
    "A team of 150,000 - 200,000 users.",
    # A code inside a longer word is not a currency.
    "Rewards of 150,000 - 200,000 USDC tokens for the protocol.",
    "Founded 1999 - 2004 by INRIA researchers.",
])
def test_a_code_that_is_not_a_currency_token_is_no_evidence(text):
    assert _stated(text) is None


# --------------------------------------------------------------------------- #
# A range the sentence names as other money is never a base band
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("text", [
    "Sign-on bonus of $50,000 - $100,000 for eligible hires.",
    "Equity grant of $100,000 - $200,000, vesting over four years.",
    "Relocation assistance of $10,000 - $20,000 is available.",
    "Program budget: $150,000 - $200,000 for the first year.",
    "Experience owning revenue of $150,000 - $200,000 a quarter.",
    # iCapital: a quota, read as a salary when no other band competed.
    "exceed an annual revenue quota of approximately $900,000 to $1,000,000 in year one",
])
def test_a_range_its_sentence_names_as_other_money_is_no_band(text):
    """Fails "magnitude is the only gate", which stores each of these as a
    base band when no salary competes."""
    assert _read(text) is None


@pytest.mark.parametrize(("text", "expected"), [
    # Other money after the band is what the band leaves out, not what it is.
    ("Base salary of $150,000 - $200,000 plus bonus and equity.", (150_000, 200_000, PayPeriod.year)),
    # A salary word in the same lead wins: the sentence is about pay.
    ("The base salary range, before bonus, is $150,000 - $200,000.", (150_000, 200_000, PayPeriod.year)),
    # Total compensation names its equity and is still the posting's pay.
    ("Total compensation including equity: $150,000 - $200,000.", (150_000, 200_000, PayPeriod.year)),
    # A benefits list flattened into the pay text, no sentence end before the band.
    ("401(k) and company match Professional development stipend Strong culture of "
     "collaboration, performance, and personal growth $175,000 - $225,000 a year",
     (175_000, 225_000, PayPeriod.year)),
    # Peregrine: the pay word is far back, the other money right before the band.
    ("Base Salary + Equity (if applicable) + Bonus (if applicable) $150,000—$180,000 USD",
     (150_000, 180_000, PayPeriod.year)),
    # Other money in the previous sentence says nothing about this one.
    ("Annual bonus eligible. $150,000 - $200,000.", (150_000, 200_000, PayPeriod.year)),
    # And beside a salary it still never displaces it.
    ("Salary: $150,000 - $200,000. Sign-on bonus of $20,000 - $30,000.", (150_000, 200_000, PayPeriod.year)),
])
def test_a_salary_beside_other_money_still_reads(text, expected):
    assert _read(text) == expected
