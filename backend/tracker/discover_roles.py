"""`python -m tracker.discover_roles`: one manual scope inventory refresh, for a
maintainer at a terminal. The code is `tracker.workflows.discover_roles`; the
supervisor runs its own `role_discovery` entry. A command, not a compat shim,
so it keeps its path: `tests/test_no_compat_shims.py` ENTRYPOINTS.
"""

from tracker.workflows.discover_roles import *  # noqa: F401,F403

if __name__ == "__main__":
    import asyncio

    from tracker.workflows.discover_roles import _main

    asyncio.run(_main())
