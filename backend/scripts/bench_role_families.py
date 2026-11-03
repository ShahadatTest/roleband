"""What a role-family classifier change moves, across every stored title.

Read-only. Re-classifies each stored job with the current `classify_family` and
reports every row whose family would change, grouped as (stored -> now) with
examples. Stored families are current (the `roles_backfill` post pass keeps
them so), so the report is exactly what landing the change will move. A
change that only files unsorted titles moves nothing here; any
family-to-family move is a regression until read and accepted.

    .venv/bin/python -m scripts.bench_role_families [--examples 6]
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict

from sqlalchemy import select

from tracker.db.models import Job
from tracker.db.session import session_scope
from tracker.enrich.classify import classify_family
from tracker.schema import RawJob


async def moves(examples: int) -> tuple[int, Counter, dict]:
    async with session_scope() as session:
        rows = (await session.execute(
            select(Job.company, Job.req_id, Job.title, Job.url, Job.department, Job.team, Job.family)
        )).all()
    counts: Counter = Counter()
    samples: dict = defaultdict(list)
    for row in rows:
        now = classify_family(RawJob(
            company=row.company, req_id=row.req_id, title=row.title, url=row.url or "",
            department=row.department, team=row.team,
        ))
        if now != row.family:
            counts[(row.family, now)] += 1
            if len(samples[(row.family, now)]) < examples:
                samples[(row.family, now)].append(f"{row.company}: {row.title}")
    return len(rows), counts, samples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--examples", type=int, default=6)
    args = parser.parse_args()
    total, counts, samples = asyncio.run(moves(args.examples))
    print(f"{total} stored jobs, {sum(counts.values())} would change family")
    for (before, after), n in counts.most_common():
        print(f"{n:5}  {before} -> {after}")
        for line in samples[(before, after)]:
            print(f"         {line}")


if __name__ == "__main__":
    main()
