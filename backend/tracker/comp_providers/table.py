"""The comp estimate read from stored per-level rows, never fetched.

This provider reads the rows a refresh already stored, so the same rows always
give the same estimate and enrichment makes no network call.

Pure: the pipeline loads the rows once per run, `comp_package.pay_level_index`
chooses one per key, and the index is handed in; this module imports no
database or analytics code (layer L3).

The key is the JOB's family (our taxonomy, as every row is keyed), at the
job's band, through the one rung `comp_package.choose_rung_row` picks, the row
the package beside the estimate reads. A family with no row of its own
borrows the reference family's, as the package does. A row prices only a
posting in its own country (`CompContext.country`), and a US row that cannot be
US pay (`comp_market.us_rows`) prices none. The estimate is in the row's own
currency: nothing here converts, so a rung published in euros produces a
euro estimate rather than a dollar one that is wrong by the exchange rate.

A row answers the components it states: a total and a base, or a base alone,
which is a base estimate with the total unknown. Components are never added
up: a base and a grant with no total is a base, not a total.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Protocol

from tracker.comp_providers.base import CompContext, CompEstimate, CompProvider, company_name
from tracker.levels.pay import level_label
from tracker.taxonomy.comp_families import REFERENCE_FAMILY

#: The estimate is a point; the band around it is stated, not measured.
_SPREAD = 0.15


class PayLevelRow(Protocol):
    company_slug: str
    family: str
    band: str | None
    level_label: str
    base_amount: int | None
    currency: str
    tc_median: int | None
    provider: str
    as_of: date | None
    country: str | None


class ReferenceTableProvider(CompProvider):
    name = "reference_table"

    def __init__(self, index: Mapping[tuple[str, str, str, str], PayLevelRow]) -> None:
        """`index`: (company, taxonomy family, band, country) -> the one row that stands for it."""
        self._index = index

    def __len__(self) -> int:
        return len(self._index)

    async def lookup(self, ctx: CompContext) -> CompEstimate | None:
        if ctx.country is None:
            return None
        band = ctx.band.value
        own = ctx.family
        for family in dict.fromkeys(f for f in (own, REFERENCE_FAMILY) if f):
            row = self._index.get((ctx.company, family, band, ctx.country))
            if row is not None and (row.tc_median or row.base_amount):
                median = int(row.tc_median) if row.tc_median else None
                base = int(row.base_amount) if row.base_amount else None
                label = level_label(ctx.company, ctx.band)
                return CompEstimate(
                    median=median,
                    low=int(median * (1 - _SPREAD)) if median else None,
                    high=int(median * (1 + _SPREAD)) if median else None,
                    currency=row.currency,
                    source=(
                        f"{company_name(ctx.company)} {label} estimated"
                        f" {'median' if median else 'base'} ({family})"
                    ),
                    detail={
                        "provider": self.name,
                        "level": row.level_label,
                        "family": family,
                        "borrowed": family != own,
                    },
                    base_median=base,
                    base_low=int(base * (1 - _SPREAD)) if base else None,
                    base_high=int(base * (1 + _SPREAD)) if base else None,
                    provider=row.provider,
                    as_of=row.as_of,
                )
        return None
