"""Shared fixtures for the usage-sharing tests (docs/architecture.md)."""

from __future__ import annotations

from datetime import UTC, datetime

from tracker.usage_stats.consent import set_sharing
from tracker.usage_stats.registry import Group, fingerprint

#: A fixed moment, so day boundaries in the tests are deliberate.
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
CONSENT_TEXT = "Help shape RoleBand. Share screens, clicks and crash reports. Never your job details."


async def share(session, *groups: Group, now: datetime = NOW, shared: bool = True):
    """Answer `groups` the way the consent screen would, with current fingerprints."""
    return await set_sharing(
        session,
        {group: shared for group in groups},
        text=CONSENT_TEXT,
        locale="en",
        fingerprints={group: fingerprint(group) for group in groups},
        now=now,
    )
