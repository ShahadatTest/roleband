"""Bring every stored estimate to the current reference set.

    .venv/bin/python -m scripts.reestimate --status        # from backend/, as people type it
    .venv/bin/python -m tracker.plugins.reestimate_cli --wait 600  # the supervisor's `reestimate`

`scripts.reestimate` lists the options; both spellings run this module.

Each batch commits in its own transaction and the cursor is keyed by the target
fingerprint, so a stopped run resumes where it stopped. It takes the run lock
per batch and stops, exit `LOCKED`, when a scrape holds it (after `--wait`
seconds, if given): the scrape re-estimates before it collects. The pipeline,
its `reference` post pass and the scheduler's idle branch call the same
function; this is for a manual run, and for the run the supervisor starts after
a plugin is enabled, disabled or refreshed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from tracker.db.models import ReferenceState
from tracker.db.session import session_scope
from tracker.plugins.reestimate import BATCH, pending_jobs, reestimate, reference_inputs

#: A run that held the lock, or moved the target, stopped this one; the
#: supervisor reads it as busy, not failed.
LOCKED = 3


async def _status() -> int:
    async with session_scope() as session:
        state = await session.get(ReferenceState, 1)
        current = await reference_inputs(session)
        out = {
            "applied_fp": state.applied_fp if state else None,
            "current_fp": current.fingerprint,
            "due": (state.applied_fp if state else None) != current.fingerprint,
            "target_fp": state.target_fp if state else None,
            "cursor_job_id": state.cursor_job_id if state else None,
            "pending_jobs": await pending_jobs(session),
            "last_change_id": state.last_change_id if state else None,
            "providers": current.providers,
        }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


async def _run(args: argparse.Namespace) -> int:
    async with session_scope() as session:
        result = await reestimate(session, take_lock=True, lock_wait=args.wait, batch=args.batch,
                                  max_batches=args.max_batches)
    if result.current:
        print(f"current: {result.target_fp[:12]}, nothing to do")
        return 0
    if result.skipped:
        print(f"stopped: a run holds the lock or moved the target; {result.reached} jobs estimated so far")
        return LOCKED
    if result.applied:
        report = result.report
        print(
            f"applied {result.target_fp[:12]} as change {result.change_id}: {report['jobs']} jobs, "
            f"{report['moved']} moved, {report['gained']} gained, {report['lost']} lost"
        )
        return 0
    # Nothing a reader shows has moved yet: the last batch moves every job at once.
    print(f"partial: {result.batches} batches, {result.reached} jobs estimated; rerun to continue")
    return 0


def main(argv: list[str] | None = None, *, prog: str = "tracker.plugins.reestimate_cli") -> int:
    parser = argparse.ArgumentParser(prog=prog, description="Bring every stored estimate to the current reference set.")
    parser.add_argument("--status", action="store_true", help="print applied vs current and exit")
    parser.add_argument("--batch", type=int, default=BATCH)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--wait", type=float, default=0.0,
                        help="seconds to wait for a run holding the lock before stopping (default: ask once)")
    args = parser.parse_args(argv)
    return asyncio.run(_status() if args.status else _run(args))


if __name__ == "__main__":
    sys.exit(main())
