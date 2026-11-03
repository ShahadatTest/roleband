"""Strip the listing's query string from stored Google posting URLs.

A card's href as served echoes the results page's own state:
`.../jobs/results/1333...-technical-program-manager
?page=81&sort_by=date&location=United+States`. A shared link has no query, so
URL search cannot resolve a posting stored that way, and `page` moves between
runs. The adapter keeps the job path alone (`platform.util.without_query`) and
a scan rewrites the rows it lists, so this repairs the rest: closed postings,
and inventory rows no scan reads again.

Only `url` is written. Observations and lifecycle events carry no URL, and
identity is `company:req_id`, so no history or grouping moves. An inventory
row's `content_hash` is left as it was: the next scan of that posting sees a
different hash and rewrites the row once, which it would have done anyway.

Dry-run by default. `--apply` writes in batches of `BATCH` rows, each its own
transaction; a rerun selects only URLs that still carry a query, so
it resumes by itself.

Run from backend/:
    .venv/bin/python -m scripts.backfill_google_urls            # dry run
    .venv/bin/python -m scripts.backfill_google_urls --apply    # write
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import or_, select

from tracker.db.models import Job, PostingInventory
from tracker.db.session import commit_in_batches, session_scope
from tracker.platform.util import without_query

log = logging.getLogger(__name__)

#: Rows per transaction: the most a killed `--apply` can lose.
BATCH = 500

#: Every google-adapter posting URL starts here, whichever company slug holds
#: it (google and google-deepmind share the board).
JOB_URL_PREFIX = "https://www.google.com/about/careers/applications/jobs/results/"

TABLES = (Job, PostingInventory)


def _pending(model):
    return select(model.id).where(
        model.url.startswith(JOB_URL_PREFIX, autoescape=True),
        or_(model.url.contains("?", autoescape=True), model.url.contains("#", autoescape=True)),
    )


async def backfill(apply: bool, batch: int = BATCH) -> dict[str, int]:
    pending: dict[str, list[int]] = {}
    async with session_scope() as session:
        for model in TABLES:
            pending[model.__tablename__] = list(
                (await session.scalars(_pending(model).order_by(model.id))).all()
            )
    stats = {f"{name}_pending": len(ids) for name, ids in pending.items()}
    if not apply:
        return stats

    for model in TABLES:
        async def write(session, ids: list[int], model=model) -> int:
            rows = (await session.scalars(select(model).where(model.id.in_(ids)))).all()
            changed = 0
            for row in rows:
                clean = without_query(row.url)
                if clean != row.url:
                    row.url = clean
                    changed += 1
            return changed

        stats[f"{model.__tablename__}_rewritten"] = await commit_in_batches(
            pending[model.__tablename__], write, size=batch, label=f"{model.__tablename__} urls"
        )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist (default: dry run)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = asyncio.run(backfill(args.apply))
    log.info("google url backfill: %s", stats)
    if not args.apply and any(stats.values()):
        log.info("Dry run: nothing written. Re-run with --apply to persist.")


if __name__ == "__main__":
    main()
