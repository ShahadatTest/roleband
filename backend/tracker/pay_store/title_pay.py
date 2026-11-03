"""Filed pay per company x title x state x year, a shipped table of the store.

One cell per company, the title as the filing states it, the worksite's US
state and the filing year, holding how many filings say it and the spread of
the base they offer. No source column: the two filing programmes (LCA and PERM)
state the same thing about the same title and year, so they merge. Level and
family are NOT stored; a reader reads them from the title at use time, so a
change to the level reader never needs this table rebuilt.

What a value is: the filing's offered base FROM (`pay_low`, annualised by the
store), which sits at or below the posted range's middle. The four `level_*`
counts are the prevailing-wage level the employer chose for the job (I-IV); it
tracks stated seniority and is absent on PERM filings.

Every cell carries the same `as_of`, the date the dataset starts for every
company. A cell's own year is `year`; an older year is history, never this
year's pay.

Pure: rows in, rows out. The command that reads the store and writes the atlas
file is `scripts.build_title_pay`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from tracker.taxonomy.locations import US_STATE_BY_NAME, US_STATE_CODES

#: The store's sources that are filings; our own postings are not (they ship
#: as `pay_grades` / `pay_bands`).
FILING_SOURCES = frozenset({"dol_lca", "dol_perm"})
#: US territories the filings name; a worksite there is a US filing.
_TERRITORIES = frozenset({"PR", "VI", "GU", "MP", "AS"})
#: The prevailing-wage levels, in the column order they ship.
WAGE_LEVELS = ("I", "II", "III", "IV")
#: The spread each cell ships, as fractions.
QUANTILES = (("base_p10", 0.10), ("base_p25", 0.25), ("base_p50", 0.50), ("base_p75", 0.75), ("base_p90", 0.90))

DROP_NOT_NAMED = "company not named"
DROP_NO_STATE = "no US state"
DROP_NO_YEAR = "no year"


def state_code(location: str) -> str:
    """The US state of a worksite ("Georgetown, TX", "San Francisco,
    CALIFORNIA"), or "" when the last part names none ("N/A")."""
    last = location.rsplit(",", 1)[-1].strip()
    code = last.upper()
    if code in US_STATE_CODES or code in _TERRITORIES:
        return code
    return US_STATE_BY_NAME.get(" ".join(last.lower().split()), "")


def title_key(title: str) -> str:
    """A title as the table keys it: lowercase, single-spaced. "Senior
    Software Engineer" and "SENIOR SOFTWARE  ENGINEER" are one title."""
    return " ".join(title.lower().split())


def quantile(ordered: list[int], q: float) -> int:
    """Linear interpolation between closest ranks (the spreadsheet PERCENTILE
    rule), over an ascending list; one value is its own every quantile."""
    if not ordered:
        raise ValueError("no values")
    position = q * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low))


@dataclass
class Built:
    rows: list[dict]
    dropped: Counter[str]


def build(observations: Iterable[Mapping[str, str]], companies: frozenset[str] | set[str], as_of: str) -> Built:
    """The table's rows, sorted by key, and why each filing that made no
    cell was left out. `observations` are the store's rows (`Observation`
    columns as text); rows from other sources are skipped, not counted."""
    pay: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    levels: dict[tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)
    dropped: Counter[str] = Counter()
    for row in observations:
        if row["source"] not in FILING_SOURCES:
            continue
        if row["company"] not in companies:
            dropped[DROP_NOT_NAMED] += 1
            continue
        state = state_code(row["location"])
        if not state:
            dropped[DROP_NO_STATE] += 1
            continue
        year = row["vintage"]
        if not (len(year) == 4 and year.isdigit()):
            dropped[DROP_NO_YEAR] += 1
            continue
        key = (row["company"], title_key(row["title"]), state, year)
        pay[key].append(int(row["pay_low"]))
        if row["wage_level"] in WAGE_LEVELS:
            levels[key][row["wage_level"]] += 1
    rows = []
    for key in sorted(pay):
        company, title, state, year = key
        ordered = sorted(pay[key])
        cell: dict = {"company": company, "title": title, "state": state, "year": int(year), "n": len(ordered)}
        for name, q in QUANTILES:
            cell[name] = quantile(ordered, q)
        for level in WAGE_LEVELS:
            # Empty is none (the atlas's rule), so a PERM-only cell stays sparse.
            cell[f"level_{level.lower()}"] = levels[key][level] or None
        cell["as_of"] = as_of
        rows.append(cell)
    return Built(rows, dropped)
