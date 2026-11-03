"""Title normalization for repost matching: strips noise, never over-collapses."""

from __future__ import annotations

import pytest

from tracker.lineage.normalize import (
    title_grade,
    title_jaccard,
    title_key,
    titles_equal,
)


@pytest.mark.parametrize(
    "a, a_locs, b, b_locs",
    [
        # req-id noise
        ("Staff Software Engineer (R-4831)", [], "Staff Software Engineer", []),
        ("Staff Software Engineer #128374", [], "Staff Software Engineer", []),
        ("Staff Software Engineer - 449201", [], "Staff Software Engineer", []),
        ("Data Scientist Req 88213", [], "Data Scientist", []),
        # bracket noise a repost toggles
        ("Software Engineer (Remote)", [], "Software Engineer", []),
        ("Software Engineer (m/f/d)", [], "Software Engineer", []),
        ("Software Engineer (US)", [], "Software Engineer", []),
        # trailing location suffix using the job's OWN locations
        ("Software Engineer - London, UK", ["London, UK"], "Software Engineer", []),
        ("Software Engineer, Mountain View, CA", ["Mountain View, CA"], "Software Engineer", []),
        # level tokens dropped (level_band is an independent gate)
        ("Staff Software Engineer II", [], "Software Engineer", []),
        ("Senior Software Engineer", [], "Sr. Software Engineer", []),
        ("Software Engineer III", [], "Software Engineer", []),
        # punctuation / dashes / case
        ("Software Engineer, Infrastructure", [], "software engineer infrastructure", []),
        ("AI / ML Engineer", [], "ai ml engineer", []),
    ],
)
def test_reposts_with_minor_changes_key_equal(a, a_locs, b, b_locs):
    assert titles_equal(title_key(a, a_locs), title_key(b, b_locs))


@pytest.mark.parametrize(
    "a, b",
    [
        ("Engineering Manager, Data Platform", "Engineering Manager, Payments"),
        ("Software Engineer, Frontend", "Software Engineer, Backend"),
        ("Product Manager, Ads", "Product Manager, Search"),
    ],
)
def test_distinct_roles_do_not_key_equal(a, b):
    # locations empty -> the facet after the comma is a role facet, NOT a location,
    # so it survives normalization and keeps the roles distinct.
    ka, kb = title_key(a), title_key(b)
    assert not titles_equal(ka, kb)
    assert title_jaccard(ka, kb) < 0.6  # below the suspected-tier gate


def test_iOS_and_AI_are_not_mistaken_for_roman_or_level_tokens():
    assert title_key("iOS Engineer") == "ios engineer"
    assert title_key("AI Research Scientist") == "ai research scientist"


def test_explicit_title_grades_survive_match_key_normalization():
    assert title_key("Technical Program Manager I") == title_key("Technical Program Manager III")
    assert title_grade("Technical Program Manager I") == "i"
    assert title_grade("Technical Program Manager III") == "iii"
    assert title_grade("iOS Engineer") is None


def test_empty_and_none_titles_are_safe():
    assert title_key(None) == ""
    assert title_key("") == ""
    assert titles_equal("", "") is False  # two blanks are not a positive match
    assert title_jaccard("", "") == 1.0


def test_location_facet_only_stripped_when_it_is_the_jobs_location():
    # "Platform" is this job's team facet, not a location -> kept.
    assert title_key("Engineer, Platform", locations=["Seattle, WA"]) == "engineer platform"
    # Same string, but now Platform IS declared a location -> stripped.
    assert title_key("Engineer, Platform", locations=["Platform"]) == "engineer"
