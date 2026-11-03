"""The outbox counts exactly, sends a day only once it is over, and ages
only sent rows (docs/architecture.md).

Concurrency is real here: two sessions on two connections increment the same
day's count, as the API, the scheduler and the pipeline do.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.usage_fixtures import NOW, share
from tracker.db.models import UsageEvent
from tracker.usage_stats import outbox
from tracker.usage_stats.recorder import record_count, record_daily, record_milestone
from tracker.usage_stats.registry import CATALOGUE, Group

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]

TOMORROW = (NOW + timedelta(days=1)).date()
RETRY = timedelta(hours=1)


async def _all(session) -> list[UsageEvent]:
    return list((await session.execute(select(UsageEvent).order_by(UsageEvent.id))).scalars())


async def test_two_connections_counting_together_lose_nothing(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)

    async def bump(times: int) -> None:
        async with factory() as session:
            for _ in range(times):
                await record_count(session, "daily_action", {"action": "save_job"}, now=NOW)
                await session.commit()

    await asyncio.gather(bump(25), bump(25))
    rows = await _all(db_session)
    assert len(rows) == 1
    assert rows[0].count == 50


async def test_a_milestone_is_one_row_ever(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE)
    assert await record_milestone(db_session, "first_job_saved", now=NOW) is True
    assert await record_milestone(db_session, "first_job_saved", now=NOW + timedelta(days=3)) is False
    rows = await _all(db_session)
    assert [(row.name, row.first_at) for row in rows] == [("first_job_saved", NOW)]


async def test_a_sent_milestone_outlives_the_prune_and_is_never_recorded_again(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE)
    assert await record_milestone(db_session, "first_job_saved", now=NOW) is True
    [row] = await _all(db_session)
    await outbox.mark_sent(db_session, [row.id], now=NOW - timedelta(days=31))

    assert await outbox.prune_sent(db_session, now=NOW) == 0
    assert await record_milestone(db_session, "first_job_saved", now=NOW + timedelta(days=1)) is False
    assert [(r.name, r.first_at) for r in await _all(db_session)] == [("first_job_saved", NOW)]


async def test_sharing_again_the_day_it_was_declined_counts_into_a_row_that_can_be_sent(
    db_session, sharing_allowed,
) -> None:
    heartbeat = {"app_version": "0.1.0", "os": "macos", "arch": "arm64", "python": "3.12",
                 "install_method": "source", "db_mode": "embedded"}
    await share(db_session, Group.USAGE)
    await record_count(db_session, "daily_action", {"action": "save_job"}, now=NOW)
    await record_daily(db_session, "daily_heartbeat", heartbeat, now=NOW)
    await share(db_session, Group.USAGE, shared=False, now=NOW + timedelta(minutes=1))
    await share(db_session, Group.USAGE, now=NOW + timedelta(minutes=2))
    await record_count(db_session, "daily_action", {"action": "save_job"}, now=NOW + timedelta(minutes=3))
    await record_daily(db_session, "daily_heartbeat", heartbeat, now=NOW + timedelta(minutes=3))

    rows = await _all(db_session)
    withdrawn = [r for r in rows if r.withdrawn_at is not None]
    live = [r for r in rows if r.withdrawn_at is None]
    assert sorted(r.name for r in withdrawn) == sorted(r.name for r in live) == ["daily_action", "daily_heartbeat"]
    assert all(r.dedupe_key.startswith(f"withdrawn:{r.id}:") for r in withdrawn)
    assert [r.count for r in live if r.name == "daily_action"] == [1]
    claimed = await outbox.claim(db_session, groups=[Group.USAGE], today=TOMORROW, now=NOW, retry_after=RETRY)
    assert sorted(r.id for r in claimed) == sorted(r.id for r in live)


async def test_a_daily_snapshot_is_replaced_the_same_day(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE)
    base = {"app_version": "0.1.0", "os": "macos", "arch": "arm64", "python": "3.12",
            "install_method": "source", "db_mode": "embedded"}
    await record_daily(db_session, "daily_heartbeat", base | {"followed_bucket": "1-5"}, now=NOW)
    await record_daily(db_session, "daily_heartbeat", base | {"followed_bucket": "6-20"}, now=NOW + timedelta(hours=2))
    await record_daily(db_session, "daily_heartbeat", base, now=NOW + timedelta(days=1))
    rows = await _all(db_session)
    assert [(row.day, row.props.get("followed_bucket")) for row in rows] == [
        (NOW.date(), "6-20"),
        (TOMORROW, None),
    ]


async def test_today_waits_and_a_claim_is_not_claimed_twice(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE)
    await record_count(db_session, "daily_action", {"action": "save_job"}, now=NOW)
    await record_milestone(db_session, "first_job_saved", now=NOW)

    # On the day itself only the milestone (no day) is sendable.
    today = await outbox.claim(db_session, groups=[Group.USAGE], today=NOW.date(), now=NOW, retry_after=RETRY)
    assert [row.name for row in today] == ["first_job_saved"]

    # The next day the count is final and sendable; the milestone's attempt is
    # a day old, past the retry window, so it is claimed again too.
    later = NOW + timedelta(days=1)
    first = await outbox.claim(db_session, groups=[Group.USAGE], today=TOMORROW, now=later, retry_after=RETRY)
    assert sorted(row.name for row in first) == ["daily_action", "first_job_saved"]
    # Within the retry window nothing is claimed again; after it, the unsent rows are.
    again = await outbox.claim(db_session, groups=[Group.USAGE], today=TOMORROW, now=later + timedelta(minutes=30), retry_after=RETRY)
    assert again == []
    retry = await outbox.claim(db_session, groups=[Group.USAGE], today=TOMORROW, now=later + timedelta(hours=2), retry_after=RETRY)
    assert sorted(row.name for row in retry) == ["daily_action", "first_job_saved"]


async def test_only_shared_groups_are_claimed(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE, Group.CRASHES)
    await record_count(db_session, "daily_action", {"action": "save_job"}, now=NOW)
    claimed = await outbox.claim(db_session, groups=[Group.CRASHES], today=TOMORROW, now=NOW, retry_after=RETRY)
    assert claimed == []


async def test_prune_removes_only_sent_rows_older_than_30_days(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE, Group.CRASHES)
    spec = CATALOGUE["daily_action"]
    for offset, action in enumerate(("save_job", "unsave_job", "dismiss_job", "follow")):
        await outbox.add_count(db_session, spec, {"action": action}, day=NOW.date() - timedelta(days=offset), at=NOW)
    rows = {row.props["action"]: row for row in await _all(db_session)}
    await outbox.mark_sent(db_session, [rows["save_job"].id], now=NOW - timedelta(days=31))
    await outbox.mark_sent(db_session, [rows["unsave_job"].id], now=NOW - timedelta(days=29))
    await outbox.mark_rejected(db_session, [rows["dismiss_job"].id], now=NOW - timedelta(days=60))
    await outbox.withdraw(db_session, [Group.USAGE], now=NOW - timedelta(days=60))

    assert await outbox.prune_sent(db_session, now=NOW) == 1
    left = sorted(row.props["action"] for row in await _all(db_session))
    assert left == ["dismiss_job", "follow", "unsave_job"]
