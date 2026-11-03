"""Backfill materialized notifications from historical scrape runs.

Saved per `BATCH` runs, each its own transaction; inserts are
idempotent, so a rerun after a kill repeats only unsaved work.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from tracker.db.models import ScrapeRun
from tracker.db.session import commit_in_batches, session_scope
from tracker.notifications import generate_notifications

#: Runs per transaction: the most a killed run can lose.
BATCH = 50


async def main(days: int | None = None, batch: int = BATCH) -> int:
    async with session_scope() as session:
        stmt = select(ScrapeRun.id).where(ScrapeRun.status != "running").order_by(ScrapeRun.id.asc())
        if days is not None:
            cutoff = datetime.now(UTC) - timedelta(days=days)
            stmt = stmt.where(ScrapeRun.started_at >= cutoff)
        run_ids = list((await session.scalars(stmt)).all())

    async def generate(session, ids: list[int]) -> int:
        runs = (await session.scalars(select(ScrapeRun).where(ScrapeRun.id.in_(ids)).order_by(ScrapeRun.id))).all()
        return sum([await generate_notifications(session, run) for run in runs])

    total = await commit_in_batches(run_ids, generate, size=batch, label="runs")
    print(f"backfilled notifications from {len(run_ids)} runs; attempted {total} inserts")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=None, help="Only backfill runs started within N days")
    args = parser.parse_args()
    asyncio.run(main(args.days))
