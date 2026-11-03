"""Consulting firms read by their own rank.

EY, KPMG, Deloitte, PwC and Accenture title their people by firm rank, and the
rank words do not mean what a tech ladder means by them: EY's entry rung is
"Staff", and its "Senior" is the second rung, three to six years in. Read
literally, the entry rung would band staff and the second rung senior. For
these firms the evidence outranks the word: years in rank (the firms' own
career paths), cross-firm mappings, and the base ranges the firms post on
their own US listings.

The rank is read anywhere in the title, because these firms write it as its
own segment ("Cyber - Enterprise Security Architect - Manager - Consulting"),
and it outranks the generic words, Director included. Every title below is a
stored title, verbatim.
"""

from __future__ import annotations

import pytest

from tracker.enrich.classify import classify_family
from tracker.enrich.level_mapper import read_level
from tracker.levels.ladder import rung_for_code
from tracker.levels.pay import level_label, pay_label, seed_range
from tracker.levels.titles import PROFILES
from tracker.schema import LevelBand, LevelBasis, RawJob

E, M, S = LevelBand.ENTRY, LevelBand.MID, LevelBand.SENIOR
ST, P, D = LevelBand.STAFF, LevelBand.PRINCIPAL, LevelBand.DIRECTOR_PLUS

FIRMS = ("ey", "kpmg", "deloitte", "pwc", "accenture")


def _read(company: str, title: str):
    job = RawJob(company=company, req_id="t", title=title, url="")
    return read_level(job, classify_family(job))


RANKED = [
    # EY writes the rank as its own segment, anywhere in the title.
    ("ey", "LMS ECG Staff - EY Global Delivery Services", E),
    ("ey", "Associate Consultant - Business Consulting Risk - National - CNS - Risk - Digital Risk - Pune", E),
    ("ey", "Consultant - Tech Consulting - FS - CNS - TC - Java Developer - Mumbai", E),
    ("ey", "EYP - Transactions & Corporate Finance (TCF) - SaT - TCF - Financial Diligence - Senior 1", M),
    ("ey", "Senior Consultant - Supply Chain and Operations", M),
    ("ey", "Accounts Payable Senior Associate", M),
    ("ey", "Assistant Manager - Assurance - National - ASU - FAAS - Financial&AccountingAdv - Bangalore, Gurgaon", M),
    ("ey", "Cyber - Enterprise Security Architect - Manager - Consulting", S),
    ("ey", "Manager - Data Science & AI - AI & Data - Technology Consulting - Belfast", S),
    ("ey", "GDS Consulting - FS Risk - Senior Manager", ST),
    ("ey", "Insights Strategy Execution Senior Specialist-Associate Director", P),
    ("ey", "EY-Parthenon - Strategy and Execution - Deal Management - Director", P),
    ("ey", "EY-Parthenon- Investment Banking - MedTech - Managing Director", D),
    # KPMG leads with the rank.
    ("kpmg", "Associate, Economic Valuation Services - Complex Securities | Multiple Locations Winter 2027", E),
    ("kpmg", "Senior Associate, Indirect Tax", M),
    ("kpmg", "Manager, International Tax", S),
    ("kpmg", "Senior Manager, SALT - Income Franchise (Corp)", ST),
    ("kpmg", "Associate Director, AI Security Frontier Engineering", P),
    ("kpmg", "Director, SAP S4 Public Cloud Delivery Lead", P),
    ("kpmg", "Associate Managing Director, Data Portfolio Management", D),
    # Deloitte: Analyst, Consultant, Senior Consultant, Manager, Senior Manager.
    ("deloitte", "Consultative Offerings - Analyst - Enterprise Strategy", E),
    # Deloitte's second rung reads mid, as every other firm's second rung does.
    ("deloitte", "Cyber Operate SOC L1 Analyst - Consultant", M),
    ("deloitte", "Cyber Identity - Saviynt Senior Consultant", M),
    ("deloitte", "Tax Senior, Legal Business Services - Technology", M),
    ("deloitte", "MES Solution Architect Manager (AVEVA)", S),
    ("deloitte", "Cyber Network Security Architecture – Senior Manager", ST),
    ("deloitte", "Associate Director, Technology Controls Advisory", P),
    # PwC appends the rank.
    ("pwc", "P&C Technical Solutions Architect, Manager", S),
    ("pwc", "Applied AI Health Data Architect-Senior Manager", ST),
    ("pwc", "Deal Data Technology & Analytics, Director", P),
    # Accenture's career levels: Analyst (CL11), Senior Analyst (10),
    # Consultant (9), Associate Manager (8), Manager (7), Senior Manager (6),
    # Associate Director (5), Principal Director and Managing Director above.
    ("accenture", "Business Analyst - 6470764", E),
    ("accenture", "Group Insurance Billing Senior Analyst", M),
    ("accenture", "SAP S/4HANA Finance Consultant - Utilities", M),
    ("accenture", "Digital Product Design Associate Manager", M),
    ("accenture", "SAP Product Costing Manager - CMT (High Tech)", S),
    ("accenture", "Security Solution Architect Senior Manager", ST),
    ("accenture", "Modern Service Management Assoc Director", P),
    ("accenture", "Public Service Management Consulting Principal Director", D),
    # A craft or team name must not outrank the firm's stated rank.
    ("ey", "EY Wavespace-Facilitator-Supervising Associate", M),
    # The rank is Supervising Associate; Art Director names the craft.
    ("ey", "CBS-BMC-Creative Services-Supervising Associate-Art Director", M),
    ("deloitte", "Cyber Oracle Identity Senior Consultant / Senior Engineering", M),
    ("accenture", "Accenture Construct – Senior Project Cost Analyst, ANS", M),
]


@pytest.mark.parametrize(("company", "title", "band"), RANKED)
def test_a_firm_rank_reads_its_band(company, title, band):
    reading = _read(company, title)
    assert (reading.band, reading.basis) == (band, LevelBasis.COMPANY), title


@pytest.mark.parametrize(("company", "title", "band"), [
    # Two ranks offered for one req read by the lower, the convention for a
    # dual-level posting (`taxonomy.stated_level.lowest_stated_rung`).
    ("kpmg", "Manager/Senior Manager, Transfer Pricing", S),
    ("kpmg", "Senior Manager or Manager, SALT M&A", S),
    ("accenture", "Supply Chain and Engineering– Software Defined Vehicle (SDV) Go-To-Market, "
                  "Senior Manager / Associate Director", ST),
])
def test_two_ranks_for_one_req_read_the_lower(company, title, band):
    assert _read(company, title).band is band


@pytest.mark.parametrize(("company", "title"), [
    # A role word that only looks like a rank: no firm rank is read.
    ("accenture", "Droga5 Senior Social Art Director"),
    ("accenture", "Creative Agency Associate Creative Director, Copywriter"),
    ("ey", "Microsoft Alliance, Operations Specialist - Partner Programs - EY GDS"),
    # A Big 4 "Principal" in these titles is a technical role, not the rank.
    ("ey", "Principal Data & AI Architect - Government Services"),
    ("deloitte", "Principal Architect"),
    # EY India's Associate Vice President is not the Associate rank.
    ("ey", "Associate Vice President - SaT - National - SaT - S&E - Corporate Finance - Mumbai"),
])
def test_a_role_word_is_not_a_rank(company, title):
    reading = _read(company, title)
    assert reading.basis is not LevelBasis.COMPANY, (title, reading)


def test_a_partner_program_is_not_the_partner_rank():
    """"Partner Program" names a team; the rank in this title is Assistant
    Director, EY's Senior Manager equivalent."""
    reading = _read("ey", "GDS Microsoft Partner Program Specialist - Assistant Director")
    assert (reading.band, reading.basis) == (ST, LevelBasis.COMPANY)


@pytest.mark.parametrize(("raw_level", "title", "band"), [
    # Accenture's listing sends its career level (`careerLevel`); the firm's
    # own field decides before the title, which often names no rank.
    ("Team Lead/Consultant", "Workday Advanced Compensation and Benefits Lead", M),
    ("Senior Manager", "Retail Banking Senior Manager", ST),
    ("Associate Director", "Retirement Management Consulting Associate Director", P),
    ("Manager", "AGBG Mid Market Sales Engineer - UK", S),
])
def test_accentures_career_level_field_decides_first(raw_level, title, band):
    job = RawJob(company="accenture", req_id="t", title=title, url="", raw_level=raw_level)
    reading = read_level(job, classify_family(job))
    assert reading.band is band, (title, reading)
    assert reading.basis in (LevelBasis.STATED, LevelBasis.COMPANY)


def test_a_firm_rank_is_never_read_again_from_the_page():
    """A posting is read in full when the page could state its level;
    a firm rank already did, and Accenture's field is read with the listing."""
    from tracker.enrich.level_mapper import full_read_can_state

    # PwC has a measured data-science range and this head names no rung, so
    # only the rank says no (shaped like PwC's "P&C Technical Solutions
    # Architect, Manager").
    for company, title in (("pwc", "Customer Analytics Data Scientist, Manager"),
                           ("ey", "Cyber - Enterprise Security Architect - Manager - Consulting"),
                           ("accenture", "Workday Advanced Compensation and Benefits Lead")):
        job = RawJob(company=company, req_id="t", title=title, url="")
        assert full_read_can_state(job, classify_family(job)) is False, title


def test_an_intern_stays_an_intern():
    # The firm's rank never reaches an intern: Intern is its own rung.
    reading = _read("kpmg", "Advisory Intern, Federal Supply Chain & Operations | McLean Summer 2027")
    assert reading.band is LevelBand.INTERN and reading.basis is LevelBasis.GENERIC


@pytest.mark.parametrize(("company", "title", "band", "basis"), [
    # The rank reading is the five firms' alone: the same words elsewhere
    # keep their generic reading. A manager
    # rank elsewhere is a level in that company's own terms we cannot place
    #: the generic band stays, unmapped.
    ("acme", "Senior Manager, Strategy", ST, LevelBasis.UNMAPPED),
    ("acme", "Director, Product Analytics", D, LevelBasis.GENERIC),
    ("acme", "Staff Software Engineer", ST, LevelBasis.GENERIC),
    ("acme", "Senior Consultant, Platform", S, LevelBasis.GENERIC),
])
def test_other_companies_keep_the_generic_reading(company, title, band, basis):
    reading = _read(company, title)
    assert reading.band is band and reading.basis is basis


@pytest.mark.parametrize("firm", FIRMS)
def test_every_rank_names_a_rung_of_the_firm(firm):
    ranks = PROFILES[firm].ranks
    assert ranks, firm
    assert [r.rung for r in ranks if rung_for_code(firm, r.rung) is None] == []


@pytest.mark.parametrize("firm", FIRMS)
@pytest.mark.parametrize("band", [S, ST, P, D])
def test_pay_reads_what_it_read_before_the_ladder(firm, band):
    """Without a ladder the pay lookups ask by the band word and no seed
    applies; a consulting rung says the same, so no estimate moves."""
    assert level_label(firm, band) == band.value
    assert pay_label(firm, band) == band.value
    assert seed_range(firm, band) is None
