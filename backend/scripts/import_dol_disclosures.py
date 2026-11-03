"""Turn a US Department of Labor disclosure file into a slim CSV (pay data).

    .venv/bin/python -m scripts.import_dol_disclosures LCA_Disclosure_Data_FY2026_Q3.xlsx
    .venv/bin/python -m scripts.import_dol_disclosures PERM_Disclosure_Data_FY2025_Q4.xlsx --dir <sources>

The Office of Foreign Labor Certification publishes every H-1B labour condition
application (LCA) and every permanent labour certification (PERM) each quarter:
employer, job title, occupation code, worksite and the wage offered. It is public
government data and the largest source of employer-stated base pay by job title
the pay dataset has.

The files also name the people who filed them (contact and attorney names,
emails, phone numbers). This script keeps an ALLOWLIST of columns, so a column
the agency adds later is dropped rather than copied, and no person's name or
address leaves the original file. The slim CSV is the only form the builder
reads (`scripts.build_pay_observations`).

Output: `<dir>/dol/<kind>_fy<year>_q<n>.csv`, one row per certified case, with
Excel serial dates written as ISO dates. Quarterly files of one fiscal year can
overlap (FY2026 Q3 holds October to June), so the builder keeps one row per case
number across files, the latest decision.

Stdlib only (the files are .xlsx; no spreadsheet package is a dependency): the
sheet is streamed, so a 250 MB file is read in about a minute.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path
from xml.etree.ElementTree import iterparse

from tracker.pay_store.observations import excel_date
from tracker.platform.paths import DATA_DIR

SOURCES_DIR = DATA_DIR / "level-atlas-sources"

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

#: The columns kept, per file kind, as (output name, source names in preference
#: order: PERM files of the agency's 2024 form name their columns differently).
#: Anything not named here is never written: names, emails, phones and
#: addresses of the filers stay in the original file.
COLUMNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "lca": (
        ("case_number", ("CASE_NUMBER",)),
        ("case_status", ("CASE_STATUS",)),
        ("received_date", ("RECEIVED_DATE",)),
        ("decision_date", ("DECISION_DATE",)),
        ("visa_class", ("VISA_CLASS",)),
        ("job_title", ("JOB_TITLE",)),
        ("soc_code", ("SOC_CODE",)),
        ("soc_title", ("SOC_TITLE",)),
        ("full_time", ("FULL_TIME_POSITION",)),
        ("positions", ("TOTAL_WORKER_POSITIONS",)),
        ("employer_name", ("EMPLOYER_NAME",)),
        ("employer_fein", ("EMPLOYER_FEIN",)),
        ("naics_code", ("NAICS_CODE",)),
        ("worksite_city", ("WORKSITE_CITY",)),
        ("worksite_state", ("WORKSITE_STATE",)),
        ("wage_from", ("WAGE_RATE_OF_PAY_FROM",)),
        ("wage_to", ("WAGE_RATE_OF_PAY_TO",)),
        ("wage_unit", ("WAGE_UNIT_OF_PAY",)),
        ("prevailing_wage_level", ("PW_WAGE_LEVEL",)),
    ),
    "perm": (
        ("case_number", ("CASE_NUMBER",)),
        ("case_status", ("CASE_STATUS",)),
        ("received_date", ("RECEIVED_DATE",)),
        ("decision_date", ("DECISION_DATE",)),
        ("visa_class", ()),
        ("job_title", ("JOB_TITLE",)),
        ("soc_code", ("PWD_SOC_CODE", "PW_SOC_CODE")),
        ("soc_title", ("PWD_SOC_TITLE", "PW_SOC_TITLE")),
        ("full_time", ("OTHER_REQ_IS_FULLTIME_EMP",)),
        ("positions", ()),
        ("employer_name", ("EMP_BUSINESS_NAME", "EMPLOYER_NAME")),
        ("employer_fein", ("EMP_FEIN", "EMPLOYER_FEIN")),
        ("naics_code", ("EMP_NAICS", "NAICS_CODE")),
        ("worksite_city", ("PRIMARY_WORKSITE_CITY", "WORKSITE_CITY")),
        ("worksite_state", ("PRIMARY_WORKSITE_STATE", "WORKSITE_STATE")),
        ("wage_from", ("JOB_OPP_WAGE_FROM", "WAGE_OFFER_FROM")),
        ("wage_to", ("JOB_OPP_WAGE_TO", "WAGE_OFFER_TO")),
        ("wage_unit", ("JOB_OPP_WAGE_PER", "WAGE_OFFER_UNIT_OF_PAY")),
        ("prevailing_wage_level", ()),
    ),
}
_DATES = ("received_date", "decision_date")
#: `received_date` is when the employer filed, i.e. stated the wage: a PERM
#: decision can come many months later, so the decision date dates the agency's
#: work, not the pay.
#: A file without one of these is refused; any other column may be absent (the
#: FY2024 PERM files carry no full-time flag, the new form no occupation code).
REQUIRED = (
    "case_number", "case_status", "received_date", "decision_date", "job_title", "employer_name", "wage_from", "wage_unit",
)


def kind_of(path: Path) -> str:
    name = path.name.upper()
    if name.startswith("LCA"):
        return "lca"
    if name.startswith("PERM"):
        return "perm"
    raise ValueError(f"{path.name}: not an LCA or PERM disclosure file")


def period_of(path: Path) -> str:
    """`fy2026_q3` from the file name; a file without a quarter is `q4` (a full year)."""
    match = re.search(r"FY(\d{4})(?:_Q(\d))?", path.name, re.I)
    if not match:
        raise ValueError(f"{path.name}: no fiscal year in the name")
    return f"fy{match.group(1)}_q{match.group(2) or 4}"


def _column(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):  # type: ignore[union-attr]
        n = n * 26 + ord(ch) - 64
    return n - 1


def _shared_strings(book: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    out: list[str] = []
    with book.open("xl/sharedStrings.xml") as handle:
        for _, el in iterparse(handle, events=("end",)):
            if el.tag == _NS + "si":
                out.append("".join(t.text or "" for t in el.iter(_NS + "t")))
                el.clear()
    return out


def sheet_rows(path: Path) -> Iterator[list[str]]:
    """The first sheet's rows as lists of strings, streamed. Rows with no
    value at all (the blank padding these files end with) are skipped."""
    with zipfile.ZipFile(path) as book:
        strings = _shared_strings(book)
        sheet = sorted(n for n in book.namelist() if n.startswith("xl/worksheets/sheet"))[0]
        with book.open(sheet) as handle:
            for _, el in iterparse(handle, events=("end",)):
                if el.tag != _NS + "row":
                    continue
                cells: dict[int, str] = {}
                for cell in el.iter(_NS + "c"):
                    kind = cell.get("t")
                    if kind == "inlineStr":
                        value = "".join(t.text or "" for t in cell.iter(_NS + "t"))
                    else:
                        v = cell.find(_NS + "v")
                        value = v.text or "" if v is not None else ""
                        if kind == "s" and value:
                            value = strings[int(value)]
                    if value != "":
                        cells[_column(cell.get("r", "A1"))] = value
                el.clear()
                if cells:
                    yield [cells.get(i, "") for i in range(max(cells) + 1)]


def slim_rows(path: Path) -> Iterator[dict[str, str]]:
    """Certified cases of one file, as the allowlisted columns."""
    rows = sheet_rows(path)
    header = next(rows)
    where = {name: i for i, name in enumerate(header)}
    spec = COLUMNS[kind_of(path)]
    missing = [names[0] for name, names in spec if name in REQUIRED and not any(n in where for n in names)]
    if missing:
        raise ValueError(f"{path.name}: columns not found: {missing}")
    for row in rows:
        out: dict[str, str] = {}
        for name, sources in spec:
            value = ""
            for src in sources:
                i = where.get(src)
                if i is not None and i < len(row) and row[i] != "":
                    value = row[i].strip()
                    break
            out[name] = excel_date(value) if name in _DATES else value
        if out["case_status"].startswith("Certified"):
            yield out


def write(path: Path, out_dir: Path) -> Path:
    kind = kind_of(path)
    # PERM FY2024 ships two files, one per form version: both are kept.
    form = "_newform" if "NEW_FORM" in path.name.upper() else ""
    target = out_dir / f"{kind}_{period_of(path)}{form}.csv"
    latest: dict[str, dict[str, str]] = {}
    for row in slim_rows(path):
        key = row["case_number"]
        if key not in latest or row["decision_date"] >= latest[key]["decision_date"]:
            latest[key] = row
    out_dir.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[name for name, _ in COLUMNS[kind]], lineterminator="\n")
        writer.writeheader()
        for key in sorted(latest):
            writer.writerow(latest[key])
    print(f"{path.name}: {len(latest)} certified cases -> {target}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path, help="LCA_* or PERM_* .xlsx disclosure files")
    parser.add_argument("--dir", type=Path, default=SOURCES_DIR, help="pay sources directory (git-ignored)")
    args = parser.parse_args(argv)
    for path in args.files:
        write(path, args.dir / "dol")
    return 0


if __name__ == "__main__":
    sys.exit(main())
