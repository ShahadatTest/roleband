"""Backfill disclosed-salary-band extraction over the existing corpus.

Bulk catch-up for the deterministic extraction pass. The daily pipeline already
runs it incrementally; this re-scans the existing corpus, which is what you want
after the scanner itself changes. No model, no configuration, any platform.

    python -m tracker.workflows.backfill_disclosed_comp --open        # currently-open jobs
    python -m tracker.workflows.backfill_disclosed_comp --open --limit 20
    python -m tracker.workflows.backfill_disclosed_comp --force       # re-run even if fresh

Incremental by default (gated by `disclosed_comp.owed_ids`: never read, text or
parser changed, or the place a band was chosen for moved). `--force` also
re-reads every selected row the text pass last read before the command
started; it clears nothing first, so a row keeps its band and stamp until its
own read commits, and a connector's band, which the text pass never reads,
is never touched. It prints that moment: `--force-before <it>`
resumes an interrupted forced read without re-reading what it finished.
`--dry-run` counts the selection and writes nothing. Commits each batch of
`BATCH` jobs, newest first: interrupting it keeps every finished batch, and a
rerun resumes with what is still owed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime

from sqlalchemy import func, select

from tracker.db.models import Job
from tracker.db.session import session_scope
from tracker.intelligence_runtime.disclosed_comp import (
    active_parser_version,
    extract_disclosed_comp,
    owed_ids,
    settle_stored_bands,
)
from tracker.workflows.posting_pages import page_band

logger = logging.getLogger(__name__)


#: Jobs per transaction: the batch an interruption can lose at most.
BATCH = 200


async def run(
    *,
    open_only: bool,
    force: bool,
    limit: int | None,
    batch: int = BATCH,
    force_before: datetime | None = None,
    dry_run: bool = False,
) -> dict:
    async with session_scope() as session:
        # The database's clock, the one the text pass stamps with: a read in
        # this first transaction stamps this very moment, which is not before
        # it, so a resume naming it never reads that row twice.
        read_before = (
            force_before
            if force_before is not None
            else (await session.scalar(select(func.now())) if force else None)
        )
        if read_before is not None:
            logger.warning(
                "forced read of rows last read before %s; if interrupted, resume with "
                "--force-before %s", read_before.isoformat(), read_before.isoformat(),
            )

        id_stmt = select(Job.id).order_by(Job.id.desc())
        if open_only:
            id_stmt = id_stmt.where(Job.status == "open")
        job_ids = list((await session.scalars(id_stmt)).all())

        if dry_run:
            active = await active_parser_version(session)
            owed = settled = 0
            for start in range(0, len(job_ids), batch):
                owed += len(await owed_ids(
                    session, job_ids[start:start + batch], active, read_before=read_before,
                ))
                # Settled in the session, then rolled back: counted, never written.
                settled += await settle_stored_bands(session, job_ids[start:start + batch])
            await session.rollback()
            return {"owed": owed if limit is None else min(owed, limit), "processed": 0,
                    "settled": settled}

        summary = {"processed": 0, "disclosed": 0, "prefiltered": 0, "settled": 0}
        for start in range(0, len(job_ids), batch):
            left = None if limit is None else limit - summary["processed"]
            if left is not None and left <= 0:
                break
            # A forced re-scan must not erase a band only the posting page
            # stated: with no band in the text, the page's is kept.
            part = await extract_disclosed_comp(
                session, job_ids[start:start + batch], cap=left, page_band=page_band,
                read_before=read_before,
            )
            # Connector and page bands are not the text pass's to re-read; the
            # role and salary readings reach them here.
            part["settled"] = await settle_stored_bands(session, job_ids[start:start + batch])
            await session.commit()
            for key in summary:
                summary[key] += part[key]
            logger.info("disclosed-comp backfill: %s of %s jobs looked at, %s",
                        min(start + batch, len(job_ids)), len(job_ids), summary)
        if read_before is not None:
            summary["force_before"] = read_before.isoformat()
        return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill disclosed-salary-band extraction.")
    parser.add_argument("--open", action="store_true", help="only currently-open jobs")
    parser.add_argument("--force", action="store_true", help="re-extract even if already fresh")
    parser.add_argument(
        "--force-before", type=datetime.fromisoformat, default=None, metavar="ISO",
        help="resume a forced read: re-read rows last read before this moment (implies --force)",
    )
    parser.add_argument("--limit", type=int, default=None, help="cap the number of jobs processed")
    parser.add_argument("--dry-run", action="store_true", help="count the selection, write nothing")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    summary = asyncio.run(run(
        open_only=args.open, force=args.force or args.force_before is not None, limit=args.limit,
        force_before=args.force_before, dry_run=args.dry_run,
    ))
    print(summary)


if __name__ == "__main__":
    main()
