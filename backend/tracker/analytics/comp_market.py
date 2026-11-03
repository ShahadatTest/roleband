"""Which reported per-level pay rows can stand for US pay.

A reported per-level row labelled "United States" can hold a company's worldwide mix. Where
most of a company's reports come from a low-wage country, its "median" is that country's pay,
far below what the company's own US filings show for the same work. Read as US pay, such rows
would give US postings another country's bonus and stock ratios, and call a posted range "far
above what the company pays".

The rule, pure and read at use time (no stored flag, no data rewritten):
- a row stated in another currency is not US pay, whatever its number: the
  floor below is dollars, and 40,000 euro is not 40,000 dollars;
- a row that states its country is US pay exactly when that country is the US:
  a German rung at $150K is not, a US rung at $40K is, and neither counts
  toward a company's mix below. The floor and the mix read only rows that
  state no country, the ones a "United States" label can hide a worldwide
  mix in;
- a row whose median base is below `US_BASE_FLOOR_USD` is not US pay;
- a company x family whose priced rows are at least half below the floor is a worldwide mix, so
  every row of it is set aside (its upper rungs clear the floor only because they are senior).
Interns are exempt: an annualised internship can sit below a full-time floor.

It catches low-wage mixes; a mid-wage country (Taiwan, Korea, much of Europe) clears the floor and
needs a comparison against our own US evidence, which is a stored, refresh-time check (not here).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Protocol

from tracker.comp_providers.base import OUR_PAY_COUNTRY, OUR_PAY_CURRENCY

#: Below the lowest US base our filings show for this work: the lowest 10th-percentile base of the
#: US filing cells (engineering, data, analyst and consultant titles, 5+ filings) at the named
#: companies sits above it. A median under it is not US pay.
US_BASE_FLOOR_USD = 45_000

_EXEMPT_BANDS = frozenset({"intern"})


class PayRow(Protocol):
    """What the rule reads of a `company_comp_level` row (a model, a result row, a test double)."""

    @property
    def company_slug(self) -> str: ...
    @property
    def family(self) -> str: ...
    @property
    def band(self) -> str | None: ...
    @property
    def base_amount(self) -> int | None: ...
    @property
    def currency(self) -> str: ...


def _stated_country(row: PayRow) -> str | None:
    """The country the row itself states (`reference_pay.banded` keeps it as
    `stated_country`), never the one it is read for: `country` defaults ours
    to the US, and that default is no statement. A row without it states none."""
    return getattr(row, "stated_country", None)


def _priced_in_dollars(row: PayRow) -> bool:
    """The floor is a dollar figure, so only a dollar row can be read against it."""
    return getattr(row, "currency", OUR_PAY_CURRENCY) == OUR_PAY_CURRENCY


def _below(row: PayRow) -> bool:
    """Below the floor, and comparable with it. A row in another currency is
    not US pay at all, which `us_rows` decides; it is never "below" here,
    because that would make its number a dollar number."""
    return (
        row.band not in _EXEMPT_BANDS
        and _priced_in_dollars(row)
        and row.base_amount is not None
        and row.base_amount < US_BASE_FLOOR_USD
    )


def us_rows[Row: PayRow](rows: Iterable[Row]) -> list[Row]:
    """The rows that can stand for US pay. Each row carries `company_slug`, `family`, `band` and
    `base_amount`, `currency` (rows without a base are kept: they claim no pay)."""
    rows = list(rows)
    priced: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for row in rows:
        if (row.base_amount is not None and row.band not in _EXEMPT_BANDS and _priced_in_dollars(row)
                and _stated_country(row) is None):
            priced[(row.company_slug, row.family)].append(row)
    mixed = {key for key, group in priced.items() if 2 * sum(map(_below, group)) >= len(group)}

    def kept(row: Row) -> bool:
        if row.base_amount is None:
            return True
        if not _priced_in_dollars(row):
            return False
        stated = _stated_country(row)
        if stated is not None:
            return stated == OUR_PAY_COUNTRY
        return (row.company_slug, row.family) not in mixed and not _below(row)

    return [row for row in rows if kept(row)]


def set_aside[Row: PayRow](rows: Sequence[Row]) -> list[Row]:
    """The rows `us_rows` drops, for reports."""
    kept = {id(row) for row in us_rows(rows)}
    return [row for row in rows if id(row) not in kept]
