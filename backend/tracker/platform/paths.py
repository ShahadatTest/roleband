"""Code, immutable resources and writable state for source and packaged engines."""

from __future__ import annotations

import os
from pathlib import Path

# Both layouts put tracker two levels below the resource root:
# backend/tracker/platform in a checkout, engine/tracker/platform in a bundle.
REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGED = os.environ.get("ROLEBAND_PACKAGED") == "1"
BACKEND_DIR = REPO_ROOT / ("engine" if PACKAGED else "backend")
DATA_DIR = Path.home() / ".roleband" if PACKAGED else REPO_ROOT / "data"
#: One slot file per rate-limit scope, shared by every provider-facing process
#: of this checkout (`ratelimit.enable_shared_pacing`).
PACING_DIR = DATA_DIR / "pacing"
DASHBOARD_DIST = REPO_ROOT / "dashboard" if PACKAGED else REPO_ROOT / "dashboard" / "dist"
VERSION_FILE = BACKEND_DIR / "release.json" if PACKAGED else REPO_ROOT / "dashboard" / "package.json"


def backend_dir(root: Path) -> Path:
    """Backend working directory within a caller's resource root."""
    return root / ("engine" if PACKAGED else "backend")
