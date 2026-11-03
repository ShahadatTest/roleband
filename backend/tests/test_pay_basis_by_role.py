"""A pay range the posting defines per kind of role.

Anthropic, Adobe, Databricks and Palo Alto Networks define their range as base
salary for non-sales roles and on-target earnings (or base + commission) for
sales roles. The text alone cannot say which applies, the role can. Contracts:

- Only an `unclear` band is settled; a marker the band's own text states wins.
- A non-sales role's band is base and a sales role's is total, as the employer
  defines them. Pre-sales, customer success, a customer-facing architect title
  and a row with no family stay unclear.
- A sentence about a bonus plan for non-sales roles is not a range definition.
- Every writer of a band (connector, text, page) applies the same rule, and
  reads a stated bonus target against the basis it settles on.
- A band its own paragraph calls a salary is base, outside a
  conditional clause, and never at Netflix, whose "salary" is a chosen share of
  a total. A posting that defines its band per kind of role is read by the role.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import tracker.pay_disclosure as pay_disclosure
from tracker.connectors.detail.base import source_disclosed_comp_from_text
from tracker.connectors.listing.greenhouse import pay_tiers
from tracker.db.models import Job
from tracker.db.repo import _apply_fields
from tracker.intelligence_runtime.disclosed_comp import extract_disclosed_comp, settle_stored_bands
from tracker.pay_disclosure import (
    PayBasis,
    basis_for_role,
    defines_band_by_role,
    derive_pay_basis,
    extract_grounded_band,
)
from tracker.schema import (
    AccessSurface,
    ApplicationFormFacts,
    EnrichedJob,
    JobDescriptionSection,
    LevelBand,
    LevelConfidence,
    PostingPage,
    RawJob,
    RetrievalState,
    SourceDisclosedComp,
    SourceJobFacts,
)
from tracker.taxonomy.roles import sells
from tracker.workflows.posting_pages import apply_page

# The employers' own sentences, verbatim.
ANTHROPIC = (
    "The annual compensation range for this role is listed below. For sales roles, the range "
    "provided is the role’s On Target Earnings (\"OTE\") range, meaning that the range includes "
    "both the sales commissions/sales bonuses target and annual base salary for the role.\n\n"
    "Annual Salary:\n$305,000—$385,000 USD"
)
ADOBE = (
    "The U.S. pay range for this position is $148,100 - $282,100 annually.\n\n"
    "At Adobe, for sales roles starting salaries are expressed as total target compensation "
    "(TTC = base + commission), and short-term incentives are in the form of sales commission "
    "plans.  Non-sales roles starting salaries are expressed as base salary and short-term "
    "incentives are in the form of the Annual Incentive Plan (AIP)."
)
DATABRICKS = (
    "The pay range(s) for this role is listed below and represents the expected salary range "
    "for non-commissionable roles or on-target earnings for commissionable roles.\n\n"
    "$226,000 - $285,000 USD"
)
PALO_ALTO = (
    "For candidates who receive an offer at the posted level, the starting base salary (for "
    "non-sales roles) or base salary + commission target (for sales/com-missioned roles) is "
    "expected to be the annual range listed below.\n\n$185,900 - $300,675/yr"
)
FIGMA = (
    "Figma also offers sales incentive compensation for most sales roles and an annual bonus "
    "plan for eligible non-sales roles.\n\nAnnual Base Salary Range:\n$258,000—$376,000 USD"
)


@pytest.mark.parametrize("text", [ANTHROPIC, ADOBE, DATABRICKS, PALO_ALTO], ids=["anthropic", "adobe", "databricks", "palo-alto"])
def test_each_employer_definition_is_read_as_one(text):
    assert defines_band_by_role(text)


def test_a_bonus_plan_for_non_sales_roles_defines_no_range():
    assert not defines_band_by_role(FIGMA)
    assert not defines_band_by_role("The base salary range for this role is $200,000 - $250,000.")
    assert not defines_band_by_role(None)


@pytest.mark.parametrize("text", [ANTHROPIC, ADOBE, DATABRICKS, PALO_ALTO], ids=["anthropic", "adobe", "databricks", "palo-alto"])
def test_a_non_sales_role_reads_base_and_a_sales_role_total(text):
    assert basis_for_role("unclear", text, "software_engineering", "Staff Software Engineer") == "base"
    assert basis_for_role("unclear", text, "product_management", "Principal Product Manager") == "base"
    assert basis_for_role("unclear", text, "sales_business_development", "Manager, Enterprise Sales") == "total"


@pytest.mark.parametrize("family, title", [
    ("solutions_sales_eng", "Manager, Forward Deployed Engineering"),
    ("customer_success", "Customer Success Manager"),
    (None, "Lead Learning Technical Enablement Specialist"),
    # Anthropic files this under ML research; its posted ranges top the base it files.
    ("ml_ai_research", "Applied AI Architect, Enterprise Tech"),
    ("ml_ai_research", "Manager of Applied AI Architecture, Startups"),
])
def test_a_role_whose_commission_cannot_be_told_stays_unclear(family, title):
    assert basis_for_role("unclear", ANTHROPIC, family, title) == "unclear"


def test_a_basis_the_band_states_is_never_overridden():
    # A sales role at a company that calls the band base keeps base, and a total stays total.
    assert basis_for_role("base", DATABRICKS, "sales_business_development", "Account Executive") == "base"
    assert basis_for_role("total", ANTHROPIC, "software_engineering", "Software Engineer") == "total"
    assert basis_for_role(None, ANTHROPIC, "software_engineering", "Software Engineer") is None


def test_without_a_definition_an_unclear_band_stays_unclear():
    assert basis_for_role("unclear", "Pay range: $200,000 - $250,000", "software_engineering", "Engineer") == "unclear"
    assert basis_for_role("unclear", FIGMA, "software_engineering", "Engineer") == "unclear"


@pytest.mark.parametrize("family, title, expected", [
    ("sales_business_development", "Account Executive", True),
    ("software_engineering", "Software Engineer", False),
    ("ml_ai_research", "Research Scientist", False),
    ("solutions_sales_eng", "Solutions Engineer", None),
    ("customer_success", "Customer Success Manager", None),
    (None, None, None),
    ("ml_ai_research", "Applied AI Security Architect", None),
    ("software_engineering", "Solutions Architect, Cloud", None),
    ("software_engineering", "Software Architect", False),
])
def test_who_sells(family, title, expected):
    assert sells(family, title) is expected


# --- a band its paragraph calls a salary ------- #

from tracker.pay_disclosure import names_salary, settle_band  # noqa: E402

NETFLIX = (
    "Compensation & Benefits\nGenerally, our compensation structure consists solely of an annual "
    "salary; we do not have bonuses. You choose each year how much of your compensation you want "
    "in salary versus stock options. To determine your personal top of market compensation, we "
    "rely on market indicators and consider your specific job family, background, skills, and "
    "experience to determine your compensation in the market range. The range for this role is "
    "$436,000.00 - $791,000.00."
)


@pytest.mark.parametrize("text, bounds", [
    ("Role Location Annual Salary Range California $94,400 to $266,300", [94400, 266300]),  # Accenture
    ("California Salary Range:\n$198,000 - $368,000", [198000, 368000]),  # KPMG
    ("Salary:\n$163,000.00 - $224,000.00", [163000, 224000]),  # Applied Materials
    ("The typical starting salary range for this role is:\n$104,800—$165,700 USD", [104800, 165700]),  # Elastic
], ids=["accenture", "kpmg", "applied-materials", "elastic"])
def test_a_band_its_paragraph_calls_a_salary_is_base(text, bounds):
    assert names_salary(text, bounds)
    assert settle_band("unclear", text, "product_management", "Principal Product Manager", bounds).pay_basis == "base"


def test_netflix_is_the_exception():
    """Netflix's "salary" is the cash the person chooses out of a total: its band
    reads total, and an unclear one is never made base by the word."""
    bounds = [436000, 791000]
    assert derive_pay_basis(NETFLIX, bounds) is PayBasis.total
    assert not names_salary(NETFLIX, bounds)
    assert settle_band("unclear", NETFLIX, "software_engineering", "Engineering Manager", bounds).pay_basis == "unclear"


def test_salary_in_a_conditional_clause_or_elsewhere_does_not_settle_it():
    bounds = [200000, 250000]
    conditional = "For sales roles, the salary range includes commission.\nThe range is $200,000 - $250,000."
    history = "We never ask about salary history.\n\nThe range is $200,000 - $250,000."
    for text in (conditional, history):
        assert not names_salary(text, bounds)
    assert not names_salary("Annual Salary: $305,000—$385,000", [999, 1000])  # band not in the text


def test_a_posting_that_defines_its_band_per_role_is_read_by_the_role_not_the_word():
    """Adobe also says "salary range"; its sales roles still read total."""
    text = ADOBE.replace("The U.S. pay range", "The U.S. salary range")
    bounds = [148100, 282100]
    assert settle_band("unclear", text, "sales_business_development", "Account Executive", bounds).pay_basis == "total"
    assert settle_band("unclear", text, "product_management", "Product Manager", bounds).pay_basis == "base"


def test_settling_never_overrides_a_stated_basis():
    text = "Salary:\n$163,000.00 - $224,000.00"
    assert settle_band("total", text, "product_management", "PM", [163000, 224000]).pay_basis == "total"
    assert settle_band(None, text, "product_management", "PM", [163000, 224000]).pay_basis is None


FORWARD_SALARY = (
    "Compensation\nSalary and Other Compensation: The annual salary range for this position is displayed below. "
    "Factors which may affect starting pay within this range may include geography/market, skills, "
    "education, experience and other qualifications of the successful candidate.\n\n"
    "The Company offers the following benefits for this position, subject to applicable eligibility "
    "requirements: medical insurance, dental insurance, vision insurance, flexible spending accounts, "
    "health savings accounts (HSA) with company contribution, 401(k) retirement plan with matching, "
    "employee stock purchase program, life insurance, AD&D, short-term disability insurance, "
    "long-term disability insurance, generous paid time off, company holidays, parental leave, "
    "identity theft protection, pet insurance, pre-paid legal insurance, back-up child and eldercare "
    "days, product discounts, referral bonus program, and more.\n\nPay Range\n$125,000—$150,000 USD"
)


def test_an_explicit_forward_salary_reference_survives_the_intervening_benefits_paragraph():
    assert settle_band("unclear", FORWARD_SALARY, "hardware_engineering", "Firmware Developer",
                        [125000, 150000]).pay_basis == "base"
    assert not names_salary(FORWARD_SALARY, [120000, 150000])


@pytest.mark.parametrize("text", [
    FORWARD_SALARY.replace("The annual salary range for this position", "For sales roles, the annual salary range"),
    FORWARD_SALARY.replace("The annual salary range for this position", "The annual salary range for other positions"),
    FORWARD_SALARY.replace("Pay Range", "Signing Bonus Range"),
    FORWARD_SALARY.replace("Pay Range", "Total Pay Range"),
    FORWARD_SALARY + "\n\nAnother location's Pay Range\n$140,000—$180,000 USD",
    FORWARD_SALARY.replace("Pay Range", "The range includes commission.\nPay Range"),
    FORWARD_SALARY.replace("Pay Range", "On-target earnings (OTE).\nPay Range"),
    FORWARD_SALARY + "\n\n" + "Additional details. " * 80 + "The range includes commission.",
    FORWARD_SALARY.replace("Pay Range", "For some roles the range differs.\nPay Range"),
    FORWARD_SALARY.replace("Pay Range", "Other Compensation\n" + "Unrelated duties. " * 200 + "\nPay Range"),
], ids=["conditional", "other-position", "bonus", "total-heading", "multiple-ranges", "inclusive", "ote",
        "later-inclusive", "conditional-range", "remote-reference"])
def test_a_forward_reference_never_settles_an_unrelated_or_ambiguous_band(text):
    assert settle_band("unclear", text, "hardware_engineering", "Firmware Developer",
                        [125000, 150000]).pay_basis == "unclear"


def test_a_forward_reference_keeps_an_already_stated_total_and_employee_election():
    assert settle_band("total", FORWARD_SALARY, "hardware_engineering", "Firmware Developer",
                        [125000, 150000]).pay_basis == "total"
    assert not names_salary(FORWARD_SALARY + "\n" + NETFLIX, [125000, 150000])


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["connector", "text"])
async def test_salary_reference_reaches_stored_base_without_changing_the_employer_numbers(db_session, source):
    raw = RawJob(company="sharkninja", req_id="firmware", title="Senior Firmware Developer",
                 url="https://example.test/firmware", raw_level="Senior", locations=["Needham, MA"],
                 description_sections=[JobDescriptionSection("pay_and_benefits", "Compensation", FORWARD_SALARY)])
    if source == "connector":
        raw.source_disclosed_comp = SourceDisclosedComp(
            base_min=125000, base_max=150000, currency="USD", pay_period="year")
    job = Job(company=raw.company, req_id=raw.req_id, dedupe_key=raw.dedupe_key())
    _apply_fields(job, EnrichedJob(raw=raw, level_band=LevelBand.SENIOR, level_confidence=LevelConfidence.CONFIRMED,
                                  family="hardware_engineering", location_groups=["united_states"]))
    db_session.add(job)
    await db_session.flush()
    if source == "text":
        result = await extract_disclosed_comp(db_session, [job.id], page_band=None)
        assert result["disclosed"] == 1
    await db_session.commit()
    await db_session.refresh(job)
    assert (job.disclosed_base_min, job.disclosed_base_max) == (125000, 150000)
    assert (job.disclosed_pay_basis, job.disclosed_pay_period, job.disclosed_currency) == ("base", "year", "USD")
    assert job.disclosed_source == source and job.raw_level == "Senior"


# --- a bonus target read against the settled basis ------- #

#: No marker of its own makes this band base; the word "salary" settles it,
#: and the bonus target beside it is then that base's bonus.
SALARY_AND_BONUS = "Salary range: $150,000 - $200,000 per year. Annual bonus target of 15%."
SALARY_BOUNDS = [150000, 200000]


def test_a_band_its_salary_wording_makes_base_keeps_the_bonus_target_beside_it():
    assert derive_pay_basis(SALARY_AND_BONUS, SALARY_BOUNDS) is PayBasis.unclear
    assert settle_band("unclear", SALARY_AND_BONUS, "software_engineering", "Staff Engineer",
                       SALARY_BOUNDS) == ("base", 0.15)
    # Negative controls: a band nothing makes base, and one the posting
    # defines per kind of role read for a sales role, carry no bonus share.
    pay_range = SALARY_AND_BONUS.replace("Salary range", "Pay range")
    assert settle_band("unclear", pay_range, "software_engineering", "Staff Engineer",
                       SALARY_BOUNDS) == ("unclear", None)
    per_role = DATABRICKS.replace("$226,000 - $285,000 USD", "$226,000 - $285,000 USD. Annual bonus target of 15%.")
    assert settle_band("unclear", per_role, "sales_business_development", "Account Executive",
                       [226000, 285000]) == ("total", None)
    assert settle_band("unclear", per_role, "software_engineering", "Staff Engineer",
                       [226000, 285000]) == ("base", 0.15)


def test_the_band_is_located_once_from_the_read_to_the_stored_bonus(monkeypatch):
    calls = []
    real = pay_disclosure.locate_pay_span

    def counted(text, bounds):
        calls.append(tuple(bounds))
        return real(text, bounds)

    monkeypatch.setattr(pay_disclosure, "locate_pay_span", counted)
    band = extract_grounded_band(SALARY_AND_BONUS, SALARY_AND_BONUS)
    settled = settle_band(band.pay_basis.value, SALARY_AND_BONUS, "software_engineering", "Staff Engineer",
                          [band.base_min, band.base_max], span=band.span)
    assert settled == ("base", 0.15)
    assert calls == [tuple(SALARY_BOUNDS)]


def test_a_bonus_the_source_read_beside_its_band_stands_on_a_base_band():
    """A connector reads its own pay block; carving it into a section can leave
    the stored band paragraphs away from "a 20% annual bonus"."""
    text = ("For this position, the annual salary will include a 20% annual bonus.\n\n"
            + "We offer medical, dental and vision coverage. " * 8
            + "\n\nCompensation\nSalary Range\n$252,000 - $300,000 USD")
    bounds = [252000, 300000]
    assert settle_band("base", text, "software_engineering", "Director", bounds) == ("base", None)
    assert settle_band("base", text, "software_engineering", "Director", bounds,
                       stated_bonus=0.2) == ("base", 0.2)
    assert settle_band("total", text, "software_engineering", "Director", bounds,
                       stated_bonus=0.2) == ("total", None)


_PAGE_NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize("writer", ["connector-field", "connector-text", "text", "page", "stored-settle"])
async def test_every_writer_stores_the_bonus_target_of_a_band_its_salary_wording_makes_base(db_session, writer):
    raw = RawJob(company="acme", req_id=f"eng-{writer}", title="Staff Software Engineer",
                 url=f"https://example.test/{writer}", raw_level="Staff", locations=["Austin, TX"],
                 description_sections=[JobDescriptionSection("pay_and_benefits", "Compensation", SALARY_AND_BONUS)])
    if writer == "connector-field":
        raw.source_disclosed_comp = SourceDisclosedComp(
            base_min=150000, base_max=200000, currency="USD", pay_period="year")
    elif writer == "connector-text":
        raw.source_disclosed_comp = source_disclosed_comp_from_text(SALARY_AND_BONUS, SALARY_AND_BONUS)
    job = Job(company=raw.company, req_id=raw.req_id, dedupe_key=raw.dedupe_key())
    _apply_fields(job, EnrichedJob(raw=raw, level_band=LevelBand.STAFF, level_confidence=LevelConfidence.CONFIRMED,
                                  family="software_engineering", location_groups=["united_states"]))
    if writer == "page":
        job.source_facts = SourceJobFacts(
            provider="greenhouse", access_surface=AccessSurface.PUBLIC_API,
            tenant_identity="acme", posting_id="1",
        ).as_dict()
        tier = pay_tiers([{"title": "Salary range", "min_cents": 15000000, "max_cents": 20000000,
                           "currency_type": "USD"}], _PAGE_NOW)
        form = ApplicationFormFacts(state=RetrievalState.PRESENT, required=1, written=0, choices=1,
                                    observed_at=_PAGE_NOW)
        assert apply_page(job, PostingPage(form, tier))
    elif writer == "stored-settle":
        # A connector band stored unclear before the salary reading existed.
        job.disclosed_base_min, job.disclosed_base_max = SALARY_BOUNDS
        job.disclosed_currency, job.disclosed_pay_period = "USD", "year"
        job.disclosed_pay_basis, job.disclosed_bonus_pct = "unclear", None
        job.disclosed_source = "connector"
    db_session.add(job)
    await db_session.flush()
    if writer == "text":
        assert (await extract_disclosed_comp(db_session, [job.id], page_band=None))["disclosed"] == 1
    elif writer == "stored-settle":
        assert await settle_stored_bands(db_session, [job.id]) == 1
    await db_session.commit()
    await db_session.refresh(job)
    assert (job.disclosed_base_min, job.disclosed_base_max) == tuple(SALARY_BOUNDS)
    assert (job.disclosed_pay_basis, job.disclosed_bonus_pct) == ("base", 0.15)
    assert job.disclosed_source == {"connector-field": "connector", "connector-text": "connector",
                                    "stored-settle": "connector"}.get(writer, writer)
