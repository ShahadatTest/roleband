#!/usr/bin/env bash
set -euo pipefail

if [ "$(uname -s)" != Darwin ]; then
  echo "The menu-bar launcher installs on macOS only." >&2
  exit 1
fi
LAUNCHER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! xcrun --find swiftc >/dev/null 2>&1; then
  echo "Apple's Command Line Tools are required to build the launcher." >&2
  exit 1
fi
PYTHON="${ROLEBAND_LAUNCHER_PYTHON:-python3}"
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/roleband-source-install.XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT
ROLEBAND_LAUNCHER_APP_PATH="$STAGING/RoleBand Launcher.app" "$LAUNCHER_ROOT/build-app.sh"
"$PYTHON" "$LAUNCHER_ROOT/Tools/install_app.py" "$STAGING/RoleBand Launcher.app"
