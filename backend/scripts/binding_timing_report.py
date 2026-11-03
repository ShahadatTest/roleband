"""How long does each source binding take, and how close is it to its budget?

    .venv/bin/python -m scripts.binding_timing_report                  # slowest first
    .venv/bin/python -m scripts.binding_timing_report --provider eightfold
    .venv/bin/python -m scripts.binding_timing_report --days 14 --json

The measurement to take BEFORE any ordering, pacing or budget change for a
large board: a per-binding budget raise, lower pacing for a family, or a
timestamp-sorted first sweep are global or per-family changes that must be
justified by the tenants we already collect, not by one board that overran.

Per binding (company, provider) over `scrape_source_runs` in the window:

* runs and their outcomes (`ok`, `lossy`, `bounded`, ...);
* whole-source duration p50 / p95 / max, from `started_at`..`finished_at`;
* postings scanned (p50) and seconds per scanned posting (p50), the rate that
  projects an unmeasured board of known size;
* the budget that bounds it: the learned `source_binding_tuning` row `*`
  when one exists, else `scraper_source_budget_seconds`; and headroom = budget
  minus p95. Negative headroom, or any `bounded` run, is the list to read.

Durations are wall time and include pacing, retries and hydration; a
discovery-mode run hydrates less than a reconcile run, so both are shown mixed
and the mode split is in `--json`. Read-only; safe against the live database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from statistics import median


@dataclass(frozen=True)
class SourceRun:
    company: str
    provider: str
    scan_mode: str
    outcome: str
    seconds: float
    scanned: int


@dataclass(frozen=True)
class BindingTiming:
    company: str
    provider: str
    runs: int
    outcomes: dict[str, int]
    modes: dict[str, int]
    p50_seconds: float
    p95_seconds: float
    max_seconds: float
    scanned_p50: float
    seconds_per_posting_p50: float | None
    budget_seconds: float
    budget_learned: bool
    headroom_seconds: float

    @property
    def at_risk(self) -> bool:
        """Our budget already fired, or the slow tail does not fit under it."""
        return self.outcomes.get("bounded", 0) > 0 or self.headroom_seconds < 0


def _p95(values: list[float]) -> float:
    """Nearest-rank p95: with fewer than 20 runs it is the maximum, never an
    interpolation below a duration that really happened."""
    ordered = sorted(values)
    rank = max(1, -(-95 * len(ordered) // 100))
    return ordered[rank - 1]


def summarize(
    runs: Iterable[SourceRun],
    learned_budgets: Mapping[tuple[str, str], float],
    default_budget: float,
) -> list[BindingTiming]:
    """One row per binding, most at-risk first, then slowest p95."""
    grouped: dict[tuple[str, str], list[SourceRun]] = {}
    for run in runs:
        grouped.setdefault((run.company, run.provider), []).append(run)
    rows: list[BindingTiming] = []
    for (company, provider), group in grouped.items():
        seconds = [r.seconds for r in group]
        rates = [r.seconds / r.scanned for r in group if r.scanned > 0]
        outcomes: dict[str, int] = {}
        modes: dict[str, int] = {}
        for r in group:
            outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1
            modes[r.scan_mode] = modes.get(r.scan_mode, 0) + 1
        learned = learned_budgets.get((company, provider))
        budget = learned if learned is not None else default_budget
        p95 = _p95(seconds)
        rows.append(BindingTiming(
            company=company, provider=provider, runs=len(group),
            outcomes=dict(sorted(outcomes.items())), modes=dict(sorted(modes.items())),
            p50_seconds=round(median(seconds), 1), p95_seconds=round(p95, 1),
            max_seconds=round(max(seconds), 1),
            scanned_p50=median(r.scanned for r in group),
            seconds_per_posting_p50=round(median(rates), 3) if rates else None,
            budget_seconds=budget, budget_learned=learned is not None,
            headroom_seconds=round(budget - p95, 1),
        ))
    rows.sort(key=lambda row: (not row.at_risk, -row.p95_seconds))
    return rows


async def load(days: int, provider: str | None) -> tuple[list[SourceRun], dict[tuple[str, str], float]]:
    from sqlalchemy import select

    from tracker.db.models import ScrapeSourceRun, SourceBinding, SourceBindingTuning
    from tracker.db.session import session_scope

    since = datetime.now(UTC) - timedelta(days=days)
    async with session_scope() as session:
        query = select(ScrapeSourceRun).where(ScrapeSourceRun.started_at >= since)
        if provider:
            query = query.where(ScrapeSourceRun.provider_key == provider)
        runs = [
            SourceRun(
                company=r.company_slug, provider=r.provider_key, scan_mode=r.scan_mode,
                outcome=r.outcome, seconds=(r.finished_at - r.started_at).total_seconds(),
                scanned=r.scanned,
            )
            for r in (await session.scalars(query)).all()
        ]
        learned = {
            (slug, connector): budget
            for slug, connector, budget in (await session.execute(
                select(SourceBinding.company_slug, SourceBinding.connector_id,
                       SourceBindingTuning.tuned_budget_seconds)
                .join(SourceBindingTuning, SourceBindingTuning.binding_id == SourceBinding.id)
                .where(SourceBindingTuning.query_key == "*",
                       SourceBindingTuning.tuned_budget_seconds.is_not(None))
            )).all()
        }
    return runs, learned


def _table(rows: list[BindingTiming]) -> str:
    head = f"{'company':32} {'provider':20} {'runs':>4} {'p50 s':>7} {'p95 s':>7} {'max s':>7} " \
           f"{'scanned':>7} {'s/post':>7} {'budget':>8} {'headroom':>8}  outcomes"
    lines = [head, "-" * len(head)]
    for r in rows:
        rate = f"{r.seconds_per_posting_p50:.3f}" if r.seconds_per_posting_p50 is not None else "-"
        budget = f"{r.budget_seconds:.0f}{'*' if r.budget_learned else ''}"
        flag = "  !" if r.at_risk else ""
        outcomes = " ".join(f"{k}={v}" for k, v in r.outcomes.items())
        lines.append(
            f"{r.company[:32]:32} {r.provider[:20]:20} {r.runs:>4} {r.p50_seconds:>7.1f} "
            f"{r.p95_seconds:>7.1f} {r.max_seconds:>7.1f} {r.scanned_p50:>7.0f} {rate:>7} "
            f"{budget:>8} {r.headroom_seconds:>8.1f}  {outcomes}{flag}"
        )
    lines.append("budget* = learned per binding; ! = a bounded run, or p95 over budget")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=30, help="window of runs (default 30)")
    parser.add_argument("--provider", default=None, help="one provider key, e.g. eightfold")
    parser.add_argument("--limit", type=int, default=40, help="rows in the table (default 40)")
    parser.add_argument("--json", action="store_true", help="every row, machine-readable")
    args = parser.parse_args()

    from tracker.config import get_settings

    runs, learned = asyncio.run(load(args.days, args.provider))
    rows = summarize(runs, learned, float(get_settings().scraper_source_budget_seconds))
    if args.json:
        print(json.dumps([{**asdict(r), "at_risk": r.at_risk} for r in rows], indent=2))
    else:
        print(_table(rows[: args.limit]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
