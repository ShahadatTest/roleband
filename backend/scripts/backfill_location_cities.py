"""Backfill `jobs.location_cities` from the stored raw `locations` strings.

Idempotent: recomputes via tracker/taxonomy/locations.py::normalize_cities and writes
only rows whose value would change, so it is safe to re-run after tuning the
normalizer. Never touches any other column.

Run from backend/:  .venv/bin/python -m scripts.backfill_location_cities
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from tracker.db.models import Job
from tracker.db.session import session_scope
from tracker.taxonomy.locations import normalize_cities

log = logging.getLogger(__name__)
BATCH = 500


async def backfill() -> dict:
    scanned = updated = 0
    async with session_scope() as session:
        jobs = (await session.scalars(select(Job))).all()
        for job in jobs:
            scanned += 1
            cities = normalize_cities(job.locations or [])
            if (job.location_cities or []) != cities:
                job.location_cities = cities
                updated += 1
                if updated % BATCH == 0:
                    await session.commit()
        await session.commit()
    return {"scanned": scanned, "updated": updated}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = asyncio.run(backfill())
    log.info("location_cities backfill: %s", stats)


if __name__ == "__main__":
    main()
