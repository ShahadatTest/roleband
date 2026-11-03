"""A director rung in a segment the head skipped reads its level.

Level rules read the role segment and the segments that are nothing but
seniority words. A rung sharing its segment with a product or org must still
be read: Cadence "Application Engineer, RTL2GDS Sr Director" and Applied
Materials "Business Development (Director)" (a parenthesis must not be stripped
as a language tag) would otherwise sit in "Level not placed". Every case below
is a stored title.
"""

from __future__ import annotations

import pytest

from tracker.enrich.classify import classify_family
from tracker.enrich.level_mapper import read_level
from tracker.schema import LevelBand, LevelBasis, RawJob
from tracker.taxonomy.title_parse import normalize


def _read(company: str, title: str):
    raw = RawJob(company=company, req_id="x", title=title, url="")
    return read_level(raw, classify_family(raw))


@pytest.mark.parametrize(("company", "title"), [
    ("cadence", "Application Engineer, RTL2GDS Sr Director"),  # the rung closes a segment
    ("synopsys", "Product Management, Senior Director- Synopsys ICV Custom Rules"),
    ("applied-materials", "Applied Global Services Business Development (Director)"),  # in parentheses
    ("qualcomm", "RTL Design (Director)"),
    ("okx", "Deputy General Counsel, Head of Americas Legal"),  # the rung opens a segment
    ("tiktok", "TikTok Shop - Head of Content Governance"),
    ("moonlake", "Member of Technical Staff - Head of Robotics"),
    ("asana", "VP/GM, Product Management- Asana for Services Management"),  # a tech VP leads with it
])
def test_a_director_rung_beside_an_org_reads_director(company, title):
    assert _read(company, title).band is LevelBand.DIRECTOR_PLUS


@pytest.mark.parametrize(("company", "title"), [
    # A bank appends its corporate rank; a VP rank closing the title is no
    # director, with or without a profile saying so.
    ("btig", "Technology, Software Development Engineer in Test (SDET), Vice President"),
    ("icapital", "Sales & Partnerships Europe - Vice President"),
    # Where the company states its bank rank, a "Head of" beside it does not overrule it.
    ("icapital", "Global Head of Payroll - Vice President / Senior Vice President"),
    # The people the role supports, in parentheses.
    ("render", "Executive Business Partner (CEO, VP of Finance, VP of People)"),
    # Someone else's office.
    ("acme", "Program Manager, Office of the Director"),
    ("acme", "Analyst, Director's Office"),
    # An agency account rank in the middle of a segment is no closing rung.
    ("burson", "Social & Content Strategist - Account Director level - Corporate"),
])
def test_a_rung_that_names_someone_else_or_a_bank_rank_is_not_read(company, title):
    assert _read(company, title).band is not LevelBand.DIRECTOR_PLUS


@pytest.mark.parametrize(("company", "title", "band"), [
    # A rung in the head stands: the segment names a function the role directs.
    ("shield-ai", "Senior Staff Engineer, Test Director (R5445)", LevelBand.PRINCIPAL),
    ("databricks", "Principal AI Research Scientist, Research Director - AI Scaling", LevelBand.PRINCIPAL),
    # An org path still says nothing below director.
    ("amazon", "Sr. Program Manager, Principal Investigator Team", LevelBand.SENIOR),
])
def test_a_rung_in_the_head_is_never_overruled_by_another_segment(company, title, band):
    assert _read(company, title).band is band


@pytest.mark.parametrize(("title", "band"), [
    ("Software Engineer (Senior)", LevelBand.SENIOR),
    ("Machine Learning Engineer (Staff)", LevelBand.STAFF),
])
def test_a_rung_in_parentheses_is_no_language_tag(title, band):
    reading = _read("candidhealth", title)
    assert (reading.band, reading.basis) == (band, LevelBasis.GENERIC)


def test_a_language_tag_is_still_stripped():
    assert normalize("Account Executive (Korean, English)") == "Account Executive"
    assert normalize("Software Engineer (Senior)") == "Software Engineer (Senior)"
