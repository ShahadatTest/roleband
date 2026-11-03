"""The tracked set: the job ids a per-role notification is allowed to speak about.

Tracked = saved (`favorites`) OR being pursued (`pursuits`), extended across
repost lineage. This is the gate the whole per-role channel sits behind.

Why a gate at all: a notification about a role you never asked to follow
cannot be acted on, so it is not a notification, it is a log line that rings a
bell.

Discovery is NOT this channel's job. A role the user has not tracked yet
reaches them through the daily digest (`notifications/digest.py`), ranked by
fit, once. Ambient discovery on a digest, interrupts only for tracked work:
mixing the two trains the user to clear the feed in bulk instead of reading it.

Lineage extension matters because a repost is a NEW job row with a new req_id.
Without it, the successor of the role you saved is an untracked stranger and
falls silently into the digest: exactly the event the user most wants rung.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Favorite, Job, Pursuit


async def tracked_job_ids(session: AsyncSession) -> set[int]:
    """Saved + pursued job ids, widened to every member of their lineages.

    One query per step and no per-job work: the set is small (single-user tool)
    and is resolved once per run, not once per event.
    """
    ids = set((await session.scalars(select(Favorite.job_id))).all())
    ids |= set((await session.scalars(select(Pursuit.job_id))).all())
    if not ids:
        return ids

    lineage_ids = set(
        (
            await session.scalars(
                select(Job.lineage_id).where(Job.id.in_(ids), Job.lineage_id.isnot(None))
            )
        ).all()
    )
    if lineage_ids:
        ids |= set(
            (await session.scalars(select(Job.id).where(Job.lineage_id.in_(lineage_ids)))).all()
        )
    return ids
