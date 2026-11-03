"""Deterministic pay-pattern pre-filter (pure). Recall-favoring: it must fire on
real disclosures; a false positive only costs one cheap local call."""

from __future__ import annotations

import pytest

from tracker.intelligence.prefilter import has_pay_pattern
from tracker.pay_disclosure import extract_grounded_band
from tracker.pay_numbers import USD_PER_UNIT


def test_fires_on_currency_range():
    assert has_pay_pattern("Annual Salary:\n$210,000—$260,000 USD") is True


def test_fires_on_k_shorthand_and_iso_code():
    assert has_pay_pattern("Base pay 150k-200k") is True
    assert has_pay_pattern("Compensation is 240,000 USD") is True


def test_fires_on_explicit_phrase_without_symbol():
    assert has_pay_pattern("The salary range for this role is competitive.") is True
    assert has_pay_pattern("We publish the base salary for every posting.") is True


def test_does_not_fire_on_prose_without_pay():
    prose = (
        "We are looking for a senior program manager to lead cross-functional "
        "initiatives. You will collaborate with teams across the company."
    )
    assert has_pay_pattern(prose) is False


def test_empty_and_none_are_false():
    assert has_pay_pattern("") is False
    assert has_pay_pattern(None) is False


def test_bare_small_numbers_do_not_fire():
    # "top 5 priorities", "3 years" — no monetary or salary-phrase signal.
    assert has_pay_pattern("You have 8 years of experience and 3 direct reports.") is False


# --------------------------------------------------------------------------- #
# Whatever the parser reads, the pre-filter lets through
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("code", sorted(USD_PER_UNIT))
def test_every_currency_the_parser_reads_passes_the_prefilter(code):
    """Every currency code the parser accepts must pass the pre-filter, or a
    posting can be stamped processed before the parser sees its band. Here
    ungrouped digits have no salary phrase, so the code is the only signal."""
    # A salary of USD 50,000-60,000, which every code's units keep under
    # `MAX_COMP` (won included).
    low, high = (int(50_000 / USD_PER_UNIT[code]), int(60_000 / USD_PER_UNIT[code]))
    text = f"{code} {low} - {high} per year"
    assert extract_grounded_band(text, text).disclosed, text
    assert has_pay_pattern(text) is True


@pytest.mark.parametrize("text", [
    "Rewards of 150000 - 200000 USDC tokens for the protocol.",
    "Founded 1999 - 2004 by INRIA researchers.",
])
def test_a_code_inside_a_word_is_still_no_money(text):
    assert has_pay_pattern(text) is False
