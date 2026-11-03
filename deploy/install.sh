#!/usr/bin/env bash
# One-command install: build the dashboard, register RoleBand's one background
# item (com.roleband: the supervisor, which serves the API and runs every job),
# and start it. Idempotent: safe to re-run after a pull.
set -euo pipefail

# The always-on runtime is a launchd agent: macOS only. Refuse BEFORE touching
# anything, so a host without launchctl is never left with a half-install
# (tests/test_deploy_platform_guard.py).
if [ "$(uname -s)" != "Darwin" ]; then
  echo "deploy/install.sh installs a launchd agent and runs on macOS only (this is $(uname -s))." >&2
  echo "Everything else runs here: ./setup.sh, then the supervisor in the foreground" >&2
  echo "(backend/.venv/bin/python -m tracker.supervisor run; see docs/development.md)." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UID_NUM="$(id -u)"
LA="$HOME/Library/LaunchAgents"
LABEL=com.roleband
PY="$ROOT/backend/.venv/bin/python"

# The background item runs the backend's own interpreter. Without it, refuse
# before building or registering anything: launchd would restart a missing
# program every few seconds.
if [ ! -x "$PY" ]; then
  echo "deploy/install.sh needs the backend's virtualenv (backend/.venv): run ./setup.sh first, then this again." >&2
  exit 1
fi

mkdir -p "$ROOT/data/logs" "$LA"

echo "==> Building dashboard (served by the API)"
if [ -d "$ROOT/dashboard" ]; then
  ( cd "$ROOT/dashboard" && npm ci ) && "$ROOT/deploy/build_dashboard.sh"
fi

echo "==> Ensuring backend dependencies"
# The set ./setup.sh installs, so the record below names what is installed:
# the runtime, the test and lint tools the supervisor's preflight runs, and the
# robots matcher from this checkout. Pinned through the macOS lock (this script
# refuses other OSes above; onnxruntime ships no Intel macOS wheel, so arm64 is
# the one macOS lock).
"$PY" -m pip install -q -r "$ROOT/backend/requirements.txt" -r "$ROOT/backend/requirements-dev.txt" \
  -c "$ROOT/backend/constraints/macos-arm64.txt"
"$PY" -m pip install -q -e "$ROOT/robots/python"
# Optional extras, never fatal: the supervisor runs without them, and
# apple-fm-sdk needs a full Xcode to build from its sdist.
"$PY" -m pip install -q -r "$ROOT/backend/requirements-optional.txt" \
  -c "$ROOT/backend/constraints/macos-arm64.txt" 2>/dev/null \
  || echo "   optional extras skipped (apple-fm-sdk needs a full Xcode); nothing required is affected"

( cd "$ROOT/backend" && "$PY" -m tracker.supervisor.activation record-deps >/dev/null ) \
  || echo "!! could not record the installed dependencies; updates will not wait for them" >&2

# Pre-warm the embedding model so first run is already semantic. Never fatal:
# the API warms itself in the background on startup, so a failure here only
# means the board starts lexical-only until weights land.
# `--offline <dir>` side-loads a pre-fetched, sha256-verified copy (air-gapped
# installs); any other arguments are ignored.
OFFLINE_DIR=""
if [ "${1:-}" = "--offline" ] && [ -n "${2:-}" ]; then
  OFFLINE_DIR="$2"
fi
echo "==> Pre-warming embedding model (background-safe; ~90-600 MB on first install)"
if [ -n "$OFFLINE_DIR" ]; then
  ( cd "$ROOT/backend" && "$PY" -m tracker.semantic.provision --offline "$OFFLINE_DIR" ) \
    || echo "!! model side-load failed; the API will retry downloading in the background" >&2
else
  ( cd "$ROOT/backend" && "$PY" -m tracker.semantic.provision ) \
    || echo "!! model pre-warm failed; the API will retry in the background" >&2
fi

# `bootout` is ASYNCHRONOUS: it returns before launchd has finished unloading the
# job, and a bootstrap into that window fails with "Bootstrap failed: 5:
# Input/output error". Wait until `launchctl print` stops finding the job.
unload() {
  launchctl bootout "gui/$UID_NUM/$1" 2>/dev/null || true
  for _ in $(seq 1 50); do
    launchctl print "gui/$UID_NUM/$1" >/dev/null 2>&1 || break
    sleep 0.2
  done
}

# Advisory, never fatal. The supervisor holds collection while a dirty tree fails
# its own suite (deploy/preflight.sh); an operator installing mid-edit should
# learn that here rather than from missed due work.
echo "==> Checking the tree is fit for unattended runs"
if ! "$ROOT/deploy/preflight.sh"; then
  echo "!! Collection WILL WAIT until this is fixed (or run with ROLEBAND_SKIP_PREFLIGHT=1)." >&2
  echo "!! Install continues; the API and everything else still run." >&2
fi

# An install brings RoleBand up: a maintenance pause left from before ends here.
( cd "$ROOT/backend" && "$PY" -m tracker.supervisor maintenance off --wait 0 >/dev/null 2>&1 ) || true

echo "==> Installing $LABEL"
sed "s|__ROLEBAND_ROOT__|$ROOT|g" "$ROOT/deploy/$LABEL.plist.template" > "$LA/$LABEL.plist"
# A running supervisor stops on bootout and leaves its jobs running; the new
# one adopts them.
unload "$LABEL"
launchctl bootstrap "gui/$UID_NUM" "$LA/$LABEL.plist"
launchctl enable "gui/$UID_NUM/$LABEL"
( cd "$ROOT/backend" && "$PY" -m tracker.supervisor.launcher register ) \
  || echo "!! launcher discovery could not be written; the supervisor will retry at startup" >&2
echo "    installed $LABEL"

cat <<EOF

RoleBand is installed and self-managing: one background item, "roleband".
  Dashboard + API : http://127.0.0.1:8010 (up within a minute)
  Background jobs : python -m tracker.supervisor plan   (from backend/)
  Logs            : $ROOT/data/logs/
  Uninstall       : $ROOT/deploy/uninstall.sh
EOF

"$ROOT/deploy/offer_launcher.sh" || echo "The optional launcher was skipped; the background engine remains installed." >&2
