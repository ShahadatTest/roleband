"""The `usage_events` outbox: the only writer and reader of that table.

Storage only. Whether anything may be written is `recorder.py`'s question
(consent, kill switches, the catalogue); whether anything may leave is
`flush.py`'s. Every write is an upsert on `dedupe_key`, so the API, the
scheduler and the pipeline can count the same day together without losing an
increment. Nothing here commits: the caller owns the transaction.

A count row belongs to its UTC day and is sent only once that day is over, so a
day's number is final when it leaves. Milestones and crashes have no waiting
day beyond that: milestones carry no day, crashes are counted per day too.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from datetime import date, datetime, timedelta

from sqlalchemy import ColumnElement, String, cast, delete, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import UsageEvent
from tracker.usage_stats.registry import Event, Group, Kind

#: How long a sent row stays for "What was sent recently" before it is pruned.
SENT_KEPT = timedelta(days=30)


def props_hash(props: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(props, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _row(spec: Event, key: str, props: Mapping[str, object], *, day: date | None, at: datetime) -> dict:
    return {
        "dedupe_key": key,
        "kind": spec.kind.value,
        "name": spec.name,
        "consent_group": spec.group.value,
        "props": dict(props),
        "day": day,
        "count": 1,
        "first_at": at,
        "last_at": at,
    }


async def add_count(
    session: AsyncSession, spec: Event, props: Mapping[str, object], *, day: date, at: datetime, by: int = 1
) -> None:
    """One more (or `by` more) of a COUNT or EXCEPTION event on `day`."""
    if spec.kind not in (Kind.COUNT, Kind.EXCEPTION):
        raise ValueError(f"{spec.name} is a {spec.kind.value} event, not a count")
    if by < 1:
        return
    key = f"{spec.kind.value}:{day.isoformat()}:{spec.name}:{props_hash(props)}"
    values = _row(spec, key, props, day=day, at=at) | {"count": by}
    stmt = insert(UsageEvent).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[UsageEvent.dedupe_key],
        set_={"count": UsageEvent.count + by, "last_at": at},
        where=UsageEvent.withdrawn_at.is_(None),
    )
    await session.execute(stmt)


async def set_count(
    session: AsyncSession,
    spec: Event,
    props: Mapping[str, object],
    *,
    day: date,
    at: datetime,
    count: int,
    key_props: Mapping[str, object] | None = None,
) -> None:
    """A COUNT row whose number is recomputed, not accumulated (a day's scan
    health, rolled up from the runs). Idempotent; a row already sent is left
    as it was sent. `key_props` are the properties that name the row when the
    rest are figures recomputed with it (a median latency, a token total)."""
    if spec.kind is not Kind.COUNT:
        raise ValueError(f"{spec.name} is a {spec.kind.value} event, not a count")
    if count < 1:
        return
    key = f"{spec.kind.value}:{day.isoformat()}:{spec.name}:{props_hash(props if key_props is None else key_props)}"
    values = _row(spec, key, props, day=day, at=at) | {"count": count}
    stmt = insert(UsageEvent).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[UsageEvent.dedupe_key],
        set_={"count": count, "props": dict(props), "last_at": at},
        where=UsageEvent.sent_at.is_(None),
    )
    await session.execute(stmt)


async def put_daily(session: AsyncSession, spec: Event, props: Mapping[str, object], *, day: date, at: datetime) -> None:
    """The day's snapshot of a DAILY event; a later one the same day replaces it."""
    if spec.kind is not Kind.DAILY:
        raise ValueError(f"{spec.name} is a {spec.kind.value} event, not a daily snapshot")
    key = f"daily:{day.isoformat()}:{spec.name}"
    stmt = insert(UsageEvent).values(**_row(spec, key, props, day=day, at=at))
    stmt = stmt.on_conflict_do_update(
        index_elements=[UsageEvent.dedupe_key],
        set_={"props": dict(props), "last_at": at},
        where=UsageEvent.withdrawn_at.is_(None),
    )
    await session.execute(stmt)


async def put_milestone(session: AsyncSession, spec: Event, props: Mapping[str, object], *, at: datetime) -> bool:
    """A milestone, once ever. True when this call recorded it. Its row is the
    proof, so `prune_sent` keeps it."""
    if spec.kind is not Kind.MILESTONE:
        raise ValueError(f"{spec.name} is a {spec.kind.value} event, not a milestone")
    stmt = (
        insert(UsageEvent)
        .values(**_row(spec, f"milestone:{spec.name}", props, day=None, at=at))
        .on_conflict_do_nothing(index_elements=[UsageEvent.dedupe_key])
        .returning(UsageEvent.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


def _sendable(*, groups: Collection[Group], today: date) -> tuple[ColumnElement[bool], ...]:
    return (
        UsageEvent.sent_at.is_(None),
        UsageEvent.rejected_at.is_(None),
        UsageEvent.withdrawn_at.is_(None),
        UsageEvent.consent_group.in_([group.value for group in groups]),
        (UsageEvent.day.is_(None)) | (UsageEvent.day < today),
    )


async def pending(session: AsyncSession, *, groups: Collection[Group], today: date) -> list[UsageEvent]:
    """What the next send would carry, without claiming it (Settings' preview)."""
    if not groups:
        return []
    stmt = select(UsageEvent).where(*_sendable(groups=groups, today=today)).order_by(UsageEvent.id)
    return list((await session.execute(stmt)).scalars())


async def claim(
    session: AsyncSession,
    *,
    groups: Collection[Group],
    today: date,
    now: datetime,
    retry_after: timedelta,
) -> list[UsageEvent]:
    """Mark the sendable rows as being sent now and return them.

    A row attempted within `retry_after` is left to the attempt in flight (or to
    its retry), so two ticks never post the same row twice; `SKIP LOCKED` keeps
    a concurrent claim from waiting on this one."""
    if not groups:
        return []
    candidates = (
        select(UsageEvent.id)
        .where(
            *_sendable(groups=groups, today=today),
            (UsageEvent.attempted_at.is_(None)) | (UsageEvent.attempted_at < now - retry_after),
        )
        .with_for_update(skip_locked=True)
    )
    stmt = (
        update(UsageEvent)
        .where(UsageEvent.id.in_(candidates.scalar_subquery()))
        .values(attempted_at=now)
        .returning(UsageEvent)
        .execution_options(synchronize_session=False)
    )
    rows = list((await session.execute(stmt)).scalars())
    return sorted(rows, key=lambda row: row.id)


async def mark_sent(session: AsyncSession, ids: Sequence[int], *, now: datetime) -> None:
    if ids:
        await session.execute(update(UsageEvent).where(UsageEvent.id.in_(ids)).values(sent_at=now))


async def mark_rejected(session: AsyncSession, ids: Sequence[int], *, now: datetime) -> None:
    """The service refused these (a 4xx that is not 429): never retried."""
    if ids:
        await session.execute(update(UsageEvent).where(UsageEvent.id.in_(ids)).values(rejected_at=now))


async def withdraw(session: AsyncSession, groups: Collection[Group], *, now: datetime) -> int:
    """The user stopped sharing `groups`: their unsent rows are never sent.

    Kept, not deleted: deleting user data needs an explicit request (AGENTS.md,
    "Data safety"). A withdrawn row gives up its key, so a later upsert on the
    same key, after the user shares again the same day, starts a row of its
    own instead of adding to one that is never sent."""
    if not groups:
        return 0
    stmt = (
        update(UsageEvent)
        .where(
            UsageEvent.sent_at.is_(None),
            UsageEvent.withdrawn_at.is_(None),
            UsageEvent.consent_group.in_([group.value for group in groups]),
        )
        .values(
            withdrawn_at=now,
            dedupe_key=literal("withdrawn:") + cast(UsageEvent.id, String) + ":" + UsageEvent.dedupe_key,
        )
    )
    result = await session.execute(stmt)
    return int(getattr(result, "rowcount", 0) or 0)


async def prune_sent(session: AsyncSession, *, now: datetime, keep: timedelta = SENT_KEPT) -> int:
    """Delete rows sent more than `keep` ago. Unsent, rejected and withdrawn
    rows are never touched, and neither is a milestone: its row is what makes
    it once ever, and an install has a handful."""
    stmt = delete(UsageEvent).where(
        UsageEvent.sent_at.is_not(None),
        UsageEvent.sent_at < now - keep,
        UsageEvent.kind != Kind.MILESTONE.value,
    )
    result = await session.execute(stmt)
    return int(getattr(result, "rowcount", 0) or 0)


async def sent_since(session: AsyncSession, since: datetime) -> list[UsageEvent]:
    stmt = (
        select(UsageEvent)
        .where(UsageEvent.sent_at.is_not(None), UsageEvent.sent_at >= since)
        .order_by(UsageEvent.sent_at.desc(), UsageEvent.id.desc())
    )
    return list((await session.execute(stmt)).scalars())


async def last_sent_at(session: AsyncSession) -> datetime | None:
    stmt = select(UsageEvent.sent_at).where(UsageEvent.sent_at.is_not(None)).order_by(UsageEvent.sent_at.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def last_attempted_at(session: AsyncSession) -> datetime | None:
    stmt = (
        select(UsageEvent.attempted_at)
        .where(UsageEvent.attempted_at.is_not(None))
        .order_by(UsageEvent.attempted_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
