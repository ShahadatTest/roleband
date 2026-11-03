"""Bring every stored job's level in line with the leveling model.

`jobs.level_band`, `level_confidence` and `level_basis` are written at scrape
time, so a ladder, title-rule or pay-grade change reaches only rows observed
again: a closed row, or one at a paused company, would keep the old band, and
the Board would disagree with the Walk. `relevel_jobs` is the
`levels_backfill` post pass; `scripts.backfill_level_bands` is its dry-run
report.

One reading for both: `stored_raw` rebuilds what `read_level` needs from the
stored columns, the stored family included (the reading the scrape gave;
`roles_backfill` runs first, so it is current). The employer's printed rung is
read from the stored description only where the employer prints one and the
column is empty, so the pass does not load every description on every run.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Job
from tracker.db.repo import refresh_listed_rungs, set_job_levels
from tracker.enrich.level_mapper import LevelReading, read_level
from tracker.levels.ladder import prints_rungs_in_text
from tracker.plugins import reestimate
from tracker.schema import (
    LevelBasis,
    LevelConfidence,
    RawJob,
    SourceDisclosedComp,
    parse_band,
)
from tracker.scope.projection import recompute_saved_scope
from tracker.taxonomy.stated_level import stated_level

#: The columns a reading needs, plus the scope axes a report needs.
_COLUMNS = (
    Job.id, Job.company, Job.req_id, Job.title, Job.url, Job.status, Job.raw_level, Job.family,
    Job.track, Job.location_groups, Job.domains, Job.level_band, Job.level_confidence,
    Job.level_basis, Job.disclosed_base_min, Job.disclosed_base_max, Job.disclosed_currency,
    Job.disclosed_pay_basis, Job.disclosed_pay_period, Job.first_posted_at, Job.posted_at,
    Job.first_seen,
)


def stored_raw(row: Row[Any], description: str | None = None) -> RawJob:
    """What `read_level` reads, rebuilt from a stored row.

    `raw_level` falls back to the stored description: an older row may never
    have had the scrape-time reader run on it, and the printed rung is the top
    tier. The stated range and first date carry the pay-grade reading;
    without them this would undo every `pay_grade` band.
    """
    pay = None
    if row.disclosed_base_min and row.disclosed_base_max:
        pay = SourceDisclosedComp(
            base_min=row.disclosed_base_min, base_max=row.disclosed_base_max,
            currency=row.disclosed_currency, pay_basis=row.disclosed_pay_basis or "unclear",
            pay_period=row.disclosed_pay_period or "unclear",
        )
    return RawJob(
        company=row.company,
        req_id=row.req_id,
        title=row.title,
        url=row.url or "",
        raw_level=row.raw_level or stated_level(row.company, description),
        source_disclosed_comp=pay,
        posted_at=row.posted_at,
        held_first_posted_at=row.first_posted_at,
        held_first_seen=row.first_seen,
    )


def stored_reading(row: Row[Any]) -> LevelReading:
    """The reading the row holds. A NULL basis is an older
    row: its band was read as a level, so it compares as generic."""
    basis = LevelBasis(row.level_basis) if row.level_basis else LevelBasis.GENERIC
    return LevelReading(parse_band(row.level_band), LevelConfidence(row.level_confidence), basis)


@dataclass(frozen=True)
class Relevel:
    """One stored row whose reading differs from the model's."""

    row: Any  # a `_COLUMNS` row
    reading: LevelReading

    @property
    def band_moved(self) -> bool:
        return self.reading.band.value != self.row.level_band


def _differs(row: Row[Any], reading: LevelReading) -> bool:
    return (
        reading.band.value != row.level_band
        or reading.confidence.value != row.level_confidence
        or reading.basis.value != row.level_basis
    )


async def pending_relevels(
    session: AsyncSession, *, company: str | None = None
) -> tuple[int, list[Relevel]]:
    """(rows read, rows whose stored reading is not the model's). Read-only."""
    stmt = select(*_COLUMNS).order_by(Job.id.asc())
    if company:
        stmt = stmt.where(Job.company == company)
    rows = (await session.execute(stmt)).all()
    # Descriptions only where a printed rung could be in them, is not stored,
    # and could band: the atlas decides (`prints_rungs_in_text`). An employer
    # whose printed "Level 4" is family-relative and bands on no ladder would
    # otherwise have its descriptions read every run for nothing.
    printing = {company for company in {r.company for r in rows} if prints_rungs_in_text(company)}
    needs_text = [r.id for r in rows if r.raw_level is None and r.company in printing]
    texts: dict[int, str | None] = {}
    if needs_text:
        texts = dict((await session.execute(
            select(Job.id, Job.description_text).where(Job.id.in_(needs_text))
        )).tuples().all())
    pending = []
    for row in rows:
        reading = read_level(stored_raw(row, texts.get(row.id)), row.family)
        if _differs(row, reading):
            pending.append(Relevel(row, reading))
    return len(rows), pending


def level_changes(pending: Sequence[Relevel]) -> list[dict]:
    """The `set_job_levels` payload for these rows."""
    return [
        {
            "id": item.row.id,
            "level_band": item.reading.band.value,
            "level_confidence": item.reading.confidence.value,
            "level_basis": item.reading.basis.value,
        }
        for item in pending
    ]


async def relevel_jobs(session: AsyncSession) -> dict[str, int]:
    """The `levels_backfill` post pass. Writes only changed rows, so once
    caught up it is a scan that writes nothing; `in_scope` is recomputed when
    anything changed, since band and basis are scope inputs. Commits nothing.

    A held row the sync stopped keeping first takes the rung its board now
    prints (`refresh_listed_rungs`), so the level re-read here and
    the scope projected from it are the board's, not the row's first write."""
    refreshed = await refresh_listed_rungs(session)
    _, pending = await pending_relevels(session)
    await set_job_levels(session, level_changes(pending))
    # A band is an estimate input no fingerprint names.
    await reestimate.refresh_jobs(session, [item.row.id for item in pending if item.band_moved])
    rescoped = await recompute_saved_scope(session) if pending else 0
    return {
        "rungs_refreshed": len(refreshed),
        "relevelled": len(pending),
        "band_moved": sum(item.band_moved for item in pending),
        "in_scope_changed": rescoped,
    }
