"""Backfill repost lineage over the existing corpus.

The historical data is the longitudinal asset — without a backfill the links only
start accruing from today, and you can't measure how big the double-counting was.
DRY RUN by default: nothing is written unless ``--apply`` is passed. Additive only —
writes link + lineage rows and the jobs.lineage_* projection; never touches
job_observations, job_lifecycle_events, first_seen, or status.

    python -m tracker.lineage.backfill --calibrate         # read-only cosine histogram
    python -m tracker.lineage.backfill                     # dry run: proposals + impact
    python -m tracker.lineage.backfill --company google -v
    python -m tracker.lineage.backfill --apply             # write links + projection
    python -m tracker.lineage.backfill --apply --auto-only # skip the suspected tier

Order matters: run --calibrate first, tune the lineage_* thresholds in config to the
distribution you actually see, THEN dry-run and read the impact report, THEN --apply.
Processes jobs first_seen ASC so chains form in order and the depth guard sees them grow.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select, text

from tracker.db.models import Job
from tracker.db.session import session_scope
from tracker.lineage.detect import (
    detect_lineage,
    fetch_candidates,
    rebuild_lineage_projection,
)

logger = logging.getLogger(__name__)

_DECILES = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]


def _percentiles(values: list[float]) -> dict[int, float]:
    if not values:
        return {}
    s = sorted(values)
    out = {}
    for p in _DECILES:
        idx = min(len(s) - 1, max(0, round((p / 100) * (len(s) - 1))))
        out[p] = round(s[idx], 3)
    return out


async def calibrate(company: str | None, limit: int | None) -> None:
    """Print the cosine distribution of gate-passing candidate pairs, split by
    whether the normalized titles are identical. Read-only."""
    async with session_scope() as session:
        q = select(Job).where(Job.embedding.isnot(None)).order_by(Job.first_seen.asc())
        if company:
            q = q.where(Job.company == company)
        if limit:
            q = q.limit(limit)
        jobs = list((await session.scalars(q)).all())

        eq: list[float] = []
        ne: list[float] = []
        for job in jobs:
            for sc in await fetch_candidates(session, job, k=10):
                (eq if sc.candidate.title_equal else ne).append(sc.candidate.cosine)

    print(f"calibrated over {len(jobs)} jobs "
          f"({'company=' + company if company else 'all companies'})")
    print(f"gate-passing candidate pairs: title-equal={len(eq)}  title-differ={len(ne)}")
    print(f"  title-equal cosine deciles : {_percentiles(eq)}")
    print(f"  title-differ cosine deciles: {_percentiles(ne)}")
    print("\nTune config: cos_title_equal below the low end of the title-equal spread;")
    print("cos_auto above the boilerplate ceiling of the title-differ spread.")


def _print_dry_run(summary: dict) -> None:
    proposals = summary.get("proposals") or []
    per_company: dict[str, dict[str, int]] = {}
    autos, rejects = [], []
    successors = 0
    for p in proposals:
        bucket = per_company.setdefault(p["company"], {"auto": 0, "suspected": 0, "reject": 0})
        chosen = p["chosen"]
        if chosen:
            successors += 1
        for c in chosen:
            bucket[c["decision"]] += 1
            if c["decision"] == "auto":
                autos.append((p, c))
        bucket["reject"] += len(p["rejected"])
        rejects.extend((p, r) for r in p["rejected"])

    print("=== DRY RUN (nothing written) ===")
    print(f"jobs processed: {summary['processed']}  auto: {summary['auto']}  "
          f"suspected: {summary['suspected']}")
    print("\nper company:")
    for co, b in sorted(per_company.items()):
        print(f"  {co:14s} auto={b['auto']:4d} suspected={b['suspected']:4d} rejected={b['reject']:5d}")

    autos.sort(key=lambda t: t[1]["cosine"], reverse=True)
    print(f"\ntop proposed AUTO links ({len(autos)} total):")
    for p, c in autos[:20]:
        print(f"  [{p['company']}] {c['prior_title'][:44]!r} -> {p['job_title'][:44]!r}  "
              f"cos={c['cosine']} {c['method']} rel={c['relation']} gap={c['gap_days']}d")

    rejects.sort(key=lambda t: t[1]["cosine"], reverse=True)
    print("\ntop REJECTED pairs by cosine (what the thresholds throw away):")
    for p, r in rejects[:10]:
        print(f"  [{p['company']}] {r['prior_title'][:44]!r} vs {p['job_title'][:44]!r}  "
              f"cos={r['cosine']}  ({r['reason']})")

    print("\n=== projected impact ===")
    print(f"  {summary['auto']} opened events would reclassify new -> repost/duplicate")
    print(f"  {successors} distinct jobs become lineage successors")
    print("  (historical demand_metrics rows are NOT rewritten; the shift starts at apply time)")


async def run(*, company: str | None, apply: bool, auto_only: bool,
              limit: int | None, force: bool) -> None:
    async with session_scope() as session:
        if force:
            stmt = text("UPDATE jobs SET lineage_checked_at = NULL")
            if company:
                stmt = text("UPDATE jobs SET lineage_checked_at = NULL WHERE company = :c")
                await session.execute(stmt, {"c": company})
            else:
                await session.execute(stmt)
            await session.commit()

        companies = {company} if company else None
        summary = await detect_lineage(
            session, None, companies=companies, cap=limit,
            dry_run=not apply, auto_only=auto_only,
        )
        if not apply:
            _print_dry_run(summary)
            return

        n = await rebuild_lineage_projection(session)
        await session.commit()
        print("=== APPLIED ===")
        print({**{k: v for k, v in summary.items() if k != "proposals"}, "lineages": n})


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill repost lineage detection.")
    parser.add_argument("--calibrate", action="store_true",
                        help="read-only: print the cosine distribution and exit")
    parser.add_argument("--apply", action="store_true",
                        help="write links + projection (default is a dry run)")
    parser.add_argument("--auto-only", action="store_true",
                        help="persist only auto links; skip the suspected review tier")
    parser.add_argument("--company", type=str, default=None, help="restrict to one company slug")
    parser.add_argument("--limit", type=int, default=None, help="cap jobs processed")
    parser.add_argument("--force", action="store_true",
                        help="null lineage_checked_at first so every job is re-detected")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    if args.calibrate:
        asyncio.run(calibrate(args.company, args.limit))
        return
    asyncio.run(run(company=args.company, apply=args.apply, auto_only=args.auto_only,
                    limit=args.limit, force=args.force))


if __name__ == "__main__":
    main()
