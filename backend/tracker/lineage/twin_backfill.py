"""Dry-run or apply twin proposals across the existing corpus.

No posting dates participate in candidate selection or scoring. Reviewed twin
decisions are immutable to this detector; rejected duplicate proposals remain
eligible because they are a separate artifact.

    python -m tracker.lineage.twin_backfill
    python -m tracker.lineage.twin_backfill --company amazon --limit 500
    python -m tracker.lineage.twin_backfill --apply
"""

from __future__ import annotations

import argparse
import asyncio

from tracker.db.session import session_scope
from tracker.lineage.twins import detect_twins


def _print(summary: dict) -> None:
    proposals = summary.get("proposals") or []
    print("=== TWIN DRY RUN (nothing written) ===")
    print(f"jobs processed: {summary['processed']}  suspected: {summary['suspected']}")
    for proposal in proposals[:100]:
        print(
            f"  {proposal['job_a_id']} ↔ {proposal['job_b_id']}  "
            f"cos={proposal['cosine']:.4f} title={proposal['title_similarity']:.4f}  "
            f"{proposal['left_title']!r} / {proposal['right_title']!r}"
        )
        for reason in proposal["reasons"]:
            print(f"    - {reason}")
    if len(proposals) > 100:
        print(f"  ... {len(proposals) - 100} more")


async def run(*, company: str | None, limit: int | None, apply: bool) -> None:
    async with session_scope() as session:
        summary = await detect_twins(
            session,
            None,
            companies={company} if company else None,
            cap=limit,
            dry_run=not apply,
            stale_only=False,
        )
        if apply:
            print("=== TWIN PROPOSALS APPLIED ===")
            print({key: value for key, value in summary.items() if key != "proposals"})
        else:
            _print(summary)


_DECILES = (1, 2, 5, 10, 25, 50, 75, 90, 95, 98, 99)


def _pct(values: list[float]) -> dict[int, float]:
    if not values:
        return {}
    ordered = sorted(values)
    return {
        p: round(ordered[min(len(ordered) - 1, max(0, round((p / 100) * (len(ordered) - 1))))], 3)
        for p in _DECILES
    }


async def calibrate(company: str | None, limit: int | None) -> None:
    """Print the cosine distribution of pairs that reach the twin cosine test.

    Read-only. Mirrors `fetch_twin_candidates` and applies exactly the gates
    that run BEFORE `twin_cos_floor` (family/band come from the SQL; lineage,
    grade and department from the pure rules), then splits by title evidence:

      identical  — normalized display titles equal: near-certain twins, the
                   population a floor must KEEP.
      near       — title jaccard in [twin_title_jaccard_min, 1): the ambiguous
                   band the cosine floor actually adjudicates.
      different  — title jaccard below the gate: same company/family/band but a
                   different role. The negative control a floor must EXCLUDE.

    Reported on two independent half-samples (job-id parity) because a
    threshold that only holds on one sample is a coincidence.
    """
    from sqlalchemy import select

    from tracker.config import get_settings
    from tracker.db.models import Job
    from tracker.lineage.normalize import normalize_title, title_grade, title_jaccard, title_key
    from tracker.lineage.twins import _neighbor_rows, department_relation

    settings = get_settings()
    buckets: dict[str, dict[str, list[float]]] = {
        name: {"A": [], "B": []} for name in ("identical", "near", "different")
    }

    async with session_scope() as session:
        q = select(Job).where(Job.embedding.isnot(None)).order_by(Job.id.asc())
        if company:
            q = q.where(Job.company == company)
        if limit:
            q = q.limit(limit)
        jobs = list((await session.scalars(q)).all())

        for job in jobs:
            half = "A" if job.id % 2 == 0 else "B"
            job_key = title_key(job.title, job.locations or [])
            job_display = normalize_title(job.title, job.locations or [])
            job_grade = title_grade(job.title, job.locations or [])
            for row in await _neighbor_rows(session, job, k=10):
                other_grade = title_grade(row.title, row.locations or [])
                # Gates that precede the cosine test, in production order.
                if job.lineage_id is not None and row.lineage_id == job.lineage_id:
                    continue
                if not (job_grade is None or other_grade is None or job_grade == other_grade):
                    continue
                if department_relation(job.department, row.department) == "mismatch":
                    continue
                sim = title_jaccard(job_key, title_key(row.title, row.locations or []))
                equal = bool(job_display) and job_display == normalize_title(
                    row.title, row.locations or []
                )
                name = (
                    "identical" if equal
                    else "near" if sim >= settings.twin_title_jaccard_min
                    else "different"
                )
                buckets[name][half].append(float(row.cosine))

    print(f"calibrated over {len(jobs)} jobs "
          f"({'company=' + company if company else 'all companies'})")
    print(f"current: twin_cos_floor={settings.twin_cos_floor} "
          f"title_jaccard_min={settings.twin_title_jaccard_min} "
          f"text_jaccard_min={settings.twin_text_jaccard_min}\n")
    for name in ("identical", "near", "different"):
        for half in ("A", "B"):
            values = buckets[name][half]
            print(f"  {name:9} half-{half}  n={len(values):6}  {_pct(values)}")
        print()
    print("Set twin_cos_floor ABOVE the 'different' high percentiles (it must reject a")
    print("different role) and BELOW the 'identical' low percentiles (it must keep a real")
    print("twin) — and require both half-samples to agree.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill twin-opportunity proposals.")
    parser.add_argument("--calibrate", action="store_true",
                        help="read-only: print the cosine distribution by title evidence and exit")
    parser.add_argument("--apply", action="store_true", help="write pending proposals")
    parser.add_argument("--company", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    if args.calibrate:
        asyncio.run(calibrate(args.company, args.limit))
        return
    asyncio.run(run(company=args.company, limit=args.limit, apply=args.apply))


if __name__ == "__main__":
    main()
