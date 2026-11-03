"""`python -m tracker.scheduler`: one manual scheduler tick, for a maintainer
at a terminal. The code is `tracker.workflows.scheduler`; the supervisor runs
its own `scan` entry and never this command.

After `daily.lock` is released, the manual tick also asks for due plugin jobs,
through the supervisor's own `plugins_due` step.
"""

import logging

from tracker.supervisor import entries
from tracker.workflows.scheduler import *  # noqa: F401,F403


async def start_due_plugins() -> dict:
    """The supervisor's `plugins_due`, logged instead of raised: plugin work
    never fails a manual tick."""
    from tracker.platform.util import describe_exception

    try:
        return await entries.plugins_due()
    except Exception as error:  # noqa: BLE001 - plugin work never fails a tick
        logging.getLogger("tracker.scheduler").warning("plugin start failed", exc_info=True)
        return {"error": describe_exception(error)[:200]}


if __name__ == "__main__":
    from tracker.workflows.scheduler import main

    main(after_lock=[("plugins", start_due_plugins)])
