"""What the pay-period rule changes, before any row is rewritten.

Read-only. For every open posting with a stated band it reports three things:

- STORED: `disclosed_*` as the stored rows hold them;
- SHOWN: what the screen serves with no row rewritten
  (`pay_period.effective_period`, the read-time guard);
- RE-READ: what the current parser stores when it next reads the posting's own
  pay text (`extract_grounded_band` over `pay_input_text`, the pass's input).

The transition table (stored -> re-read) is what a reviewer reads before the
stored labels are corrected; rows are listed per transition with samples.

NEGATIVE CONTROL. Stored bands that are already right (stored `year`, a
salary-sized amount, and a period word next to it or none at all) must come
back unchanged. If more than `CONTROL_TOLERANCE` of them change, the parser
is breaking good rows and the run exits 1.

    python -m scripts.bench_pay_period
    python -m scripts.bench_pay_period --samples 8 --company netflix
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import sys
from dataclasses import dataclass

from sqlalchemy import select

from tracker.db.models import Job
from tracker.db.session import session_scope
from tracker.intelligence_runtime.disclosed_comp import pay_input_text
from tracker.pay_disclosure import extract_grounded_band
from tracker.pay_period import PayPeriod, effective_period, size_class

#: Share of already-correct bands the parser may change before the run fails.
CONTROL_TOLERANCE = 0.01


@dataclass(frozen=True)
class Row:
    job_id: int
    company: str
    stored: tuple[int | None, int | None, str | None, str | None]
    shown: str
    reread: tuple[int | None, int | None, str | None, str | None] | None
    snippet: str
    #: No stored text to read again (a band kept from an earlier read of a
    #: posting whose description is gone). Such a row is never re-derived by
    #: the pass either, so it is reported apart and is no evidence.
    readable: bool = True

    @property
    def transition(self) -> str:
        old = self.stored[3] or "none"
        if not self.readable:
            return f"{old} (no text to re-read)"
        if self.reread is None:
            return f"{old} -> no band"
        new = self.reread[3] or "none"
        moved = " (amount changed)" if self.reread[:2] != self.stored[:2] else ""
        return f"{old} -> {new}{moved}"

    @property
    def is_control(self) -> bool:
        low, high, currency, period = self.stored
        return (
            self.readable
            and period == "year"
            and size_class(low, high, currency) is PayPeriod.year
        )


async def load(company: str | None) -> list[Row]:
    rows: list[Row] = []
    async with session_scope() as session:
        query = select(Job).where(Job.status == "open", Job.disclosed_base_min.isnot(None))
        if company:
            query = query.where(Job.company == company)
        for job in (await session.scalars(query)).all():
            pay_text, _source = pay_input_text(job)
            readable = bool((pay_text or "").strip())
            band = extract_grounded_band(pay_text, job.description_text or pay_text)
            stored = (job.disclosed_base_min, job.disclosed_base_max,
                      job.disclosed_currency, job.disclosed_pay_period)
            rows.append(Row(
                job_id=job.id,
                company=job.company,
                stored=stored,
                shown=effective_period(*stored[3:], *stored[:3]),
                reread=(band.base_min, band.base_max, band.currency, band.pay_period.value)
                if band.disclosed else None,
                snippet=(job.disclosed_snippet or "")[:110],
                readable=readable,
            ))
    return rows


def render(rows: list[Row], samples: int) -> int:
    print(f"Open postings with a stated band: {len(rows)}\n")

    print("1. What the screen shows the moment this lands (no row rewritten)")
    shown = collections.Counter((r.stored[3], r.shown) for r in rows)
    for (old, new), n in sorted(shown.items(), key=lambda x: -x[1]):
        mark = "" if old == new else "   <- changes on screen"
        print(f"   stored {old or 'none':8} shown {new:8} {n:5}{mark}")

    print("\n2. What re-reading each posting with the new rule would store")
    by = collections.defaultdict(list)
    for r in rows:
        by[r.transition].append(r)
    for transition, members in sorted(by.items(), key=lambda x: -len(x[1])):
        companies = collections.Counter(r.company for r in members).most_common(4)
        print(f"   {transition:36} {len(members):5}   {', '.join(f'{c} {n}' for c, n in companies)}")

    print("\n3. Samples of every change")
    for transition, members in sorted(by.items(), key=lambda x: -len(x[1])):
        if transition in ("year -> year", "hour -> hour", "month -> month") or "no text" in transition:
            continue
        print(f"\n   {transition}")
        for r in members[:samples]:
            new = "no band" if r.reread is None else f"{r.reread[0]}-{r.reread[1]} {r.reread[2]} {r.reread[3]}"
            print(f"     #{r.job_id} {r.company:14} {r.stored[0]}-{r.stored[1]} {r.stored[2]} -> {new}")
            print(f"        \"{r.snippet}\"")

    controls = [r for r in rows if r.is_control]
    broken = [r for r in controls if r.reread is None or r.reread != r.stored]
    rate = len(broken) / len(controls) if controls else 0.0
    print(f"\n4. Control: {len(controls)} bands already right (stored year, salary-sized); "
          f"{len(broken)} change ({rate:.1%}, tolerance {CONTROL_TOLERANCE:.0%})")
    for r in broken[:samples]:
        new = "no band" if r.reread is None else f"{r.reread}"
        print(f"     #{r.job_id} {r.company:14} {r.stored} -> {new}  \"{r.snippet[:70]}\"")
    if rate > CONTROL_TOLERANCE:
        print("\nFAIL: the new parser changes too many bands the old rule already had right.")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", type=int, default=5, help="rows printed per transition")
    parser.add_argument("--company", help="limit to one company slug")
    args = parser.parse_args()
    return render(asyncio.run(load(args.company)), args.samples)


if __name__ == "__main__":
    sys.exit(main())
