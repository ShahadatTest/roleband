"""Bench the track classifier against the live catalog.

Read-only. Replays `classify_track` over every catalog example title and every
stored job, and reports what the current rule files differently from the older
one ("manager" anywhere = leadership): moves per family and track,
and samples each way so a reviewer reads the titles, not only the counts.

The labelled contract (IC managers leave, people managers stay) is pytest
(`tests/test_track.py`); this measures the reach on real data.

    .venv/bin/python -m scripts.bench_track_classifier [--samples 8]
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict

from sqlalchemy import text

from tracker.db.session import get_engine
from tracker.enrich.track import classify_track
from tracker.schema import RoleTrack

_OLD_MGMT = ("manager", "director", "head of", "vp ", "vice president", "svp", "evp")


def _before(title: str, family: str | None) -> RoleTrack:
    """The older rule, only where it differs: "manager" alone was leadership."""
    hay = f" {title.lower().strip()} "
    if family not in ("product_management", "program_management", "technical_program_management",
                      "engineering_management") and any(w in hay for w in _OLD_MGMT):
        return RoleTrack.MANAGEMENT
    return classify_track(title, family)


def _title(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("title", ""))
    return str(item)


async def bench(samples: int) -> None:
    async with get_engine().connect() as con:
        catalog = (await con.execute(text("select role_group, examples from role_catalog"))).all()
        jobs = (await con.execute(text("select title, family, status from jobs"))).all()
    sets = {
        "catalog examples": [(_title(i), fam) for fam, ex in catalog for i in ex or []],
        "open jobs": [(t, f) for t, f, s in jobs if s == "open"],
    }
    for name, rows in sets.items():
        moves: Counter[tuple[str, str, str | None]] = Counter()
        seen: dict[tuple[str, str], list[str]] = defaultdict(list)
        mgmt_before = mgmt_after = 0
        for title, family in rows:
            old, new = _before(title, family), classify_track(title, family)
            mgmt_before += old == RoleTrack.MANAGEMENT
            mgmt_after += new == RoleTrack.MANAGEMENT
            if old != new:
                moves[(old.value, new.value, family)] += 1
                if len(seen[(old.value, new.value)]) < samples:
                    seen[(old.value, new.value)].append(title)
        print(f"\n== {name}: {len(rows)} titles; leadership {mgmt_before} -> {mgmt_after}")
        for (old, new, family), count in moves.most_common():
            print(f"  {count:5}  {old} -> {new}  [{family}]")
        for (old, new), titles in seen.items():
            print(f"  e.g. {old} -> {new}: " + "; ".join(titles))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", type=int, default=8)
    asyncio.run(bench(parser.parse_args().samples))


if __name__ == "__main__":
    main()
