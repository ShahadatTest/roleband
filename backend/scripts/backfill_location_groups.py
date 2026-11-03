"""Backfill `jobs.location_groups` from the stored raw `locations` strings.

Recomputes the coarse scope-group tags (metro + country) via
tracker/enrich/classify.py::location_groups_for. Idempotent: writes only rows
whose value would change. Never touches any other column: `in_scope` is left
to the pipeline/scope-gate, and the enabled set is unchanged, so a row keeps its
scope membership as long as its enabled-group tags are preserved.

Dry-run by default: reports what would change AND flags any row that would LOSE an
enabled location-group tag (a scope regression) without writing. Pass --apply to
persist.

Run from backend/:
    .venv/bin/python -m scripts.backfill_location_groups            # dry run
    .venv/bin/python -m scripts.backfill_location_groups --apply    # write
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

from tracker.db.models import Job
from tracker.db.session import session_scope
from tracker.enrich.classify import location_slugs_for
from tracker.taxonomy.locations import default_enabled_location_groups

log = logging.getLogger(__name__)
BATCH = 500


async def backfill(apply: bool) -> dict:
    enabled = set(default_enabled_location_groups())
    scanned = changed = written = 0
    # A regression = a row losing a tag that is CURRENTLY enabled (would drop it
    # from scope). Recompute uses the *shipped* enabled set as the yardstick.
    regressions: list[dict] = []
    async with session_scope() as session:
        jobs = (await session.scalars(select(Job))).all()
        for job in jobs:
            scanned += 1
            old = list(job.location_groups or [])
            new = location_slugs_for(job.locations or [])
            if old == new:
                continue
            changed += 1
            lost_enabled = (set(old) & enabled) - set(new)
            if lost_enabled:
                regressions.append(
                    {"id": job.id, "company": job.company, "locations": job.locations,
                     "old": old, "new": new, "lost_enabled": sorted(lost_enabled)}
                )
            if apply:
                job.location_groups = new
                written += 1
                if written % BATCH == 0:
                    await session.commit()
        if apply:
            await session.commit()
        else:
            await session.rollback()
    return {
        "scanned": scanned,
        "changed": changed,
        "written": written,
        "regressions": regressions,
        "applied": apply,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist changes (default: dry run)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = asyncio.run(backfill(args.apply))
    regs = stats.pop("regressions")
    log.info("location_groups backfill: %s", stats)
    if regs:
        log.warning("SCOPE REGRESSIONS (%d rows would lose an enabled tag):", len(regs))
        for r in regs[:20]:
            log.warning("  #%s %s %s: %s -> %s (lost %s)",
                        r["id"], r["company"], r["locations"], r["old"], r["new"], r["lost_enabled"])
        if not stats["applied"]:
            log.warning("Refusing nothing — this was a dry run. Investigate before --apply.")
    else:
        log.info("No scope regressions: every row keeps its enabled-group tags.")


if __name__ == "__main__":
    main()
