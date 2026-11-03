"""Functional tests for smart-search query parsing (pure, no DB / no network).

Covers the structured-extraction + money-cue + remainder invariants documented in
`tracker/search/parse.py`, plus the LLM layer's taxonomy coercion and its guaranteed
fallback to the local parser when disabled (the default).
"""

from __future__ import annotations

import asyncio

import pytest

from tracker.company_discovery import company_names
from tracker.search.llm import _coerce, _tool, resolve_query
from tracker.search.parse import companies_mentioned, parse_query
from tracker.taxonomy.roles import classify_role

#: Every named company, as the Board knows the ones it shows.
KNOWN = company_names()


def parse(query: str):
    return parse_query(query, companies=KNOWN)


def test_full_structured_query_extracts_every_facet():
    p = parse("staff ml engineer at google remote over 500k")
    assert p.company == ["google"]
    assert "staff" in p.level_band
    assert p.family == ["ml_ai_research"]
    assert "remote" in p.workplace_type
    assert p.comp_min == 500_000
    assert p.comp_max is None
    # Every token was consumed by a filter, so remainder falls back to full text
    # (never lose semantic signal) rather than going empty.
    assert p.remainder


def test_money_cue_required_so_counts_are_not_comp():
    # "top 5" / "5 roles" must NOT be read as a $5 comp bound — no money cue.
    p = parse("top 5 machine learning roles")
    assert p.comp_min is None
    assert p.comp_max is None
    assert p.family == ["ml_ai_research"]


def test_comp_range_min_max_and_plus_forms():
    assert (parse("400k-600k principal").comp_min,
            parse("400k-600k principal").comp_max) == (400_000, 600_000)
    assert parse("over 300k").comp_min == 300_000
    assert parse("under 250k").comp_max == 250_000
    assert parse("500k+").comp_min == 500_000


def test_small_number_without_magnitude_is_not_comp():
    # A money cue ("comp") is present, but 500 with no k/m suffix is implausibly
    # small for total comp and must be ignored.
    p = parse("comp 500")
    assert p.comp_min is None
    assert p.comp_max is None


def test_remainder_keeps_unstructured_skill_terms():
    p = parse("kubernetes at google")
    assert p.company == ["google"]
    # Company span + orphaned connective "at" removed, skill term preserved.
    assert p.remainder == "kubernetes"


@pytest.mark.parametrize(
    ("query", "family"),
    [
        ("solutions engineer in london", "solutions_sales_eng"),
        ("sales engineer, new york", "solutions_sales_eng"),
        ("forward deployed engineer remote", "solutions_sales_eng"),
        ("customer engineer at google", "solutions_sales_eng"),
        ("support engineer remote", "it_support"),
        ("documentation engineer remote", "technical_writing"),
        # The negative control: a software engineer is still one.
        ("software engineer remote", "software_engineering"),
        ("senior engineer, payments", "software_engineering"),
    ],
)
def test_a_query_names_the_family_its_postings_are_filed_under(query, family):
    # Software engineering's catch-all `engineer ` matches any trailing word or
    # comma, so a parser that let it win would filter the real postings out.
    assert parse(query).family == [family]
    assert classify_role(query) == family


def test_the_family_s_words_leave_the_remainder():
    p = parse("solutions engineer kubernetes")
    assert p.family == ["solutions_sales_eng"]
    assert p.remainder == "kubernetes"


def test_applied_science_query_parses_a_family():
    # Amazon's canonical title phrase is "applied science". Carried only in
    # department_keywords, which `parse_query` never reads, it would send the
    # whole query to the semantic remainder with no family filter. The taxonomy
    # table is shared by ingestion and parsing, which is why it is asserted on
    # both surfaces.
    p = parse("Applied Science Manager, Prime Video Personalization & Discovery")
    assert p.family == ["ml_ai_research"]
    # The role phrase is consumed as structure; the mission text stays semantic.
    assert "Prime Video" in p.remainder


def test_empty_query_yields_empty_parse():
    p = parse("   ")
    assert p.remainder == ""
    assert p.company == [] and p.level_band == [] and p.comp_min is None


def test_structured_returns_only_nonempty_filters():
    assert parse("remote").structured() == {"workplace_type": ["remote"]}


def test_llm_coerce_drops_values_outside_taxonomy():
    parsed = _coerce(
        {
            "company": ["google", "not_a_real_company"],
            "level_band": ["staff", "bogus"],
            "family": [],
            "workplace_type": [],
            "location_group": [],
            "comp_min": 500_000,
            "comp_max": None,
            "remainder": "ml",
        },
        fallback_remainder="fallback text",
        company_slugs=list(KNOWN),
    )
    assert parsed.company == ["google"]  # hallucinated slug dropped
    assert parsed.level_band == ["staff"]
    assert parsed.comp_min == 500_000
    assert parsed.remainder == "ml"


def test_llm_coerce_blank_remainder_falls_back():
    parsed = _coerce({"remainder": "   "}, fallback_remainder="from local parser", company_slugs=[])
    assert parsed.remainder == "from local parser"


def test_resolve_query_uses_local_parser_when_llm_disabled():
    # search_llm_enabled defaults to False, so resolve_query must equal the local
    # parser output — search works with no API key configured.
    p = asyncio.run(resolve_query("remote at google", egress_allowed=False, companies=KNOWN))
    assert p.company == ["google"]
    assert p.workplace_type == ["remote"]


# --------------------------------------------------------------------------- #
# The companies a query may name are the caller's: every named company here,
# the ones the Board shows in search (`best_match.board_company_names`).
# --------------------------------------------------------------------------- #


def test_a_catalog_company_named_in_a_query_is_a_company_filter():
    """Stripe is a catalog company, not one of the built-ins."""
    p = parse("stripe staff engineer")
    assert p.company == ["stripe"]
    assert p.level_band == ["staff"]
    assert parse("payments at stripe").remainder == "payments", "the name leaves the remainder"


def test_a_name_outside_the_given_companies_stays_in_the_remainder():
    p = parse_query("stripe staff engineer", companies={"google": KNOWN["google"]})
    assert p.company == []
    assert "stripe" in p.remainder
    assert parse_query("kubernetes at google", companies={}).company == []


def test_a_display_name_or_an_alias_names_the_company():
    assert parse("scale ai data engineer").company == ["scaleai"]
    assert parse("snapchat ios engineer").company == ["snap"]


def test_the_longest_company_name_wins_over_one_inside_it():
    assert parse("google deepmind research engineer").company == ["google-deepmind"]
    assert parse("google research engineer").company == ["google"], "the control"


@pytest.mark.parametrize("query", [
    "google deepmind research engineer",
    "stripe staff engineer",
    "snapchat ios engineer",
    "Platform Strategy Lead, Cloud",
    "product manager",
])
def test_the_companies_a_query_mentions_parse_it_as_every_company_does(query):
    """Search reads the Board's companies only for those a query mentions, so
    the mentioned ones must parse the query exactly as all of them do."""
    mentioned = companies_mentioned(query, KNOWN)
    assert parse_query(query, companies=mentioned) == parse(query)
    shown = {slug: names for slug, names in KNOWN.items() if slug != "google-deepmind"}
    assert parse_query(query, companies=companies_mentioned(query, shown)) == parse_query(query, companies=shown)


def test_a_name_inside_another_word_is_not_mentioned():
    assert companies_mentioned("Platform Strategy Lead, Cloud", KNOWN) == {}, "ea is inside lead"
    assert "electronic-arts" in companies_mentioned("ea producer", KNOWN), "the control"


def test_the_model_may_choose_only_the_companies_it_was_given():
    offered = _tool(["google", "stripe"])["input_schema"]["properties"]["company"]
    assert offered["items"]["enum"] == ["google", "stripe"]
    assert _tool([])["input_schema"]["properties"]["company"] == {"type": "array", "maxItems": 0}
    parsed = _coerce(
        {"company": ["stripe", "openai"], "remainder": "staff engineer"},
        fallback_remainder="staff engineer", company_slugs=["stripe"],
    )
    assert parsed.company == ["stripe"], "a company it was not given is dropped"


# --------------------------------------------------------------------------- #
# Word boundaries on display names. The loop that matches location
# display names against free text cannot use a bare substring search over
# hundreds of groups: "china" appears inside "china shop", "chad" and
# "jordan" are common words and names, and "georgia" is a US state everyone
# searches for by name.
# --------------------------------------------------------------------------- #


def test_a_country_name_inside_another_word_is_not_a_location():
    # Bounded matching fixes names EMBEDDED in longer words. It cannot fix
    # genuine lexical ambiguity — "a china shop" really does contain the whole
    # word "china" — and claiming otherwise would be a test that lies about
    # what the change bought.
    assert "china" not in parse("chinatown restaurant lead").location_group
    assert "chad" not in parse("hiring manager chadwick").location_group
    assert "india" not in parse("indianapolis site lead").location_group
    assert "georgia" not in parse("georgian software engineer").location_group


def test_a_country_named_as_a_whole_word_still_parses():
    assert "china" in parse("engineering manager in China").location_group
    assert "india" in parse("staff engineer, India").location_group
    assert "uae" in parse("product lead UAE").location_group


def test_curated_substrings_stay_loose():
    """The hand-written `substrings` are deliberately partial (", uk", " uk")
    and must keep matching inside a phrase — only display names got boundaries."""
    assert "uk" in parse("engineering manager, london uk").location_group


def test_an_internship_and_a_junior_role_name_different_rungs():
    """Intern is its own rung; "junior" names Entry / Junior."""
    assert parse("software intern london").level_band == ["intern"]
    assert parse("software internship").level_band == ["intern"]
    assert parse("junior data analyst").level_band == ["entry"]
