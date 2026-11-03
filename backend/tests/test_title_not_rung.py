"""A title word that is not a rung at one company.

iCapital runs a banking title ladder, published in its own "Job Listing
Level" field: Analyst < Associate < AVP < VP < SVP < Managing Director. Its
"Vice President" is mid-career, and the generic tier reads it as an executive,
which would put its postings on a director-only Board as Director+. The company's
profile masks those phrases, so they state no level until the ladder is
calibrated. "Vice President" anywhere else is still an executive.
"""

from __future__ import annotations

import pytest

from tracker.enrich.level_mapper import is_level_guess, read_level
from tracker.levels.titles import not_rung_pattern
from tracker.schema import LevelBand, LevelBasis, RawJob


def _read(company: str, title: str):
    return read_level(RawJob(company=company, req_id="x", title=title, url=""), None)


@pytest.mark.parametrize("title", [
    "Regulatory & Compliance (UK & EMEA) - Vice President",
    "Sales & Partnerships Europe - Vice President",
    "EMEA Legal Counsel - Assistant Vice President ",
    "Corporate Finance, Strategic Finance - AVP",
    "Head of Japan and Client Solutions, Japan - Senior Vice President",
    "Vice President",
])
def test_a_banking_vice_president_states_no_level(title):
    reading = _read("icapital", title)
    assert (reading.band, reading.basis) == (LevelBand.MID, LevelBasis.NONE)
    # Not stated, so the person's "level not stated" switch decides it.
    assert is_level_guess(title, reading, "icapital")


def test_a_managing_director_is_still_a_director_at_a_bank():
    # "Managing Director" is the only director word here (no Head of, no Chief).
    reading = _read("icapital", "Portfolio Construction - Managing Director")
    assert (reading.band, reading.basis) == (LevelBand.DIRECTOR_PLUS, LevelBasis.GENERIC)


@pytest.mark.parametrize(("company", "title"), [
    ("elastic", "Vice President, Product Management"),
    ("acme", "Senior Vice President, Engineering"),
    ("okta", "VP, Security Engineering"),
])
def test_a_vice_president_elsewhere_is_still_an_executive(company, title):
    assert not_rung_pattern(company) is None
    assert _read(company, title).band is LevelBand.DIRECTOR_PLUS


def test_a_rung_word_beside_the_masked_phrase_still_reads():
    # Only the declared phrase is masked: the rest of the title keeps its words.
    reading = _read("icapital", "Senior Software Engineer - Vice President")
    assert (reading.band, reading.basis) == (LevelBand.SENIOR, LevelBasis.GENERIC)
