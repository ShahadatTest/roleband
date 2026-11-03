"""Stored US posted base ranges, keeping title context for reading at use time.

A single employer posting is pay evidence. It does not establish an exact
range -> level mapping; that still needs two independent anchors (`levels.pay_grades`).
No stored band, vendor input or inferred pay. Pure rows in, cells out.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime

from tracker.pay_period import effective_period
from tracker.taxonomy.locations import pay_country


@dataclass
class Built:
    rows: list[dict]
    dropped: Counter[str]


def build(postings: Iterable[Mapping], companies: frozenset[str] | set[str], as_of: str) -> Built:
    """One cell per title/context/year/exact range, deduplicated by posting id.

    Both annual USD base bounds and exclusively US locations are required. Captured
    title, department, team and printed code let the current reader decide
    family and band without feeding the range into its own classification.
    """
    cells: Counter[tuple] = Counter()
    dropped: Counter[str] = Counter()
    seen: set[tuple[str, str]] = set()
    for row in postings:
        identity = (row["company"], str(row.get("req_id") or row["id"]))
        if identity in seen:
            continue
        seen.add(identity)
        if row["company"] not in companies:
            dropped["company not named"] += 1
            continue
        if pay_country(row.get("location_groups")) != "US":
            dropped["not exclusively US locations"] += 1
            continue
        if (row.get("disclosed_currency") != "USD" or row.get("disclosed_pay_basis") != "base"
                or row.get("disclosed_pay_period") != "year"):
            dropped["not annual USD base"] += 1
            continue
        low, high = row.get("disclosed_base_min"), row.get("disclosed_base_max")
        if not isinstance(low, int) or not isinstance(high, int) or not 0 < low <= high:
            dropped["no valid complete range"] += 1
            continue
        if effective_period("year", low, high, "USD") != "year":
            dropped["not annual USD base"] += 1
            continue
        dates = [row.get(k) for k in ("first_posted_at", "posted_at", "first_seen")]
        years = [d.year for d in dates if isinstance(d, (datetime, date))]
        if not years:
            dropped["no year"] += 1
            continue
        # Same earliest posting/seen year used by level_date.
        title = " ".join((row.get("title") or "").split())
        if not title:
            dropped["no title"] += 1
            continue
        key = (row["company"], title, row.get("department") or "", row.get("team") or "",
               row.get("raw_level") or "", min(years), low, high)
        cells[key] += 1
    columns = ("company", "title", "department", "team", "raw_level", "year", "base_min", "base_max")
    return Built([{**dict(zip(columns, key, strict=True)), "n": cells[key], "as_of": as_of}
                  for key in sorted(cells)], dropped)
