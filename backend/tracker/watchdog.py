"""`python -m tracker.watchdog`: one manual watchdog pass, for a maintainer at a
terminal. The code is `tracker.workflows.watchdog`; the supervisor runs its own
`health` entry. A command, not a compat shim, so it keeps its path:
`tests/test_no_compat_shims.py` ENTRYPOINTS.
"""

from tracker.workflows.watchdog import *  # noqa: F401,F403

if __name__ == "__main__":
    from tracker.workflows.watchdog import main

    main()
