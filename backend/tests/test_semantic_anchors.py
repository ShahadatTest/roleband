"""World-anchor classifier: pure verdict logic (no model, no DB).

Accuracy lives in `scripts.bench_relevance_review --builtin` (two-directional
cohorts); these tests pin the decision rule — thresholds, fail-closed slugs,
margin-monotone confidence, and the deterministic rationale.
"""

from __future__ import annotations

import pytest

from tracker.semantic import anchors

TRACKED = frozenset({"ai_ml", "cloud_infra"})


def _scores(**over) -> dict[str, float]:
    base = {"ai_ml": 0.10, "cloud_infra": 0.10, "logistics_fulfillment": 0.10}
    base.update(over)
    return base


def test_tracked_top_world_is_relevant():
    a = anchors.classify_scores(_scores(ai_ml=0.30, logistics_fulfillment=0.25), TRACKED)
    assert a.relevance == "relevant"
    assert a.domain == "ai_ml"


def test_untracked_top_world_is_irrelevant():
    a = anchors.classify_scores(_scores(logistics_fulfillment=0.30, ai_ml=0.25), TRACKED)
    assert a.relevance == "irrelevant"
    assert a.domain == "logistics_fulfillment"


def test_thin_margin_is_uncertain_with_no_domain():
    a = anchors.classify_scores(
        _scores(ai_ml=0.30, logistics_fulfillment=0.30 - anchors.TAU_MARGIN / 2), TRACKED
    )
    assert a.relevance == "uncertain"
    assert a.domain is None


def test_degenerate_low_cosine_is_uncertain():
    a = anchors.classify_scores(
        _scores(ai_ml=anchors.TAU_ACCEPT - 0.05, logistics_fulfillment=0.05), TRACKED
    )
    assert a.relevance == "uncertain"


def test_unknown_world_slug_fails_closed():
    with pytest.raises(ValueError):
        anchors.classify_scores({"made_up_world": 0.9, "ai_ml": 0.2}, TRACKED)


def test_single_world_scores_fail_closed():
    with pytest.raises(ValueError):
        anchors.classify_scores({"ai_ml": 0.9}, TRACKED)


def test_confidence_is_monotone_in_margin():
    narrow = anchors.classify_scores(_scores(ai_ml=0.30, cloud_infra=0.27), TRACKED)
    wide = anchors.classify_scores(_scores(ai_ml=0.40, cloud_infra=0.27), TRACKED)
    assert wide.confidence > narrow.confidence, "the flat-0.95 pathology must not return"
    assert 0 < narrow.confidence <= 0.95
    assert wide.confidence <= 0.95


def test_rationale_is_deterministic_and_names_the_anchor():
    a = anchors.classify_scores(_scores(ai_ml=0.32, cloud_infra=0.24), TRACKED)
    b = anchors.classify_scores(_scores(ai_ml=0.32, cloud_infra=0.24), TRACKED)
    assert a.rationale == b.rationale
    assert "AI" in a.rationale  # display name of the winning world
    assert "cosine 0.32" in a.rationale


def test_classify_embedding_uses_dot_products(monkeypatch):
    monkeypatch.setattr(
        anchors, "anchor_matrix",
        lambda: (("ai_ml", "logistics_fulfillment"), [[1.0, 0.0], [0.0, 1.0]]),
    )
    a = anchors.classify_embedding([0.9, 0.1], TRACKED)
    assert a.domain == "ai_ml"
    assert a.relevance == "relevant"


def test_anchor_text_carries_display_and_lexicon():
    text = anchors.anchor_text("logistics_fulfillment")
    assert "logistics" in text.lower()
    assert "warehouse" in text or "supply chain" in text
