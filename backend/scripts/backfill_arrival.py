"""Classify how each stored role arrived (`jobs.arrival`) on a source install.

The app does this itself while preparing its database after an update. A
source install runs it after `alembic upgrade head`, with its launchers
drained: it rewrites `first_seen` of roles the inventory saw first, and
rebuilds the lineage projection at the end. Each batch commits; a rerun
continues with the roles still unclassified.

Run from backend/:
    .venv/bin/python -m scripts.backfill_arrival
"""

from __future__ import annotations

import argparse
import asyncio

from tracker.workflows.arrival_backfill import BATCH, backfill_arrivals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=BATCH, help="roles per transaction")
    args = parser.parse_args()
    done = asyncio.run(backfill_arrivals(batch=args.batch))
    print(f"classified {done} roles")


if __name__ == "__main__":
    main()
