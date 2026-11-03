"""Bring stored roles and postings in line with the classifier now, without
waiting for a pipeline run.

The post passes own this (no producer is reachable only by CLI): on every
run `roles_backfill` re-files each job's family and track, `levels_backfill`
re-reads its level, and the inventory re-derives when the classifier
fingerprint moves. This script runs the same derivations in the same order and
reports what they would change: a level or role rule change
reaches the database at once instead of at the next run.

1. Jobs: family and track (`post_passes.pending_roles`).
2. Jobs: level (`scripts.backfill_level_bands`, which reads the stored family,
   so it runs after step 1 is written).
3. The posting inventory (`inventory_store.pending_inventory_classes`), then
   the classifier fingerprint, so the next run does not repeat it.

Dry run by default. `--apply` writes each step in batches of `BATCH` rows, each
its own transaction, and recomputes the saved scope. A run that dies
keeps the batches it saved; a rerun derives only the rows still pending. A dry
run's level count is read against the families stored now, so it can differ
from what `--apply` writes after step 1.

Run from backend/ (long: detach it, `start_new_session`):
    .venv/bin/python -m scripts.backfill_classifier            # dry run
    .venv/bin/python -m scripts.backfill_classifier --apply    # write
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections import Counter

from sqlalchemy import select

from scripts import backfill_level_bands
from tracker.db.inventory_store import (
    mark_classified,
    pending_inventory_classes,
    write_inventory_classes,
)
from tracker.db.models import Job, PostingInventory
from tracker.db.repo import set_job_roles
from tracker.db.session import commit_in_batches, session_scope
from tracker.plugins.reestimate import refresh_jobs
from tracker.scope.projection import recompute_saved_scope
from tracker.workflows.post_passes import pending_roles

log = logging.getLogger(__name__)

#: Rows per transaction: the most a killed `--apply` can lose.
BATCH = 500


async def _stored(session, model, ids: list[int], *columns) -> dict[int, tuple]:
    """The stored values of `columns` for `ids`, to report old -> new."""
    rows = (await session.execute(select(model.id, *columns).where(model.id.in_(ids)))).all()
    return {row[0]: tuple(row[1:]) for row in rows}


async def backfill(apply: bool, batch: int = BATCH) -> dict:
    async with session_scope() as session:
        roles = await pending_roles(session)
        inventory = await pending_inventory_classes(session)
        old_roles = await _stored(session, Job, [c["id"] for c in roles], Job.family)
        old_inventory = await _stored(
            session, PostingInventory, [c["id"] for c in inventory],
            PostingInventory.level_band, PostingInventory.family,
        )
        await session.rollback()  # the derivations read; writes go in batches below

    family_moves = Counter((old_roles[c["id"]][0], c["family"]) for c in roles)
    inventory_bands = Counter(
        (old_inventory[c["id"]][0], c["level_band"]) for c in inventory
        if old_inventory[c["id"]][0] != c["level_band"]
    )
    inventory_families = Counter(
        (old_inventory[c["id"]][1], c["family"]) for c in inventory
        if old_inventory[c["id"]][1] != c["family"]
    )

    if apply:
        by_id = {c["id"]: c for c in roles}

        async def write_roles(session, ids: list[int]) -> int:
            await set_job_roles(session, [by_id[i] for i in ids])
            await refresh_jobs(session, ids)  # a family is an estimate input
            return len(ids)

        await commit_in_batches(list(by_id), write_roles, size=batch, label="role changes")

    # Levels read the stored family, so they come after the roles are written.
    levels = await backfill_level_bands.backfill(apply, None, batch)

    if apply:
        rows = {c["id"]: c for c in inventory}

        async def write_rows(session, ids: list[int]) -> int:
            return await write_inventory_classes(session, [rows[i] for i in ids])

        await commit_in_batches(list(rows), write_rows, size=batch, label="inventory classifications")
        async with session_scope() as session:
            await mark_classified(session)
            await recompute_saved_scope(session)

    return {
        "applied": apply,
        "jobs_roles": len(roles), "family_moves": family_moves,
        "jobs_levels": levels["band_changed"], "level_moves": levels["moves"],
        "leaving_scope": levels["leaving_scope"], "entering_scope": levels["entering_scope"],
        "inventory": len(inventory), "inventory_bands": inventory_bands,
        "inventory_families": inventory_families,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="persist (default: dry run)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = asyncio.run(backfill(args.apply))
    log.info("jobs: %d role changes, %d level changes (scope: %d leave, %d enter)",
             stats["jobs_roles"], stats["jobs_levels"], stats["leaving_scope"], stats["entering_scope"])
    for (old, new), count in stats["family_moves"].most_common():
        log.info("  family %s -> %s: %d", old, new, count)
    for (old, new), count in stats["level_moves"].most_common():
        log.info("  level %s -> %s: %d", old, new, count)
    log.info("inventory: %d rows reclassified", stats["inventory"])
    for (old, new), count in stats["inventory_bands"].most_common():
        log.info("  level %s -> %s: %d", old, new, count)
    for (old, new), count in stats["inventory_families"].most_common():
        log.info("  family %s -> %s: %d", old, new, count)
    if not stats["applied"]:
        log.info("Dry run: nothing written. Re-run with --apply to persist.")


if __name__ == "__main__":
    main()
