"""Blueprint completeness — the gate that keeps every company fully wired.

Every `BLUEPRINT` company must pass every registered `ARTIFACT_CHECKS` entry.
A new company fails here until each per-company surface (adapter, level
vocabulary, comp seeds, ladder, price fixture, dashboard branding) is filled.
A new per-company feature must register a check in `tracker/blueprint.py`, at
which point this test gates it for all companies at once. Never weaken this
test to land a company — fill the artifact instead.
"""

from __future__ import annotations

from tracker.blueprint import (
    ARTIFACT_CHECKS,
    BLUEPRINT,
)
from tracker.config import COMPANIES


def test_blueprint_complete():
    problems: list[str] = []
    for slug, bp in BLUEPRINT.items():
        for name, check in ARTIFACT_CHECKS:
            problems.extend(f"{slug}: {name}: {p}" for p in check(bp))
    assert not problems, "blueprint artifacts missing:\n" + "\n".join(problems)


def test_config_companies_derived_from_blueprint():
    assert set(COMPANIES) == set(BLUEPRINT)
    for slug, cfg in COMPANIES.items():
        bp = BLUEPRINT[slug]
        assert cfg["display"] == bp.display
        assert cfg["adapter"] == bp.adapter
        assert cfg["enabled"] == bp.enabled


def test_private_companies_have_no_ticker():
    for slug in ("openai", "anthropic"):
        bp = BLUEPRINT[slug]
        assert bp.is_public is False
        assert bp.ticker is None
