"""What Settings > Privacy and the consent screen read: the state, the next
batch, and what was sent. Read-only; the router serves these as they are."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.usage_stats import batch, outbox
from tracker.usage_stats.consent import get_sharing
from tracker.usage_stats.install_id import get_install_id
from tracker.usage_stats.kill import blocked_by
from tracker.usage_stats.registry import BROWSER_SCOPE, Group, fingerprint

SENT_SHOWN = timedelta(days=30)


async def state(session: AsyncSession, *, now: datetime) -> dict:
    sharing = await get_sharing(session)
    settings = get_settings()
    pending = await outbox.pending(session, groups=sharing.shared_groups(), today=now.date())
    return {
        "groups": [
            {
                "group": group.value,
                "status": sharing.status(group).value,
                "fingerprint": fingerprint(group),
                "browser_scope": list(BROWSER_SCOPE.get(group, ())),
                "decided_at": sharing.decided_at(group),
            }
            for group in Group
        ],
        "blocked_by": blocked_by(),
        "install_id": await get_install_id(session),
        "host": settings.usage_stats_host,
        "project_key": settings.usage_stats_project_key,
        "last_sent_at": await outbox.last_sent_at(session),
        "pending_events": len(pending),
    }


async def preview(session: AsyncSession, *, now: datetime) -> dict:
    sharing = await get_sharing(session)
    rows = await outbox.pending(session, groups=sharing.shared_groups(), today=now.date())
    install_id = await get_install_id(session) or "00000000-0000-4000-8000-000000000000"
    built = batch.build(rows, install_id=install_id, api_key=get_settings().usage_stats_project_key)
    return {"body": built.body, "left_out": len(built.unfit)}


async def sent(session: AsyncSession, *, now: datetime) -> dict:
    rows = await outbox.sent_since(session, now - SENT_SHOWN)
    return {
        "events": [
            {
                "name": row.name,
                "group": row.consent_group,
                "day": row.day,
                "count": row.count,
                # A crash shows its type and our frames, as it was sent.
                "props": dict(row.props or {}),
                "sent_at": row.sent_at,
            }
            for row in rows
            if row.sent_at is not None
        ]
    }
