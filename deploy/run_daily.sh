#!/usr/bin/env bash
# Wrapper for one full pipeline run (`tracker.daily`), started by hand; the
# installed supervisor runs its own scans (`tracker.supervisor`). Overlap
# protection lives in Python (filesystem and database run locks).
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

# Record the working-tree version beside the terminal's run output. The
# persisted code_version makes the same source identity available with the run.
# A diagnostic failure must not stop collection.
if command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  echo "roleband: running $(git -C "$ROOT" rev-parse --short HEAD) on $(git -C "$ROOT" rev-parse --abbrev-ref HEAD)$(
    [ -n "$(git -C "$ROOT" status --porcelain)" ] && echo ' (dirty tree)'
  )"
fi

# Verify a dirty backend before creating a ScrapeRun. A refusal leaves no
# running marker; fix the tree and rerun this command.
if ! "$ROOT/deploy/preflight.sh"; then
  echo "roleband: preflight refused this run — not scraping" >&2
  exit 75
fi

# Keep the Mac awake for the whole scrape. -s prevents system sleep, -i prevents
# idle sleep; caffeinate exits with, and when, the wrapped python exits.
#
# The heartbeat reconciler does not cover a forced sleep: a sleep does not kill
# this process, so the run never goes stuck-in-running for it to find. The
# process resumes with dead sockets, so the run finishes and reports a
# healthy-looking result with one source broken.
#
# -s is honored on AC power only and neither flag prevents clamshell sleep, so
# the pipeline measures suspension directly rather than assuming this worked.
if command -v caffeinate >/dev/null 2>&1; then
  exec caffeinate -s -i "$ROOT/backend/.venv/bin/python" -m tracker.daily "$@"
fi
exec "$ROOT/backend/.venv/bin/python" -m tracker.daily "$@"
