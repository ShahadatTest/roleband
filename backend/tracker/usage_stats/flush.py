"""The daily send: at most once a day, from the scheduler tick.

The checks run cheapest first, and the first that says no ends it:

1. an environment switch (`kill.py`, no database);
2. no project key configured (a fork that sends nothing);
3. nothing shared (a database read);
4. not due: the last send was under `DUE_EVERY` ago, or an attempt is under
   `RETRY_AFTER` old;
5. a maintenance wake (`platform.power`): a lid-shut Mac sends nothing.

Then three steps, the network call with no transaction open:

* transaction 1 writes the day rows (scan health for completed days, the
  first scan's milestone, today's heartbeat) and claims every sendable row (`outbox.claim` stamps
  `attempted_at`, so a concurrent tick claims none of them), then commits;
* one POST of one batch (`sender.post_batch`);
* transaction 2 marks the rows sent (and prunes sent rows past `outbox.SENT_KEPT`) or
  rejected; a retryable failure leaves them claimed, for another try after
  `RETRY_AFTER`.

Rows that do not fit the catalogue are marked rejected without being sent.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.platform.locks import advisory_xact_lock
from tracker.platform.power import Power
from tracker.usage_stats import batch, outbox, rollup, sender
from tracker.usage_stats.consent import SHARING_LOCK_KEY, get_sharing
from tracker.usage_stats.install_id import ensure_install_id
from tracker.usage_stats.kill import blocked_by

logger = logging.getLogger(__name__)

DUE_EVERY = timedelta(hours=24)
RETRY_AFTER = timedelta(hours=1)

Scope = Callable[[], AbstractAsyncContextManager[AsyncSession]]


async def flush_if_due(
    *,
    scope: Scope,
    power: Callable[[], Power] | None,
    client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> dict:
    """Send what is due. `force` skips only the once-a-day gate (the operator's
    `scripts.usage_send_now`); every other check still applies."""
    now = now or datetime.now(UTC)
    switch = blocked_by()
    if switch is not None:
        return {"sent": 0, "reason": f"switched off by {switch}"}
    settings = get_settings()
    if not settings.usage_stats_project_key:
        return {"sent": 0, "reason": "no project key"}

    async with scope() as session:
        sharing = await get_sharing(session)
        groups = sharing.shared_groups()
        if not groups:
            return {"sent": 0, "reason": "nothing shared"}
        last_sent = await outbox.last_sent_at(session)
        last_attempt = await outbox.last_attempted_at(session)
    if not force and last_sent is not None and now - last_sent < DUE_EVERY:
        return {"sent": 0, "reason": "not due"}
    if last_attempt is not None and now - last_attempt < RETRY_AFTER and (last_sent is None or last_attempt > last_sent):
        return {"sent": 0, "reason": "an attempt is under an hour old"}
    if power is not None:
        waiting = power().wait_reason(mains=False)
        if waiting is not None:
            return {"sent": 0, "reason": waiting}

    async with scope() as session:
        # The claim commits before the network call; consent edits serialize
        # with this final authorization, rollup and claim transaction.
        await advisory_xact_lock(session, SHARING_LOCK_KEY)
        sharing = await get_sharing(session)
        groups = sharing.shared_groups()
        if not groups:
            return {"sent": 0, "reason": "nothing shared"}
        await rollup.scan_health(session, sharing=sharing, now=now)
        await rollup.first_scan(session, sharing=sharing, now=now)
        await rollup.ai_tasks(session, sharing=sharing, now=now)
        await rollup.heartbeat(session, sharing=sharing, now=now)
        rows = await outbox.claim(session, groups=groups, today=now.date(), now=now, retry_after=RETRY_AFTER)
        install_id = await ensure_install_id(session, now=now)
        await session.commit()
    if not rows:
        return {"sent": 0, "reason": "nothing to send"}

    built = batch.build(rows, install_id=install_id, api_key=settings.usage_stats_project_key)
    result = sender.SendResult("sent", None)
    if built.ids:
        result = await sender.post_batch(built.body, host=settings.usage_stats_host, client=client)

    async with scope() as session:
        if built.unfit:
            await outbox.mark_rejected(session, built.unfit, now=now)
        if result.outcome == "sent":
            await outbox.mark_sent(session, built.ids, now=now)
            pruned = await outbox.prune_sent(session, now=now)
        elif result.outcome == "rejected":
            await outbox.mark_rejected(session, built.ids, now=now)
            pruned = 0
        else:
            pruned = 0
        await session.commit()
    sent = len(built.ids) if result.outcome == "sent" else 0
    return {
        "sent": sent,
        "outcome": result.outcome,
        "status": result.status,
        "left_out": len(built.unfit),
        "pruned": pruned,
    }
