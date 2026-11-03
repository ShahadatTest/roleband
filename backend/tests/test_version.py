"""The backend and the dashboard ship as one release and carry one version."""

from __future__ import annotations

import json
from pathlib import Path

import tracker

ROOT = Path(__file__).resolve().parents[2]


def test_backend_and_dashboard_versions_match():
    dashboard = json.loads((ROOT / "dashboard" / "package.json").read_text(encoding="utf-8"))
    assert tracker.__version__ == dashboard["version"]
