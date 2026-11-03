"""Promotion: postings a sync already read join `jobs` when the scope widens.

A scope save re-projects `jobs.in_scope` over rows `jobs` holds. The posting
inventory holds every posting a sync read, so the rows a widening
admits that `jobs` never held can join it in the same save instead of waiting
for each company's next sync. Candidates: inventory rows not gone, read by a
scan within `inventory_promotion_fresh_hours`, at a followed active
company, passing the saved scope (the same `job_scope_expr` over the
inventory's columns, learned exclusions included), and not in `jobs`.

Freshness. `gone_at` is set only by an authoritative listing, so a company that
went unscanned (unfollowed, then followed again; or failing) keeps rows that
look live however long ago they closed. Admitting one would write a closed
posting into `jobs` history as open, and its eventual closure would stretch
"time posted" by every day it went unscanned.

Concurrency. The pipeline's writer loads each company's `jobs` before its scan
and inserts a key it did not see; a promotion inserting that key in between
would fail the run on `jobs.dedupe_key`. So promotion runs only under the run
lock: a scope save takes it for its own transaction
(`pg_try_advisory_xact_lock`, which conflicts with the run's session lock and
is released by the save's commit, so a run cannot start between the insert
and the commit). A save that finds a run holding it reports `pending`; every
run promotes in its `inventory_promotion` post pass, holding the lock already.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Select, exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.db.inventory_store import at_followed_company, read_recently
from tracker.db.models import Job, JobSourceIdentity, PostingInventory
from tracker.db.queries.scope import job_scope_expr, load_scope_exclusions
from tracker.db.repo import admit_from_inventory
from tracker.plugins.reestimate import refresh_jobs
from tracker.scope.projection import saved_scope

logger = logging.getLogger(__name__)

#: Rows one promotion admits; the next run's post pass admits the rest.
PROMOTION_LIMIT = 2000
#: How long a save waits for a finishing run's lock before reporting pending.
_LOCK_WAIT_SECONDS = 2.0


@dataclass(frozen=True)
class PromotionResult:
    promoted: int = 0
    #: A run held the lock, or more rows qualified than one promotion admits:
    #: the run's post pass admits them.
    pending: bool = False
    job_ids: tuple[int, ...] = ()
    companies: tuple[str, ...] = field(default=())


async def candidates_stmt(
    session: AsyncSession, *, now: datetime | None = None,
) -> Select[tuple[PostingInventory]]:
    """Inventory rows the saved scope admits that `jobs` does not hold, newest
    sighting first, unlimited. The one query promotion and the save preview
    read, so the preview counts what the save admits.

    A row no sync has named (`last_seen_run_id` NULL: read only by "Count
    now") is left for the next sync: its observation needs a run. A
    row no scan read within `inventory_promotion_fresh_hours` waits for its
    company's next scan.
    """
    axes, keywords = await saved_scope(session)
    gate = job_scope_expr(
        *axes, await load_scope_exclusions(session), **keywords, model=PostingInventory,
    )
    return (
        select(PostingInventory)
        .where(
            at_followed_company(),
            PostingInventory.gone_at.is_(None),
            PostingInventory.last_seen_run_id.isnot(None),
            read_recently(now),
            gate,
            ~exists().where(Job.dedupe_key == PostingInventory.dedupe_key),
            ~exists().where(
                JobSourceIdentity.binding_id == PostingInventory.binding_id,
                JobSourceIdentity.source_key == PostingInventory.dedupe_key,
            ),
        )
        .order_by(PostingInventory.last_seen_at.desc(), PostingInventory.id.desc())
    )


async def promotion_candidates(
    session: AsyncSession, *, limit: int = PROMOTION_LIMIT, now: datetime | None = None,
):
    """The first `limit + 1` candidates: one more than a promotion admits, so
    the caller knows whether more wait."""
    stmt = (await candidates_stmt(session, now=now)).limit(limit + 1)
    return list((await session.scalars(stmt)).all())


async def promote_locked(session: AsyncSession, *, limit: int = PROMOTION_LIMIT) -> PromotionResult:
    """Admit the candidates. The caller holds the run lock; commits nothing."""
    if not get_settings().inventory_promotion_enabled:
        return PromotionResult()
    rows = await promotion_candidates(session, limit=limit)
    overflow = len(rows) > limit
    jobs = await admit_from_inventory(session, rows[:limit])
    # A new row, estimated now as a scanned one is in its run: otherwise it
    # shows no pay until its company's next scan.
    await refresh_jobs(session, [job.id for job in jobs])
    return PromotionResult(
        promoted=len(jobs),
        pending=overflow,
        job_ids=tuple(job.id for job in jobs),
        companies=tuple(sorted({job.company for job in jobs})),
    )


async def run_lock_held(session: AsyncSession) -> bool:
    """Whether a run (or a count) holds the run lock now, read from
    `pg_locks` without taking it: a read must never make a run wait. Advisory
    locks are per database and `pg_locks` lists the whole cluster, so the
    database is part of the question."""
    key = get_settings().advisory_lock_key
    held = await session.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted"
            " AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
            " AND objsubid = 1 AND ((classid::bigint << 32) | objid::bigint) = :k)"
        ),
        {"k": key},
    )
    return bool(held)


async def _try_run_lock(session: AsyncSession, *, wait_seconds: float) -> bool:
    key = get_settings().advisory_lock_key
    deadline = time.monotonic() + wait_seconds
    while True:
        if await session.scalar(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key}):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.25)


async def promote_on_save(session: AsyncSession, *, wait_seconds: float = _LOCK_WAIT_SECONDS) -> PromotionResult:
    """Promotion for a scope save, after its re-projection and before its commit.

    Never fails the save: the promotion runs in a savepoint, and an error rolls
    back only the promotion and reports it pending for the next run.
    """
    if not get_settings().inventory_promotion_enabled:
        return PromotionResult()
    if not await _try_run_lock(session, wait_seconds=wait_seconds):
        return PromotionResult(pending=True)
    try:
        async with session.begin_nested():
            return await promote_locked(session)
    except Exception:  # noqa: BLE001 - the scope save must still succeed
        logger.warning("promotion failed; the next run promotes", exc_info=True)
        return PromotionResult(pending=True)
