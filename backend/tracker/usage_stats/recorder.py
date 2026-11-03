"""The one door into the outbox: consent, kill switches and catalogue first.

Every function returns False without writing when the environment switches
sharing off, when the event's group is not shared (undecided, declined or
stale), and raises `UsageEventError` for an event the catalogue does not
declare. Callers in a request, a run or a tick wrap the call so a usage event
never fails the work around it; tests let it raise.

Consent is read with `consent.get_sharing_to_record`, whose lock keeps a
consent edit waiting until the caller's transaction ends. Pass `sharing` only
when the caller read it under that lock in the same transaction (a drain
recording many counts, or the sender's rollup under its exclusive hold);
otherwise it is read here.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.usage_stats import outbox, scrub
from tracker.usage_stats.consent import Sharing, get_sharing_to_record
from tracker.usage_stats.kill import blocked_by
from tracker.usage_stats.registry import Event, Kind, UsageEventError, validate


async def _admitted(
    session: AsyncSession, name: str, props: Mapping[str, object], sharing: Sharing | None
) -> Event | None:
    spec = validate(name, props)
    if blocked_by() is not None:
        return None
    current = sharing if sharing is not None else await get_sharing_to_record(session)
    return spec if current.shared(spec.group) else None


async def record_count(
    session: AsyncSession,
    name: str,
    props: Mapping[str, object],
    *,
    now: datetime,
    by: int = 1,
    sharing: Sharing | None = None,
) -> bool:
    spec = await _admitted(session, name, props, sharing)
    if spec is None:
        return False
    if spec.kind is not Kind.COUNT:
        raise UsageEventError(f"{name} is a {spec.kind.value} event, not a count")
    await outbox.add_count(session, spec, props, day=now.date(), at=now, by=by)
    return True


async def record_total(
    session: AsyncSession,
    name: str,
    props: Mapping[str, object],
    *,
    day: date,
    count: int,
    now: datetime,
    sharing: Sharing | None = None,
    key_props: Mapping[str, object] | None = None,
) -> bool:
    """A count recomputed from stored data (a day's scan health): replaces the
    day's number rather than adding to it, so a rollup can run again."""
    spec = await _admitted(session, name, props, sharing)
    if spec is None:
        return False
    if spec.kind is not Kind.COUNT:
        raise UsageEventError(f"{name} is a {spec.kind.value} event, not a count")
    await outbox.set_count(session, spec, props, day=day, at=now, count=count, key_props=key_props)
    return True


async def record_daily(
    session: AsyncSession, name: str, props: Mapping[str, object], *, now: datetime, sharing: Sharing | None = None
) -> bool:
    spec = await _admitted(session, name, props, sharing)
    if spec is None:
        return False
    await outbox.put_daily(session, spec, props, day=now.date(), at=now)
    return True


async def record_milestone(
    session: AsyncSession,
    name: str,
    props: Mapping[str, object] | None = None,
    *,
    now: datetime,
    sharing: Sharing | None = None,
) -> bool:
    """A milestone, once ever: the first time it happens AFTER the user shared
    usage (the drain and the rollup only see that time), kept to one row."""
    props = props or {}
    spec = await _admitted(session, name, props, sharing)
    if spec is None:
        return False
    return await outbox.put_milestone(session, spec, props, at=now)


async def record_exception(
    session: AsyncSession,
    exc: BaseException,
    *,
    source: str,
    now: datetime,
    handled: bool = False,
    sharing: Sharing | None = None,
) -> bool:
    """A crash, scrubbed (`scrub.py`) before anything is stored. Marks `exc`
    as recorded, so a caller that re-raises it is not recorded twice."""
    recorded = await record_shape(session, scrub.scrub(exc, handled=handled), source=source, now=now, sharing=sharing)
    if recorded:
        try:
            exc._usage_recorded = True  # type: ignore[attr-defined]
        except AttributeError:
            pass
    return recorded


async def record_shape(
    session: AsyncSession,
    shape: scrub.Shape,
    *,
    source: str,
    now: datetime,
    sharing: Sharing | None = None,
) -> bool:
    """A crash already scrubbed (the API tallies shapes, not exceptions)."""
    props = {"source": source}
    spec = await _admitted(session, "$exception", props, sharing)
    if spec is None:
        return False
    stored = props | {"exception": scrub.to_props(shape), "fingerprint": shape.fingerprint()}
    await outbox.add_count(session, spec, stored, day=now.date(), at=now)
    return True
