"""Title normalization, head extraction, and per-company ladder rungs.

Titles here are verbatim from stored postings, so the suite fails for the real
shapes, not for invented ones.
"""

from __future__ import annotations

import pytest

from tracker.blueprint import BLUEPRINT, CompanyBlueprint, _check_title_profile
from tracker.enrich.level_mapper import map_level, read_level
from tracker.levels.ladder import band_for
from tracker.levels.titles import (
    PROFILES,
    RungRule,
    TitleProfile,
    match_rung_phrase,
    rung_for_title,
)
from tracker.schema import LevelBand, LevelBasis, LevelConfidence, RawJob
from tracker.taxonomy.title_parse import head_with_seniority, normalize, segments, title_head


def _job(company: str, title: str) -> RawJob:
    return RawJob(company=company, req_id="x", title=title, url="u", locations=["Seattle, WA"])


# --- normalization --------------------------------------------------------- #


def test_normalize_strips_req_codes_and_language_markers():
    assert normalize("Technical Program Manager III - AMZ27040.1") == "Technical Program Manager III"
    assert normalize("Program Manager III - AMZ27254.1") == "Program Manager III"
    assert (
        normalize("Forward Deployed Engineering Manager, GenAI (Korean, English)")
        == "Forward Deployed Engineering Manager, GenAI"
    )


def test_normalize_repairs_source_punctuation_damage():
    # All three shapes occur verbatim in stored amazon/google postings.
    assert normalize("Engineering Manager, Sensitive Deployments ") == "Engineering Manager, Sensitive Deployments"
    assert normalize("Principal, Technical Program Manager , Amazon Customer Service") == (
        "Principal, Technical Program Manager, Amazon Customer Service"
    )
    assert normalize("Sr. Program Manager, Same Day Programs,  ") == "Sr. Program Manager, Same Day Programs"
    assert segments("Senior Product Manager - Technical,  ") == ["Senior Product Manager", "Technical"]


def test_normalize_preserves_level_markers_that_look_like_parentheticals():
    # netflix encodes the rung in the title; stripping it would destroy evidence.
    assert normalize("Security Engineer (L5) - Cloud Architecture") == "Security Engineer (L5) - Cloud Architecture"


# --- head extraction ------------------------------------------------------- #


def test_title_head_skips_a_seniority_only_first_segment():
    # Stored postings have this shape; naive "head = first segment" reads
    # `Principal` as the role.
    assert title_head("Principal, Technical Program Manager , Amazon Customer Service") == (
        "Technical Program Manager"
    )
    assert head_with_seniority("Principal, Technical Program Manager , Amazon Customer Service") == (
        "Principal Technical Program Manager"
    )
    assert title_head("Director, Product Management, Discover and Gmail Ads") == "Product Management"


def test_title_head_stops_before_the_org_path():
    assert title_head("Forward Deployed Engineering Manager, GenAI, Delta, Google Cloud") == (
        "Forward Deployed Engineering Manager"
    )
    assert title_head("Sr. Category Manager - Packaging, Global Procurement Operations") == (
        "Sr. Category Manager"
    )


def test_title_head_handles_org_first_titles():
    # apple writes `Org - Role` often enough to matter: taking the first
    # segment reads a department as the job.
    assert title_head("User Experience - Quality Engineering Manager") == "Quality Engineering Manager"
    assert title_head("Machine Learning - Engineering Program Manager") == "Engineering Program Manager"
    # ...but a role-first title must not be dragged into its org path, even when
    # the org path also contains a role-ish word.
    assert title_head("GPU Performance Engineer, Platform Architecture") == "GPU Performance Engineer"
    assert title_head("Sr. Technical Program Manager, WW Tech Partners Solutions Architecture") == (
        "Sr. Technical Program Manager"
    )


def test_seniority_is_collected_from_any_position():
    # meta puts the rung after the role, apple in the middle. Reading only a
    # leading seniority segment demotes both.
    assert head_with_seniority("Product Management, Director - AI Platforms") == (
        "Director Product Management"
    )
    assert head_with_seniority("AIML - Director, Data Science and Insights") == (
        "Director Data Science and Insights"
    )
    assert map_level(_job("meta", "Product Management, Director"))[0] is LevelBand.DIRECTOR_PLUS
    assert map_level(_job("apple", "AIML - Director, Data Science"))[0] is LevelBand.DIRECTOR_PLUS


def test_head_with_seniority_never_absorbs_an_org_prefix():
    # Only seniority-only segments join the head; an org prefix carrying a level
    # word must not promote the role.
    assert head_with_seniority("User Experience - Quality Engineering Manager") == (
        "Quality Engineering Manager"
    )
    assert head_with_seniority("Principal Investigator Team - Program Manager") == "Program Manager"


def test_title_head_never_empty_for_a_nonempty_title():
    assert title_head("Principal") == "Principal"
    assert title_head("") == ""


# --- company ladder rungs -------------------------------------------------- #


@pytest.mark.parametrize(
    "title,rung",
    [
        ("Sr. Technical Program Manager", "L6"),
        ("Senior Technical Program Manager, Controls Engineering", "L6"),
        ("Technical Program Manager III", "L6"),
        ("Technical Program Manager II", "L5"),
    ],
)
def test_amazon_ladder_vocabulary(title, rung):
    assert rung_for_title("amazon", head_with_seniority(title)) == rung


@pytest.mark.parametrize(
    "title,family,rung",
    [
        ("Principal Product Manager - Technical", "product_management", "L7"),
        ("Sr. Principal Engineer", "software_engineering", "L8"),
        ("Senior Principal Engineer", "software_engineering", "L8"),
        ("Distinguished Engineer", "software_engineering", "L10"),
    ],
)
def test_amazon_rung_names_are_atlas_phrases(title, family, rung):
    """The words that NAME an Amazon rung are atlas rows, read
    for every function (its L-ladder is company-wide); the regex keeps none."""
    match = match_rung_phrase("amazon", head_with_seniority(title), family)
    assert match is not None and match.row.code == rung
    # The phrase is read before the regex's leading-"Sr." rule (L6): the
    # posting reads the rung its title names, on the company's own word.
    reading = read_level(_job("amazon", title), family)
    assert reading.basis is LevelBasis.COMPANY
    assert reading.band is band_for("amazon", rung, match.ladder)


def test_ladder_is_silent_for_companies_that_do_not_speak_it():
    # apple/meta/nvidia ladders are absent from titles; a guess would silently
    # move postings in or out of the board.
    for company in ("apple", "meta", "nvidia", "microsoft"):
        assert rung_for_title(company, "Senior Software Engineer") is None


def test_inherited_profile_resolves_through_the_parent():
    assert rung_for_title("google-deepmind", "Staff Research Engineer") == "L6"


# --- banding: the behaviour the user sees ---------------------------------- #


def test_amazon_sr_is_l6_senior_and_ii_is_l5_mid():
    # Amazon's own ladder: "Sr." is L6 (Senior SDE) and "II" is L5 (SDE II), its
    # senior and mid rungs. Reading L6 as staff and L5 as senior puts every
    # such posting one band high.
    band, confidence = map_level(_job("amazon", "Sr. Technical Program Manager, Amazon Robotics"))
    assert band is LevelBand.SENIOR
    assert confidence is LevelConfidence.CONFIRMED
    assert map_level(_job("amazon", "Technical Program Manager III - AMZ27040.1"))[0] is LevelBand.SENIOR
    # The ladder confirms what the generic tier left ambiguous ("Program Manager").
    band, confidence = map_level(_job("amazon", "Technical Program Manager II"))
    assert (band, confidence) == (LevelBand.MID, LevelConfidence.CONFIRMED)
    assert map_level(_job("amazon", "Software Development Engineer II, AWS"))[0] is LevelBand.MID
    assert map_level(_job("amazon", "Principal Software Development Engineer"))[0] is LevelBand.PRINCIPAL


def test_ladder_never_overturns_an_explicit_leadership_signal():
    # Negative control. "Sr." means L6 at Amazon, but a Sr. Director is a
    # director; the rung rule must not demote an explicit generic verdict.
    assert map_level(_job("amazon", "Sr. Director, Supply Chain"))[0] is LevelBand.DIRECTOR_PLUS
    assert map_level(_job("amazon", "Senior Director of Engineering"))[0] is LevelBand.DIRECTOR_PLUS
    # Amazon's Sr. Manager is its L7 by its own posted ranges: the
    # "Sr." rule never pulls it down to L6.
    assert map_level(_job("amazon", "Sr. Manager, Manufacturing Operations"))[0] is LevelBand.PRINCIPAL


def test_org_path_cannot_decide_a_level():
    # Negative control: "Principal" appears only in the team name.
    band, _ = map_level(_job("amazon", "Sr. Program Manager, Principal Investigator Team"))
    assert band is LevelBand.SENIOR  # from "Sr.", not PRINCIPAL from the org path


def test_management_vocabulary_survives_segmentation():
    # Segmenting removes the comma, so a needle written as "manager, engineering"
    # cannot fire on the head. Apple writes exactly this shape.
    assert map_level(_job("apple", "Manager, Engineering Program Manager, Apple Foundation Models"))[0] is (
        LevelBand.STAFF
    )
    assert map_level(_job("apple", "Manager, Engineering Project Management, Build Health"))[0] is (
        LevelBand.STAFF
    )


def test_org_acronyms_cannot_promote_a_level():
    # Negative control from a stored posting: the "vp " needle matched the org
    # acronym "TVP", banding a BI engineer as director_plus.
    assert map_level(_job("amazon", "Business Intelligence Engineer II, SCOT-FO, TVP"))[0] is (
        LevelBand.MID
    )
    # "architect" in an org path is not a principal signal.
    assert map_level(_job("nvidia", "Senior Program Manager, Architecture Review Board"))[0] is (
        LevelBand.SENIOR
    )
    assert map_level(_job("apple", "GPU Performance Engineer, Platform Architecture"))[0] is LevelBand.MID


def test_early_stage_markers_still_outrank_the_ladder():
    assert map_level(_job("amazon", "Software Development Engineer Intern"))[0] is LevelBand.INTERN
    assert map_level(_job("amazon", "Junior Program Manager"))[0] is LevelBand.ENTRY


# --- early-stage words are whole words -------------------------------- #


@pytest.mark.parametrize(
    "company,title,band",
    [
        # "intern" inside Internet / Internal / Internals / International is not
        # an intern: a substring rule reads each as entry CONFIRMED.
        ("google", "Staff Software Engineer, Internet Egress", LevelBand.STAFF),
        ("google", "Technology Auditor, Internal Audit", LevelBand.MID),
        ("databricks", "Senior Software Engineer - Database Engine Internals", LevelBand.SENIOR),
        ("anthropic", "Marketing Events Manager, International", LevelBand.MID),
    ],
)
def test_intern_inside_another_word_is_not_an_entry_marker(company, title, band):
    assert map_level(_job(company, title))[0] is band


def test_internal_audit_manager_is_not_entry():
    assert map_level(_job("deloitte", "Internal Audit Manager"))[0] not in (LevelBand.INTERN, LevelBand.ENTRY)


@pytest.mark.parametrize(
    "title,band",
    [
        # Internships and student jobs are the Intern rung ...
        ("Research Intern, PhD", LevelBand.INTERN),
        ("Software Development Engineer Intern", LevelBand.INTERN),
        ("Software Engineering Internship, Summer 2027", LevelBand.INTERN),
        ("Werkstudent Audit Execution CoE - Wirtschaftsprüfung (w/m/d)", LevelBand.INTERN),
        ("Praktikant Wirtschaftsprüfung (w/m/d)", LevelBand.INTERN),
        ("INTERN_NVE Design Eng", LevelBand.INTERN),
        # ... and a first full-time role is Entry.
        ("Software Engineer, TPU Compiler, PhD, Early Careers", LevelBand.ENTRY),
        ("Berufseinstieg FinancePLUS: Dein Traineeprogramm in der Assurance (w/m/d)", LevelBand.ENTRY),
        ("Collectibles Strategy ManagerGraduate (US E-Commerce) - 2027 Start (MBA)", LevelBand.ENTRY),
    ],
)
def test_real_early_stage_markers_read_their_stage(title, band):
    # Controls: the whole-word fix must keep every marker the substring caught,
    # including German compounds and words a board glued to their neighbour.
    assert map_level(_job("google", title)) == (band, LevelConfidence.CONFIRMED)


@pytest.mark.parametrize(
    "company,title,band",
    [
        ("amazon", "Associate Principal, Insights & Measurement", LevelBand.PRINCIPAL),
        ("google", "Associate Principal Analyst, Trust and Safety, Shopping", LevelBand.PRINCIPAL),
        # Titles first read at EY and KPMG; those firms read by their own rank
        # (tests/test_consulting_ladders.py), so the generic reading is held on
        # a company without one.
        ("acme", "Supply Chain and Operations Associate Director", LevelBand.DIRECTOR_PLUS),
        ("acme", "Senior Associate, Financial Due Diligence", LevelBand.SENIOR),
        # First read at Synopsys, which marks a bare Senior unconfirmed: the
        # generic reading is held on a company without that flag.
        ("acme", "Sales Account Representative, Sr Associate", LevelBand.SENIOR),
    ],
)
def test_associate_reads_by_its_stronger_rung_word(company, title, band):
    assert map_level(_job(company, title)) == (band, LevelConfidence.CONFIRMED)


@pytest.mark.parametrize(
    "company,title",
    [
        ("google", "Associate Product Manager"),
        # Role words are not rung words: a lead or an architect is not a staff
        # or principal rung, so "associate" still decides these.
        ("amazon", "Retail Lead Associate (Reduced-Time), Customer Experience Operations"),
        ("deloitte", "Associate Solution Architect with Modernization Experience"),
        ("ey", "Asistente Jr de Soporte Financiero"),
        ("ey", "Indirect tax Juniors - EY Global Delivery Services"),
    ],
)
def test_associate_without_a_stronger_rung_word_stays_entry(company, title):
    # The first full-time rung: Junior was folded into Entry.
    assert map_level(_job(company, title)) == (LevelBand.ENTRY, LevelConfidence.CONFIRMED)


@pytest.mark.parametrize(
    "company,title",
    [
        ("shopify", "Associate General Counsel, Employment"),
        ("verkada", "Deputy / Associate General Counsel, Corporate"),
        ("the-trade-desk", "Employment Associate General Counsel"),
        ("acme", "Associate Partner"),
        ("acme", "Associate Partner, Strategy & Operations"),
    ],
)
def test_associate_before_a_senior_office_is_no_entry_marker(company, title):
    # An Associate General Counsel is paid like a Senior Counsel and an
    # Associate Partner is the consulting rank. Neither names a band we
    # can place generically, so the title states a level we do not read.
    reading = read_level(_job(company, title))
    assert reading.band is not LevelBand.ENTRY
    assert (reading.band, reading.basis) == (LevelBand.MID, LevelBasis.NONE)


@pytest.mark.parametrize(
    "company,title",
    [
        # Below plain Counsel: the first attorney rung.
        ("google", "Associate Product Counsel, Ads"),
        ("amazon", "Associate Corporate Counsel, AWS Legal"),
        ("lyft", "Associate Counsel, Employment"),
        # A Business Partner is a role, and Partner here names a team, not a rank.
        ("fortinet", "Associate HR Business Partner"),
        ("salesforce", "Associate Partner Operations Manager"),
        ("salesforce", "Associate Partner Development Manager"),
    ],
)
def test_associate_counsel_and_business_partner_stay_entry(company, title):
    reading = read_level(_job(company, title))
    assert (reading.band, reading.basis) == (LevelBand.ENTRY, LevelBasis.GENERIC)


@pytest.mark.parametrize(
    "title,band,basis",
    [
        ("Channel Sales Launch Partner Manager- Austin (Third-Party Associate)", LevelBand.MID, LevelBasis.NONE),
        ("Creator Project Specialist - TikTok Shop - Germany (Third-party Associate)", LevelBand.MID, LevelBasis.NONE),
        ("Sourcing Coordinator, TikTok Local Services (Third Party Associate, Japan)", LevelBand.MID, LevelBasis.NONE),
        # The rest of the title still speaks.
        ("Senior Data Analyst (Third-party Associate)", LevelBand.SENIOR, LevelBasis.GENERIC),
        ("Associate Designer (Third-Party Associate)", LevelBand.ENTRY, LevelBasis.GENERIC),
        ("Junior Designer (Third-Party Associate)", LevelBand.ENTRY, LevelBasis.GENERIC),
    ],
)
def test_a_third_party_associate_tag_is_no_rung(title, band, basis):
    # TikTok tags a contractor role "(Third-Party Associate)": read by the tag
    # alone, each would read Entry.
    reading = read_level(_job("tiktok", title))
    assert (reading.band, reading.basis) == (band, basis)


@pytest.mark.parametrize(
    "title",
    [
        # Durations, counts and versions are not Netflix-style rungs:
        # read on the digit alone, each would be Senior. Real titles.
        "B2B Event Marketing Manager (6-Month Contract)",
        "Technical Recruiter [6 Month Contract]",
        "Recruiting Coordinator (7-month Fixed-Contract)",
        "Accounts Payable Assistant (3-6 Month Freelance)",
        "Administrator FTC 6 months",
        "Software Engineer (7+ years of experience)",
        "Civil Highway Engineer (4+ years of Transportation Design)",
        "24/7 Content Admin",
        "Spa Therapist Female (5-star Hotel)",
        "SAP BI 4.0 Dashboard Developer",
        "Controller (m/w/d) mit Schwerpunkt SAP S/4 HANA",
        "Care Assistant - Sutton Coldfield - Evenings 5-11 pm",
        "Consulting Manager ( min 6 ans d'experience)",
        "Lading Inspecteur 5-ploegen",
    ],
)
def test_a_number_that_is_no_rung_states_no_level(title):
    reading = read_level(_job("acme", title))
    assert (reading.band, reading.basis) == (LevelBand.MID, LevelBasis.NONE)


@pytest.mark.parametrize(
    "company,title",
    [
        ("netflix", "Software Engineer 5 - Ads Eventing"),
        ("netflix", "Software Engineer 6 - Creative Studio"),
        ("western-digital", "Technician 4, Manufacturing Equipment Maintenance"),
        ("broadcom", "R&D Engineer Software 5"),
        ("adobe", "Software Development Engineer 4"),
        ("amazon", "ICQA Operations Manager (Level 6)"),
    ],
)
def test_a_rung_numeral_still_reads_senior(company, title):
    assert read_level(_job(company, title)).band is LevelBand.SENIOR


# --- a company rule that names the rung ------------------------------- #


def test_a_rule_naming_the_rung_outranks_a_generic_role_word():
    # "Architect" alone would make these principal; Amazon's II/III and Google's Staff name
    # the rung itself.
    assert map_level(_job("amazon", "Solutions Architect II, Data and AI GTM"))[0] is LevelBand.MID
    assert map_level(_job("amazon", "Solutions Architect III"))[0] is LevelBand.SENIOR
    assert map_level(_job("google", "Staff Hardware System Architect, Pixel Watch"))[0] is LevelBand.STAFF
    # Amazon's Sr. Principal is L8, which its ladder bands director_plus.
    assert map_level(_job("amazon", "Sr. Principal Scientist, Kiro Science"))[0] is (
        LevelBand.DIRECTOR_PLUS
    )


def test_a_seniority_prefix_rule_does_not_get_that_reach():
    # Negative controls: Amazon's "Sr." rule and Google's "Senior" rule name no
    # manager rung (a senior manager sits above the IC "Senior" rung at both),
    # so they must not pull a manager title down to senior. Which band these
    # belong in is the family ladders' question, not this rule's.
    assert map_level(_job("amazon", "Sr. Manager, Product Management, Worldwide Returns"))[0] is not (
        LevelBand.SENIOR
    )
    assert map_level(_job("google", "Senior Engineering Manager, Android Application Safety"))[0] is not (
        LevelBand.SENIOR
    )


def test_no_company_rule_outranks_an_early_stage_marker():
    assert map_level(_job("amazon", "Robotics - Applied Scientist II Intern / Co-op - 2026"))[0] is (
        LevelBand.INTERN
    )
    assert map_level(_job("amazon", "IT Support Associate II, Ops Tech Solutions (OTS)"))[0] is (
        LevelBand.ENTRY
    )


def test_a_director_verdict_is_never_overridden_by_a_rule_naming_a_rung():
    # Amazon's "Principal" rule names a rung, but "Principal, Director" is a director.
    assert map_level(_job("amazon", "Director, Principal Programs"))[0] is LevelBand.DIRECTOR_PLUS
    assert map_level(_job("google", "Head of Staff Engineering Programs"))[0] is LevelBand.DIRECTOR_PLUS


def test_uncalibrated_companies_are_completely_unchanged():
    # apple keeps its deliberate weak-signal downgrade; google keeps its title
    # vocabulary. A profile that has not been measured must be inert.
    assert map_level(_job("apple", "Senior Software Engineer")) == (
        LevelBand.SENIOR,
        LevelConfidence.UNCONFIRMED,
    )
    assert map_level(_job("google", "Staff Software Engineer"))[0] is LevelBand.STAFF
    assert map_level(_job("google", "Product Manager")) == (
        LevelBand.SENIOR,
        LevelConfidence.UNCONFIRMED,
    )
    assert map_level(_job("microsoft", "Principal Software Engineer"))[0] is LevelBand.PRINCIPAL


# --- the blueprint gate ---------------------------------------------------- #


def test_every_shipped_company_declares_a_title_profile():
    for slug, bp in BLUEPRINT.items():
        assert _check_title_profile(bp) == [], slug
        assert slug in PROFILES


def test_gate_rejects_a_rung_absent_from_the_company_ladder(monkeypatch):
    bogus = TitleProfile("amazon", calibrated=True, rung_rules=(RungRule("L99", r"\bsr\.?\b"),))
    monkeypatch.setitem(PROFILES, "amazon", bogus)
    problems = _check_title_profile(BLUEPRINT["amazon"])
    assert problems and "is not a rung of the amazon ladder" in problems[0]


def test_gate_rejects_rules_on_an_uncalibrated_profile(monkeypatch):
    sloppy = TitleProfile("amazon", rung_rules=(RungRule("L6", r"\bsr\.?\b"),))
    monkeypatch.setitem(PROFILES, "amazon", sloppy)
    assert "uncalibrated" in " ".join(_check_title_profile(BLUEPRINT["amazon"]))


def test_gate_names_a_company_with_no_profile(monkeypatch):
    monkeypatch.delitem(PROFILES, "amazon")
    assert _check_title_profile(CompanyBlueprint("amazon", "Amazon", "amazon", True)) == [
        "missing from levels/titles.PROFILES"
    ]
