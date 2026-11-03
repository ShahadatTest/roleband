"""The API's in-process tally of actions and crashes, drained to the outbox.

A request never touches the database for usage sharing: the middleware
(`api/usage_counter.py`) adds to this tally, and only while the matching group
is shared (the flags). A task in the API's lifespan drains it every minute
(`run`): it refreshes the flags from the stored consent, then writes the counts
and scrubbed crashes through the recorder, which checks consent again. A hard
kill loses at most a minute of counts, which is the price of keeping the
request path free of writes.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.usage_stats import recorder
from tracker.usage_stats.consent import Sharing, get_sharing_to_record
from tracker.usage_stats.kill import blocked_by
from tracker.usage_stats.registry import Group
from tracker.usage_stats.scrub import Shape

logger = logging.getLogger(__name__)

DRAIN_SECONDS = 60
#: Actions whose first occurrence after the user shared usage is a milestone.
MILESTONES = {
    "save_job": "first_job_saved",
    "add_company": "first_company_followed",
    "follow_all": "first_company_followed",
    "company_selection_saved": "first_company_followed",
}
#: Crashes held between drains; a crash loop beyond this is counted by type only once.
MAX_PENDING_CRASHES = 200


@dataclass
class ApiTally:
    #: Whether to tally at all, per group; refreshed by every drain and set at
    #: once by the consent route, so a user who stops sharing stops the tally.
    usage: bool = False
    crashes: bool = False
    actions: Counter[str] = field(default_factory=Counter)
    crashes_pending: list[Shape] = field(default_factory=list)

    def set_flags(self, sharing: Sharing) -> None:
        allowed = blocked_by() is None
        self.usage = allowed and sharing.shared(Group.USAGE)
        self.crashes = allowed and sharing.shared(Group.CRASHES)
        if not self.usage:
            self.actions.clear()
        if not self.crashes:
            self.crashes_pending.clear()

    def count(self, action: str) -> None:
        if self.usage:
            self.actions[action] += 1

    def crash(self, shape: Shape) -> None:
        if self.crashes and len(self.crashes_pending) < MAX_PENDING_CRASHES:
            self.crashes_pending.append(shape)

    def take(self) -> tuple[Counter[str], list[Shape]]:
        actions, crashes = self.actions, self.crashes_pending
        self.actions, self.crashes_pending = Counter(), []
        return actions, crashes


#: The API process's tally.
TALLY = ApiTally()


async def drain(session: AsyncSession, tally: ApiTally = TALLY, *, now: datetime | None = None) -> int:
    """Refresh the flags, write what was tallied, commit. Returns rows touched."""
    now = now or datetime.now(UTC)
    sharing = await get_sharing_to_record(session)
    tally.set_flags(sharing)
    actions, crashes = tally.take()
    written = 0
    for action, times in sorted(actions.items()):
        try:
            if await recorder.record_count(
                session, "daily_action", {"action": action}, now=now, by=times, sharing=sharing
            ):
                written += 1
        except ValueError:
            logger.warning("usage: dropped an undeclared action %r", action)
            continue
        milestone = MILESTONES.get(action)
        if milestone is not None and await recorder.record_milestone(session, milestone, now=now, sharing=sharing):
            written += 1
    for shape in crashes:
        if await recorder.record_shape(session, shape, source="api", now=now, sharing=sharing):
            written += 1
    await session.commit()
    return written


async def run(
    session_factory: Callable[[], AsyncSession],
    tally: ApiTally = TALLY,
    *,
    interval: float = DRAIN_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """The lifespan task: drain forever; a failed drain is logged, never fatal."""
    while True:
        try:
            async with session_factory() as session:
                await drain(session, tally)
        except Exception:  # noqa: BLE001 - usage sharing never takes the API down
            logger.warning("usage: could not drain the API tally", exc_info=True)
        await sleep(interval)
