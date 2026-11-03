"""What is each catalog company worth, and what does it cost?

    .venv/bin/python -m scripts.company_fact_sheet            # table
    .venv/bin/python -m scripts.company_fact_sheet --json     # the same rows
    .venv/bin/python -m scripts.company_fact_sheet --sector faang

Curated membership, which companies a fresh install follows before anyone has
chosen anything, is a maintainer's decision. It needs one sheet per company
rather than five screens, so this REPORTS and changes nothing: no writes, no
flags, no roster edits. A maintainer reads it and decides which rule to apply.

Per company it answers, in this order, because that is the order the decision
asks them in:

* **can we collect it at all** — the connector state (`live`, `ready`,
  `family`, `planned`, `parked`) and the provider;
* **may we, without asking** — walled or not (a walled company is never
  curated: it is collected only after the user follows it);
* **what does it put on the radar** — open in-scope postings we hold today;
* **what does it cost** — the median whole-scan time, absent when never
  measured (never read as zero — an unscanned company is not instant);
* **where does it sit** — its sectors, and whether it is curated TODAY.

The counts are of what we HOLD, not what the board has: a company that is
`ready` but never enabled reads 0 postings and no scan time, which is exactly
the question the sheet serves: whether to turn it on. So every discovery
company is listed, tracked or not.

Read-only; safe against the live database.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.company_discovery import (
    COMPANY_DISCOVERY,
    SECTORS,
    collecting_provider,
    company_wall,
    connector_state,
    is_curated,
)
from tracker.company_store import get_tracked_companies
from tracker.db.queries.companies import open_counts_by_company, scan_seconds_by_company
from tracker.db.session import session_scope


async def fact_sheet(sector: str | None = None) -> list[dict]:
    """One row per discovery company, over the app's own database."""
    async with session_scope() as session:
        return await collect(session, sector)


async def collect(session: AsyncSession, sector: str | None = None) -> list[dict]:
    """The sheet, from a session the caller owns; sorted by radar postings."""
    tracked = {row.slug: row for row in await get_tracked_companies(session)}
    counts = await open_counts_by_company(session)
    seconds = await scan_seconds_by_company(session)

    rows: list[dict] = []
    for slug, company in COMPANY_DISCOVERY.items():
        if sector and sector not in company.sectors:
            continue
        row = tracked.get(slug)
        wall = company_wall(slug, row)
        rows.append({
            "slug": slug,
            "display": company.display,
            "sectors": list(company.sectors),
            "state": connector_state(slug, row),
            # However it is known: the stored row, else the catalog's declaration
            # — the same rule the wall gate resolves a company through.
            "provider": collecting_provider(slug, row),
            "walled": wall.provider if wall is not None else None,
            "tracked": row is not None and row.status == "active",
            "curated": is_curated(slug, row),
            "radar_open": counts.get(slug, 0),
            # None, never 0: a company nobody scanned has no measured duration.
            "scan_seconds": seconds.get(slug),
        })
    rows.sort(key=lambda r: (-r["radar_open"], r["display"].lower()))
    return rows


def render(rows: list[dict]) -> str:
    head = f"{'company':24} {'state':8} {'provider':16} {'radar':>6} {'scan':>8}  {'flags':22} sectors"
    lines = [head, "-" * len(head)]
    for row in rows:
        flags = " ".join(filter(None, (
            "curated" if row["curated"] else "",
            "tracked" if row["tracked"] and not row["curated"] else "",
            f"walled:{row['walled']}" if row["walled"] else "",
        )))
        scan = f"{row['scan_seconds']:.0f}s" if row["scan_seconds"] is not None else "-"
        lines.append(
            f"{row['display'][:24]:24} {row['state']:8} {(row['provider'] or '-')[:16]:16}"
            f" {row['radar_open']:>6} {scan:>8}  {flags[:22]:22} {','.join(row['sectors'])}"
        )
    curated = sum(1 for r in rows if r["curated"])
    measured = [r for r in rows if r["scan_seconds"] is not None]
    total = sum(r["scan_seconds"] for r in measured)
    lines += [
        "-" * len(head),
        f"{len(rows)} companies, {curated} curated, {sum(r['radar_open'] for r in rows)} open in-scope postings",
        f"scan time measured for {len(measured)}; those together take {total / 60:.0f} min per full round",
        "unmeasured companies are NOT instant — they have never been scanned",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--json", action="store_true", help="emit the rows as JSON")
    parser.add_argument("--sector", choices=[s.slug for s in SECTORS], help="one sector only")
    args = parser.parse_args()

    rows = asyncio.run(fact_sheet(args.sector))
    print(json.dumps(rows, indent=2) if args.json else render(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
