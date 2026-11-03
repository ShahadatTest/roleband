"""Company pay facts for the raw store: what an employer states that is not a salary.

Read by `scripts.build_pay_observations` into `facts.csv`, one row per fact per
period, uninterpreted. The name maps it matches against stay with the scripts
(`scripts/pay_sources/`), and the caller passes their paths. Sources, each a kind of evidence:

| `source` | Facts |
|---|---|
| `uk_gpg` | the UK gender pay gap report per employer and year: share of men and of women paid a bonus (UK law counts vested shares as bonus, so a share is evidence that SOME bonus or equity is paid, not that a cash bonus is), the median bonus and hourly gaps, the size band |
| `sec_xbrl` | stock-based compensation expense per fiscal year, from the company's XBRL facts; headcount where the company tags it |
| `sec_annual_report` | from the annual report's text: the headcount sentence and the sentences stating how restricted stock units vest |

A text fact keeps the company's own sentence as `evidence`; reading it into a
schedule ("4 years, quarterly after a 1-year cliff") is normalisation.

The UK file names a "responsible person" per employer: only the columns below
are read, so no person reaches the store.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import re
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path

ANNUAL_FORMS = ("10-K", "20-F", "40-F", "10-K/A", "20-F/A")

#: Stock-based compensation expense, in preference order (US GAAP, then IFRS).
SBC_TAGS = (
    ("us-gaap", "ShareBasedCompensation"),
    ("us-gaap", "AllocatedShareBasedCompensationExpense"),
    ("ifrs-full", "ExpenseFromSharebasedPaymentTransactionsWithEmployees"),
    ("ifrs-full", "ExpenseFromSharebasedPaymentTransactions"),
)
EMPLOYEE_TAG = ("dei", "EntityNumberOfEmployees")

#: UK report columns read, and the fact each becomes.
UK_FACTS = (
    ("MaleBonusPercent", "bonus_share_men_pct"),
    ("FemaleBonusPercent", "bonus_share_women_pct"),
    ("DiffMedianBonusPercent", "bonus_gap_median_pct"),
    ("DiffMedianHourlyPercent", "hourly_gap_median_pct"),
    ("EmployerSize", "employer_size"),
)


@dataclass(frozen=True)
class Fact:
    fact_id: str
    source: str
    source_ref: str
    observed_on: str
    period_end: str
    company: str
    employer: str
    fact: str
    value: str
    unit: str
    evidence: str


FACT_COLUMNS = [f.name for f in fields(Fact)]


def _fact(source: str, ref: str, fact: str, **kw: str) -> Fact:
    fid = hashlib.sha256(f"{source}|{ref}|{fact}|{kw.get('period_end', '')}".encode()).hexdigest()[:16]
    return Fact(fact_id=fid, source=source, source_ref=ref, fact=fact,
                observed_on=kw.get("observed_on", ""), period_end=kw.get("period_end", ""),
                company=kw.get("company", ""), employer=kw.get("employer", ""),
                value=kw.get("value", ""), unit=kw.get("unit", ""), evidence=kw.get("evidence", ""))


def names(path: Path) -> dict[str, str]:
    by_slug: dict[str, list[str]] = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for slug, names in by_slug.items():
        for name in names:
            key = " ".join(name.upper().split())
            if key in out and out[key] != slug:
                raise ValueError(f"{name!r} is listed for both {out[key]} and {slug}")
            out[key] = slug
    return out


# --- UK gender pay gap -------------------------------------------------------- #


def uk_facts(row: dict[str, str], employers: dict[str, str]) -> list[Fact]:
    """One UK report row as facts, when the employer is one we track."""
    employer = " ".join(row["EmployerName"].upper().split())
    company = employers.get(employer)
    if not company:
        return []
    period = _uk_date(row.get("DueDate", "")[:10])
    ref = f"{row['EmployerId']}/{period[:4]}"
    observed = _uk_date(row.get("DateSubmitted", "")[:10])
    out = []
    for column, fact in UK_FACTS:
        value = row.get(column, "").strip()
        if value == "":
            continue
        unit = "" if fact == "employer_size" else "pct"
        out.append(_fact("uk_gpg", ref, fact, observed_on=observed, period_end=period,
                         company=company, employer=row["EmployerName"].strip(), value=value, unit=unit))
    return out


def _uk_date(text: str) -> str:
    """The report's "2026/04/05 00:00:00" (or dd/mm/yyyy) as an ISO date; anything else unchanged."""
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", text)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return text


def uk_gpg(folder: Path, employers: dict[str, str]) -> list[Fact]:
    out: list[Fact] = []
    for path in sorted(folder.glob("gpg_*.csv")):
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                out.extend(uk_facts(row, employers))
    return out


# --- SEC: XBRL facts ------------------------------------------------------------ #


def _annual(entries: list[dict]) -> dict[str, dict]:
    """Fiscal-year values from annual reports, one per period end (the latest
    filing wins, so a restated year keeps its restatement)."""
    out: dict[str, dict] = {}
    for e in entries:
        if e.get("form") not in ANNUAL_FORMS or not e.get("end"):
            continue
        start = e.get("start")
        if start:
            days = (date.fromisoformat(e["end"]) - date.fromisoformat(start)).days
            if not 350 <= days <= 380:
                continue  # a quarter or a stub period, not the year
        prev = out.get(e["end"])
        if prev is None or e.get("filed", "") >= prev.get("filed", ""):
            out[e["end"]] = e
    return out


def xbrl_facts(company: str, doc: dict) -> list[Fact]:
    facts = doc.get("facts", {})
    out: list[Fact] = []
    for taxonomy, tag in SBC_TAGS:
        units = facts.get(taxonomy, {}).get(tag, {}).get("units", {})
        if not units:
            continue
        for unit, entries in units.items():
            for end, e in sorted(_annual(entries).items()):
                out.append(_fact("sec_xbrl", e.get("accn", ""), "sbc_expense", observed_on=e.get("filed", ""),
                                 period_end=end, company=company, employer=doc.get("entityName", ""),
                                 value=str(round(e["val"])), unit=unit, evidence=f"{taxonomy}:{tag}"))
        break  # the first tag the company reports is its figure
    # One headcount per period, the latest filing's, as for the expense: each
    # annual report and its amendment tag the same date again.
    taxonomy, tag = EMPLOYEE_TAG
    for unit, entries in facts.get(taxonomy, {}).get(tag, {}).get("units", {}).items():
        for end, e in sorted(_annual(entries).items()):
            out.append(_fact("sec_xbrl", e.get("accn", ""), "employees", observed_on=e.get("filed", ""),
                             period_end=end, company=company,
                             employer=doc.get("entityName", ""), value=str(e["val"]), unit=unit))
    return out


# --- SEC: annual report text ----------------------------------------------------- #

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_HEADCOUNT = re.compile(
    r"(?:approximately|had|employed|employ|total of)\s+(?:approximately\s+|about\s+)?"
    # Three digits up: a company of 850 says so too.
    r"(\d{1,3}(?:,\d{3})+|\d{3,7})\s+(?:[A-Za-z-]+\s+){0,4}?(?:employees|people|team members)",
    re.I,
)
_VESTING = re.compile(r"(restricted stock units?|RSUs?)\b[^.]{0,400}\bvest", re.I)


def report_text(raw: str) -> str:
    """An annual report's HTML as plain text (hidden XBRL header dropped)."""
    raw = re.sub(r"(?is)<ix:header>.*?</ix:header>", " ", raw)
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", raw))).strip()


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.;])\s+(?=[A-Z(])", text)


def report_facts(company: str, report: dict, text: str, max_vesting: int = 4, max_headcount: int = 6) -> list[Fact]:
    """Every headcount sentence (a report often states a department's first,
    so choosing the company-wide one is normalisation) and the vesting sentences."""
    ref, period, filed = report["accession"], report["report_date"], report["filed"]
    out: list[Fact] = []
    counted: set[str] = set()
    for sentence in _sentences(text):
        if len(counted) >= max_headcount:
            break
        s = sentence.strip()
        m = _HEADCOUNT.search(s)
        if m and len(s) < 600 and s not in counted:
            counted.add(s)
            out.append(_fact("sec_annual_report", f"{ref}#h{len(counted)}", "employees_stated", observed_on=filed,
                             period_end=period, company=company, value=m.group(1).replace(",", ""),
                             unit="people", evidence=s))
    seen: set[str] = set()
    for sentence in _sentences(text):
        if len(seen) >= max_vesting:
            break
        s = sentence.strip()
        if _VESTING.search(s) and 40 < len(s) < 900 and s not in seen:
            seen.add(s)
            out.append(_fact("sec_annual_report", f"{ref}#{len(seen)}", "vesting_terms", observed_on=filed,
                             period_end=period, company=company, value="", unit="", evidence=s))
    return out


def sec(folder: Path) -> list[Fact]:
    out: list[Fact] = []
    for path in sorted((folder / "companyfacts").glob("*.json")):
        out.extend(xbrl_facts(path.stem, json.loads(path.read_text(encoding="utf-8"))))
    for index in sorted((folder / "annual").glob("*/index.json")):
        company = index.parent.name
        for report in json.loads(index.read_text(encoding="utf-8")):
            doc = index.parent / f"{report['accession']}.htm"
            if doc.exists():
                out.extend(report_facts(company, report, report_text(doc.read_text(encoding="utf-8", errors="replace"))))
    return out


def inputs(base: Path, name_maps: list[Path]) -> list[Path]:
    """Every file the facts read, for the manifest; `name_maps` are the
    employer and company name files the caller loaded."""
    return (sorted((base / "uk_gpg").glob("gpg_*.csv")) + sorted((base / "sec" / "companyfacts").glob("*.json"))
            + sorted((base / "sec" / "annual").glob("*/*.htm")) + list(name_maps))
