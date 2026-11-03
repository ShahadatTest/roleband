"""The generic seniority words are whole words.

Read as substrings, "director" would band Active Directory, "staff" Staffing,
"fellow" a Fellowship and "sr " an ASR Scientist, each CONFIRMED; and where a
director word can veto a printed rung, the false friend would discard the
employer's own statement. Mutation: `levels.vocabulary.has_word` as
`n in text` fails every case here."""

from __future__ import annotations

import pytest

from tracker.enrich.level_mapper import read_level
from tracker.schema import LevelBand, LevelBasis, LevelConfidence, RawJob


def _read(company: str, title: str, raw_level: str | None = None):
    return read_level(RawJob(company=company, req_id="x", title=title, url="", raw_level=raw_level), None)


def test_a_printed_rung_survives_a_directory_in_the_title():
    reading = _read("microsoft", "Active Directory Engineer", raw_level="IC4")
    assert reading.basis is LevelBasis.STATED
    assert reading.band is not LevelBand.DIRECTOR_PLUS


@pytest.mark.parametrize(("company", "title", "not_band"), [
    ("acme", "Staffing Manager", LevelBand.STAFF),
    ("acme", "ASR Scientist", LevelBand.SENIOR),
    ("apple", "Apple SkillBridge Fellowship Program", LevelBand.DIRECTOR_PLUS),
    ("acme", "Directory Services Administrator", LevelBand.DIRECTOR_PLUS),
])
def test_a_word_that_merely_contains_a_rung_word_names_no_rung(company, title, not_band):
    reading = _read(company, title)
    assert not (reading.band is not_band and reading.confidence is LevelConfidence.CONFIRMED)
    assert reading.basis is LevelBasis.NONE, "nothing in the title states a level"


def test_the_whole_words_still_read():
    assert _read("acme", "Staff Software Engineer").band is LevelBand.STAFF
    assert _read("acme", "Director, Engineering").band is LevelBand.DIRECTOR_PLUS
    assert _read("acme", "Sr. Data Scientist").band is LevelBand.SENIOR
    assert _read("acme", "Distinguished Fellow").band is LevelBand.DIRECTOR_PLUS
    assert _read("acme", "VP, Marketing").band is LevelBand.DIRECTOR_PLUS


def test_a_firm_rank_is_read_over_the_masked_title():
    """EY's "Staff" rank is its entry rung. "Chief of Staff" is an org role the
    mapper masks before every other tier, and the rank tier read the raw title,
    so a chief of staff to the CEO read as an entry-level hire."""
    reading = _read("ey", "Chief of Staff to the CEO")
    assert reading.basis is not LevelBasis.COMPANY
    assert reading.band is not LevelBand.ENTRY
    control = _read("ey", "Staff Consultant, Assurance")
    assert (control.band, control.basis) == (LevelBand.ENTRY, LevelBasis.COMPANY)
