"""What every scope save does after it re-projects `in_scope`.

A save that can widen the scope promotes the postings a sync already read
(`scope.promotion.promote_on_save`) and queues a sync of the companies it
admitted from, so their descriptions, pay and derivations follow within one
scheduler tick. Queued, not started: the always-on dispatcher collects due
work, and a save that spawned processes would reach every test that drives
it. A user-directed source is left to the user's own Sync.
Promotion runs before the save's commit, the queue after it; neither can
fail the save.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.scope.promotion import PromotionResult, promote_on_save
from tracker.workflows.scheduler import queue_promoted_reconciliation

logger = logging.getLogger(__name__)


async def promote_after_save(session: AsyncSession) -> PromotionResult:
    """Promote before the save commits, so its Board count includes the rows."""
    return await promote_on_save(session)


async def queue_follow_up(session: AsyncSession, result: PromotionResult) -> None:
    """After the save's commit: make the promoted companies due now.

    `queue_promoted_reconciliation` commits by itself (it queues as `/api/sync`
    does), so it runs only once the save is whole. A failure costs nothing but
    time: the rows are on the Board, and the scheduler's own cadence reaches them.
    """
    if not result.companies:
        return
    try:
        await queue_promoted_reconciliation(session, list(result.companies))
    except Exception:  # noqa: BLE001 - the save is already committed
        await session.rollback()
        logger.warning("could not queue the follow-up scan for %s", result.companies, exc_info=True)


def promotion_fields(result: PromotionResult) -> dict:
    """The two keys every scope save answers with."""
    return {"promoted": result.promoted, "promotion_pending": result.pending}
