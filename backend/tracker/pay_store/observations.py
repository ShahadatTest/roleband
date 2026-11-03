"""Raw pay observations: the pure half of the store.

What one data point is (`Observation`), how a stated amount becomes a year's
pay (`annual`, bounded by the text parser's own size classes), and how a DOL
filing row or one of our postings becomes an observation.
`scripts/build_pay_observations.py` reads the files and the database and writes
the store; the column meanings are that script's docstring. Nothing here reads
a file but the employer map the caller names, or the database.

Why a row is dropped is counted (`DROP_*`), so the store's manifest says how
many rows each source lost and why, not just how many it kept.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta
from pathlib import Path

from tracker.pay_numbers import USD_PER_UNIT
from tracker.pay_period import PayPeriod, size_classes

_EXCEL_EPOCH = date(1899, 12, 30)


#: The text forms a filing date takes when a file stores it as text.
_TEXT_DATES = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d")


def excel_date(value: str) -> str:
    """A filing date as an ISO date: an Excel serial day ("45931") or a text
    date ("10/01/2025", "2025-10-01 00:00:00").  hygiene: allow (input formats)
    Anything else is "", never passed on: a raw text date would make a bad
    `vintage` and order "latest wins" lexically, 12/01/2025 after 02/01/2026."""
    text = (value or "").strip()
    try:
        return (_EXCEL_EPOCH + timedelta(days=int(float(text)))).isoformat()
    except (ValueError, OverflowError):
        # Not a number, NaN, or a serial no calendar holds ("Infinity",
        # "1e309", 99999999999 days): no date, never an aborted build.
        pass
    for form in _TEXT_DATES:
        try:
            return datetime.strptime(text.split(" ")[0], form).date().isoformat()
        except ValueError:
            continue
    return ""


#: Annual multiplier per stated pay unit (a 2,080-hour year).
UNITS = {"year": 1, "hour": 2080, "week": 52, "bi-weekly": 26, "month": 12}
#: The other spellings the agency's files use for the same units.
UNIT_SPELLINGS = {
    "yearly": "year", "annual": "year", "hourly": "hour", "weekly": "week",
    "biweekly": "bi-weekly", "bi weekly": "bi-weekly", "monthly": "month",
}
#: Units the text parser's size classes bound (`pay_period._SIZE_CLASSES`):
#: a salary typed into an hourly row is $4.8M a year, inside `PLAUSIBLE`.
_BOUNDED = {"hour": PayPeriod.hour, "month": PayPeriod.month}
#: Annual amounts outside this are typing errors in the source, not pay.
PLAUSIBLE = (15_000, 5_000_000)

_POSTING_KIND = {"base": "posted_base_range", "total": "posted_total_range"}


@dataclass(frozen=True)
class Observation:
    obs_id: str
    source: str
    source_ref: str
    stated_on: str
    decided_on: str
    last_confirmed: str
    vintage: str
    company: str
    employer: str
    title: str
    location: str
    location_groups: str
    pay_kind: str
    pay_low: int
    pay_high: int | None
    currency: str
    unit: str
    full_time: str
    soc_code: str
    wage_level: str
    positions: str


COLUMNS = [f.name for f in fields(Observation)]


def obs_id(source: str, ref: str) -> str:
    """Stable per (source, case or posting): a rebuild keeps every id."""
    return hashlib.sha256(f"{source}|{ref}".encode()).hexdigest()[:16]


def unit_name(unit: str) -> str:
    name = " ".join(unit.strip().lower().split())
    return UNIT_SPELLINGS.get(name, name)


#: Why a row is no data point. Counted per source in the manifest. One
#: unusable value is a reason; a source that changed shape (a missing column)
#: still raises, so the two never read alike.
DROP_NO_AMOUNT = "no usable amount"
DROP_UNKNOWN_UNIT = "unknown pay unit"
DROP_UNKNOWN_CURRENCY = "unknown currency"
DROP_NO_DATE = "no readable decision date"


def _number(value: str | float | None) -> float | None:
    """A finite number, or None: `float()` reads "NaN", "Infinity" and
    "1e309", which `round()` refuses, aborting the build."""
    if value is None or value == "":
        return None
    try:
        amount = float(str(value).replace(",", "").replace("$", ""))
    except ValueError:
        return None
    return amount if math.isfinite(amount) else None


def amount_problem(value: str | float | None, unit: str, currency: str = "USD") -> str | None:
    """Why `annual` makes no amount of these, or None.

    Bounded in the amount's own currency, by the text parser's table
    (`pay_numbers.USD_PER_UNIT`, a size class, never a conversion): the
    hour and month size classes, then a year's pay inside `PLAUSIBLE` once
    in dollars. A currency the table does not know cannot be bounded, so it
    is rejected by name rather than read as dollars."""
    name = unit_name(unit)
    if name not in UNITS:
        return DROP_UNKNOWN_UNIT
    code = (currency or "USD").upper()
    if code not in USD_PER_UNIT:
        return DROP_UNKNOWN_CURRENCY
    amount = _number(value)
    if amount is None or amount <= 0:
        return DROP_NO_AMOUNT
    if name in _BOUNDED and _BOUNDED[name] not in size_classes(amount, amount, code):
        return DROP_NO_AMOUNT
    if not PLAUSIBLE[0] <= amount * UNITS[name] * USD_PER_UNIT[code] <= PLAUSIBLE[1]:
        return DROP_NO_AMOUNT
    return None


def annual(value: str | float | None, unit: str, currency: str = "USD") -> int | None:
    """An amount in `unit` as a year's pay, in its own currency; None when
    it is not a usable amount (`amount_problem` says why)."""
    if amount_problem(value, unit, currency) is not None:
        return None
    amount = _number(value)
    assert amount is not None  # `amount_problem` checked it
    return round(amount * UNITS[unit_name(unit)])


def load_employers(path: Path) -> dict[str, str]:
    """Filing employer name (upper case) -> our slug."""
    by_slug: dict[str, list[str]] = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for slug, names in by_slug.items():
        for name in names:
            key = name.strip().upper()
            if key in out and out[key] != slug:
                raise ValueError(f"{name!r} is filed for both {out[key]} and {slug}")
            out[key] = slug
    return out


def from_filing(row: dict[str, str], source: str, employers: dict[str, str]) -> Observation | None:
    unit = row["wage_unit"]
    # A US agency's filing states US dollars; it carries no currency column.
    low = annual(row["wage_from"], unit, "USD")
    if low is None:
        return None
    high = annual(row["wage_to"], unit, "USD")
    employer = row["employer_name"].strip()
    decided = excel_date(row["decision_date"])
    if not decided:
        return None
    stated = excel_date(row.get("received_date") or "") or decided
    return Observation(
        obs_id=obs_id(source, row["case_number"]),
        source=source,
        source_ref=row["case_number"],
        stated_on=stated,
        decided_on=decided,
        last_confirmed="",
        vintage=stated[:4],
        company=employers.get(employer.upper(), ""),
        employer=employer,
        title=" ".join(row["job_title"].split()),
        location=", ".join(p for p in (row["worksite_city"].strip().title(), row["worksite_state"].strip()) if p),
        location_groups="united_states",
        pay_kind="offered_base",
        pay_low=low,
        pay_high=high if high is not None and high >= low else None,
        currency="USD",
        unit=unit_name(unit),
        full_time=row["full_time"],
        soc_code=row["soc_code"],
        wage_level=row["prevailing_wage_level"],
        positions=row["positions"],
    )


def drop_reason(row: dict[str, str]) -> str | None:
    """Why `from_filing` would make no observation of `row`, or None."""
    problem = amount_problem(row["wage_from"], row["wage_unit"], "USD")
    if problem is not None:
        return problem
    if not excel_date(row["decision_date"]):
        return DROP_NO_DATE
    return None


def latest_filings(rows: Iterable[tuple[str, dict[str, str]]]) -> list[tuple[str, dict[str, str]]]:
    """One row per (source, case number) across overlapping quarterly files:
    the latest decision wins."""
    latest: dict[tuple[str, str], tuple[str, dict[str, str]]] = {}
    for source, row in rows:
        key = (source, row["case_number"])
        if key not in latest or excel_date(row["decision_date"]) >= excel_date(latest[key][1]["decision_date"]):
            latest[key] = (source, row)
    return list(latest.values())


def observe_filings(
    rows: Iterable[tuple[str, dict[str, str]]], employers: dict[str, str]
) -> tuple[list[Observation], Counter[tuple[str, str]]]:
    """Every filing's observation, and the (source, reason) count of the rows
    that became none."""
    out: list[Observation] = []
    dropped: Counter[tuple[str, str]] = Counter()
    for source, row in latest_filings(rows):
        obs = from_filing(row, source, employers)
        if obs is None:
            dropped[(source, drop_reason(row) or "unreadable")] += 1
        else:
            out.append(obs)
    return out, dropped


def _posting_terms(job: dict) -> tuple[str, str]:
    """The posting's unit and currency as stored: a band with no period was
    read as yearly, one with no currency as dollars (`repo._apply_fields`)."""
    return (job["disclosed_pay_period"] or "year").lower(), (job["disclosed_currency"] or "USD").upper()


def from_posting(job: dict) -> Observation | None:
    unit, currency = _posting_terms(job)
    low = annual(job["disclosed_base_min"], unit, currency)
    if low is None:
        return None
    high = annual(job["disclosed_base_max"], unit, currency)
    seen = job["first_seen"]
    last = job.get("last_seen")
    stated = seen.date().isoformat() if seen else ""
    return Observation(
        obs_id=obs_id("posting", str(job["id"])),
        source="posting",
        source_ref=str(job["id"]),
        stated_on=stated,
        decided_on="",
        last_confirmed=last.date().isoformat() if last else "",
        vintage=stated[:4],
        company=job["company"],
        employer="",
        title=" ".join((job["title"] or "").split()),
        location="|".join(job["location_cities"] or job["locations"] or []),
        location_groups="|".join(g for g in job["location_groups"] or [] if not g.startswith("city_")),
        pay_kind=_POSTING_KIND.get(job["disclosed_pay_basis"] or "", "posted_range_unclear"),
        pay_low=low,
        pay_high=high if high is not None and high >= low else None,
        currency=currency,
        unit=unit,
        full_time="",
        soc_code="",
        wage_level="",
        positions="",
    )


def postings(rows: Iterable[dict]) -> tuple[list[Observation], Counter[tuple[str, str]]]:
    """Every posting's observation, and the ("posting", reason) count of the
    rows that became none, as `observe_filings` counts filings."""
    out: list[Observation] = []
    dropped: Counter[tuple[str, str]] = Counter()
    for row in rows:
        obs = from_posting(row)
        if obs is not None:
            out.append(obs)
            continue
        unit, currency = _posting_terms(row)
        reason = amount_problem(row["disclosed_base_min"], unit, currency) or "unreadable"
        dropped[("posting", reason)] += 1
    return out, dropped
