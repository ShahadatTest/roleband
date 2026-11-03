"""Re-attempt only the sources a run failed on.

    python -m tracker.workflows.retry_sources          # retry the last run's failures
    python -m tracker.workflows.retry_sources --dry-run
    python -m tracker.workflows.retry_sources --max-attempts 3

Twenty companies with three failures should cost three sources of work, not
twenty. A full cycle re-scrapes everything; a targeted retry of one source
takes a fraction of that. That gap matters most for recovery: a
binding leaves `quarantined` only on a clean run, so without this a source that
fails once waits a whole cycle for its next chance.

Eligibility is not restated here: it is read off the outcome vocabulary
(`RETRYABLE`). Two exclusions carry the meaning: `OK` has nothing to redo, and
`CAPPED` is an operator's `--max-list` instruction that a retry would override.
`BOUNDED` is the ideal candidate: we stopped it while it was still producing.

Three properties this must hold, each of which is a way to make things worse:

* the retry run is `scope=targeted`, so a success over 3 of 20 sources can never
  advance `last_success_at` and switch off the catch-up for the other 17;
* attempts are bounded per source per cycle, so a permanently broken source
  cannot storm;
* it *skips* rather than waits when a full run holds the lock — a retry is the
  lowest-priority work in the system and must never delay a scheduled scrape.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from sqlalchemy import Select, cast, func, select
from sqlalchemy.dialects.postgresql import JSONB

from tracker.connectors.recipes.outcome import RETRYABLE, board_missing, classify_source_outcome
from tracker.db.models import ScrapeRun
from tracker.db.session import session_scope
from tracker.health import RunScope
from tracker.platform.locks import AlreadyRunning, run_lock
from tracker.platform.paths import DATA_DIR, PACING_DIR
from tracker.platform.ratelimit import enable_shared_pacing
from tracker.workflows.pipeline import run_pipeline

logger = logging.getLogger(__name__)

#: How many times one source may be retried for a single full run before we stop.
#: A source failing every attempt is a health problem, not a scheduling problem;
#: retrying it forever would just multiply its load and its anomaly count.
DEFAULT_MAX_ATTEMPTS = 2


def retry_candidates(per_source: dict) -> list[str]:
    """Sources from a finished run that are worth re-attempting.

    Pure over the `per_source` blob, like `classify_source_outcome` itself.
    A board gone from its address is not retried: it answers 404 again.
    """
    return sorted(
        company
        for company, stats in (per_source or {}).items()
        if classify_source_outcome(stats) in RETRYABLE and not board_missing(stats)
    )


def reference_run(runs: list[ScrapeRun]) -> ScrapeRun | None:
    """The newest run that can say which sources still need work.

    Two conditions. It must be `full`, because a targeted run only ever
    covered a subset and its `per_source` is silent about everyone else. It
    must also have *recorded* per-source evidence: a `full` run that died
    before collecting anything, taken as the reference, would report every
    source as having no outcome at all while the real evidence sits one run
    below it. A run that observed nothing is not evidence about anything: the
    same rule that makes a company the reference never touched report `null`
    rather than `failed`.

    `/api/sync/targets` applies the same rule through
    `reference_per_source_stmt`, so the "failed last run" the user sees and the
    set the scheduler retries are chosen from the same run.
    """
    return next((r for r in runs if r.scope == RunScope.FULL and r.per_source), None)


def reference_per_source_stmt(window: int) -> Select:
    """`reference_run` over the newest `window` finished runs, in SQL: the
    chosen run's `per_source`, and only that run's.

    The same two conditions as `reference_run`, a `full` scope and a
    `per_source` holding at least one source. A stored `per_source` holds every
    company's counts and errors, so a reader that needs the reference's blob
    asks for this one instead of loading the window.
    """
    empty = cast({}, JSONB)
    window_runs = (
        select(ScrapeRun.id, ScrapeRun.scope, ScrapeRun.per_source)
        .where(ScrapeRun.status.in_(("ok", "partial", "error")))
        .order_by(ScrapeRun.id.desc())
        .limit(window)
        .subquery()
    )
    reference_id = (
        select(window_runs.c.id)
        .where(
            window_runs.c.scope == RunScope.FULL,
            func.coalesce(window_runs.c.per_source, empty) != empty,
        )
        .order_by(window_runs.c.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    return select(ScrapeRun.per_source).where(ScrapeRun.id == reference_id)


def _attempts_so_far(runs: list[ScrapeRun], company: str) -> int:
    """How many targeted runs have already re-attempted this company.

    Counted from the run log rather than kept in memory: the retry is a separate
    process, so anything it remembers dies with it. Counting stops at the newest
    `full` run, because that is what resets the cycle: a fresh full attempt is
    a new question about the source, not a continuation of the old one.
    """
    attempts = 0
    for run in runs:  # newest first
        if run.scope == RunScope.FULL:
            break
        if company in (run.per_source or {}):
            attempts += 1
    return attempts


async def plan_retry(max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> dict:
    """Decide what a retry would cover, without running anything."""
    async with session_scope() as session:
        runs = list(
            (
                await session.scalars(
                    select(ScrapeRun)
                    .where(ScrapeRun.status.in_(("ok", "partial", "error")))
                    .order_by(ScrapeRun.id.desc())
                    .limit(20)
                )
            ).all()
        )

    reference = reference_run(runs)
    if reference is None:
        return {"companies": [], "reason": "no full run to retry from"}

    candidates = retry_candidates(reference.per_source)
    if not candidates:
        return {"companies": [], "reason": "no retry-eligible sources", "run_id": reference.id}

    exhausted = {c: _attempts_so_far(runs, c) for c in candidates}
    companies = [c for c in candidates if exhausted[c] < max_attempts]
    return {
        "companies": companies,
        "run_id": reference.id,
        "eligible": candidates,
        "skipped_attempts_exhausted": {
            c: n for c, n in exhausted.items() if n >= max_attempts
        },
    }


async def run(*, max_attempts: int = DEFAULT_MAX_ATTEMPTS, dry_run: bool = False) -> dict:
    plan = await plan_retry(max_attempts)
    if dry_run or not plan["companies"]:
        return {**plan, "ran": False}

    try:
        # Non-blocking: a scheduled scrape or a manual sync outranks a retry, and
        # waiting would let a retry delay the run whose failures it is fixing.
        with run_lock(DATA_DIR / "daily.lock"):
            summary = await run_pipeline(
                companies=plan["companies"],
                run_scope=RunScope.TARGETED,
            )
    except AlreadyRunning:
        logger.info("a run is already in progress; skipping retry")
        return {**plan, "ran": False, "reason": "run in progress"}

    return {**plan, "ran": True, "summary": summary}


def main() -> None:
    enable_shared_pacing(PACING_DIR)
    p = argparse.ArgumentParser(description="Re-attempt the sources a run failed on")
    p.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
        help=f"retries per source per full-run cycle (default {DEFAULT_MAX_ATTEMPTS})",
    )
    p.add_argument("--dry-run", action="store_true", help="report the plan, run nothing")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    result = asyncio.run(run(max_attempts=args.max_attempts, dry_run=args.dry_run))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
