"""Coverage gate for calibrated title profiles.

`calibrated=True` is a claim this gate measures. It reads
the committed title snapshot (CI has no corpus) and holds each calibrated
company to the share of rung-naming titles its own vocabulary decides.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from scripts.bench_level_bands import TITLE_SNAPSHOT, control_failures, decided_share
from tracker.levels.titles import PROFILES

SNAPSHOT = json.loads(TITLE_SNAPSHOT.read_text())
CALIBRATED = sorted(slug for slug, profile in PROFILES.items() if profile.calibrated)


def test_every_calibrated_company_is_measured():
    assert sorted(SNAPSHOT["floors"]) == CALIBRATED
    assert all(SNAPSHOT["titles"].get(slug) for slug in CALIBRATED)


@pytest.mark.parametrize("company", CALIBRATED)
def test_a_calibrated_company_decides_its_floor_of_its_titles(company):
    share = decided_share(company, SNAPSHOT["titles"][company])
    floor = SNAPSHOT["floors"][company]
    assert share >= floor, f"{company} decides {share:.1%} of its rung-naming titles, floor {floor:.0%}"
    # The floor may only rise: a gain left unrecorded is a regression waiting.
    assert share < floor + 0.02, f"{company} decides {share:.1%}: raise its floor from {floor:.0%}"


def test_a_thin_profile_fails_the_gate(monkeypatch):
    # Planted control: Amazon keeps its calibrated flag but loses its rules.
    monkeypatch.setitem(PROFILES, "amazon", replace(PROFILES["amazon"], rung_rules=()))
    assert decided_share("amazon", SNAPSHOT["titles"]["amazon"]) < SNAPSHOT["floors"]["amazon"]


def test_the_bench_controls_read_as_planted():
    assert control_failures() == []


def test_a_moved_control_is_reported():
    from scripts.bench_level_bands import CONTROLS

    planted = (replace(CONTROLS[0], band="entry"),)
    assert control_failures(planted) != []
