"""The stored per-level pay rows the comp estimate reads.

One read per pipeline run, handed to `comp_providers.table.ReferenceTableProvider`,
which is pure and imports no database code.

Every reader of `company_comp_level`, `company_benefit` and
`external_comp_observation` filters through its scope (`level_scope`,
`benefit_scope`, `reported_rows`): a retired row is never read, and only the
ONE source answering the slot is (`Providers.where`): the selected plugin's rows
for the companies it has read whole, or ours, never both and never one filling
in for the other per family, cell or company.

A plugin's rung is banded when it is READ (`banded`): our
atlas places its label (`levels.words.rung_band`), and its stored row, which
holds what the plugin sent, is never re-banded in place. A row of ours keeps the
band it was entered with. So a reader selects `level_label`, `aliases` and
`provider`, never filters `band` in SQL, and filters it after banding.

Every rung is for one country, read with it (`banded`): the country the
plugin stated, or ours (`OUR_PAY_COUNTRY`) on a row of ours. A plugin's rung
that states none is for no country we can name, so no posting reads it. A
reader that prices one posting keeps only its country's rows.

`keep` is a reader's value filter (a band, a total, a base, a split), applied in
Python after the scope: a plugin rung that states a total but no base is simply
not a base, never a reason to read another source's base beside it. The reads
that filter by value live here (`pay_level_rows`, `package_rows`, `split_rows`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from types import SimpleNamespace
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.comp_providers.base import OUR_PAY_COUNTRY, OUR_PAY_CURRENCY
from tracker.db.models import CompanyBenefit, CompanyCompLevel, ExternalCompObservation
from tracker.levels.words import rung_band
from tracker.plugins.registry import (
    COMPANY_BENEFITS,
    PAY_LEVELS,
    PAY_OBSERVATIONS,
    Providers,
    reader_providers,
)
from tracker.taxonomy.comp_families import REFERENCE_FAMILY


def level_scope(providers: Providers) -> list[ColumnElement[bool]]:
    """The predicates every `company_comp_level` read carries."""
    return [CompanyCompLevel.retired_at.is_(None),
            providers.where(PAY_LEVELS, CompanyCompLevel.provider, CompanyCompLevel.company_slug)]


def _fields(row: Any) -> dict[str, Any]:
    """A result row's or a model instance's columns, as a plain dict: never a
    live instance, which a reader setting `band` would write back."""
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    if hasattr(row, "__table__"):
        return {c.key: getattr(row, c.key) for c in row.__table__.columns}
    return dict(vars(row))


def banded(providers: Providers, rows: Iterable[Any]) -> list[SimpleNamespace]:
    """`rows` as plain records whose `band` and `country` are read now: a
    plugin's rung placed by our atlas from its label and aliases, for the
    country it stated (None when it stated none); a row of ours as entered, for
    our country unless it names another. The currency rides along as stored,
    because no reader may convert one figure into another."""
    out = []
    for row in rows:
        fields = _fields(row)
        plugin = fields["provider"] in providers.plugins
        if plugin:
            fields["band"], fields["band_source"] = rung_band(
                fields["company_slug"], fields["level_label"], fields.get("aliases") or ())
        # What the row itself states, apart from the country it is read for:
        # a stated country decides US pay by itself (`comp_market.us_rows`).
        fields["stated_country"] = fields.get("country")
        fields["country"] = fields.get("country") or (None if plugin else OUR_PAY_COUNTRY)
        fields["currency"] = fields.get("currency") or OUR_PAY_CURRENCY
        out.append(SimpleNamespace(**fields))
    return out


def admit_levels(
    providers: Providers, rows: Iterable[Any], *, keep: Callable[[Any], bool] | None = None
) -> list[Any]:
    """The rows of the source answering `pay.levels`, banded now, then the
    reader's `keep`. Rows carry `company_slug`, `level_label`, `provider` and,
    for a plugin's rung, `aliases`."""
    chosen = banded(providers, providers.admit(PAY_LEVELS, rows, provider=lambda r: r.provider))
    return chosen if keep is None else [r for r in chosen if keep(r)]


def reference_ladder() -> ColumnElement[bool]:
    """`family` names the reference family. Every row read is keyed by our
    taxonomy's family names."""
    return CompanyCompLevel.family == REFERENCE_FAMILY


def benefit_scope(providers: Providers) -> list[ColumnElement[bool]]:
    """The predicates every `company_benefit` read carries."""
    return [CompanyBenefit.retired_at.is_(None),
            providers.where(COMPANY_BENEFITS, CompanyBenefit.provider, CompanyBenefit.company_slug)]


def admit_benefits(providers: Providers, rows: Iterable[Any]) -> list[Any]:
    """The `company_benefit` rows of the source answering `company.benefits`:
    the selected plugin's, or none (ours are the bundled dataset, never rows)."""
    return providers.admit(COMPANY_BENEFITS, rows, provider=lambda r: r.provider)


async def reported_rows(
    session: AsyncSession, providers: Providers, *, hidden: Sequence[str] = ()
) -> tuple[list[Any], Any]:
    """Self-reported pay points (`pay.observations`), banded: each company's
    latest snapshot from the one source answering the slot. Returns the rows and
    the newest snapshot date among them.

    Latest PER COMPANY, not per provider. A plugin is free to refresh company by
    company, and a newest-date-per-provider filter would hide every company it
    did not publish on its newest day, silently and without retiring a row: the
    company would simply stop having reported pay the day another company was
    refreshed.

    Only submissions this comparison can read: paid in our country and
    currency, stating a total and its equity. A submission for another market
    or none is kept and never compared with US pay; nothing is converted.

    One query with a window rather than a max-per-group followed by a tuple
    `IN`: a company publishes several rungs on a snapshot date, so the filter
    cannot collapse to one row per company, and the `IN` list would carry a
    parameter per company toward the protocol's limit.
    """
    scope = [
        providers.where(PAY_OBSERVATIONS, ExternalCompObservation.provider, ExternalCompObservation.company_slug),
        ExternalCompObservation.country == OUR_PAY_COUNTRY,
        ExternalCompObservation.currency == OUR_PAY_CURRENCY,
        ExternalCompObservation.total_amount.isnot(None),
        ExternalCompObservation.equity_amount.isnot(None),
    ]
    if hidden:
        scope.append(ExternalCompObservation.company_slug.notin_(list(hidden)))
    newest_for_company = func.max(ExternalCompObservation.snapshot_date).over(
        partition_by=(ExternalCompObservation.provider, ExternalCompObservation.company_slug)
    ).label("newest_for_company")
    observed = (
        select(
            ExternalCompObservation.company_slug,
            ExternalCompObservation.source_level,
            ExternalCompObservation.total_amount,
            ExternalCompObservation.equity_amount,
            ExternalCompObservation.provider,
            ExternalCompObservation.snapshot_date,
            newest_for_company,
        )
        .where(*scope)
        .subquery()
    )
    rows = (await session.execute(
        select(observed).where(observed.c.snapshot_date == observed.c.newest_for_company)
    )).all()
    if not rows:
        return [], None
    chosen = []
    for row in providers.admit(PAY_OBSERVATIONS, rows, provider=lambda r: r.provider):
        # Banded now, never stored, as a plugin's rung is: our atlas, else the label's words.
        band, _source = rung_band(row.company_slug, row.source_level)
        chosen.append(SimpleNamespace(company_slug=row.company_slug, band=band,
                                      total_usd=row.total_amount, equity_usd=row.equity_amount,
                                      provider=row.provider, snapshot_date=row.snapshot_date))
    return chosen, max((r.snapshot_date for r in chosen), default=None)


async def pay_level_rows(session: AsyncSession, providers: Providers | None = None) -> Sequence[Any]:
    """Every priced, banded per-level row: what the estimate may read. Priced
    is a total or a base: a rung that states a base alone answers the base
    estimate (`comp_providers.table`)."""
    providers = providers or await reader_providers(session)
    rows = (
        await session.execute(
            select(
                CompanyCompLevel.company_slug,
                CompanyCompLevel.family,
                CompanyCompLevel.band,
                CompanyCompLevel.level_label,
                CompanyCompLevel.aliases,
                CompanyCompLevel.base_amount,
                CompanyCompLevel.currency,
                CompanyCompLevel.tc_median,
                CompanyCompLevel.provider,
                CompanyCompLevel.as_of,
                CompanyCompLevel.country,
            ).where(*level_scope(providers))
        )
    ).all()
    return admit_levels(providers, rows, keep=lambda r: r.band is not None and (
        r.tc_median is not None or r.base_amount is not None))


async def package_rows(
    session: AsyncSession, providers: Providers, company: str, country: str | None
) -> list[Any]:
    """The rungs a job's pay package measures a posting against: the company's
    banded rows for the posting's country that state a base, every family, read
    as taxonomy families. None when the posting has no one country."""
    if country is None:
        return []
    rows = (
        await session.execute(
            select(
                CompanyCompLevel.company_slug,
                CompanyCompLevel.family,
                CompanyCompLevel.band,
                CompanyCompLevel.level_label,
                CompanyCompLevel.aliases,
                CompanyCompLevel.base_amount,
                CompanyCompLevel.currency,
                CompanyCompLevel.stock_amount,
                CompanyCompLevel.bonus_amount,
                CompanyCompLevel.provider,
                CompanyCompLevel.as_of,
                CompanyCompLevel.country,
            ).where(CompanyCompLevel.company_slug == company, *level_scope(providers))
        )
    ).all()
    return admit_levels(providers, rows, keep=lambda r: (
        r.band is not None and r.base_amount is not None and r.country == country))


async def split_rows(session: AsyncSession, providers: Providers, country: str) -> list[Any]:
    """The measured splits for one country: reference-ladder rows that know
    every component's share (`stock_pct` is set only when all three are known)."""
    rows = (
        await session.execute(
            select(
                CompanyCompLevel.company_slug,
                CompanyCompLevel.family,
                CompanyCompLevel.band,
                CompanyCompLevel.level_label,
                CompanyCompLevel.aliases,
                CompanyCompLevel.base_amount,
                CompanyCompLevel.currency,
                CompanyCompLevel.base_pct,
                CompanyCompLevel.stock_pct,
                CompanyCompLevel.bonus_pct,
                CompanyCompLevel.provider,
                CompanyCompLevel.country,
            ).where(reference_ladder(), *level_scope(providers))
        )
    ).all()
    return admit_levels(providers, rows, keep=lambda r: (
        r.band is not None and r.stock_pct is not None and r.country == country))
