"""Entrypoint for `python -m tracker.daily`; the code is `tracker.workflows.daily`.

A documented command (deploy/*.sh, setup.sh, docs), not a compat shim, so
it keeps its path: `tests/test_no_compat_shims.py` ENTRYPOINTS.
"""

from tracker.workflows.daily import *  # noqa: F401,F403

if __name__ == "__main__":
    import asyncio

    from tracker.workflows.daily import _main

    raise SystemExit(asyncio.run(_main()))
