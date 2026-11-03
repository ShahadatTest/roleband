"""Is the posting inventory ready to count the scope screens?

Per followed company, the stored catalog's cells (`role_catalog`) against the
cells the inventory builds (`scope.inventory_joint`), every city kept, learned
exclusions NOT applied (the stored catalog never applied them). Two answers:

- coverage: how many followed companies have a complete inventory read. The
  switch (`scope_counts_source = "inventory"`) waits for all of them;
- agreement: a difference is a DEFECT only when both sides were written by the
  same reconcile (`role_catalog_scanned_at` within 60 s of the complete read).
  With different reads it is expected: the inventory also keeps what later
  probes and counts read.

A benchmark that cannot fail measures nothing: `--plant` adds one
cell to the inventory side of the first comparable company, in memory, and
the run exits 0 only if that shows up as a defect.

Read-only. Exit 1 on any defect (or a plant that went unseen), else 0.

    python -m scripts.bench_inventory_joint
    python -m scripts.bench_inventory_joint --plant
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select

from tracker.company_store import get_tracked_companies, off_board_company_slugs
from tracker.db.models import RoleCatalog
from tracker.db.session import session_scope
from tracker.scope.inventory_joint import complete_reads, inventory_counts

#: How far apart the catalog's write and the complete read may be and still
#: be the same reconcile: both are written in one company's finalize.
SAME_READ = timedelta(seconds=60)

CellKey = tuple[str, str, str, tuple[str, ...], tuple[str, ...]]


def cells_of(entries: Iterable) -> Counter[CellKey]:
    """One company's cells, keyed by every coordinate, from catalog rows or
    inventory entries alike."""
    out: Counter[CellKey] = Counter()
    for entry in entries:
        for cell in entry.scope_cells or []:
            key = (
                entry.role_group, cell["band"], cell["track"],
                tuple(cell["locations"]), tuple(cell["domains"]),
            )
            out[key] += int(cell["count"])
    return out


@dataclass(frozen=True)
class Verdict:
    company: str
    #: equal | defect | expected | no_complete_read | no_catalog
    state: str
    differing: int = 0


def judge(
    company: str, catalog: Counter[CellKey], inventory: Counter[CellKey],
    catalog_at: datetime | None, complete_at: datetime | None,
) -> Verdict:
    if complete_at is None:
        return Verdict(company, "no_complete_read")
    if catalog_at is None:
        return Verdict(company, "no_catalog")
    differing = sum(1 for key in catalog.keys() | inventory.keys() if catalog[key] != inventory[key])
    if differing == 0:
        return Verdict(company, "equal")
    same_read = abs(catalog_at - complete_at) <= SAME_READ
    return Verdict(company, "defect" if same_read else "expected", differing)


async def _run(plant: bool) -> int:
    async with session_scope() as session:
        tracked = await get_tracked_companies(session)
        hidden = await off_board_company_slugs(session)
        followed = [row for row in tracked if row.enabled and row.status == "active" and row.slug not in hidden]
        complete = await complete_reads(session, [row.slug for row in followed])
        inventory = await inventory_counts(session, tracked, hidden, apply_exclusions=False)
        stored = (await session.scalars(select(RoleCatalog))).all()

    verdicts = []
    planted = None
    for row in followed:
        catalog_cells = cells_of(entry for entry in stored if entry.company == row.slug)
        inventory_cells = cells_of(entry for entry in inventory.entries if entry.company == row.slug)
        verdict = judge(row.slug, catalog_cells, inventory_cells, row.role_catalog_scanned_at, complete.get(row.slug))
        if plant and planted is None and verdict.state == "equal":
            inventory_cells[("planted", "staff", "technical", ("uk",), ())] += 1
            verdict = judge(row.slug, catalog_cells, inventory_cells, row.role_catalog_scanned_at, complete[row.slug])
            planted = verdict
        verdicts.append(verdict)

    states = Counter(verdict.state for verdict in verdicts)
    print(f"coverage: {len(complete)} of {len(followed)} followed companies have a complete inventory read")
    print("verdicts: " + ", ".join(f"{state}={count}" for state, count in sorted(states.items())))
    for verdict in verdicts:
        if verdict.state in {"defect", "expected"}:
            print(f"  {verdict.company}: {verdict.state}, {verdict.differing} cells differ")
    if plant:
        if planted is None:
            print("plant: no comparable company to plant in; the control could not run")
            return 1
        seen = planted.state == "defect"
        print(f"plant: planted in {planted.company}, {'reported' if seen else 'NOT reported'}")
        return 0 if seen else 1
    return 1 if states["defect"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plant", action="store_true", help="negative control: plant one cell")
    return asyncio.run(_run(parser.parse_args(argv).plant))


if __name__ == "__main__":
    sys.exit(main())
