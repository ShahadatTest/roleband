"""Re-project the saved scope onto `jobs.in_scope` from what is stored.

For the saves that change what the scope admits without carrying the axes
themselves: a learned exclusion rule created or deleted, a profile suggestion
accepted. The saves that DO carry the
axes (`PUT /api/settings`, `PUT /api/profile`) hand them to
`db.repo.apply_saved_scope_to_jobs` directly. Flushes nothing and commits
nothing: the calling save owns its transaction.
"""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.repo import apply_saved_scope_to_jobs
from tracker.settings_store import (
    forget_cached_settings,
    get_enabled_bands,
    get_enabled_domains,
    get_enabled_locations,
    get_enabled_roles,
    get_enabled_tracks,
    get_excluded_domains,
    get_excluded_locations,
    get_include_unstated_level,
    get_role_answers,
)


async def saved_scope(session: AsyncSession) -> tuple[tuple, dict]:
    """The stored scope as `job_scope_expr`'s arguments: five axes, then the
    keyword inputs. Read in one place so projection and promotion
    gate by the same saved scope."""
    await forget_cached_settings(session)
    axes = (
        await get_enabled_roles(session),
        await get_enabled_bands(session),
        await get_enabled_tracks(session),
        await get_enabled_locations(session),
        await get_enabled_domains(session),
    )
    return axes, {
        "excluded_domains": await get_excluded_domains(session),
        "answers": await get_role_answers(session),
        "excluded_locations": await get_excluded_locations(session),
        "include_unstated_level": await get_include_unstated_level(session),
    }


async def recompute_saved_scope(session: AsyncSession, job_ids: Collection[int] | None = None) -> int:
    """Project the saved scope onto every row, or onto `job_ids` only. A
    caller ordering itself against saves (the run's writer) holds
    `hold_scope_projection` from before its first write, so the scope read
    here cannot change before it commits."""
    axes, keywords = await saved_scope(session)
    if job_ids is not None:
        keywords = {**keywords, "job_ids": job_ids}
    return await apply_saved_scope_to_jobs(session, *axes, **keywords)
