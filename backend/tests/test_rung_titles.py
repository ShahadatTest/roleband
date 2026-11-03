"""A phrase a company uses for one of its rungs reads that rung.

The atlas holds each company's rungs (Apple's M1-M3), and a new ladder alone
moves pay, never a posting out of "level not placed". `rung_titles.csv` states the
company's own phrases ("senior engineering manager" is M3), and the reader
places a title that meets one. Phrases, never regexes, so the reviewer reads
exactly what a row matches. The table ships empty; these tests plant rows
against real atlas rungs.
"""

from __future__ import annotations

import re
import shutil
from datetime import date

import pytest

from tracker.enrich.classify import classify_family
from tracker.enrich.level_mapper import full_read_can_state, read_level
from tracker.levels import atlas, titles
from tracker.levels.atlas import AtlasError
from tracker.levels.model import RungTitle
from tracker.schema import LevelBand, LevelBasis, RawJob


def _row(company: str, family: str, code: str, phrase: str, match: str = "prefix") -> RungTitle:
    return RungTitle(company, family, code, phrase, match, date(2026, 10, 3), "employer_titles")


@pytest.fixture
def plant(monkeypatch):
    def _plant(*rows: RungTitle) -> None:
        monkeypatch.setattr(titles, "RUNG_PHRASES", titles.phrase_index(rows))
    return _plant


def _read(company: str, title: str, raw_level: str | None = None):
    raw = RawJob(company=company, req_id="x", title=title, url="", raw_level=raw_level)
    return read_level(raw, classify_family(raw))


def test_a_company_phrase_places_a_manager_title_we_could_not(plant):
    title = "Senior Engineering Manager, Siri"
    assert _read("apple", title).basis is LevelBasis.UNMAPPED  # with no row: a guess from a role word
    plant(_row("apple", "engineering_management", "M3", "senior engineering manager"))
    assert (_read("apple", title).band, _read("apple", title).basis) == (LevelBand.PRINCIPAL, LevelBasis.COMPANY)


def test_the_longest_phrase_wins(plant):
    # "engineering manager" as whole words also meets "Senior Engineering
    # Manager": only the order (most specific first) gives M3.
    plant(
        _row("apple", "engineering_management", "M2", "engineering manager", "word"),
        _row("apple", "engineering_management", "M3", "senior engineering manager"),
    )
    assert _read("apple", "Engineering Manager, Maps").band is LevelBand.STAFF
    assert _read("apple", "Senior Engineering Manager, Maps").band is LevelBand.PRINCIPAL


def test_a_phrase_reads_only_the_ladder_it_is_on(plant):
    # An engineering-management phrase says nothing about a marketing title,
    # and another company's phrase says nothing about Apple's.
    plant(
        _row("apple", "engineering_management", "M2", "senior manager", "word"),
        _row("google", "engineering_management", "L7", "senior engineering manager"),
    )
    before = _read("acme", "Senior Manager, Retail Marketing")
    assert _read("apple", "Senior Manager, Retail Marketing") == before
    assert _read("apple", "Senior Engineering Manager, Siri").basis is LevelBasis.UNMAPPED


def test_a_phrase_never_pulls_a_director_down(plant):
    plant(_row("apple", "engineering_management", "M3", "director", "word"))
    reading = _read("apple", "Director, Engineering")
    assert (reading.band, reading.basis) == (LevelBand.DIRECTOR_PLUS, LevelBasis.GENERIC)
    # It may confirm one: a phrase naming a director rung reads as the company's.
    plant(_row("apple", "engineering_management", "D1", "director", "word"))
    assert _read("apple", "Director, Engineering").basis is LevelBasis.COMPANY


def test_a_printed_rung_and_an_intern_outrank_a_phrase(plant):
    plant(
        _row("reddit", "software_engineering", "IC6", "staff software engineer"),
        _row("apple", "engineering_management", "M2", "engineering manager", "word"),
    )
    printed = _read("reddit", "Staff Software Engineer, Ads", raw_level="IC4")
    assert (printed.band, printed.basis) == (LevelBand.SENIOR, LevelBasis.STATED)
    assert _read("apple", "Engineering Manager Intern").band is LevelBand.INTERN


def test_a_phrase_decides_before_a_range_so_the_page_is_not_read_for_it(plant):
    job = RawJob(company="google", req_id="x", title="Engineering Manager, Cloud Networking", url="")
    family = classify_family(job)
    assert full_read_can_state(job, family)  # control: a measured range could place it
    plant(_row("google", "engineering_management", "L6", "engineering manager"))
    assert not full_read_can_state(job, family)
    assert read_level(job, family).basis is LevelBasis.COMPANY


@pytest.mark.parametrize(("words", "match", "meets"), [
    ("senior manager", "exact", True),
    ("senior manager data science", "exact", False),
    ("senior manager data science", "prefix", True),
    ("director senior manager", "prefix", False),
    ("director senior manager", "word", True),
    ("seniormanager", "word", False),
])
def test_the_three_match_modes(words, match, meets):
    assert titles.phrase_meets(words, _row("apple", "engineering_management", "M2", "senior manager", match)) is meets


#: Companies whose phrase rows were reviewed, with the decision. A row for
#: any other company fails: rows land only after review, and only on evidence
#: that names the rung.
REVIEWED = {
    "amazon": "2026-10-03: Sr. Manager is L7, Applied Science Manager is L6, by Amazon's own posted ranges",
    "cadence": "2026-10-09: Lead is senior (owner), filed at wage level II and paid beside Engineer II",
}


def test_every_committed_row_is_for_a_company_the_owner_reviewed():
    rows = atlas.load_rung_titles()
    assert rows, "the committed table holds the reviewed rows"
    assert sorted({row.company for row in rows} - set(REVIEWED)) == []


def test_every_committed_row_names_its_evidence_and_its_date():
    for row in atlas.load_rung_titles():
        assert row.basis != "government_disclosure"  # pay alignment alone never lands
        assert row.as_of.year >= 2026


@pytest.mark.parametrize(("title", "band"), [
    # Amazon's Sr. Manager is L7 (principal at Amazon) in every function: its
    # L-ladder is company-wide, so a supply-chain title reads it too.
    ("Sr. Manager, Customer Success Specialists", LevelBand.PRINCIPAL),
    ("Senior Manager, Supply Chain Manager, WWEI", LevelBand.PRINCIPAL),
    ("Sr Manager, Ground Systems Supply Chain", LevelBand.PRINCIPAL),
    ("Applied Science Manager, Stores-Ads Science", LevelBand.SENIOR),
])
def test_amazon_manager_titles_read_their_reviewed_rung(title, band):
    reading = _read("amazon", title)
    assert (reading.band, reading.basis) == (band, LevelBasis.COMPANY)


@pytest.mark.parametrize(("title", "band"), [
    ("Sr. Product Manager, Amazon Customer Service", LevelBand.SENIOR),  # an IC title: L6, the "Sr." rule
    ("Sr. Applied Science Manager, Alexa", LevelBand.SENIOR),  # not settled by the evidence: left as read
    ("Manager III, Procurement", LevelBand.SENIOR),
])
def test_amazon_titles_the_rows_do_not_name_keep_their_reading(title, band):
    assert _read("amazon", title).band is band


def test_a_company_wide_ladder_is_the_row_its_phrases_read_every_family_by(plant):
    # Apple's engineering ladder is not company-wide: its phrases read only
    # the families that ladder levels (control for the Amazon case above).
    plant(_row("apple", "software_engineering", "ICT5", "senior manager"))
    assert _read("apple", "Senior Manager, Retail Marketing") == _read("acme", "Senior Manager, Retail Marketing")


# --- the file is refused when a row is wrong ------------------------------- #


@pytest.fixture
def scratch_atlas(tmp_path, monkeypatch):
    copy = tmp_path / "atlas"
    shutil.copytree(atlas.ATLAS_DIR, copy)
    monkeypatch.setattr(atlas, "ATLAS_DIR", copy)
    return copy


def _append(path, line: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")


def test_a_good_row_loads(scratch_atlas):
    _append(scratch_atlas / "rung_titles.csv",
            "apple,engineering_management,M2,senior manager,prefix,2026-10-03,employer_titles,")
    assert atlas.load_rung_titles()[-1] == _row("apple", "engineering_management", "M2", "senior manager")


@pytest.mark.parametrize(("line", "says"), [
    ("apple,engineering_management,M9,senior manager,prefix,2026-10-03,employer_titles,", "no rung"),
    ("apple,sales,M2,senior manager,prefix,2026-10-03,employer_titles,", "no rung"),
    ("apple,engineering_management,M2,Senior Manager,prefix,2026-10-03,employer_titles,", "lowercase words"),
    ("apple,engineering_management,M2,senior manager,regex,2026-10-03,employer_titles,", "not in"),
    ("apple,engineering_management,M2,senior manager,prefix,03/10/2026,employer_titles,", "not a date"),
    ("apple,engineering_management,M2,senior manager,prefix,2026-10-03,a vendor site,", "not in"),
    # A filing's pay alignment alone never names a rung, reviewed company or not.
    ("amazon,software_engineering,L6,software development manager,prefix,2026-10-03,government_disclosure,",
     "pay alignment alone"),
])
def test_a_wrong_row_is_refused_by_name(scratch_atlas, line, says):
    _append(scratch_atlas / "rung_titles.csv", line)
    with pytest.raises(AtlasError, match=re.escape(says)):
        atlas.load_rung_titles()
