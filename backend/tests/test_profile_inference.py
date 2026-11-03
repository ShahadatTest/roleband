"""Profile inference: deterministic world-affinity scoring and its write rules.

The scoring is pure (`user_profile/inference.py`); the pass
(`workflows/profile_inference_pass.py`) is its only writer. These tests pin the
behavior contracts: hysteresis (one dismissal never flips a world), cold-start
silence (no signals -> no suggestions), resolved-key suppression, and stale
pending expiry. Negative controls included on purpose — a suggester that fires
on empty signals measures nothing.
"""

from __future__ import annotations

import asyncio

import pytest

from tracker.company_discovery import SECTORS
from tracker.db.models import ProfileSuggestion
from tracker.taxonomy.domains import SECTOR_WORLDS, all_slugs
from tracker.user_profile.inference import (
    MIN_OFF_DISMISSALS,
    OFF_THRESHOLD,
    ON_THRESHOLD,
    WEIGHT_DISMISS_WRONG_DOMAIN,
    WEIGHT_FAVORITE,
    WEIGHT_PURSUIT,
    WorldSignals,
    suggest_worlds,
    world_affinities,
)
from tracker.workflows import profile_inference_pass

# --- sector map validity -----------------------------------------------------

def test_sector_worlds_keys_are_exactly_the_discovery_sectors():
    assert set(SECTOR_WORLDS) == {sector.slug for sector in SECTORS}


def test_sector_worlds_values_are_vocabulary_worlds():
    worlds = set(all_slugs())
    for sector, mapped in SECTOR_WORLDS.items():
        assert set(mapped) <= worlds, f"{sector} maps outside the vocabulary"


# --- scoring -----------------------------------------------------------------

ALL = frozenset(all_slugs())


def test_affinity_arithmetic_is_the_documented_weights():
    signals = WorldSignals(
        favorited={"ai_ml": 2},
        pursued={"ai_ml": 1},
        dismissed_wrong_domain={"advertising": 3},
        dismissed_other={"advertising": 1},
        tracked_sectors=("ai",),
        intent_statement="Senior product leadership in machine learning",
    )
    scores = world_affinities(signals)
    # 2*3 + 1*4 + sector 2 + intent 3
    assert scores["ai_ml"] == 2 * WEIGHT_FAVORITE + WEIGHT_PURSUIT + 2.0 + 3.0
    # 3*-4 + 1*-1
    assert scores["advertising"] == 3 * WEIGHT_DISMISS_WRONG_DOMAIN - 1.0
    assert scores["health_bio"] == 0.0


def test_no_signals_no_suggestions():
    assert suggest_worlds(WorldSignals(), ALL) == []


def test_world_off_needs_repeated_wrong_world_dismissals():
    # Score far below threshold, but only ONE explicit wrong-world dismissal:
    # hysteresis holds. (1 wrong + 5 other = -9 <= OFF_THRESHOLD.)
    one_explicit = WorldSignals(
        dismissed_wrong_domain={"advertising": 1},
        dismissed_other={"advertising": 5},
    )
    assert one_explicit.dismissed_wrong_domain["advertising"] < MIN_OFF_DISMISSALS
    assert world_affinities(one_explicit)["advertising"] <= OFF_THRESHOLD
    assert suggest_worlds(one_explicit, ALL) == []

    # Two explicit wrong-world dismissals IS the designed floor: exactly
    # MIN_OFF_DISMISSALS events, landing exactly on OFF_THRESHOLD (2 * -4).
    two_explicit = WorldSignals(dismissed_wrong_domain={"advertising": 2})
    out = suggest_worlds(two_explicit, ALL)
    assert [(s.kind, s.world) for s in out] == [("world_off", "advertising")]
    assert out[0].basis["dismissed_wrong_domain"] == 2
    assert out[0].dedupe_key == "world_off:advertising"
    # ...but two explicit dismissals offset by positive signal stays quiet:
    # the threshold is on net affinity, not the event count alone.
    conflicted = WorldSignals(
        favorited={"advertising": 1},
        dismissed_wrong_domain={"advertising": 2},
    )
    assert suggest_worlds(conflicted, ALL) == []


def test_world_off_only_for_enabled_worlds():
    signals = WorldSignals(dismissed_wrong_domain={"advertising": 3})
    enabled = frozenset(ALL - {"advertising"})
    assert suggest_worlds(signals, enabled) == []


def test_world_on_for_excluded_world_from_intent_and_sector():
    # Cold-start story: intent (+3) + one evidencing sector (+2) reaches the
    # ON threshold with zero behavioural events.
    signals = WorldSignals(
        tracked_sectors=("gaming",),
        intent_statement="Streaming and entertainment product leadership",
    )
    enabled = frozenset(ALL - {"media_entertainment"})
    out = suggest_worlds(signals, enabled)
    assert [(s.kind, s.world) for s in out] == [("world_on", "media_entertainment")]
    assert out[0].basis["sectors"] == ["gaming"]
    assert out[0].basis["intent_matched"] is True
    assert out[0].score >= ON_THRESHOLD


def test_world_on_never_fires_for_already_enabled_world():
    signals = WorldSignals(favorited={"ai_ml": 10})
    assert suggest_worlds(signals, ALL) == []


def test_background_experience_counts_toward_affinity():
    # Three media-world background entries: 3 * 2 = 6 clears ON_THRESHOLD
    # alone — a career somewhere is evidence the radar should not hide it.
    signals = WorldSignals(background={"media_entertainment": 3})
    enabled = frozenset(ALL - {"media_entertainment"})
    out = suggest_worlds(signals, enabled)
    assert [(s.kind, s.world) for s in out] == [("world_on", "media_entertainment")]
    assert out[0].basis["background"] == 3
    # Two entries (4.0) stay below the threshold: background alone needs depth.
    assert suggest_worlds(
        WorldSignals(background={"media_entertainment": 2}), enabled
    ) == []


# --- pass write rules (fake session; loader is monkeypatched) ---------------

class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows: list[ProfileSuggestion]):
        self.rows = list(rows)
        self.added: list[ProfileSuggestion] = []
        self.deleted: list[ProfileSuggestion] = []
        self.committed = False

    async def scalars(self, _stmt):
        return _FakeScalars(self.rows)

    def add(self, row):
        self.added.append(row)

    async def delete(self, row):
        self.deleted.append(row)

    async def commit(self):
        self.committed = True


def _run(session, signals, enabled):
    async def fake_load(_session):
        return signals

    async def fake_enabled(_session):
        return set(enabled)

    async def go():
        orig_load = profile_inference_pass.load_world_signals
        orig_enabled = profile_inference_pass.get_enabled_domains
        profile_inference_pass.load_world_signals = fake_load
        profile_inference_pass.get_enabled_domains = fake_enabled
        try:
            return await profile_inference_pass.run_profile_inference(session)
        finally:
            profile_inference_pass.load_world_signals = orig_load
            profile_inference_pass.get_enabled_domains = orig_enabled

    return asyncio.run(go())


HATED = WorldSignals(dismissed_wrong_domain={"advertising": 3})


def test_pass_creates_pending_suggestion():
    session = _FakeSession([])
    summary = _run(session, HATED, ALL)
    assert summary["created"] == 1
    assert session.committed
    (row,) = session.added
    assert row.dedupe_key == "world_off:advertising"
    assert row.payload == {"world": "advertising"}
    assert row.status is None or row.status == "pending"  # column default applies


def test_pass_refreshes_pending_and_never_duplicates():
    existing = ProfileSuggestion(
        kind="world_off", dedupe_key="world_off:advertising",
        payload={"world": "advertising"}, basis={"score": -1}, status="pending",
    )
    session = _FakeSession([existing])
    summary = _run(session, HATED, ALL)
    assert summary == {"created": 0, "refreshed": 1, "expired": 0, "suppressed": 0}
    assert session.added == []
    assert existing.basis["dismissed_wrong_domain"] == 3


@pytest.mark.parametrize("status", ["accepted", "dismissed"])
def test_pass_never_re_raises_a_resolved_key(status):
    resolved = ProfileSuggestion(
        kind="world_off", dedupe_key="world_off:advertising",
        payload={"world": "advertising"}, basis={}, status=status,
    )
    session = _FakeSession([resolved])
    summary = _run(session, HATED, ALL)
    assert summary["suppressed"] == 1
    assert session.added == []
    assert session.deleted == []


def test_pass_expires_pending_whose_evidence_is_gone():
    stale = ProfileSuggestion(
        kind="world_off", dedupe_key="world_off:advertising",
        payload={"world": "advertising"}, basis={}, status="pending",
    )
    session = _FakeSession([stale])
    summary = _run(session, WorldSignals(), ALL)
    assert summary["expired"] == 1
    assert session.deleted == [stale]
