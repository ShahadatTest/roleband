"""Build shadow pay evidence from stored postings; no fetch or database write.

    .venv/bin/python -m scripts.build_posted_pay --as-of YYYY-MM-DD
    .venv/bin/python -m scripts.build_posted_pay --as-of YYYY-MM-DD --check

Named companies only. The table keeps title context, not a classified band.
Read-only against the database; writes only atlas/posted_pay.csv.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from scripts.data import OUT_HELP, build_target
from tracker.company_discovery import named_companies
from tracker.levels.atlas import POSTED_PAY, posted_pay_text
from tracker.pay_store.posted_pay import build
from tracker.platform.util import parse_datetime


async def _postings() -> list[dict]:
    from sqlalchemy import select

    from tracker.db.models import Job
    from tracker.db.session import session_scope

    cols = (Job.id, Job.req_id, Job.company, Job.title, Job.department, Job.team, Job.raw_level,
            Job.location_groups, Job.disclosed_base_min, Job.disclosed_base_max,
            Job.disclosed_currency, Job.disclosed_pay_basis, Job.disclosed_pay_period,
            Job.first_posted_at, Job.posted_at, Job.first_seen)
    async with session_scope() as session:
        rows = (await session.execute(select(*cols).where(
            Job.company.in_(named_companies()), Job.disclosed_base_min.is_not(None),
        ))).all()
    return [dict(r._mapping) for r in rows]


def evidence_rows(paths: list[Path]) -> list[dict]:
    """Reviewed employer captures (git-ignored); never fetches or writes jobs."""
    rows = []
    for path in paths:
        captured = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(captured, list):
            raise ValueError(f"{path}: expected a list of reviewed posting records")
        for row in captured:
            if not row.get("req_id") or not row.get("source_url") or not row.get("snippet"):
                raise ValueError(f"{path}: capture needs requisition, official URL and pay quote")
            row = dict(row)
            for name in ("first_posted_at", "posted_at", "first_seen"):
                row[name] = parse_datetime(row.get(name))
            rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="evidence read date, YYYY-MM-DD")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--evidence", type=Path, action="append", default=[],
                        help="reviewed employer posting JSON capture; repeatable, no network")
    parser.add_argument("--out", type=Path, help=OUT_HELP)
    args = parser.parse_args(argv)
    target = build_target("atlas", POSTED_PAY.file, args.out, args.check)
    from datetime import date

    date.fromisoformat(args.as_of)
    built = build([*evidence_rows(args.evidence), *asyncio.run(_postings())], named_companies(), args.as_of)
    text = posted_pay_text(built.rows)
    print(f"cells {len(built.rows):,}; postings {sum(r['n'] for r in built.rows):,}; "
          f"companies {len({r['company'] for r in built.rows})}")
    print("left out:", dict(sorted(built.dropped.items())))
    if args.check:
        unchanged = target.exists() and target.read_text(encoding="utf-8") == text
        print("unchanged" if unchanged else f"{target.name} would change")
        return 0 if unchanged else 1
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
