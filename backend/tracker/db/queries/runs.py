"""Which `running` scrape rows are orphans rather than live progress.

A run whose process crashed, hung or was killed leaves its committed row in
`running`. Three surfaces judge that: `db/repo.py::reconcile_stale_runs` against
the DATABASE clock, `/api/status`'s stuck-run count against the PYTHON clock,
and `health.is_run_active` in Python for a row already in hand. This module is
the one spelling of the criterion, so the three agree at the boundary by
construction.

Two bounds, either of which orphans a run:

* **absolute** -- `started_at` older than `stale_minutes`, independent of any
  beat, which also reconciles rows that never beat;
* **liveness** -- the last beat (`heartbeat_at`, or `started_at` for a run that
  has not beat yet) older than `heartbeat_stale_seconds`. A killed process stops
  beating, so this clears `running` in minutes instead of waiting out the
  absolute bound. `None` disarms it.

Both are strict `<`: a row exactly at a bound is still live, and
`health.is_run_active` says the same. `tests/test_stale_runs.py` holds the two
implementations to each other over real Postgres, boundary rows included.

`now` is whatever clock the caller answers with -- a `datetime`, or `func.now()`
for the database's. The rows are written with BOTH (`pipeline.py` stamps
`started_at` and progress beats in Python, and the periodic beat with `now()`),
so this module cannot pick one for everybody; it only keeps the comparison
spelled once.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import ScrapeRun, ScrapeSourceRun


def stale_run_where(
    now,
    *,
    stale_minutes: float,
    heartbeat_stale_seconds: float | None,
):
    """The criterion selecting orphaned `running` rows at instant `now`.

    Silence is the signal. A live run beats every `run_heartbeat_seconds` from
    a task detached from its work, so a gap means the process is gone.
    `coalesce` measures a run that has never beaten from its start, which is
    why "has not beaten yet" needs no rule of its own.

    `stale_minutes` answers only for a caller that supplies no heartbeat
    window. Applied beside one it reconciles runs that are beating AND
    working: a full collection can outlast any fixed budget, and the row then
    flips to `error` while the process is still writing, only for the terminal
    status it records later to overwrite the reconciliation. A run is never
    bounded by its length: each source is bounded by its own `SourceClock`.
    """
    if heartbeat_stale_seconds is None:
        silent = ScrapeRun.started_at < now - timedelta(minutes=stale_minutes)
    else:
        silent = func.coalesce(ScrapeRun.heartbeat_at, ScrapeRun.started_at) < now - timedelta(
            seconds=heartbeat_stale_seconds
        )
    return and_(ScrapeRun.status == "running", silent)


def committed_per_source_expr(run_id):
    """SQL for an unfinished run's `per_source`, projected from the
    `scrape_source_runs` rows it committed: `{company: stats}`, `{}` for none.
    A run writes `per_source` once, at its terminal record; until then, and for
    a run that never reaches one, this is what it reported."""
    return func.coalesce(
        select(func.jsonb_object_agg(ScrapeSourceRun.company_slug, ScrapeSourceRun.stats))
        .where(ScrapeSourceRun.run_id == run_id)
        .scalar_subquery(),
        func.jsonb_build_object(),
    )


async def committed_per_source(session: AsyncSession, run_id: int) -> dict[str, dict]:
    """`committed_per_source_expr` for one run, read now."""
    return dict(await session.scalar(select(committed_per_source_expr(run_id))) or {})
