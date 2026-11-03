"""Data retention: remove stored postings no scan has read for the user's window.

The user picks the window in Settings > Data retention (default 60 days, or
Never). A posting taken off its board stops being read, and so does every
posting of a company the user stopped following, so one clause
(`inventory_store.unread_since`) is the whole rule. Only `posting_inventory` is touched: `jobs`, observations,
lifecycle events, saved roles and pursuits are the longitudinal asset and are
never removed here.

Two callers, one function:

- the `inventory_retention` post pass, inside a full run that already holds
  the run lock;
- the scheduler tick when nothing is due (`retention_when_idle`). Without it a
  user who stops following every company, the case this exists for, would
  never have a run to remove anything in. It takes the run lock per batch and
  stops when a run holds it.

Each batch commits, so a large first removal holds no long lock, and a run
removes at most `REMOVAL_BATCH * REMOVAL_MAX_BATCHES` rows; the rest are
reported as `more` and removed by the next caller.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.db.inventory_store import remove_unread
from tracker.db.session import session_scope
from tracker.settings_store import get_retention_days, record_retention_removal

logger = logging.getLogger(__name__)

#: Rows one DELETE removes; each batch is its own transaction.
REMOVAL_BATCH = 5_000
#: Batches one call runs before leaving the rest to the next.
REMOVAL_MAX_BATCHES = 20


@dataclass(frozen=True)
class RetentionResult:
    #: The window applied, None for Never (or retention switched off).
    days: int | None
    removed: int = 0
    #: The batch bound stopped the call with rows still due.
    more: bool = False
    #: The idle caller found a run holding the lock and removed nothing.
    skipped: bool = False


async def apply_retention(
    session: AsyncSession,
    *,
    now: datetime,
    take_lock: bool = False,
    batch: int = REMOVAL_BATCH,
    max_batches: int = REMOVAL_MAX_BATCHES,
) -> RetentionResult:
    """Remove what the saved window makes due; commits each batch.

    `take_lock`: take the run lock for each batch's transaction and stop when a
    run holds it. The post pass passes False: its run holds the lock already.
    """
    settings = get_settings()
    # Capture off freezes every row's `last_seen_at`, so a window measured
    # against it would remove rows scans DID read: retention is off with it.
    if not settings.inventory_retention_enabled or not settings.inventory_enabled:
        return RetentionResult(days=None)
    days = await get_retention_days(session)
    if days is None:
        return RetentionResult(days=None)
    cutoff = now - timedelta(days=days)
    removed = 0
    more = False
    skipped = False
    for index in range(max_batches):
        if take_lock and not await session.scalar(
            text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": settings.advisory_lock_key}
        ):
            # A run started: it removes the rest in its own post pass.
            await session.rollback()
            skipped = True
            break
        count = await remove_unread(session, cutoff=cutoff, limit=batch)
        await session.commit()
        removed += count
        if count < batch:
            break
        more = index == max_batches - 1
    await record_retention_removal(session, at=now.isoformat(), removed=removed, more=more)
    await session.commit()
    if removed:
        logger.info("retention: removed %d postings unread for %d days%s",
                    removed, days, " (more due)" if more else "")
    return RetentionResult(days=days, removed=removed, more=more, skipped=skipped)


async def retention_when_idle(now: datetime | None = None) -> RetentionResult:
    """The scheduler tick's call when no work is due: its own session, the run
    lock taken per batch."""
    async with session_scope() as session:
        return await apply_retention(session, now=now or datetime.now(UTC), take_lock=True)
