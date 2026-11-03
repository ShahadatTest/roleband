"""The rung the employer PRINTS, and what the mapper is allowed to do with it.

`level_band` + `family` are the KEY that selects one `company_comp_level` row, and
every comp figure is read off that row. These tests pin the two claims that make
reading a printed rung safe: it must outrank every guess, and it must stay silent
for every employer whose rung we have not calibrated.
"""

from __future__ import annotations

import pytest

from tracker.enrich.level_mapper import map_level, read_level
from tracker.levels.ladder import band_for_stated_rung
from tracker.schema import LevelBand, LevelBasis, LevelConfidence, RawJob
from tracker.taxonomy.stated_level import lowest_stated_rung, stated_level, stated_rungs

# The real shape, verbatim from job 4595 (microsoft). The
# discipline prefix and the "- The typical base pay" anchor are both load-bearing.
MS_SENTENCE = (
    "Compensation\n"
    "Business Analytics M6 - The typical base pay range for this role across the "
    "U.S. is USD $155,800 - $277,200 per year. There is a different range "
    "applicable to specific work locations, within the San Francisco Bay area and "
    "New York City metropolitan area, and the base pay range for this role in "
    "those locations is USD $199,600 - $304,200 per year."
)
# Job 1592: one req, two rungs, a shape Microsoft postings use.
MS_DUAL = (
    "Product Management IC4 - The typical base pay range for this role across the "
    "U.S. is USD $119,800 - $234,700 per year.\n"
    "Product Management IC5 - The typical base pay range for this role across the "
    "U.S. is USD $142,800 - $274,800 per year."
)
# Job 1277 (nvidia): a band per level, in the same sentence.
NV_SENTENCE = (
    "Your base salary will be determined based on your location, experience, and "
    "the pay of employees in similar positions. The base salary range is 200,000 "
    "USD - 322,000 USD for Level 5, and 240,000 USD - 379,500 USD for Level 6."
)


def _job(company: str, title: str, raw_level: str | None = None) -> RawJob:
    return RawJob(
        company=company,
        req_id="x",
        title=title,
        url="u",
        locations=["Redmond, WA"],
        raw_level=raw_level,
    )


def test_microsoft_rung_is_read_from_the_compensation_sentence():
    assert stated_level("microsoft", MS_SENTENCE) == "M6"
    assert stated_rungs("microsoft", MS_SENTENCE) == ["M6"]


def test_dual_rung_posting_keeps_both_rungs_ascending():
    # A req open at two rungs is a fact about the req. Collapsing it here would
    # discard the only evidence that it is dual-level.
    assert stated_level("microsoft", MS_DUAL) == "IC4/IC5"
    # Order of the two blocks in the text must not change the stored string.
    flipped = "\n".join(reversed(MS_DUAL.split("\n")))
    assert stated_level("microsoft", flipped) == "IC4/IC5"


def test_dual_rung_bands_at_the_lower_rung():
    # The stored disclosed band is the LOWER rung's block, so banding at the
    # higher one would pair a high level with a low band.
    assert lowest_stated_rung("IC4/IC5") == "IC4"
    band, conf = map_level(_job("microsoft", "Principal + Senior Product Manager", "IC4/IC5"))
    assert band is LevelBand.SENIOR
    assert conf is LevelConfidence.CONFIRMED


def test_nvidia_level_is_recorded_but_never_banded():
    # Nvidia's printed level is family-relative: at Level 4 it posts three
    # different bands and titles them senior / senior-staff / lead. Recording the
    # fact is right; banding from it would be a guess wearing an employer's voice.
    assert stated_level("nvidia", NV_SENTENCE) == "Level 5/Level 6"
    assert band_for_stated_rung("nvidia", "Level 5") is None
    # ...so the title mapper still decides.
    band, _ = map_level(_job("nvidia", "Principal Hardware Engineer", "Level 5/Level 6"))
    assert band is LevelBand.PRINCIPAL


@pytest.mark.parametrize(
    "text",
    [
        "the CPUs in the M1/M2 Mac are not levels",
        "we work directly with L5/L6 PMs across the org",
        "Level 3 support escalations are handled by this team",
        "The typical base pay range for this role is USD $1 - $2 per year.",
    ],
)
def test_prose_that_looks_like_a_rung_is_not_read_as_one(text):
    # Postings at other employers contain rung-shaped prose. A false
    # positive here is a wrong band stated with an employer's authority.
    assert stated_level("microsoft", text) is None
    assert stated_level("nvidia", text) is None


def test_employers_that_print_nothing_stay_silent():
    # Amazon is a large share of postings and prints no rung. The reader is a per-company
    # table for exactly this reason.
    assert stated_level("amazon", MS_SENTENCE) is None
    assert stated_level("apple", MS_SENTENCE) is None
    assert stated_level("google", NV_SENTENCE) is None


def test_stated_rung_outranks_the_title():
    # The employer's own ladder statement beats every reading of its title.
    # Job 4492: Microsoft says IC3; "Product Manager II" reads as an ambiguous PM.
    band, conf = map_level(_job("microsoft", "Product Manager II", "IC3"))
    assert (band, conf) == (LevelBand.MID, LevelConfidence.CONFIRMED)
    # "Sr. Business Program Manager" printed IC5 is Microsoft's Principal rung.
    assert map_level(_job("microsoft", "Sr Business Program Manager", "IC5"))[0] is LevelBand.PRINCIPAL
    # Without the rung, the title alone gives its own answer — so the assertions
    # above are testing the rung, not a coincidence.
    assert map_level(_job("microsoft", "Product Manager II"))[0] is LevelBand.SENIOR
    assert map_level(_job("microsoft", "Sr Business Program Manager"))[0] is LevelBand.SENIOR


@pytest.mark.parametrize(("title", "printed"), [
    # Job 4595: Microsoft prints M5/M6/IC5/IC6 on titles it calls Director;
    # the Director word stands.
    ("Senior Director Business Analytics", "M6"),
    ("Director, Silicon Design", "M5"),
    ("Group Creative Director", "M6"),
    ("Program Director - Telecommunications, Media, and Technology", "IC6"),
    ("Field Chief Information Security Officer-Manufacturing & Mobility (MFM)", "IC5"),
    ("Vice President, Azure Data", "M6"),
])
def test_a_rung_below_director_never_pulls_a_director_title_down(title, printed):
    # A printed rung below director does not outrank the
    # title's Director, VP or Chief officer. The title's own reading stands.
    reading = read_level(_job("microsoft", title, printed))
    assert reading.band is LevelBand.DIRECTOR_PLUS, title
    assert reading.basis is not LevelBasis.STATED


def test_a_director_rule_still_lets_the_rung_decide_everything_else():
    # Controls: a printed rung still decides a manager title that names no
    # director word, and a "Chief of Staff" is not a Chief officer.
    assert read_level(_job("microsoft", "Software Engineering Manager - Build and Tools", "M5")) == (
        LevelBand.PRINCIPAL, LevelConfidence.CONFIRMED, LevelBasis.STATED,
    )
    assert read_level(_job("microsoft", "Chief of Staff, Global Channel Sales", "M5")).basis is LevelBasis.STATED


def test_manager_and_ic_tracks_share_a_band_at_the_same_number():
    # M5 and IC5 post identical bands to the dollar; the track picks the ladder,
    # it does not move the rung. A mapping that offset M by one would fail here.
    for num in ("4", "5", "6"):
        assert band_for_stated_rung("microsoft", f"M{num}") is band_for_stated_rung(
            "microsoft", f"IC{num}"
        )


def test_uncalibrated_rung_falls_through_rather_than_guessing():
    # Microsoft also has a "Partner" tier; nothing in the corpus pins it, so an
    # unmapped rung must leave the title mapper in charge.
    assert band_for_stated_rung("microsoft", "IC9") is None
    band, _ = map_level(_job("microsoft", "Principal Software Engineer", "IC9"))
    assert band is LevelBand.PRINCIPAL
