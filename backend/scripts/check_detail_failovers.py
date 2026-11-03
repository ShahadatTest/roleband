"""Which detail readers miss a company's own page template?

A detail reader that fails over on one posting is a page that changed. One that
fails over, for the same reason, on many postings of one company is a reader
that does not know that company's template: a tenant on a shared source whose
pages it was never written for, or a template the company changed for every
posting at once. Each failover is a drift note on its own source run, where it
reads as one posting's quirk; only counted across runs does the pattern show.

This reads the failover notes of recent source runs and reports, per company,
connector and reason, how many distinct postings and runs they cover. A reason
that reaches `--min-postings` postings at one company is flagged: the reader
needs that company's wording or a reader of its own.

It also flags a posting noted in `--max-repeats` runs or more. A read the
pipeline stores is fresh for `description_refresh_days` and not fetched again
inside it, so the same posting failing over run after run is a read that is
never stored: it is fetched on every scan and its text stops moving.

    .venv/bin/python -m scripts.check_detail_failovers [--days 30] [--min-postings 5] [--max-repeats 4]

Reads the database; writes nothing. Exits 1 when anything is flagged.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from tracker.db.models import ScrapeSourceRun
from tracker.db.session import session_scope

#: The drift note `connectors.detail.structure_job_detail` records.
FAILOVER_MESSAGE = "job detail connector entered failover mode"


@dataclass
class Pattern:
    company: str
    connector: str
    reason: str
    notes: int = 0
    postings: set[str] = field(default_factory=set)
    runs: set[int] = field(default_factory=set)
    #: Distinct runs that noted each posting.
    seen_in: Counter[str] = field(default_factory=Counter)

    @property
    def repeats(self) -> int:
        """The most runs that noted any one posting."""
        return max(self.seen_in.values(), default=0)


def summarize(runs: Iterable[tuple[int, Iterable[Mapping]]]) -> list[Pattern]:
    """Failover notes grouped by company, connector and reason, widest first.

    `runs` is each source run's id with its drift notes. A note without a
    posting id still counts as a note, never as a posting."""
    patterns: dict[tuple[str, str, str], Pattern] = {}
    for run_id, notes in runs:
        noted: set[tuple[tuple[str, str, str], str]] = set()
        for note in notes:
            if not isinstance(note, Mapping) or note.get("message") != FAILOVER_MESSAGE:
                continue
            key = (
                str(note.get("company") or "?"),
                str(note.get("connector") or "?"),
                str(note.get("reason") or "?"),
            )
            pattern = patterns.setdefault(key, Pattern(*key))
            pattern.notes += 1
            pattern.runs.add(run_id)
            if note.get("req"):
                req = str(note["req"])
                pattern.postings.add(req)
                if (key, req) not in noted:
                    noted.add((key, req))
                    pattern.seen_in[req] += 1
    return sorted(patterns.values(), key=lambda p: (-len(p.postings), -p.notes, p.company))


def flagged(patterns: Iterable[Pattern], min_postings: int, max_repeats: int) -> list[Pattern]:
    return [
        pattern for pattern in patterns
        if len(pattern.postings) >= min_postings or pattern.repeats >= max_repeats
    ]


async def _read(days: int) -> list[tuple[int, list]]:
    since = datetime.now(UTC) - timedelta(days=days)
    async with session_scope() as session:
        rows = await session.execute(
            select(ScrapeSourceRun.run_id, ScrapeSourceRun.drift).where(
                ScrapeSourceRun.started_at >= since
            )
        )
        return [(run_id, drift or []) for run_id, drift in rows.all()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30, help="how far back to read source runs")
    ap.add_argument("--min-postings", type=int, default=5,
                    help="distinct postings of one company that flag a reason")
    ap.add_argument("--max-repeats", type=int, default=4,
                    help="runs noting one posting that flag a read that is never stored")
    args = ap.parse_args()

    patterns = summarize(asyncio.run(_read(args.days)))
    bad = flagged(patterns, args.min_postings, args.max_repeats)
    print(f"{'company':28} {'connector':12} {'postings':>8} {'notes':>6} {'runs':>5} {'repeats':>7}  reason")
    for pattern in patterns:
        mark = "!" if pattern in bad else " "
        print(
            f"{mark}{pattern.company:27} {pattern.connector:12} {len(pattern.postings):>8} "
            f"{pattern.notes:>6} {len(pattern.runs):>5} {pattern.repeats:>7}  {pattern.reason}"
        )
    if bad:
        print(
            f"\n{len(bad)} reader pattern(s) reach {args.min_postings} postings at one company "
            f"or {args.max_repeats} runs on one posting"
        )
        return 1
    print(f"\nno reason reaches {args.min_postings} postings or {args.max_repeats} repeats")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
