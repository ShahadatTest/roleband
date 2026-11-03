"""The raw pay observation store: DOL import and the builder.

Contracts:

- **No person leaves the filing.** The import keeps an allowlist of columns, so
  the filers' names, emails and phones (present in every real file) are never
  written, and a column the agency adds later is dropped, not copied.
- Only certified cases are data points; the files' blank padding is not a row.
- One observation per case across overlapping quarterly files, the latest
  decision winning; ids are stable across rebuilds.
- Pay is annualised from the stated unit; an amount that is not pay (zero, a
  typo far outside a salary, an unknown unit) is no data point.
- A filing employer belongs to at most one company we track.
"""

from __future__ import annotations

import csv
import json
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from scripts import build_pay_observations as build
from scripts import import_dol_disclosures as dol
from tracker.pay_store import observations as store

# --- a real-shaped .xlsx, written the way the agency's files are -------------- #

_LCA_HEADER = [
    "CASE_NUMBER", "CASE_STATUS", "RECEIVED_DATE", "DECISION_DATE", "VISA_CLASS", "JOB_TITLE", "SOC_CODE", "SOC_TITLE",
    "FULL_TIME_POSITION", "TOTAL_WORKER_POSITIONS", "EMPLOYER_NAME", "EMPLOYER_FEIN", "NAICS_CODE",
    "EMPLOYER_POC_LAST_NAME", "EMPLOYER_POC_EMAIL", "AGENT_ATTORNEY_EMAIL_ADDRESS",
    "WORKSITE_CITY", "WORKSITE_STATE", "WAGE_RATE_OF_PAY_FROM", "WAGE_RATE_OF_PAY_TO",
    "WAGE_UNIT_OF_PAY", "PW_WAGE_LEVEL", "SOMETHING_NEW_NEXT_YEAR",
]


def _lca_row(case, status, decided, title, employer, wage_from, wage_to="", unit="Year", poc="Rivera"):
    return [case, status, str(int(decided) - 7), decided, "H-1B", title, "15-1252.00", "Software Developers", "Y", "1",
            employer, "12-3456789", "541511", poc, f"{poc.lower()}@example.com", "atty@lawfirm.example",
            "SAN JOSE", "CA", wage_from, wage_to, unit, "III", "unexpected value"]


def _xlsx(path: Path, rows: list[list[str]], padding: int = 2) -> Path:
    """Strings shared (as the agency writes text), numbers inline, a few
    all-empty rows at the end (the agency's files end with very many)."""
    strings: list[str] = []

    def ref(text: str) -> int:
        if text not in strings:
            strings.append(text)
        return strings.index(text)

    def col(i: int) -> str:
        name = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            name = chr(65 + r) + name
        return name

    body = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            if value == "":
                continue
            if value.replace(".", "").isdigit():
                cells.append(f'<c r="{col(c)}{r}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{col(c)}{r}" t="s"><v>{ref(value)}</v></c>')
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    for r in range(len(rows) + 1, len(rows) + 1 + padding):
        body.append(f'<row r="{r}"><c r="A{r}" s="1"/></row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    shared = "".join(f"<si><t>{s.replace('&', '&amp;')}</t></si>" for s in strings)
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("xl/sharedStrings.xml", f"<sst {ns}>{shared}</sst>")
        book.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{''.join(body)}</sheetData></worksheet>")
    return path


@pytest.fixture
def lca_file(tmp_path):
    rows = [
        _LCA_HEADER,
        _lca_row("I-1", "Certified", "45931", "Senior Software Engineer", "SERVICENOW, INC.", "173000", "190000"),
        _lca_row("I-2", "Denied", "45931", "Software Engineer", "SERVICENOW, INC.", "120000"),
        _lca_row("I-3", "Certified - Withdrawn", "45950", "Staff Software Engineer", "Acme Robotics LLC", "95", "", "Hour"),
    ]
    return _xlsx(tmp_path / "LCA_Disclosure_Data_FY2026_Q3.xlsx", rows)


def test_the_import_keeps_no_person_and_no_unknown_column(lca_file, tmp_path):
    out = dol.write(lca_file, tmp_path / "dol")
    text = out.read_text(encoding="utf-8")
    assert "@" not in text and "Rivera" not in text, "a filer's contact reached the slim file"
    assert "unexpected value" not in text, "a column outside the allowlist was copied"
    assert text.splitlines()[0].split(",") == [name for name, _ in dol.COLUMNS["lca"]]


def test_the_import_keeps_certified_cases_and_no_padding(lca_file, tmp_path):
    rows = list(csv.DictReader(dol.write(lca_file, tmp_path / "dol").open()))
    assert [r["case_number"] for r in rows] == ["I-1", "I-3"]
    assert rows[0]["decision_date"] == "2025-10-01"  # Excel serial 45931
    assert rows[0]["received_date"] == "2025-09-24"
    assert rows[1]["wage_unit"] == "Hour"


def test_the_output_names_its_quarter(tmp_path):
    assert dol.period_of(Path("LCA_Disclosure_Data_FY2025_Q2.xlsx")) == "fy2025_q2"
    assert dol.period_of(Path("PERM_Disclosure_Data_FY2024.xlsx")) == "fy2024_q4"
    with pytest.raises(ValueError):
        dol.kind_of(Path("H2A_Disclosure_Data_FY2025.xlsx"))


def test_two_form_versions_of_one_year_do_not_overwrite_each_other(tmp_path):
    header = list(_LCA_HEADER)
    rows = [header, _lca_row("I-1", "Certified", "45931", "Engineer", "Acme", "100000")]
    a = dol.write(_xlsx(tmp_path / "LCA_Disclosure_Data_FY2024_Q4.xlsx", rows), tmp_path / "dol")
    b = dol.write(_xlsx(tmp_path / "LCA_Disclosure_Data_New_Form_FY2024_Q4.xlsx", rows), tmp_path / "dol")
    assert a != b and a.exists() and b.exists()


def test_an_optional_column_may_be_absent(tmp_path):
    header = [h for h in _LCA_HEADER if h != "SOC_CODE"]
    row = _lca_row("I-1", "Certified", "45931", "Engineer", "Acme", "100000")
    del row[_LCA_HEADER.index("SOC_CODE")]
    rows = list(dol.slim_rows(_xlsx(tmp_path / "LCA_Disclosure_Data_FY2024_Q1.xlsx", [header, row])))
    assert [(r["case_number"], r["soc_code"], r["wage_from"]) for r in rows] == [("I-1", "", "100000")]


def test_the_old_perm_form_reads_by_its_own_names(tmp_path):
    header = ["CASE_NUMBER", "CASE_STATUS", "RECEIVED_DATE", "DECISION_DATE", "EMPLOYER_NAME", "EMP_CONTACT_EMAIL",
              "PW_SOC_CODE", "WAGE_OFFER_FROM", "WAGE_OFFER_TO", "WAGE_OFFER_UNIT_OF_PAY", "WORKSITE_CITY",
              "WORKSITE_STATE", "JOB_TITLE"]
    row = ["A-1", "Certified", "45100", "45500", "STRIPE, INC.", "hr@example.com", "15-1252.00", "180000", "220000",
           "Year", "SEATTLE", "WA", "Software Engineer"]
    out = dol.write(_xlsx(tmp_path / "PERM_Disclosure_Data_FY2024_Q4.xlsx", [header, row]), tmp_path / "dol")
    rows = list(csv.DictReader(out.open()))
    assert [(r["employer_name"], r["soc_code"], r["wage_from"], r["wage_unit"]) for r in rows] == [
        ("STRIPE, INC.", "15-1252.00", "180000", "Year")]
    assert "@" not in out.read_text()


def test_a_missing_column_is_refused_by_name(tmp_path):
    header = [h for h in _LCA_HEADER if h != "WAGE_RATE_OF_PAY_FROM"]
    path = _xlsx(tmp_path / "LCA_Disclosure_Data_FY2026_Q1.xlsx", [header])
    with pytest.raises(ValueError, match="WAGE_RATE_OF_PAY_FROM"):
        list(dol.slim_rows(path))


# --- the builder ---------------------------------------------------------------- #


@pytest.mark.parametrize(("value", "unit", "yearly"), [
    ("173000", "Year", 173000),
    ("95", "Hour", 197600),
    ("2,500", "Week", 130000),
    ("6000", "Bi-Weekly", 156000),
    ("15000", "Month", 180000),
    ("$140,046.00", "Year", 140046),
    # The spellings other years' files use: each dropped silently.
    ("95", "Hourly", 197600),
    ("2,500", "Weekly", 130000),
    ("6000", "Biweekly", 156000),
    ("15000", "Monthly", 180000),
    ("173000", "Yearly", 173000),
])
def test_pay_is_annualised_from_its_unit(value, unit, yearly):
    assert store.annual(value, unit) == yearly


@pytest.mark.parametrize(("value", "unit"), [
    ("0", "Year"), ("", "Year"), ("n/a", "Year"), ("173000", "Fortnight"),
    ("1730000000", "Year"),  # a typo, not a salary
    ("95", "Year"),  # an hourly rate filed as a year
    # A salary typed into an hourly row: $4.8M a year, inside the yearly bound,
    # but no hourly rate (the text parser's own hourly bound).
    ("2300", "Hour"),
    ("80000", "Month"),  # nor is this a month's pay
])
def test_an_amount_that_is_not_pay_is_no_data_point(value, unit):
    assert store.annual(value, unit) is None


def _slim(case, decided, title="Staff Software Engineer", employer="SERVICENOW, INC.", wage_from="198000", wage_to="",
          received=None):
    row = dict.fromkeys(name for name, _ in dol.COLUMNS["lca"])
    row = {k: "" for k in row}
    row.update(case_number=case, case_status="Certified", received_date=received or decided, decision_date=decided,
               job_title=title,
               employer_name=employer, worksite_city="SANTA CLARA", worksite_state="CA",
               wage_from=wage_from, wage_to=wage_to, wage_unit="Year", full_time="Y")
    return row


def _write_slim(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_overlapping_quarters_give_one_observation_per_case(tmp_path):
    dol_dir = tmp_path / "dol"
    _write_slim(dol_dir / "lca_fy2026_q2.csv", [_slim("I-9", "2026-03-01", wage_from="190000")])
    _write_slim(dol_dir / "lca_fy2026_q3.csv", [_slim("I-9", "2026-05-01", wage_from="198000"), _slim("I-10", "2026-05-02")])
    obs, dropped = build.filings(dol_dir, {"SERVICENOW, INC.": "servicenow"})
    assert dropped == {}
    by_case = {o.source_ref: o for o in obs}
    assert sorted(by_case) == ["I-10", "I-9"]
    assert by_case["I-9"].pay_low == 198000 and by_case["I-9"].decided_on == "2026-05-01"


def test_a_filing_reads_as_an_observation(tmp_path):
    o = store.from_filing(_slim("I-1", "2026-05-01", wage_to="230000"), "dol_lca", {"SERVICENOW, INC.": "servicenow"})
    assert o is not None
    assert (o.company, o.employer, o.pay_kind, o.pay_low, o.pay_high, o.currency) == (
        "servicenow", "SERVICENOW, INC.", "offered_base", 198000, 230000, "USD")
    assert (o.location, o.location_groups) == ("Santa Clara, CA", "united_states")
    assert o.obs_id == store.obs_id("dol_lca", "I-1") != store.obs_id("dol_perm", "I-1")


def test_pay_is_dated_by_when_the_employer_stated_it():
    """A green-card case decided in 2026 was filed, and its wage stated, in 2024:
    its vintage is 2024, so a reader never takes it for this year's pay."""
    o = store.from_filing(_slim("G-1", "2026-03-10", received="2024-11-20"), "dol_perm", {})
    assert o is not None
    assert (o.stated_on, o.decided_on, o.vintage, o.last_confirmed) == ("2024-11-20", "2026-03-10", "2024", "")


@pytest.mark.parametrize(("value", "iso"), [
    ("45931", "2025-10-01"),          # an Excel serial day
    ("10/01/2025", "2025-10-01"),     # the agency's text dates
    ("2025-10-01", "2025-10-01"),
    ("2025-10-01 00:00:00", "2025-10-01"),
    ("soon", ""),                     # no date at all is refused, not passed on
])
def test_a_filing_date_is_stored_as_an_iso_date_or_not_at_all(value, iso):
    assert store.excel_date(value) == iso


def test_a_text_date_is_dated_and_ordered_as_a_date(tmp_path):
    """A text date is never a `vintage` like "11/2", and "latest wins" is never
    lexical: as text, 12/01/2025 sorts after 02/01/2026."""
    o = store.from_filing(_slim("G-2", "03/10/2026", received="11/20/2024"), "dol_perm", {})
    assert o is not None
    assert (o.stated_on, o.decided_on, o.vintage) == ("2024-11-20", "2026-03-10", "2024")
    dol_dir = tmp_path / "dol"
    _write_slim(dol_dir / "lca_fy2026_q1.csv", [_slim("I-7", "12/01/2025", wage_from="190000")])
    _write_slim(dol_dir / "lca_fy2026_q2.csv", [_slim("I-7", "02/01/2026", wage_from="198000")])
    (only,), _ = build.filings(dol_dir, {})
    assert (only.pay_low, only.decided_on) == (198000, "2026-02-01")


def test_a_filing_with_no_readable_decision_date_is_no_data_point():
    assert store.from_filing(_slim("I-8", "pending"), "dol_lca", {}) is None


def test_the_manifest_counts_each_vintage(tmp_path):
    rows = [store.from_filing(_slim(f"I-{i}", d, received=r), "dol_lca", {})
            for i, (d, r) in enumerate([("2026-05-01", "2026-04-20"), ("2025-01-10", "2024-12-30"), ("2025-03-01", "2025-02-20")])]
    build.write([o for o in rows if o], tmp_path, [])
    manifest = json.loads((tmp_path / "observations.json").read_text())
    assert manifest["by_vintage"] == {"dol_lca": {"2024": 1, "2025": 1, "2026": 1}}


def test_an_untracked_employer_is_still_a_data_point():
    o = store.from_filing(_slim("I-2", "2026-05-01", employer="Acme Robotics LLC"), "dol_lca", {})
    assert o is not None and o.company == "" and o.employer == "Acme Robotics LLC"


def test_a_range_that_runs_backwards_keeps_only_its_floor():
    o = store.from_filing(_slim("I-3", "2026-05-01", wage_from="200000", wage_to="150000"), "dol_lca", {})
    assert o is not None and (o.pay_low, o.pay_high) == (200000, None)


@pytest.mark.parametrize(("basis", "kind"), [
    ("base", "posted_base_range"), ("total", "posted_total_range"), ("unclear", "posted_range_unclear"), (None, "posted_range_unclear"),
])
def test_a_posting_keeps_what_its_range_was_stated_as(basis, kind):
    job = {"id": 7, "company": "brex", "title": "Senior  Software Engineer", "locations": ["New York"],
           "location_cities": ["New York, NY"], "location_groups": ["new_york", "united_states", "city_5128581"],
           "disclosed_base_min": 50, "disclosed_base_max": 75, "disclosed_currency": "USD",
           "disclosed_pay_period": "hour", "disclosed_pay_basis": basis, "first_seen": datetime(2026, 9, 1, 12),
           "last_seen": datetime(2026, 10, 2, 8)}
    o = store.from_posting(job)
    assert o is not None
    assert (o.pay_kind, o.pay_low, o.pay_high, o.unit) == (kind, 104000, 156000, "hour")
    assert (o.title, o.location_groups) == ("Senior Software Engineer", "new_york|united_states")
    assert (o.stated_on, o.last_confirmed, o.vintage, o.decided_on) == ("2026-09-01", "2026-10-02", "2026", "")


def test_the_store_and_its_manifest_are_written(tmp_path):
    o = store.from_filing(_slim("I-1", "2026-05-01"), "dol_lca", {"SERVICENOW, INC.": "servicenow"})
    assert o is not None
    src = tmp_path / "lca_fy2026_q3.csv"
    src.write_text("x\n")
    build.write([o], tmp_path, [src])
    rows = list(csv.DictReader((tmp_path / "observations.csv").open()))
    assert [r["obs_id"] for r in rows] == [o.obs_id] and rows[0]["pay_high"] == ""
    manifest = json.loads((tmp_path / "observations.json").read_text())
    assert manifest["rows"] == 1 and manifest["matched_to_a_company"] == {"dol_lca": 1}
    assert set(manifest["inputs"]) == {"lca_fy2026_q3.csv"}


# --- the employer map ------------------------------------------------------------ #


def test_every_mapped_company_is_one_we_name():
    from tracker import config
    from tracker.company_catalog import CATALOG
    from tracker.company_discovery import COMPANY_DISCOVERY

    named = set(config.COMPANIES) | set(CATALOG) | set(COMPANY_DISCOVERY)
    mapped = json.loads(build.EMPLOYERS.read_text(encoding="utf-8"))
    assert sorted(set(mapped) - named) == []


def test_a_filing_name_belongs_to_one_company(tmp_path):
    assert store.load_employers(build.EMPLOYERS)  # the shipped map loads: no name is filed for two companies
    clash = tmp_path / "map.json"
    clash.write_text(json.dumps({"citadel": ["CITADEL LLC"], "citadel-securities": ["Citadel LLC"]}))
    with pytest.raises(ValueError, match="both"):
        store.load_employers(clash)


def test_the_manifest_says_why_each_dropped_row_is_no_data_point(tmp_path):
    """A row that becomes no observation is counted by source
    and reason, so a source that starts losing rows shows it."""
    dol_dir = tmp_path / "dol"
    _write_slim(dol_dir / "lca_fy2026_q3.csv", [
        _slim("I-1", "2026-05-01"),
        _slim("I-2", "2026-05-01", wage_from="12"),  # not a wage
        _slim("I-3", "pending"),  # no decision date
    ])
    _write_slim(dol_dir / "perm_fy2026_q3.csv", [_slim("G-1", "2026-05-01", wage_from="")])
    obs, dropped = build.filings(dol_dir, {})
    assert [o.source_ref for o in obs] == ["I-1"]
    build.write(obs, tmp_path, [], dropped)
    manifest = json.loads((tmp_path / "observations.json").read_text())
    assert manifest["dropped"] == {
        "dol_lca": {"no readable decision date": 1, "no usable amount": 1},
        "dol_perm": {"no usable amount": 1},
    }


# --- malformed cells and currencies --------------- #


@pytest.mark.parametrize("value", ["NaN", "nan", "Infinity", "-Infinity", "1e309"])
def test_a_non_finite_amount_is_no_data_point_not_an_error(value):
    """`float()` reads these and `round()` raises on them: one cell must not abort the whole build."""
    assert store.annual(value, "Year") is None
    assert store.amount_problem(value, "Year") == store.DROP_NO_AMOUNT


@pytest.mark.parametrize("value", ["Infinity", "1e309", "NaN", "99999999999"])
def test_a_date_no_calendar_holds_is_no_date_not_an_error(value):
    assert store.excel_date(value) == ""


def test_one_malformed_filing_is_counted_and_the_rest_are_kept():
    rows = [
        ("dol_lca", _slim("I-1", "2026-05-01")),  # the control
        ("dol_lca", _slim("I-2", "2026-05-01", wage_from="Infinity")),
        ("dol_lca", _slim("I-3", "1e309")),
        ("dol_lca", {**_slim("I-4", "2026-05-01"), "wage_unit": "Fortnight"}),
    ]
    obs, dropped = store.observe_filings(rows, {})
    assert [o.source_ref for o in obs] == ["I-1"]
    assert dropped == {
        ("dol_lca", store.DROP_NO_AMOUNT): 1,
        ("dol_lca", store.DROP_NO_DATE): 1,
        ("dol_lca", store.DROP_UNKNOWN_UNIT): 1,
    }


def test_a_filing_missing_a_column_is_still_a_schema_error():
    """One unusable value is counted; a source that changed shape is not."""
    row = _slim("I-1", "2026-05-01")
    del row["wage_unit"]
    with pytest.raises(KeyError):
        store.observe_filings([("dol_lca", row)], {})


def _posting(low, high, currency, period, **over):
    job = {"id": 9, "company": "google", "title": "Staff Engineer", "locations": ["Tokyo, Japan"],
           "location_cities": [], "location_groups": ["japan"], "disclosed_base_min": low,
           "disclosed_base_max": high, "disclosed_currency": currency, "disclosed_pay_period": period,
           "disclosed_pay_basis": "base", "first_seen": datetime(2026, 9, 1), "last_seen": datetime(2026, 10, 1)}
    job.update(over)
    return job


@pytest.mark.parametrize(("low", "high", "currency", "period", "yearly"), [
    (15_000_000, 20_000_000, "JPY", "year", (15_000_000, 20_000_000)),  # the band the USD bound dropped
    (8_000, 9_500, "EUR", "month", (96_000, 114_000)),
    (60, 75, "GBP", "hour", (124_800, 156_000)),
    (150_000, 200_000, "USD", "year", (150_000, 200_000)),
])
def test_a_posting_is_bounded_in_its_own_currency_and_keeps_its_amounts(low, high, currency, period, yearly):
    o = store.from_posting(_posting(low, high, currency, period))
    assert o is not None
    assert (o.pay_low, o.pay_high, o.currency, o.unit) == (*yearly, currency, period)


@pytest.mark.parametrize(("low", "currency", "period", "reason"), [
    (50, "JPY", "hour", "no usable amount"),         # 0.34 USD an hour
    (15_000_000, "USD", "year", "no usable amount"),  # a JPY figure stored as dollars
    (150_000, "XYZ", "year", "unknown currency"),
    (150_000, "USD", "unclear", "unknown pay unit"),
    (float("nan"), "USD", "year", "no usable amount"),
])
def test_a_posting_that_is_no_data_point_says_why(low, currency, period, reason):
    obs, dropped = store.postings([_posting(low, None, currency, period), _posting(150_000, None, "USD", "year", id=10)])
    assert [o.source_ref for o in obs] == ["10"]
    assert dropped == {("posting", reason): 1}


def test_a_rebuilt_posting_keeps_its_id():
    job = _posting(15_000_000, 20_000_000, "JPY", "year")
    assert store.from_posting(job).obs_id == store.from_posting(dict(job)).obs_id == store.obs_id("posting", "9")
