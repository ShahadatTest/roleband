"""Domain classification: what the work is about, from category + title.

The invariant under test is precedence:
the employer's own category outranks the title, company-internal vocabulary
outranks the shared lexicon, and nothing at all yields None rather than a guess.
"""

from __future__ import annotations

from typing import get_args

from tracker.enrich.classify import classify_domain, classify_domains, source_category
from tracker.schema import RawJob
from tracker.taxonomy.domains import all_slugs, classify_domain_text, domain_display


def _job(company: str, title: str, department: str | None = None, team: str | None = None) -> RawJob:
    return RawJob(
        company=company, req_id="x", title=title, url="u",
        locations=["Seattle, WA"], department=department, team=team,
    )


def test_employer_category_outranks_the_title():
    # "Sr. Operations Manager" says nothing; Amazon's own category says logistics.
    job = _job("amazon", "Sr. Operations Manager", department="Fulfillment & Operations Management")
    assert classify_domain(job) == "logistics_fulfillment"
    job2 = _job("amazon", "Senior Program Manager", department="Supply Chain/Transportation Management")
    assert classify_domain(job2) == "logistics_fulfillment"


def test_company_self_reference_is_not_vocabulary():
    # A company name in the team field supplies no domain signal.
    assert source_category(_job("google", "Staff SWE", team="Google")) == ""
    assert source_category(_job("google-deepmind", "Research Engineer", team="Google DeepMind")) == ""
    # ...so the domain must come from the title instead of the useless category.
    assert classify_domain(_job("google", "Staff Software Engineer, Cloud Storage", team="Google")) == (
        "cloud_infra"
    )


def test_company_internal_vocabulary_beats_the_shared_lexicon():
    # No general lexicon knows "SSD" is Amazon's Sub Same Day delivery org, or
    # that Kuiper is a satellite programme.
    assert classify_domain(_job("amazon", "Sr. Program Manager, SSD Ops Integration")) == (
        "logistics_fulfillment"
    )
    assert classify_domain(_job("amazon", "Sr. Manager, Amazon Flex")) == "logistics_fulfillment"
    assert classify_domain(_job("amazon", "Principal Product Manager, Project Kuiper")) == "public_sector"
    # The same terms mean nothing at another employer.
    assert classify_domain(_job("google", "Sr. Program Manager, SSD Ops Integration")) is None


def test_domain_is_read_from_the_role_head_when_the_org_path_is_silent():
    # "Sr. Supply Chain Manager, Amazon Flex" carries the domain in the head.
    assert classify_domain(_job("microsoft", "Senior Supply Chain Manager")) == "logistics_fulfillment"
    assert classify_domain(_job("meta", "Data Center Chief Engineer")) == "cloud_infra"


def test_unclassified_is_a_real_answer():
    # Guessing would hide a posting behind a filter set for other work.
    assert classify_domain(_job("meta", "Product Manager")) is None
    assert classify_domain(_job("amazon", "Sr. Product Manager - Tech, Tablets")) is None
    assert classify_domain_text("") is None
    assert domain_display(None) == "Unclassified"


def test_first_match_wins_in_declared_order():
    # Logistics precedes cloud, so a fulfillment-centre network role is logistics
    # rather than infrastructure.
    assert classify_domain_text("fulfillment center network") == "logistics_fulfillment"
    # ...and a title with no logistics term still reaches cloud.
    assert classify_domain_text("network infrastructure") == "cloud_infra"


def test_multi_label_records_every_world_a_posting_lives_in():
    # The load-bearing case for the array shape: a cross-world
    # posting must carry BOTH worlds, or a user who enabled the other one
    # loses it at the ingest gate to a first-match label.
    ads_ml = classify_domains(_job("google", "Machine Learning Engineering Manager, Ads Ranking"))
    assert "advertising" in ads_ml and "ai_ml" in ads_ml
    # Category and title can name different worlds; both are recorded, with
    # the more specific group (declaration order) first for display.
    ops = classify_domains(
        _job("amazon", "Sr. Operations Manager", department="Fulfillment & Operations Management")
    )
    assert ops[0] == "logistics_fulfillment"
    assert "corporate_operations" in ops


def test_company_vocabulary_hits_lead_the_ordering():
    # The employer knows its own orgs better than our lexicon, so a
    # company-term hit outranks a generic hit for the primary ([0]) slot.
    domains = classify_domains(_job("amazon", "Prime Video Machine Learning Manager"))
    assert domains[0] == "media_entertainment"  # amazon domain_terms: "prime video"
    assert "ai_ml" in domains  # generic: "machine learning"


def test_single_label_compat_is_first_of_the_multi_label():
    job = _job("amazon", "Prime Video Machine Learning Manager")
    assert classify_domain(job) == classify_domains(job)[0]
    assert classify_domain(_job("meta", "Product Manager")) is None
    assert classify_domains(_job("meta", "Product Manager")) == []


def test_domain_slugs_are_unique_and_displayable():
    slugs = all_slugs()
    assert len(slugs) == len(set(slugs))
    for slug in slugs:
        assert domain_display(slug) != slug  # every group has a human label


# -- how a keyword matches ------------------------------------------ #
# The negative title cases expose the
# misfires a substring matcher produces; each one would
# pass again under a plausible regression to `kw in text`.

import pytest  # noqa: E402

from tracker.api.schemas.scope import DomainKind  # noqa: E402
from tracker.taxonomy.domains import DOMAIN_GROUPS, KINDS, match_domains  # noqa: E402


@pytest.mark.parametrize(
    ("text", "world"),
    [
        # Whole words: the substring matcher's misfires.
        ("Software Engineering Manager, Robotics Neural Reconstruction", "facilities_realestate"),
        ("Principal Product Manager - Tech, Social Advertising", "devices_hardware"),
        ("Senior Program Manager, Maintain Detail Email Systems", "ai_ml"),
        # Amazon's data-center engineering category is not customer support.
        ("Operations, IT, & Support Engineering", "customer_support"),
        # Tax, trade and asset compliance are not security work.
        ("Sr. Tax Project Manager, Foreign Reporting and Compliance", "security_privacy"),
        ("Asset Compliance Program Lead, Hardware", "security_privacy"),
        # Apple's internal employee IT is not a developer platform.
        ("Audio Visual Program Manager, Employee Experience & Productivity", "developer_platform"),
        # Product marketing and SEO are not media.
        ("Director of Product Marketing, Adoption Content & Experiences", "media_entertainment"),
    ],
)
def test_a_keyword_inside_another_word_does_not_fire(text, world):
    assert world not in match_domains(text)


@pytest.mark.parametrize(
    ("text", "world"),
    [
        # Slugs: hyphens and underscores read as spaces.
        ("team-last-mile", "logistics_fulfillment"),
        ("team_supply_chain", "logistics_fulfillment"),
        # Short tokens are safe once matching is whole-word.
        ("Senior Product Manager - Apple Cloud AI/ML", "ai_ml"),
        ("Principal Product Manager Technical, Alexa AI", "ai_ml"),
        ("Product Manager, Multimodal Safety", "ai_ml"),
        ("Staff Software Engineer, TPU, Performance", "cloud_infra"),
        ("Principal Software Engineering Manager - Azure Core", "cloud_infra"),
        # Plurals, stems, and compounds.
        ("Senior Product Manager - Tech, Devices & Services New Initiatives", "devices_hardware"),
        ("Principal Product Manager, Technical, AWS Healthcare AI", "health_bio"),
        ("Engineering Manager, Cybersecurity Products", "security_privacy"),
        ("Sr. Data Engineer, iCloud", "cloud_infra"),
        ("Senior PMT External Services, CloudFront Product Management", "cloud_infra"),
        ("Principal Product Manager - Tech, Amazon Leo E-Commerce", "retail_commerce"),
        ("Senior Staff Machine Learning Engineer - Content Platform", "media_entertainment"),
    ],
)
def test_the_vocabulary_reaches_what_it_names(text, world):
    assert world in match_domains(text)


def test_every_world_has_a_kind_and_every_kind_has_worlds():
    assert {g.kind for g in DOMAIN_GROUPS} == set(KINDS)


def test_the_wire_names_exactly_the_kinds_the_taxonomy_declares():
    # The response model is a Literal; a kind added here but not there would
    # fail validation on every catalog read, not at import.
    assert set(get_args(DomainKind)) == set(KINDS)


# --------------------------------------------------------------------------- #
# Building the product vs running the department
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "expected", "refused"),
    [
        # Both sides of each pair of worlds must classify independently.
        ("Senior Technical Product Manager, Amazon Stores FinTech", "payments_fintech",
         "finance_accounting"),
        ("Group Product Manager, Payments Product Journey", "payments_fintech",
         "finance_accounting"),
        ("Sr. Program Manager - Tax, Transactional Tax PMO", "finance_accounting",
         "payments_fintech"),
        ("ERP Reporting and Analytics Solution Architect, Accounting", "finance_accounting",
         "payments_fintech"),
        ("Procurement Manager, Global Operations", "finance_accounting", "payments_fintech"),
        ("Staff Software Engineer, AI/ML, Search Ads", "advertising", "marketing_brand"),
        ("Sr. Applied Scientist, Sponsored Products and Brands", "advertising", None),
        ("Product Marketing Manager, Growth", "marketing_brand", "advertising"),
        ("Director, Brand and Communications", "marketing_brand", "advertising"),
    ],
)
def test_the_split_worlds_separate_the_product_from_the_department(text, expected, refused):
    """Corporate finance and fintech are two jobs, not one world: a seeker hiding
    one means to keep the other."""
    domains = match_domains(text)
    assert expected in domains, (text, domains)
    if refused is not None:
        assert refused not in domains, (text, domains)


def test_a_role_that_is_genuinely_both_carries_both():
    """A posting may name both a product world and a department function.
    Keeping only one would hide it from a seeker who selected the other."""
    domains = match_domains("Head of Advertising Marketing, Brand Studio")
    assert {"advertising", "marketing_brand"} <= set(domains)


def test_the_two_halves_are_filed_under_different_kinds():
    """`kind` is what the screen groups by, and the split exists because the
    reader treats a department differently from an industry."""
    kinds = {group.slug: group.kind for group in DOMAIN_GROUPS}
    assert kinds["payments_fintech"] == "industry" and kinds["finance_accounting"] == "function"
    assert kinds["advertising"] == "industry" and kinds["marketing_brand"] == "function"


def test_every_world_says_in_one_line_what_it_covers():
    """The Interests card's second line is the world's own hint, not the
    matched postings' department names, which can put "Finance Finance" under
    AI and "Sales Sales" under Health. A hint is short enough for one line on
    the narrowest card and repeats no word of the name (not "Security, fraud,
    safety" under "Security, Privacy & Trust")."""
    import re

    def words(text: str) -> set[str]:
        return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w != "and"}

    for group in DOMAIN_GROUPS:
        assert group.hint, group.slug
        assert len(group.hint) <= 28, f"{group.slug}: {group.hint!r} wraps on a narrow card"
        shared = {
            w for w in words(group.hint)
            if any(w[:5] == n[:5] for n in words(group.display))
        }
        assert not shared, f"{group.slug}: {group.hint!r} repeats {shared} from {group.display!r}"
    hints = [group.hint for group in DOMAIN_GROUPS]
    assert len(set(hints)) == len(hints), "two worlds share a hint"
