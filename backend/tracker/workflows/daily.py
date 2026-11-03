"""CLI entrypoint for the daily run.

    python -m tracker.daily                 # full run, all companies
    python -m tracker.daily --company google anthropic
    python -m tracker.daily --max-list 150 --no-hydrate   # fast test run

Only a total failure exits non-zero; a partial run still refreshed data.
Overlapping invocations are refused (fcntl run lock) and exit 0.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from tracker.osnotify import banner, notify
from tracker.platform.locks import AlreadyRunning, run_lock
from tracker.platform.paths import DATA_DIR, PACING_DIR
from tracker.platform.ratelimit import enable_shared_pacing
from tracker.workflows.collection_types import ScanMode
from tracker.workflows.pipeline import run_pipeline

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the RoleBand job-tracker pipeline")
    # No fixed `choices`: valid slugs include built-ins (config.py) *and*
    # user-added DB companies, which aren't known at arg-parse time. The pipeline
    # intersects this list with its merged target set.
    p.add_argument("--company", nargs="*", help="subset of company slugs")
    p.add_argument("--max-list", type=int, default=None, help="cap raw jobs scanned per company")
    p.add_argument("--no-hydrate", action="store_true", help="skip full-description detail fetches")
    p.add_argument(
        "--scan-mode",
        choices=[mode.value for mode in ScanMode],
        default=ScanMode.RECONCILE.value,
        help="discovery is non-authoritative and can never close missing jobs",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


async def _main() -> int:
    enable_shared_pacing(PACING_DIR)
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        with run_lock(DATA_DIR / "daily.lock"):
            summary = await run_pipeline(
                companies=args.company,
                max_list=args.max_list,
                hydrate=not args.no_hydrate,
                scan_mode=ScanMode(args.scan_mode),
            )
    except AlreadyRunning:
        logger.warning("another daily run is in progress; exiting")
        return 0

    print(json.dumps(summary, indent=2, default=str))

    # A partial run refreshed data; binding health and the sync_warning
    # notification surface degraded sources without failing the whole run.
    if summary.get("status") == "error":
        notify(
            "RoleBand",
            banner("banner-daily-failed"),
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
