#!/usr/bin/env bash
# Remove RoleBand's background item and stop what it runs. Leaves the database
# itself (PGDATA), data/backups/, data/logs/ and the built dashboard intact.
set -euo pipefail

# launchd agents exist only on macOS, so off it there is nothing to remove, and
# the steps below would only report `launchctl: command not found`.
if [ "$(uname -s)" != "Darwin" ]; then
  echo "deploy/uninstall.sh removes a launchd agent and runs on macOS only (this is $(uname -s))." >&2
  echo "Nothing was installed here by deploy/install.sh; ./setup.sh set up the checkout" >&2
  echo "and needs no uninstall beyond stopping the processes you started." >&2
  exit 1
fi

UID_NUM="$(id -u)"
LA="$HOME/Library/LaunchAgents"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
LABEL=com.roleband

# Stop the jobs first: a bootout alone leaves them running, by design.
if [ -x "$PY" ]; then
  ( cd "$ROOT/backend" && "$PY" -m tracker.supervisor stop --jobs ) \
    || echo "!! some jobs did not stop; they end on their own, or stop them by hand" >&2
fi

if [ -f "$LA/$LABEL.plist" ] || launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
  if [ -x "$PY" ]; then
    # bootout returns before the process exits; it must stop publishing first.
    for _ in $(seq 1 50); do
      launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 || break
      sleep 0.2
    done
    if ! launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1; then
      ( cd "$ROOT/backend" && "$PY" -m tracker.supervisor.launcher unregister ) \
        || echo "!! launcher discovery could not be removed" >&2
    else
      echo "!! background item is still loaded; launcher discovery was left intact" >&2
    fi
  fi
  rm -f "$LA/$LABEL.plist"
  echo "removed $LABEL"
fi

# The embedded server deliberately outlives the processes that use it, so
# nothing stops it automatically. It is stopped only when nothing else is
# connected to it (an MCP server, a CLI, another checkout): stopping it then
# would fail their next query.
if [ -x "$PY" ]; then
  ( cd "$ROOT/backend" && "$PY" - <<'PYEOF'
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tracker.config import get_settings
from tracker.platform.embedded_db import stop_server

settings = get_settings()
pgdata = settings.embedded_pgdata()


async def others() -> int:
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            return int(await conn.scalar(text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE pid <> pg_backend_pid() AND backend_type = 'client backend'"
            )) or 0)
    finally:
        await engine.dispose()


try:
    connected = asyncio.run(others())
except Exception:
    connected = 0
if connected:
    print(f"embedded Postgres left running: {connected} other client(s) still connected")
else:
    print("stopped embedded Postgres" if stop_server(pgdata) else "embedded Postgres was not running")
PYEOF
  ) || echo "!! could not stop the embedded database; stop it by hand if it is running" >&2
fi

echo "RoleBand uninstalled. The database, data/backups/ and data/logs/ are left intact."
