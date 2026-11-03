"""Bring every stored estimate to the current reference set.

    .venv/bin/python -m scripts.reestimate --status   # applied vs current, pending jobs
    .venv/bin/python -m scripts.reestimate            # run it; commits per batch, resumable
    .venv/bin/python -m scripts.reestimate --max-batches 2
    .venv/bin/python -m scripts.reestimate --wait 600  # wait for a run holding the lock

The options are `tracker.plugins.reestimate_cli`'s, which says how a run
resumes and when it stops; the supervisor runs that module for its
`reestimate` job.
"""

from __future__ import annotations

import sys

from tracker.plugins.reestimate_cli import main

if __name__ == "__main__":
    sys.exit(main(prog="scripts.reestimate"))
