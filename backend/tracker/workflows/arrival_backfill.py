"""Classify the roles stored before `jobs.arrival` existed (`db/arrival.py`).

Each batch commits, so a run that dies keeps what it saved, and a rerun
starts from the roles still unclassified. The last batch rebuilds the lineage
projection in its own transaction, because `lineage_first_seen` follows the
corrected `first_seen`: a run killed there leaves that batch for the rerun.

Writers must be stopped. The app runs this while preparing its database,
before the engine starts; a source install drains its launchers first and
runs `scripts.backfill_arrival`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.arrival import classify_arrivals
from tracker.db.models import Job
from tracker.db.session import commit_in_batches, session_scope
from tracker.lineage.detect import rebuild_lineage_projection

BATCH = 1000


async def unclassified_ids(session: AsyncSession) -> list[int]:
    return list(
        (await session.scalars(select(Job.id).where(Job.arrival.is_(None)).order_by(Job.id))).all()
    )


async def backfill_arrivals(*, batch: int = BATCH) -> int:
    """Classify every unclassified role; returns how many were classified.
    Each saved batch prints the last id it reached."""
    async with session_scope() as session:
        ids = await unclassified_ids(session)
    if not ids:
        return 0
    last = ids[-1]

    async def classify(session: AsyncSession, chunk: list[int]) -> int:
        done = len(await classify_arrivals(session, chunk))
        if chunk[-1] == last:
            await rebuild_lineage_projection(session)
        return done

    return await commit_in_batches(ids, classify, size=batch, label="roles")
