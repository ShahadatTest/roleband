#!/usr/bin/env bash
set -euo pipefail
LAUNCHER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${ROLEBAND_PACKAGING_PYTHON:-python3}" "$LAUNCHER_ROOT/Tools/bundle.py" "$@"
