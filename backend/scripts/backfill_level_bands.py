"""Report (and optionally write) what the `levels_backfill` pass would change.

The pass (`tracker.workflows.relevel`) re-derives every stored job's
band, confidence and basis on each pipeline run. This script reads the same
derivation without waiting for a run: every band transition per company, the
basis moves, and how many rows enter and leave the user's board, the number
that decides whether a calibration change is an improvement or a flood.

Dry-run by default. `--apply` writes the same rows the pass would, through
the same writer, for one company or all: in batches of `BATCH` rows, each its
own transaction, then the saved scope once. A run that dies keeps
the batches it saved, and a rerun derives only the rows still pending; the
scope is recomputed on every apply, so a rerun with nothing pending still
finishes it.

Run from backend/:
    .venv/bin/python -m scripts.backfill_level_bands            # dry run
    .venv/bin/python -m scripts.backfill_level_bands --company amazon
    .venv/bin/python -m scripts.backfill_level_bands --apply    # write
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections import Counter

from tracker.db.repo import set_job_levels
from tracker.db.session import commit_in_batches, session_scope
from tracker.enrich.enricher import Annotation, ScopeFilter, passes_filters
from tracker.enrich.level_mapper import LevelReading
from tracker.schema import RoleTrack
from tracker.scope.projection import recompute_saved_scope
from tracker.workflows.relevel import level_changes, pending_relevels, stored_reading
from tracker.workflows.scope_filter import load_scope_filter

log = logging.getLogger(__name__)

#: Rows per transaction: the most a killed `--apply` can lose.
BATCH = 500


def _in_scope(row, reading: LevelReading, scope: ScopeFilter) -> bool:
    """`passes_filters` over the stored columns with this level reading: the
    real gate, so the estimate cannot drift from it."""
    ann = Annotation(
        band=reading.band, confidence=reading.confidence, family=row.family,
        location_groups=list(row.location_groups or []), track=RoleTrack(row.track),
        domains=list(row.domains or []), basis=reading.basis,
    )
    return passes_filters(ann, scope)


async def backfill(apply: bool, company: str | None, batch: int = BATCH) -> dict:
    moves: Counter[tuple[str | None, str]] = Counter()
    basis_moves: Counter[tuple[str | None, str]] = Counter()
    by_company: Counter[str] = Counter()
    samples: list[dict] = []
    leaving = entering = 0
    async with session_scope() as session:
        scope = await load_scope_filter(session)
        scanned, pending = await pending_relevels(session, company=company)
        for item in pending:
            row, reading = item.row, item.reading
            was = _in_scope(row, stored_reading(row), scope)
            now = _in_scope(row, reading, scope)
            leaving += was and not now
            entering += now and not was
            if reading.basis.value != row.level_basis:
                basis_moves[(row.level_basis, reading.basis.value)] += 1
            if item.band_moved:
                moves[(row.level_band, reading.band.value)] += 1
                by_company[row.company] += 1
                if len(samples) < 20:
                    samples.append({
                        "id": row.id, "company": row.company, "title": row.title,
                        "move": f"{row.level_band} -> {reading.band.value}",
                        "scope": f"{was} -> {now}",
                    })
        await session.rollback()  # the derivation reads; writes go in batches below

    rescoped = 0
    if apply:
        changes = {change["id"]: change for change in level_changes(pending)}

        async def write(session, ids: list[int]) -> int:
            await set_job_levels(session, [changes[i] for i in ids])
            return len(ids)

        await commit_in_batches(list(changes), write, size=batch, label="level changes")
        async with session_scope() as session:
            rescoped = await recompute_saved_scope(session)

    return {
        "scanned": scanned, "band_changed": sum(moves.values()), "rescoped": rescoped,
        "leaving_scope": leaving, "entering_scope": entering,
        "moves": moves, "basis_moves": basis_moves, "by_company": by_company,
        "samples": samples, "applied": apply,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist (default: dry run)")
    parser.add_argument("--company", help="limit to one company slug")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = asyncio.run(backfill(args.apply, args.company))
    moves, by_company, samples = stats.pop("moves"), stats.pop("by_company"), stats.pop("samples")
    basis_moves = stats.pop("basis_moves")
    log.info("level band backfill: %s", stats)
    log.info("  by company: %s", by_company.most_common())
    for (old, new), count in moves.most_common():
        log.info("  %s -> %s: %d", old, new, count)
    for (old, new), count in basis_moves.most_common():
        log.info("  basis %s -> %s: %d", old, new, count)
    for s in samples:
        log.info("  #%s %s %s | scope %s | %s",
                 s["id"], s["company"], s["move"], s["scope"], s["title"][:60])
    if not stats["applied"] and (stats["band_changed"] or basis_moves):
        log.info("Dry run — nothing written. Re-run with --apply to persist.")


if __name__ == "__main__":
    main()
