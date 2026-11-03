"""Deterministic pay scanning: currency-range selection and pay periods."""

from __future__ import annotations

from tests.factories import ADYEN_PAY_TEXT
from tracker.pay_disclosure import extract_grounded_band
from tracker.pay_period import PayPeriod

# --------------------------------------------------------------------------- #
# Candidate selection — the first currency range is not necessarily the pay
# --------------------------------------------------------------------------- #

GOOGLE = (
    "This is an opportunity at the heart of our growth engine, driving the "
    "efficiency of a $3-4B annual logistics spend. In this pivotal role, you "
    "will build the critical systems. Individual pay is determined by factors "
    "including job-related skills, experience, and relevant education or "
    "training. US: $159000 - $231000 (USD) + 15% bonus target + equity + benefits"
)


def test_a_budget_figure_does_not_beat_the_real_band_further_down():
    """'$3-4B annual logistics spend' appears BEFORE the salary range, and
    first-match-wins would store a $3-$4 salary."""
    band = extract_grounded_band(GOOGLE, GOOGLE)
    assert band.disclosed
    assert (band.base_min, band.base_max) == (159000, 231000)
    assert "159000" in (band.source_snippet or "")


def test_a_first_candidate_that_cannot_ground_does_not_end_the_scan():
    """The earlier range is absent from the stored posting, so it cannot ground.
    The scan must continue rather than concluding "no band"."""
    pay_text = "Budget of $5-9 handled. The salary range is $120,000 - $150,000 per year."
    description = "The salary range is $120,000 - $150,000 per year."  # no 5/9 here
    band = extract_grounded_band(pay_text, description)
    assert band.disclosed
    assert (band.base_min, band.base_max) == (120000, 150000)


def test_a_lone_band_with_no_pay_wording_is_still_accepted():
    """Pay-context ranking is a preference, never a filter: a plausible band
    with no pay word anywhere near it must still be returned."""
    text = "USA, KY, HEBRON - $151,200 - $204,600 USD annually"
    band = extract_grounded_band(text, text)
    assert band.disclosed
    assert (band.base_min, band.base_max) == (151200, 204600)


# --------------------------------------------------------------------------- #
# Currency marker position
#
# A pattern that REQUIRES a leading symbol is blind to the two formats below,
# the bulk of the bands such a pattern misses. Each case here is the verbatim shape from a real posting.
# --------------------------------------------------------------------------- #


def test_amazon_writes_no_symbol_and_puts_the_code_last():
    """A trailing currency code with decimal cents must identify the full band."""
    text = "USA, NY, New York - 126,900.00 - 181,400.00 USD annually"
    band = extract_grounded_band(text, text)
    assert band.disclosed
    assert (band.base_min, band.base_max) == (126900, 181400)
    assert band.currency == "USD"


def test_nvidia_writes_the_code_after_every_number():
    """A currency code on each bound must identify one complete band."""
    text = (
        "Your base salary will be determined based on your location, experience, "
        "and the pay of employees in similar positions. The base salary range is "
        "168,000 USD - 258,750 USD. You will also be eligible for equity."
    )
    band = extract_grounded_band(text, text)
    assert band.disclosed
    assert (band.base_min, band.base_max) == (168000, 258750)
    assert band.currency == "USD"


def test_a_code_after_the_low_number_alone_still_sets_the_currency():
    """Only the low bound carries the code. Reading just the trailing position
    would store the band with currency=None."""
    text = "The base salary range is 168,000 USD - 258,750."
    band = extract_grounded_band(text, text)
    assert band.disclosed
    assert band.currency == "USD"


def test_two_level_bands_return_one_real_band_never_a_merged_one():
    """Adjacent level bands must stay separate: the result must be a range
    written in the posting, never bounds taken from different ranges."""
    text = (
        "The base salary range is 168,000 USD - 258,750 USD for Level 4, and "
        "200,000 USD - 322,000 USD for Level 5. You will also be eligible for equity."
    )
    band = extract_grounded_band(text, text)
    assert band.disclosed
    assert (band.base_min, band.base_max) in {(168000, 258750), (200000, 322000)}
    assert (band.base_min, band.base_max) != (168000, 322000)


# --------------------------------------------------------------------------- #
# The other half of an optional symbol: what must NOT match
# --------------------------------------------------------------------------- #


def test_a_bare_number_range_with_no_currency_anywhere_is_not_a_band():
    """The safety property of the optional symbol. These are plausible salary
    MAGNITUDES with no currency marker in any of the three positions, so they
    must not be read as pay."""
    for text in (
        "Headcount grows from 120,000 - 180,000 users this year.",
        "The cluster scales between 150,000 and 250,000 requests per second.",
    ):
        assert extract_grounded_band(text, text).disclosed is False, text


def test_a_currency_elsewhere_in_the_sentence_does_not_qualify_a_bare_range():
    """Evidence must belong to the candidate, not merely share its sentence."""
    text = "We manage a $4M budget while serving 120,000 - 180,000 monthly users."
    band = extract_grounded_band(text, text)
    assert (band.base_min, band.base_max) != (120000, 180000)


# --------------------------------------------------------------------------- #
# Plausibility — money-shaped text that cannot be pay
# --------------------------------------------------------------------------- #


def test_a_project_value_range_is_not_a_salary():
    """'construction projects ranging from $250,000 to $100 million' is no
    $250k-$100M salary band, or the model that says "no band" is graded as
    WRONG for being right."""
    text = (
        "You will manage complex datacenter construction projects ranging from "
        "$250,000 to $100 million. This role requires organizational skills."
    )
    assert extract_grounded_band(text, text).disclosed is False


def test_a_sub_minimum_wage_range_is_not_a_salary():
    # "$3-4B" reduces to 3 and 4, which would otherwise pass as an hourly band.
    text = "driving the efficiency of a $3-4B annual logistics spend"
    assert extract_grounded_band(text, text).disclosed is False


def test_a_wildly_wide_range_is_not_a_salary():
    text = "Contract values run $20,000 - $900,000 depending on scope."
    assert extract_grounded_band(text, text).disclosed is False


def test_plausible_hourly_and_annual_bands_both_survive():
    hourly = "The base pay range for this role is $59 - $89/hr."
    annual = "The annual base salary range is $180,000 - $240,000."
    assert extract_grounded_band(hourly, hourly).disclosed is True
    assert extract_grounded_band(annual, annual).disclosed is True


def test_no_currency_range_still_means_no_band():
    text = "You will lead a team of 5 to 10 engineers across 3 offices."
    assert extract_grounded_band(text, text).disclosed is False


def test_a_range_absent_from_the_posting_is_refused():
    # The grounding gate is unchanged: bounds must occur in the stored posting.
    assert extract_grounded_band("Range $1,000 - $2,000", "no numbers here").disclosed is False


# --------------------------------------------------------------------------- #
# Pay period
# --------------------------------------------------------------------------- #


def test_slash_hr_is_recognised_as_hourly():
    """'$59.49 and $89.84/hr' stored as an unclear-period 59-89 band would read
    downstream as an annual salary of fifty-nine dollars."""
    text = (
        "The base pay range for this role is between $59.49 and $89.84/hr, and "
        "your base pay will depend on your skills and experience."
    )
    band = extract_grounded_band(text, text)
    assert band.disclosed
    assert band.pay_period is PayPeriod.hour


def test_hours_per_week_does_not_make_an_annual_salary_hourly():
    """Work-schedule text such as `40 hours / week` must not turn an annual
    salary range elsewhere in the posting into hourly pay."""
    text = (
        "Position is full time. (40 hours / week, 8:00am-5:00pm, "
        "Salary Range $148700 - $201200) Amazon.com is an Equal Opportunity Employer."
    )
    band = extract_grounded_band(text, text)
    assert band.disclosed
    assert (band.base_min, band.base_max) == (148700, 201200)
    assert band.pay_period is PayPeriod.year


def test_explicit_hourly_wordings_all_read_as_hourly():
    for phrasing in (
        "The rate is $50 - $70 per hour for this role.",
        "This role is paid hourly: $50 - $70.",
        "Compensation: $50 - $70/hour.",
        "Pay: $50 - $70 /hr.",
    ):
        band = extract_grounded_band(phrasing, phrasing)
        assert band.disclosed, phrasing
        assert band.pay_period is PayPeriod.hour, phrasing


def test_annual_wordings_still_read_as_year():
    text = "The annual base salary range for this role is $180,000 - $240,000."
    assert extract_grounded_band(text, text).pay_period is PayPeriod.year


def test_a_salary_sized_band_is_yearly_when_the_posting_does_not_say():
    """Size decides when no word sits next to the amount. US postings rarely
    print "per year" (Google's "US: $163000 - $236000 (USD)" among them), and
    nobody is paid $180,000 an hour."""
    text = "Range: $180,000 - $240,000."
    assert extract_grounded_band(text, text).pay_period is PayPeriod.year


# --------------------------------------------------------------------------- #
# Pay formats a scanner must recognize when a posting
# states a currency range in its text.
# --------------------------------------------------------------------------- #


def test_a_dollar_with_a_country_is_that_countrys_dollar():
    """Atlassian writes Canadian pay as CA$; storing it as USD would overstate
    the offer by a third, and a symbol-only pattern cannot read it at all."""
    text = "Zone A: CA$142,000 - CA$190,000. This role may also be eligible for benefits."
    band = extract_grounded_band(text, text)
    assert band.disclosed and (band.base_min, band.base_max) == (142000, 190000)
    assert band.currency == "CAD"

    for raw, currency in (
        ("The annual salary range is A$150,000 - A$180,000.", "AUD"),
        ("The range is S$120,000 - S$150,000 per year.", "SGD"),
        ("The range is US$155,800 - US$277,200 per year.", "USD"),
    ):
        assert extract_grounded_band(raw, raw).currency == currency, raw


def test_a_period_between_the_number_and_the_dash_is_read_through():
    """A /year suffix after each amount must not prevent range parsing."""
    text = "40 hours / week, 8:00am-5:00pm, Salary Range $175,100/year to $236,900/year."
    band = extract_grounded_band(text, text)
    assert band.disclosed and (band.base_min, band.base_max) == (175100, 236900)
    assert band.pay_period is PayPeriod.year


def test_two_amounts_with_no_separator_are_a_band():
    """Spotify writes the range with the dash dropped by its own renderer."""
    text = "The United States base range for this position is $184,050 $262,928 plus equity."
    band = extract_grounded_band(text, text)
    assert band.disclosed and (band.base_min, band.base_max) == (184050, 262928)
    assert band.currency == "USD", "'is $184,050' must not read as Singapore"


def test_two_bare_numbers_with_no_separator_are_not_a_band():
    """The separator may only be dropped when the SECOND number carries its own
    currency marker; otherwise a headcount reads as pay."""
    for raw in (
        "We are a team of 5 10 engineers building the platform.",
        "The role covers 8 12 markets across Europe.",
        "Salary is competitive; we are 50 60 people.",
        # The dangerous one: a real amount followed by an unrelated number in
        # salary range. Dropping the marker requirement reads this as a
        # 150,000-200,000 band.
        "The equity grant is $150,000 200,000 shares over four years.",
    ):
        assert not extract_grounded_band(raw, raw).disclosed, raw


# --------------------------------------------------------------------------- #
# A band split by words: "from $X ... up to $Y"
# --------------------------------------------------------------------------- #

AMAZON_GEO = (
    "The base pay for this position ranges from $133,900/year in our lowest "
    "geographic market up to $231,400/year in our highest geographic market. Pay "
    "is based on a number of factors including market location and may vary "
    "depending on job-related knowledge, skills, and experience."
)


def test_amazon_geographic_range_split_by_words_is_a_yearly_band():
    """The bounds sit 40 characters apart with no dash; a reader that needs one
    stores "no pay" for every posting written this way."""
    band = extract_grounded_band(AMAZON_GEO, AMAZON_GEO)
    assert band.disclosed
    assert (band.base_min, band.base_max, band.currency) == (133_900, 231_400, "USD")
    assert band.pay_period is PayPeriod.year
    assert band.pay_basis.value == "base"


def test_the_same_sentence_with_a_bare_to_is_the_same_band():
    """A posting can copy the sentence with "to" for "up to"; it is not "no pay"."""
    text = (
        "The base pay for this position ranges from $207,900/year in our lowest "
        "geographic market to $386,100/year in our highest geographic market."
    )
    band = extract_grounded_band(text, text)
    assert (band.base_min, band.base_max, band.pay_period) == (207_900, 386_100, PayPeriod.year)


def test_from_up_to_needs_money_on_both_bounds():
    """Words between two plain numbers are never a band: a headcount, a year,
    a percentage."""
    for text in (
        "Teams range from 5 engineers in our smallest office up to 40 in our largest.",
        "Travel from 10% of the time in some quarters up to 30% in others.",
        "Base pay ranges from $120,000 in some markets up to 180,000 in others.",
    ):
        assert not extract_grounded_band(text, text).disclosed, text


def test_from_up_to_does_not_reach_across_a_sentence_or_another_number():
    """A sentence end or a third number between the bounds means two
    statements, not one band."""
    for text in (
        "Relocation from $5,000 is offered. Salary is paid up to $150,000 in bonus.",
        "Pay starts from $90,000 for level 3 and 4 roles, up to $140,000 for level 5.",
    ):
        assert not extract_grounded_band(text, text).disclosed, text


# --------------------------------------------------------------------------- #
# Several bands, one per place: the band for the posting's place
# --------------------------------------------------------------------------- #
# `docs/pay.md`: "Pick the band for the job's location when several are
# posted." Many text bands state two or more. The shapes below are the stored postings', read with the production reader.

from tracker.enrich.classify import first_place, specific_places  # noqa: E402


def _for(text: str, *locations: str):
    return extract_grounded_band(text, text, place=first_place(list(locations)), places_in=specific_places)


MICROSOFT = (
    "Software Engineering M5 - The typical base pay range for this role across the U.S. is "
    "USD $142,800 - $274,800 per year. There is a different range applicable to specific work "
    "locations, within the San Francisco Bay area and New York City metropolitan area, and the "
    "base pay range for this role in those locations is USD $188,000 - $304,200 per year."
)


def test_a_bay_area_posting_takes_the_bay_area_band_and_redmond_the_us_one():
    assert (_for(MICROSOFT, "Mountain View, CA, US").base_min, _for(MICROSOFT, "New York, NY, US").base_min) == (
        188_000, 188_000)
    assert _for(MICROSOFT, "Redmond, WA, US").base_min == 142_800, "no band names Redmond: the order decides"
    assert extract_grounded_band(MICROSOFT, MICROSOFT).base_min == 142_800, "no place: as before"


def test_the_place_decides_whichever_band_the_text_states_first():
    """Adyen's posting: its first place is Chicago, so its
    band is Chicago's whether or not the San Francisco band reads. The stored
    text writes "$258,00", which the parser refuses; repaired, it would have
    come first and swapped the stored band."""
    assert _for(ADYEN_PAY_TEXT, "Chicago; San Francisco", "San Francisco").base_min == 235_000
    assert _for(ADYEN_PAY_TEXT.replace("258,000", "258,00"), "Chicago; San Francisco").base_min == 235_000
    assert _for(ADYEN_PAY_TEXT, "San Francisco, CA").base_min == 258_000


CLOUDFLARE = (
    "Compensation may be adjusted depending on work location. For Bay Area based hires: Estimated "
    "annual salary of $230,000 - $288,000 For Washington and New York City based hired: Estimated "
    "annual salary of $220,000 - $275,000 For Austin based hired: Estimated annual salary of "
    "$200,000 - $250,000 Equity This role is eligible to participate in Cloudflare's equity plan."
)


def test_a_label_ending_in_a_colon_belongs_to_the_band_after_it():
    """A place label introduces the following band, not the preceding one."""
    assert _for(CLOUDFLARE, "Austin, TX").base_min == 200_000
    assert _for(CLOUDFLARE, "New York, NY").base_min == 220_000
    assert _for(CLOUDFLARE, "San Francisco, CA").base_min == 230_000
    # A location listing two places is its first: read whole, it names both
    # metros, two bands name it, and the order would hand New York the Bay Area's.
    assert _for(CLOUDFLARE, "New York, NY or San Francisco, CA").base_min == 220_000


def test_a_place_written_before_its_band_and_a_place_listed_second():
    """True Anomaly's posting is in "Denver, CO or Long Beach, CA": Denver
    is named first, and each band's place is written before it."""
    text = ("COMPENSATION Base Salary: Long Beach - $220,000 to $320,000, Denver - $205,000 to "
            "$305,000, SF Bay Area - $240,000 to $350,000 Equity + Benefits")
    assert _for(text, "Denver, CO or Long Beach, CA").base_min == 205_000
    assert _for(text, "Long Beach, CA").base_min == 220_000


def test_a_place_a_band_excludes_is_not_its_place():
    text = ("For California (excluding Bay Area) based hires: Estimated annual salary of $220,000 - "
            "$290,000. For Bay Area based hires: Estimated annual salary of $250,000 - $320,000.")
    assert _for(text, "San Francisco, CA").base_min == 250_000


def test_two_bands_naming_the_place_leave_the_order_to_decide():
    """Fail closed: the rule picks only when exactly one band names the place.
    Two do here, so the band stated first, which names none, stands."""
    text = ("Typical US base pay: $150,000 - $200,000 per year. Engineers in San Francisco: "
            "$200,000 - $260,000 per year. Senior engineers in San Francisco: $240,000 - $300,000 per year.")
    assert _for(text, "San Francisco, CA").base_min == 150_000


def test_a_country_alone_names_no_place_to_choose_by():
    """Cloudflare also posts a Portugal band in euros: a country is not a city
    or metro, so an Austin posting is never handed it."""
    text = ("For US based hires: Estimated annual salary of $220,000 - $303,000 ● For Portugal based "
            "hires: Estimated annual salary is between €89,000 - €122,000.")
    assert _for(text, "Austin, TX").currency == "USD"


def test_the_first_place_is_the_first_a_location_lists():
    assert first_place(["Chicago; San Francisco", "San Francisco"]) == specific_places("Chicago")
    assert first_place(["Denver, CO or Long Beach, CA"]) == specific_places("Denver, CO")
    assert first_place(["Portland, OR"]) == specific_places("Portland, OR"), "a state code, not 'or'"
    assert first_place(["Remote, US", "Austin, TX"]) == frozenset(), "the first place names no city"
