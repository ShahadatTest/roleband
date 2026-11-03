"""`reference_per_source_stmt` picks the run `reference_run` picks.

`/api/sync/targets` chooses its reference run in SQL so it reads one run's
`per_source` instead of the window's; the scheduler's retry still chooses with
`reference_run` over loaded runs. The two must name the same run, or the
"failed last run" the user sees and the set the retry works on drift apart.
Each case seeds real rows, asks both, and checks them against the run the rule
says must win. Every run's blob is distinct, so a wrong pick shows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tracker.db.models import ScrapeRun
from tracker.health import RunScope
from tracker.workflows.retry_sources import reference_per_source_stmt, reference_run

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
FULL, TARGETED = RunScope.FULL, RunScope.TARGETED


def _run(run_id: int, scope: str, status: str, per_source: dict) -> ScrapeRun:
    return ScrapeRun(
        id=run_id,
        started_at=NOW - timedelta(hours=run_id),
        finished_at=None if status == "running" else NOW - timedelta(hours=run_id) + timedelta(minutes=30),
        status=status,
        scope=scope,
        per_source=per_source,
    )


def _blob(run_id: int) -> dict:
    return {f"company-{run_id}": {"scanned": run_id, "errors": []}}


CASES = {
    "a newer targeted run is skipped": (
        [(3, TARGETED, "ok", _blob(3)), (2, FULL, "partial", _blob(2))], 20, 2,
    ),
    "a full run that observed nothing is skipped": (
        [(3, FULL, "error", {}), (2, FULL, "partial", _blob(2))], 20, 2,
    ),
    "a run still going is not a candidate": (
        [(3, FULL, "running", _blob(3)), (2, FULL, "ok", _blob(2))], 20, 2,
    ),
    "the newest qualifying run wins": (
        [(4, FULL, "ok", _blob(4)), (3, FULL, "ok", _blob(3)), (2, FULL, "partial", _blob(2))], 20, 4,
    ),
    "no full run means no reference": (
        [(3, TARGETED, "ok", _blob(3)), (2, TARGETED, "error", _blob(2))], 20, None,
    ),
    "a reference outside the window is not reached": (
        [(4, TARGETED, "ok", _blob(4)), (3, FULL, "error", {}), (2, FULL, "ok", _blob(2))], 2, None,
    ),
}


@pytest.mark.parametrize("rows, window, expected", CASES.values(), ids=CASES.keys())
async def test_sql_and_python_pick_the_same_reference(db_session, rows, window, expected):
    db_session.add_all(_run(*row) for row in rows)
    await db_session.commit()

    picked_in_sql = await db_session.scalar(reference_per_source_stmt(window))
    loaded = (
        await db_session.scalars(
            select(ScrapeRun)
            .where(ScrapeRun.status.in_(("ok", "partial", "error")))
            .order_by(ScrapeRun.id.desc())
            .limit(window)
        )
    ).all()
    picked_in_python = reference_run(list(loaded))

    assert (picked_in_python.id if picked_in_python else None) == expected
    assert picked_in_sql == (_blob(expected) if expected is not None else None)
