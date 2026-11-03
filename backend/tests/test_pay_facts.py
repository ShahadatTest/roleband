"""Company pay facts in the raw store: UK bonus reports and SEC filings.

Contracts:

- A UK report row becomes facts only for an employer we track, with ISO dates,
  and the report's named "responsible person" never reaches a fact.
- An SEC fiscal year is a year: a quarter, or a stub period inside an annual
  report, is not that year's stock-compensation expense; a restated year keeps
  its restatement; a company's figure comes from one tag, not the sum of two.
- From the annual report's text: the headcount sentence and the sentences that
  say how restricted stock units vest, never the hidden XBRL header.
"""

from __future__ import annotations

import json

import pytest

from scripts import build_pay_observations as build
from tracker.pay_store import facts as pf

_UK = {
    "EmployerName": "REVOLUT LTD", "EmployerId": "12345", "MaleBonusPercent": "84.3", "FemaleBonusPercent": "81.7",
    "DiffMedianBonusPercent": "40.1", "DiffMedianHourlyPercent": "18.0", "EmployerSize": "1000 to 4999",
    "ResponsiblePerson": "Jane Example (Chief People Officer)", "DueDate": "2026/04/05 00:00:00",
    "DateSubmitted": "2026/03/27 13:34:41",
}


def test_a_uk_report_becomes_facts_for_a_tracked_employer():
    facts = pf.uk_facts(_UK, {"REVOLUT LTD": "revolut"})
    by = {f.fact: f for f in facts}
    assert set(by) == {f for _, f in pf.UK_FACTS}
    assert (by["bonus_share_men_pct"].value, by["bonus_share_men_pct"].unit) == ("84.3", "pct")
    assert by["employer_size"].unit == ""
    assert {(f.company, f.period_end, f.observed_on, f.source_ref) for f in facts} == {
        ("revolut", "2026-04-05", "2026-03-27", "12345/2026")}
    assert not any("Jane" in v for f in facts for v in vars(f).values())


def test_an_untracked_uk_employer_and_an_empty_cell_are_no_facts():
    assert pf.uk_facts(_UK, {}) == []
    facts = pf.uk_facts({**_UK, "DiffMedianBonusPercent": ""}, {"REVOLUT LTD": "revolut"})
    assert "bonus_gap_median_pct" not in {f.fact for f in facts}


def test_an_employer_name_is_matched_ignoring_spacing():
    facts = pf.uk_facts({**_UK, "EmployerName": "Revolut  Ltd"}, {"REVOLUT LTD": "revolut"})
    assert facts and facts[0].employer == "Revolut  Ltd"


def test_a_name_listed_for_two_companies_is_refused(tmp_path):
    clash = tmp_path / "uk.json"
    clash.write_text(json.dumps({"ey": ["ERNST & YOUNG LLP"], "kpmg": ["Ernst & Young  LLP"]}))
    with pytest.raises(ValueError, match="both"):
        pf.names(clash)


def _entry(val, start, end, form="10-K", filed="2026-02-01", accn="0001-26-000001"):
    return {"val": val, "start": start, "end": end, "form": form, "filed": filed, "accn": accn}


def _doc(**tags):
    return {"entityName": "ServiceNow, Inc.", "facts": {"us-gaap": {
        tag: {"units": {"USD": entries}} for tag, entries in tags.items()}}}


def test_only_a_full_fiscal_year_is_that_years_expense():
    doc = _doc(ShareBasedCompensation=[
        _entry(1_955_000_000, "2025-01-01", "2025-12-31"),
        _entry(480_000_000, "2025-10-01", "2025-12-31"),  # the fourth quarter, inside the 10-K
        _entry(1_199_000_000, "2026-01-01", "2026-06-30", form="10-Q"),
    ])
    facts = pf.xbrl_facts("servicenow", doc)
    assert [(f.fact, f.period_end, f.value, f.unit) for f in facts] == [
        ("sbc_expense", "2025-12-31", "1955000000", "USD")]


def test_a_restated_year_keeps_the_restatement():
    doc = _doc(ShareBasedCompensation=[
        _entry(1_700_000_000, "2024-01-01", "2024-12-31", filed="2025-02-01"),
        _entry(1_750_000_000, "2024-01-01", "2024-12-31", filed="2026-02-01"),
    ])
    assert [f.value for f in pf.xbrl_facts("servicenow", doc)] == ["1750000000"]


def test_a_headcount_is_one_per_period_the_latest_filing():
    """Each 10-K and its amendment tag the same date again: the count is one
    row per period, the latest filing's."""
    def employees(val, end, filed, form="10-K"):
        return {"val": val, "end": end, "form": form, "filed": filed, "accn": f"a-{filed}"}

    doc = {"entityName": "ServiceNow, Inc.", "facts": {"dei": {"EntityNumberOfEmployees": {"units": {"pure": [
        employees(26_293, "2025-12-31", "2026-02-01"),
        employees(26_300, "2025-12-31", "2026-04-15", form="10-K/A"),
        employees(22_668, "2024-12-31", "2025-02-01"),
        employees(22_668, "2024-12-31", "2026-02-01"),  # repeated in the next year's report
        employees(27_000, "2026-03-31", "2026-04-20", form="10-Q"),
    ]}}}}}
    heads = [(f.period_end, f.value) for f in pf.xbrl_facts("servicenow", doc) if f.fact == "employees"]
    assert heads == [("2024-12-31", "22668"), ("2025-12-31", "26300")]


def test_the_figure_comes_from_one_tag():
    doc = _doc(ShareBasedCompensation=[_entry(1_955_000_000, "2025-01-01", "2025-12-31")],
               AllocatedShareBasedCompensationExpense=[_entry(1_950_000_000, "2025-01-01", "2025-12-31")])
    facts = pf.xbrl_facts("servicenow", doc)
    assert [(f.value, f.evidence) for f in facts] == [("1955000000", "us-gaap:ShareBasedCompensation")]


_REPORT = """<html><body><ix:header><ix:hidden>As of December 31, 2025, we had approximately 1 employees.</ix:hidden></ix:header>
<p>As of December 31, 2025, we had 2,424 employees in our research and development organization.</p>
<p>Our Employees</p><p>As of December 31, 2025, we had approximately 26,293 full-time employees, of whom 48% were outside the United States.</p>
<p>Restricted stock units generally vest over four years, with 25% vesting on the first anniversary of the grant date and the remainder vesting quarterly thereafter.</p>
<p>We granted restricted stock units with a total fair value of $3.1 billion.</p>
<p>PRSUs vest based on achievement of performance targets over a three-year period.</p></body></html>"""


def test_the_report_states_its_headcount_and_vesting():
    text = pf.report_text(_REPORT)
    assert "approximately 1 employees" not in text
    facts = pf.report_facts("servicenow", {"accession": "0001-26-000001", "report_date": "2025-12-31",
                                           "filed": "2026-02-01"}, text)
    heads = [f for f in facts if f.fact == "employees_stated"]
    # A department's count comes first in many reports; both are kept, in order.
    assert [(f.value, f.unit, f.period_end) for f in heads] == [
        ("2424", "people", "2025-12-31"), ("26293", "people", "2025-12-31")]
    assert len({f.fact_id for f in facts}) == len(facts)
    vesting = [f.evidence for f in facts if f.fact == "vesting_terms"]
    assert vesting == [
        "Restricted stock units generally vest over four years, with 25% vesting on the first anniversary "
        "of the grant date and the remainder vesting quarterly thereafter.",
        "PRSUs vest based on achievement of performance targets over a three-year period.",
    ]


@pytest.mark.parametrize(("sentence", "count"), [
    ("As of December 31, 2025, we employed approximately 1,556,000 full-time and part-time employees.", "1556000"),
    ("As of September 27, 2025, the Company had approximately 166,000 full-time equivalent employees.", "166000"),
    ("As of December 31, 2025, we had a total of 125,665 employees.", "125665"),
    ("As of December 31, 2025, we had approximately 850 full-time employees.", "850"),
])
def test_a_headcount_is_read_in_the_ways_reports_say_it(sentence, count):
    facts = pf.report_facts("x", {"accession": "a", "report_date": "2025-12-31", "filed": "2026-02-01"}, sentence)
    assert [f.value for f in facts if f.fact == "employees_stated"] == [count]


def test_a_number_that_is_not_a_headcount_is_not_read():
    text = "We repurchased 12,000,000 shares. Revenue grew 2,400 basis points across 3,000 customers."
    facts = pf.report_facts("x", {"accession": "a", "report_date": "2025-12-31", "filed": "2026-02-01"}, text)
    assert facts == []


@pytest.mark.parametrize("path", [build.UK_EMPLOYERS, build.SEC_COMPANIES])
def test_every_mapped_company_is_one_we_name(path):
    from tracker import config
    from tracker.company_catalog import CATALOG
    from tracker.company_discovery import COMPANY_DISCOVERY

    named = set(config.COMPANIES) | set(CATALOG) | set(COMPANY_DISCOVERY)
    assert sorted(set(json.loads(path.read_text(encoding="utf-8"))) - named) == []
    if path == build.UK_EMPLOYERS:
        assert pf.names(path)  # loads: no name listed for two companies
