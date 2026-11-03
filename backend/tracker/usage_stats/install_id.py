"""The random ID every event from this install carries (sent as `distinct_id`).

A UUID4 made the first time the user shares anything, and nothing else: no
machine, account or name goes into it. It is pseudonymous, not anonymous (it
links one install's events together, which is what retention and survey
targeting need), and the consent wording says so. Stopping keeps it, so sharing
again continues the same timeline; Reset in Settings replaces it, after which
nothing links new events to old ones.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import AppSetting

INSTALL_ID_KEY = "usage_install_id"


def _parse(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    raw = value.get("id")
    if not isinstance(raw, str):
        return None
    try:
        parsed = uuid.UUID(raw)
    except ValueError:
        return None
    return str(parsed) if parsed.version == 4 else None


async def get_install_id(session: AsyncSession) -> str | None:
    row = await session.get(AppSetting, INSTALL_ID_KEY)
    return _parse(row.value) if row is not None else None


async def ensure_install_id(session: AsyncSession, *, now: datetime) -> str:
    """This install's ID, made now if there is none (or the stored one is unreadable)."""
    current = await get_install_id(session)
    if current is not None:
        return current
    return await reset_install_id(session, now=now)


async def reset_install_id(session: AsyncSession, *, now: datetime) -> str:
    """A new ID: events after this are not linked to events before it."""
    new_id = str(uuid.uuid4())
    value = {"id": new_id, "created_at": now.isoformat()}
    stmt = insert(AppSetting).values(key=INSTALL_ID_KEY, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": value})
    await session.execute(stmt)
    return new_id
