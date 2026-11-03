"""What a scope save would do to the Board, read before it happens.

The caller has written the draft's axes inside a SAVEPOINT it will roll back
(`scope.axes.write_scope_axes`, the save's own normalisation), so every
read here sees the scope exactly as the save would store it:

- the Board after the save is what the save then counts: the save's own
  re-projection runs here, in the same SAVEPOINT, and the Board is read with
  the save's own count (`open_in_scope_count_stmt`), a place set once. Then
  the visible rows the save's promotion would admit are added;
- the rows it would admit are `promotion.candidates_stmt`, the one query the
  save's promotion runs, capped at `PROMOTION_LIMIT` as it is;
- a run holding the run lock means the save promotes nothing now: that run's
  post pass does, at its end.

Commits nothing: every write here is the save's own, and the caller rolls the
SAVEPOINT back.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.db.models import TrackedCompany
from tracker.db.queries.jobs import open_in_scope_count_stmt
from tracker.db.repo import apply_saved_scope_to_jobs
from tracker.scope.promotion import PROMOTION_LIMIT, candidates_stmt, run_lock_held

#: Example titles the review shows.
EXAMPLES = 3


#: `job_scope_expr`'s five axes: roles, bands, tracks, locations, domains.
Axes = tuple[list[str], list[str], list[str], list[str], list[str]]


async def preview_save(session: AsyncSession, axes: Axes, keywords: dict, *, hidden: list[str]) -> dict:
    """The Board after a save of the scope `axes`/`keywords` describe (the
    arguments the save's re-projection gets), with the scope already written
    in the caller's SAVEPOINT."""
    await apply_saved_scope_to_jobs(session, *axes, **keywords)
    kept = int(await session.scalar(open_in_scope_count_stmt(hidden)) or 0)
    scan_running = await run_lock_held(session)
    if not get_settings().inventory_promotion_enabled:
        # Promotion is off: the save adds nothing from earlier scans, now or
        # later; the rows join as each company is next scanned, like any posting.
        return {
            "on_board_after": kept, "adds_now": 0, "adds_on_board": 0, "adds_later": 0,
            "scan_running": scan_running, "examples": [],
        }

    stmt = await candidates_stmt(session)
    total = int(await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    admitted = stmt.limit(PROMOTION_LIMIT).subquery()
    visible_query = select(func.count()).select_from(admitted)
    if hidden:
        visible_query = visible_query.where(admitted.c.company.notin_(hidden))
    visible = int(await session.scalar(visible_query) or 0)
    adds_now = 0 if scan_running else min(total, PROMOTION_LIMIT)
    adds_on_board = 0 if scan_running else visible

    examples_query = (
        select(admitted.c.title, admitted.c.company, TrackedCompany.display)
        .join(TrackedCompany, TrackedCompany.slug == admitted.c.company)
        .order_by(admitted.c.last_seen_at.desc(), admitted.c.id.desc())
        .limit(EXAMPLES)
    )
    if hidden:
        examples_query = examples_query.where(admitted.c.company.notin_(hidden))
    examples = [
        {"title": title, "company": company, "company_display": display}
        for title, company, display in (await session.execute(examples_query)).all()
    ]
    return {
        "on_board_after": kept + adds_on_board,
        "adds_now": adds_now,
        "adds_on_board": adds_on_board,
        "adds_later": total - adds_now,
        "scan_running": scan_running,
        "examples": examples,
    }
