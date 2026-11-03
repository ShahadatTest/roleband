#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHOICE="${ROLEBAND_INSTALL_LAUNCHER:-ask}"
case "$CHOICE" in
  no) exit 0 ;;
  ask|yes) ;;
  *) echo "ROLEBAND_INSTALL_LAUNCHER must be ask, yes or no. Launcher skipped." >&2; exit 0 ;;
esac
if ! xcrun --find swiftc >/dev/null 2>&1; then
  echo "Menu-bar launcher skipped: Apple's Command Line Tools are not available."
  echo "You can build it later with launcher/macos/install.sh."
  exit 0
fi
if [ "$CHOICE" = ask ]; then
  if [ ! -t 0 ]; then
    echo "Menu-bar launcher is optional. Run launcher/macos/install.sh to add it later."
    exit 0
  fi
  read -r -p 'Build the menu-bar launcher and install it in ~/Applications? [y/N] ' ANSWER || ANSWER=""
  case "$ANSWER" in y|Y|yes|YES) ;; *) exit 0 ;; esac
fi
if ! ROLEBAND_LAUNCHER_PYTHON="$ROOT/backend/.venv/bin/python" "$ROOT/launcher/macos/install.sh"; then
  echo "The optional launcher could not be installed. RoleBand's background engine stays installed." >&2
  echo "Run launcher/macos/install.sh to try again." >&2
fi
