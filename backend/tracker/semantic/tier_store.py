"""`app_settings.embedding_tier` — the user's durable embedding-tier choice.

Why the DB and not `provision.json`: the decision file lives at
`REPO_ROOT/data/models/`, which is **per-checkout**, while the vectors it
produces land in the one **per-user** database every checkout shares.
Left in the file, a choice made from the main checkout would
be invisible to a worktree, and that worktree's nightly pipeline would embed
into the same space at the other tier — the exact mixed-space failure the
forced re-embed exists to prevent. Auto-detection is safe in the file precisely
because it is a pure function of the hardware and therefore agrees everywhere;
a *choice* is not.

Absent row (or "auto") = follow detected RAM. The file stays the runtime
authority for every sync reader; `reconcile_tier` is what keeps it honest.
"""

from __future__ import annotations

import logging

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import AppSetting
from tracker.semantic import provision

logger = logging.getLogger(__name__)

TIER_KEY = "embedding_tier"


async def get_tier_choice(session: AsyncSession) -> str | None:
    """The user's chosen tier, or None when they have not chosen one.

    A stored tier the manifest does not offer reads as None rather than raising: the machine falls back to auto, which is
    always valid, instead of failing to embed at all.
    """
    row = await session.get(AppSetting, TIER_KEY)
    if row is None or not isinstance(row.value, dict):
        return None
    tier = row.value.get("tier")
    return tier if tier in provision.TIERS else None


async def set_tier_choice(session: AsyncSession, choice: str | None) -> None:
    """Record (or clear) the user's choice. None restores auto-detection."""
    if choice is not None and choice not in provision.TIERS:
        raise ValueError(f"unknown embedding tier {choice!r}")
    value: dict = {"tier": choice} if choice else {}
    stmt = insert(AppSetting).values(key=TIER_KEY, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": value})
    await session.execute(stmt)


async def reconcile_tier(session: AsyncSession) -> str:
    """Push the shared choice into this checkout's decision file; return the tier.

    A *user* choice is written through unconditionally. Absent one, the file's
    own first decision stands untouched — re-deriving it here would re-decide
    the tier on every startup, which `resolve_tier` refuses to do
    (re-decision means re-download and a stale corpus).
    """
    choice = await get_tier_choice(session)
    return provision.set_tier(choice) if choice else provision.resolve_tier()
