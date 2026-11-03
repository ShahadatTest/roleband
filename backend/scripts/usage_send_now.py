"""Show what usage sharing would send next, and send it now if asked.

    python -m scripts.usage_send_now           # print the next batch, send nothing
    python -m scripts.usage_send_now --yes     # send it now (skips only the once-a-day gate)

For a live check of a change (docs/architecture.md): the daily
send waits a day between batches, and a maintainer verifying a change in the
PostHog project should not have to. `--yes` bypasses that one gate and nothing
else: the kill switches, the user's consent, the project key and a maintenance
wake still decide, exactly as in the scheduler tick. It sends to whatever
project `usage_stats_project_key` names, so run it only on a machine whose user
(you) has shared.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime

from tracker.db.session import session_scope
from tracker.platform import power as host_power
from tracker.usage_stats import view
from tracker.usage_stats.flush import flush_if_due


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="send the batch now")
    args = parser.parse_args()
    now = datetime.now(UTC)
    async with session_scope() as session:
        preview = await view.preview(session, now=now)
    print(json.dumps(preview, indent=2, default=str))
    if not args.yes:
        print("Nothing sent. Run again with --yes to send this batch now.")
        return
    result = await flush_if_due(scope=session_scope, power=host_power.read_power, force=True)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
