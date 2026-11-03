"""Backfill skill requirement extraction over the stored corpus.

    python -m tracker.skills.backfill            # all jobs, incremental
    python -m tracker.skills.backfill --open     # only currently-open jobs
    python -m tracker.skills.backfill --force    # re-extract everything
    python -m tracker.skills.backfill --force --after 4210   # resume a forced run

Incremental by default: a job is skipped when its requirements_content_hash,
extractor version, and taxonomy version are all current. A catalogue edit
changes the taxonomy version, so affected jobs re-extract on the next run.

Progress is saved per batch. Each batch of `BATCH` jobs is its own
transaction, so a run that dies keeps every batch before the one it died in.
A rerun resumes by itself, since the gate above skips what is already written. `--force` ignores
the gate, so a forced run resumes with `--after`, the last job id it reported
saved (jobs are taken in id order).
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

from tracker.db.models import Job
from tracker.db.session import commit_in_batches, session_scope
from tracker.skills.catalog import get_catalog
from tracker.skills.extract import extract_requirements
from tracker.skills.sync import sync_catalog

#: Jobs per transaction: the most a killed run can lose.
BATCH = 200


async def _job_ids(*, open_only: bool, after: int | None) -> list[int]:
    async with session_scope() as session:
        stmt = select(Job.id).order_by(Job.id)
        if open_only:
            stmt = stmt.where(Job.status == "open")
        if after is not None:
            stmt = stmt.where(Job.id > after)
        return list((await session.scalars(stmt)).all())


async def run(*, open_only: bool, force: bool, after: int | None = None, batch: int = BATCH) -> dict:
    job_ids = await _job_ids(open_only=open_only, after=after)
    catalog = get_catalog()
    async with session_scope() as session:
        id_by_slug = await sync_catalog(session, catalog)

    async def extract(session, chunk: list[int]) -> int:
        return await extract_requirements(session, chunk, force=force, catalog=catalog, id_by_slug=id_by_slug)

    processed = await commit_in_batches(job_ids, extract, size=batch, label="jobs")
    return {"jobs": len(job_ids), "processed": processed}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill skill extraction.")
    parser.add_argument("--open", action="store_true", help="only currently-open jobs")
    parser.add_argument("--force", action="store_true", help="re-extract every job")
    parser.add_argument("--after", type=int, help="only jobs with a larger id (resume a forced run)")
    parser.add_argument("--batch", type=int, default=BATCH, help="jobs per transaction")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    print(asyncio.run(run(open_only=args.open, force=args.force, after=args.after, batch=args.batch)))


if __name__ == "__main__":
    main()
