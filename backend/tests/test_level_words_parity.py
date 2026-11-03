"""A rung label and a posting title read the same seniority words.

`levels.words` bands a pay source's rung label the atlas cannot place, and
`enrich.level_mapper` bands a posting's title. The comp lookup joins a posting
to a rung by band, so both read one vocabulary (`levels.vocabulary`) by one
whole-word match, in one order, and differ only where a rung label is not a
posting title. Every label here runs through both readers at a company with no
ladder of its own, so only the generic words can answer. A substring reader
fails the false friends below ("Internal" is no intern, "Active Directory" no
director); a words reader that reads the "staff" in Member of Technical Staff
as the staff rung, or skips the people-manager titles, the architect or the
chief-officer rule, fails the rest.
"""

from __future__ import annotations

import pytest

from tracker.enrich.level_mapper import read_level
from tracker.levels import vocabulary
from tracker.levels.ladder import band_for
from tracker.levels.words import atlas_band, resolve_band
from tracker.schema import LevelBand, RawJob

NO_LADDER = "stripe-like-unknown"


def _posting(title: str) -> LevelBand:
    return read_level(RawJob(company=NO_LADDER, req_id="x", title=title, url=""), None).band


def _rung(label: str) -> LevelBand:
    assert atlas_band(NO_LADDER, label) is None, "only the words may answer"
    return resolve_band(NO_LADDER, label)


@pytest.mark.parametrize(("label", "band"), [
    # Whole words: a word that merely contains a rung word names no rung.
    ("Internal Tools Engineer", LevelBand.MID),
    ("Senior Internal Auditor", LevelBand.SENIOR),
    ("Active Directory Engineer", LevelBand.MID),
    ("Staffing Manager", LevelBand.MID),
    ("Partnerships Manager", LevelBand.MID),
    ("Fellowship Program", LevelBand.MID),
    ("Sr. Network Security Engineer (VPN)", LevelBand.SENIOR),
    ("Team Leader", LevelBand.MID),
    # The "staff" in Member of Technical Staff is no staff rung.
    ("Senior Member of Technical Staff", LevelBand.SENIOR),
    ("SMTS", LevelBand.SENIOR),
    ("Principal Member of Technical Staff", LevelBand.PRINCIPAL),
    # The people-manager titles read staff.
    ("Engineering Manager", LevelBand.STAFF),
    ("Senior Engineering Manager", LevelBand.STAFF),
    ("Data Engineering Manager", LevelBand.STAFF),
    # A chief is a director only as an officer or a named equivalent.
    ("Chief of Staff", LevelBand.MID),
    ("Chief Engineer", LevelBand.MID),
    ("Chief Technology Officer", LevelBand.DIRECTOR_PLUS),
    ("Chief Scientist", LevelBand.DIRECTOR_PLUS),
    ("Chief Architect", LevelBand.PRINCIPAL),
    # Architect is a principal role word; a role word never outranks Associate.
    ("Solutions Architect", LevelBand.PRINCIPAL),
    ("Associate Solutions Architect", LevelBand.ENTRY),
    ("Associate Director", LevelBand.DIRECTOR_PLUS),
    ("Senior Associate", LevelBand.SENIOR),
    ("Associate General Counsel", LevelBand.MID),
    ("Associate Product Manager", LevelBand.ENTRY),
    ("Associate Product Manager 2", LevelBand.ENTRY),
    ("Junior Engineer", LevelBand.ENTRY),
    # The rung words.
    ("Staff Engineer", LevelBand.STAFF),
    ("Sr Staff Engineer", LevelBand.PRINCIPAL),
    ("Senior Staff Engineer", LevelBand.PRINCIPAL),
    ("Tech Lead", LevelBand.STAFF),
    ("Lead Product Manager", LevelBand.STAFF),
    ("Sr. Manager", LevelBand.STAFF),
    ("Senior Product Manager", LevelBand.SENIOR),
    ("Group Product Manager", LevelBand.PRINCIPAL),
    ("Director", LevelBand.DIRECTOR_PLUS),
    ("VP", LevelBand.DIRECTOR_PLUS),
    ("Head of Product", LevelBand.DIRECTOR_PLUS),
    ("Distinguished Engineer", LevelBand.DIRECTOR_PLUS),
    ("Software Engineer 5", LevelBand.SENIOR),
    ("Engineer", LevelBand.MID),
    # The early-stage markers.
    ("Product Manager Intern", LevelBand.INTERN),
    ("Graduate Intern", LevelBand.INTERN),
    ("Werkstudent", LevelBand.INTERN),
    ("New Grad Software Engineer", LevelBand.ENTRY),
    ("Apprentice", LevelBand.ENTRY),
])
def test_a_rung_label_reads_the_band_a_posting_titled_the_same_reads(label, band):
    assert (_posting(label), _rung(label)) == (band, band)


@pytest.mark.parametrize(("label", "posting", "rung"), [
    # A label with no rung word is the ladder's mid rung; the mapper reads a
    # bare product or program manager as senior (and flags it a guess).
    ("Product Manager", LevelBand.SENIOR, LevelBand.MID),
    ("Program Manager", LevelBand.SENIOR, LevelBand.MID),
    # A trailing numeral is the rung's place on the ladder; the mapper reads
    # only 4-9, and leaves Roman numerals to the company's ladder.
    ("Software Engineer I", LevelBand.MID, LevelBand.ENTRY),
    ("Product Manager II", LevelBand.SENIOR, LevelBand.MID),
    ("Software Engineer III", LevelBand.MID, LevelBand.SENIOR),
    ("Software Engineer 3", LevelBand.MID, LevelBand.SENIOR),
    # A firm's top rank, a rung over managers, Google's APM rung: rung words in
    # a label, not in a posting's title.
    ("Partner", LevelBand.MID, LevelBand.DIRECTOR_PLUS),
    ("Associate Partner", LevelBand.MID, LevelBand.DIRECTOR_PLUS),
    ("Group PM", LevelBand.MID, LevelBand.PRINCIPAL),
    ("APM", LevelBand.MID, LevelBand.ENTRY),
    ("APM1", LevelBand.MID, LevelBand.ENTRY),
    ("VP1", LevelBand.MID, LevelBand.DIRECTOR_PLUS),
    ("SVP2", LevelBand.MID, LevelBand.DIRECTOR_PLUS),
    # The MTS family: the mapper reads every MTS title senior, as a guess; a
    # label's prefix names its rung, and a bare MTS is the ladder's mid rung.
    ("Member of Technical Staff", LevelBand.SENIOR, LevelBand.MID),
    ("MTS", LevelBand.SENIOR, LevelBand.MID),
    ("Lead MTS", LevelBand.SENIOR, LevelBand.STAFF),
    ("Staff MTS", LevelBand.SENIOR, LevelBand.STAFF),
    ("LMTS", LevelBand.SENIOR, LevelBand.STAFF),
    ("AMTS", LevelBand.SENIOR, LevelBand.ENTRY),
    ("PMTS", LevelBand.SENIOR, LevelBand.PRINCIPAL),
    ("DMTS", LevelBand.SENIOR, LevelBand.DIRECTOR_PLUS),
])
def test_where_a_rung_label_reads_differently_from_a_posting(label, posting, rung):
    assert (_posting(label), _rung(label)) == (posting, rung)


_SHARED = {
    "DIRECTOR_PLUS": vocabulary.DIRECTOR_PLUS,
    "PRINCIPAL": vocabulary.PRINCIPAL,
    "STAFF": vocabulary.STAFF,
    "NOT_STAFF": vocabulary.NOT_STAFF,
    "MGMT_L6": vocabulary.MGMT_L6,
    "SENIOR": vocabulary.SENIOR,
}


@pytest.mark.parametrize(("name", "needle"), [(name, n) for name, needles in _SHARED.items() for n in needles])
def test_every_shared_word_reads_one_band_in_both_readers(name, needle):
    """A word added to the shared vocabulary reaches both readers at once."""
    for label in (needle.strip(), f"{needle.strip()} Engineer"):
        assert _rung(label) is _posting(label), label


@pytest.mark.parametrize("needle", vocabulary.AMBIGUOUS_MGMT)
def test_a_bare_management_title_is_a_word_list_the_rung_reader_skips(needle):
    assert (_posting(needle), _rung(needle)) == (LevelBand.SENIOR, LevelBand.MID)


@pytest.mark.parametrize(("abbreviation", "spelled"), [
    ("MTS", "Member of Technical Staff"),
    ("AMTS", "Associate Member of Technical Staff"),
    ("SMTS", "Senior Member of Technical Staff"),
    ("LMTS", "Lead Member of Technical Staff"),
    ("PMTS", "Principal Member of Technical Staff"),
    ("DMTS", "Distinguished Member of Technical Staff"),
])
def test_an_mts_abbreviation_reads_as_its_spelled_out_rung(abbreviation, spelled):
    assert _rung(abbreviation) is _rung(spelled)


@pytest.mark.parametrize(("company", "rung"), [
    ("salesforce", "AMTS"),
    ("salesforce", "MTS"),
    ("salesforce", "SMTS"),
    ("salesforce", "LMTS"),
    ("salesforce", "PMTS"),
    ("cohere", "Member of Technical Staff"),
    ("cohere", "Lead Member of Technical Staff"),
    ("xai", "Member of Technical Staff"),
    ("perplexity", "Member of Technical Staff"),
    ("runway", "Member of Technical Staff"),
])
def test_the_mts_words_band_an_unknown_ladder_as_the_atlas_bands_known_ones(company, rung):
    """The atlas's own MTS ladders are the evidence for the MTS rule. AMD's sits
    a step higher (MTS staff, SMTS principal), and the atlas places AMD's rungs
    itself, so the words follow the ladders that agree."""
    assert _rung(rung) is band_for(company, rung)
