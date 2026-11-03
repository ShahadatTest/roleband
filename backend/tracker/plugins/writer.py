"""Write a plugin's validated rows into the slot tables.

The host has already validated every row with the shared SDK models; this
module stamps the provider and upserts by the provider-led keys, so
a plugin row never touches a row another provider published. The rows arrive
as plain dicts (`model_dump()`), so nothing here imports the SDK.

Banding happens when a row is READ, never here: a
stored row keeps what the plugin sent (its label and aliases, its source level),
`band` stays NULL, and `levels.words.rung_band` / `atlas_band` place it from our
atlas at read time, so our data never rewrites a plugin's row. Levels never
switch with a plugin.

Retirement: when a publish marks a company complete, the host passes the keys
the run has published for that (slot, company); every other row of that
provider for that company in that slot is retired, never deleted,
at the publish, not at a clean end. Observations and fact claims are
append-only and never retired.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import (
    CompanyBenefit,
    CompanyCompLevel,
    CompanyProfile,
    CompSnapshot,
    ExternalCompObservation,
    JobCompEstimate,
)
from tracker.plugins.slots import (
    COMPANY_BENEFITS,
    COMPANY_FACTS,
    PAY_LEVELS,
    PAY_OBSERVATIONS,
    SPECS,
    row_key,
    spec,
)
from tracker.profiles.store import record_fact


def _pcts(base: int | None, stock: int | None, bonus: int | None) -> tuple[float | None, ...]:
    """Component shares, only when every component is known."""
    if base is None or stock is None or bonus is None or base + stock + bonus <= 0:
        return (None, None, None)
    total = base + stock + bonus
    return (base / total, stock / total, bonus / total)


async def company_exists(session: AsyncSession, slug: str) -> bool:
    return await session.get(CompanyProfile, slug) is not None


async def _write_levels(
    session: AsyncSession, provider: str, company: str, rows: Sequence[Mapping[str, Any]], now: datetime
) -> None:
    # Stored in the currency the publisher stated, never converted: a rate
    # belongs to the day it was read, and a figure converted once is wrong
    # from then on. Readers keep to one currency instead.
    for row in rows:
        base_pct, stock_pct, bonus_pct = _pcts(row.get("base"), row.get("stock"), row.get("bonus"))
        values = dict(
            band=None, band_source=None, aliases=list(row.get("aliases") or ()), tc_median=row.get("tc"),
            currency=row["currency"],
            base_amount=row.get("base"),
            stock_amount=row.get("stock"), bonus_amount=row.get("bonus"), base_pct=base_pct,
            stock_pct=stock_pct, bonus_pct=bonus_pct, source_url=row.get("source_url"),
            vendor_family=row.get("vendor_family"), country=row.get("country"),
            as_of=date.fromisoformat(str(row["as_of"])), retired_at=None, fetched_at=now,
        )
        await session.execute(
            pg_insert(CompanyCompLevel)
            .values(provider=provider, company_slug=company, family=row["family"],
                    level_label=row["label"], **values)
            .on_conflict_do_update(constraint="uq_company_comp_level", set_=values)
        )


async def _write_benefits(
    session: AsyncSession, provider: str, company: str, rows: Sequence[Mapping[str, Any]], now: datetime
) -> None:
    for row in rows:
        values = dict(
            perk_id=row.get("perk_id"), category=row["category"], value_usd=row.get("value_usd"),
            value_text=row.get("value_text"), description=row.get("description"),
            detail=row.get("detail") or {}, retired_at=None, fetched_at=now,
        )
        await session.execute(
            pg_insert(CompanyBenefit)
            .values(provider=provider, company_slug=company, name=row["name"], country=row.get("country"), **values)
            .on_conflict_do_update(constraint="uq_company_benefit", set_=values)
        )


async def _write_observations(
    session: AsyncSession, provider: str, company: str, rows: Sequence[Mapping[str, Any]], now: datetime
) -> None:
    for row in rows:
        await session.execute(
            pg_insert(ExternalCompObservation)
            .values(
                provider=provider, company_slug=company,
                source_level=row["source_level"], band=None,
                function=row.get("function"), family=row.get("family"), location=row.get("location"),
                yoe=row.get("yoe"), total_amount=row.get("total"), base_amount=row.get("base"),
                equity_amount=row.get("equity"), bonus_amount=row.get("bonus"), currency=row["currency"],
                country=row.get("country"), snapshot_date=date.fromisoformat(str(row["snapshot_date"])),
                dedup_key=row["dedup_key"],
            )
            .on_conflict_do_nothing(constraint="uq_external_comp_obs")
        )


async def _write_facts(
    session: AsyncSession, provider: str, company: str, rows: Sequence[Mapping[str, Any]], now: datetime
) -> None:
    for row in rows:
        observed = row["observed_at"]
        observed_at = observed if isinstance(observed, datetime) else datetime.fromisoformat(str(observed))
        await record_fact(session, company, row["field"], row["value"], provider, observed_at=observed_at)


#: How each slot's rows are stored; `slots.SPECS` says everything else about it.
WRITERS: dict[str, Callable[..., Awaitable[None]]] = {
    PAY_LEVELS: _write_levels,
    PAY_OBSERVATIONS: _write_observations,
    COMPANY_FACTS: _write_facts,
    COMPANY_BENEFITS: _write_benefits,
}


async def write_batch(
    session: AsyncSession, provider: str, slot: str, company: str, rows: Sequence[Mapping[str, Any]]
) -> set[tuple[str, ...]]:
    """Upsert one publish's rows; returns the keys written (for retirement)."""
    if slot not in WRITERS:
        raise ValueError(f"unknown slot {slot!r}")
    await WRITERS[slot](session, provider, company, rows, datetime.now(UTC))
    return {row_key(slot, row) for row in rows}


async def retire_unpublished(
    session: AsyncSession, provider: str, slot: str, company: str, kept: set[tuple[str, ...]]
) -> int:
    """Retire this provider's rows for `company` in `slot` a complete snapshot
    did not repeat. Returns how many it retired; 0 for a slot that keeps its
    history whole (`SlotSpec.retires`)."""
    kind = spec(slot)
    if not kind.retires:
        return 0
    model: Any = kind.table
    # Compared with NULL as a value: `NOT IN` against a key holding a NULL is
    # never true, so a row whose key has one (a rung with no country) would
    # never retire.
    cols = tuple(func.coalesce(getattr(model, column), "") for _, column in kind.key)
    live = select(model.id).where(
        getattr(model, kind.provider_column) == provider, model.company_slug == company, model.retired_at.is_(None)
    )
    if kept:
        live = live.where(tuple_(*cols).notin_([tuple("" if v is None else v for v in key) for key in kept]))
    ids = list((await session.execute(live)).scalars())
    if ids:
        await session.execute(update(model).where(model.id.in_(ids)).values(retired_at=datetime.now(UTC)))
    return len(ids)


async def provider_has_rows(session: AsyncSession, provider: str) -> bool:
    """Whether any slot table, stored estimate or pay-trend series already names
    `provider`: a new plugin under that id would read rows written
    before it existed as its own."""
    for kind in SPECS:
        model: Any = kind.table
        if await session.scalar(select(getattr(model, kind.provider_column))
                                .where(getattr(model, kind.provider_column) == provider).limit(1)) is not None:
            return True
    for column in (JobCompEstimate.source, CompSnapshot.source):
        if await session.scalar(select(column).where(column == provider).limit(1)) is not None:
            return True
    return False


async def remove_provider_rows(session: AsyncSession, provider: str) -> dict[str, int]:
    """Delete `provider`'s rows in every slot Remove data deletes (pay levels and
    benefits; `SlotSpec.removable`): the user's "Remove data",
    typed confirmation, never automatic. Commits nothing.

    Observations and fact claims are append-only history and are never deleted;
    while the plugin is not active no reader admits them. The estimates computed
    from its rows (`job_comp_estimate`) go with them: ours, stored
    beside them, are never touched. Returns the deleted count per table."""
    out = {}
    for kind in SPECS:
        if kind.removable:
            model: Any = kind.table
            result = await session.execute(delete(model).where(getattr(model, kind.provider_column) == provider))
            out[model.__tablename__] = int(getattr(result, "rowcount", 0) or 0)
    result = await session.execute(delete(JobCompEstimate).where(JobCompEstimate.source == provider))
    out[JobCompEstimate.__tablename__] = int(getattr(result, "rowcount", 0) or 0)
    # The pay-trend series computed from those estimates: left, it would come
    # back on the chart when the plugin is turned on again, built from data the
    # user removed. Ours (`roleband`) and the `mixed` days stay.
    result = await session.execute(delete(CompSnapshot).where(CompSnapshot.source == provider))
    out[CompSnapshot.__tablename__] = int(getattr(result, "rowcount", 0) or 0)
    return out
