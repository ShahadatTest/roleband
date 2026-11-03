#!/usr/bin/env bash
set -euo pipefail

LAUNCHER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_PATH="${1:?Provide the assembled app path}"
OUTPUT="${2:?Provide a new disk image path}"
if [ ! -d "$APP_PATH/Contents/MacOS" ] || [ -e "$OUTPUT" ]; then
  echo "Provide an app bundle and an output path that does not exist." >&2
  exit 1
fi
PACKAGING_PYTHON="${ROLEBAND_PACKAGING_PYTHON:-python3}"
if ! "$PACKAGING_PYTHON" -c 'import dmgbuild' 2>/dev/null; then
  echo "Install packaging-requirements.txt in a separate Python environment and set ROLEBAND_PACKAGING_PYTHON to its interpreter." >&2
  exit 1
fi
exec "$PACKAGING_PYTHON" "$LAUNCHER_ROOT/Tools/package_image.py" "$APP_PATH" "$OUTPUT" \
  --language "${ROLEBAND_LAUNCHER_LANGUAGE:-en}"
