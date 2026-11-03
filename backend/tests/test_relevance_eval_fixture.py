"""Integrity gate for the frozen relevance eval fixture.

The fixture is authored ground truth (scripts/build_relevance_eval.py); this
test holds its structure to the properties the eval's meaning depends on. It
never loads a model — live ranking quality belongs to scripts/eval_relevance.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "relevance_eval.json"


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_shape_and_scale(fixture):
    assert fixture["version"] == 1
    assert len(fixture["labels"]) >= 150, "the brief calls for ~150 labelled pairs"
    assert sum(1 for lab in fixture["labels"] if lab["control"]) >= 30
    assert len(fixture["intents"]) >= 4


def test_every_label_resolves(fixture):
    posting_keys = {p["key"] for p in fixture["postings"]}
    intent_keys = {i["key"] for i in fixture["intents"]}
    for label in fixture["labels"]:
        assert label["posting"] in posting_keys
        assert label["intent"] in intent_keys
        if label["control"]:
            assert not label["relevant"], "a negative control is by definition irrelevant"


def test_no_duplicate_pairs(fixture):
    pairs = [(lab["intent"], lab["posting"]) for lab in fixture["labels"]]
    assert len(pairs) == len(set(pairs))


def test_every_intent_can_fail(fixture):
    """Each direction has enough of both classes for AUC and the control count
    to be meaningful — an eval that cannot fail measures nothing."""
    for intent in fixture["intents"]:
        labels = [lab for lab in fixture["labels"] if lab["intent"] == intent["key"]]
        rel = [lab for lab in labels if lab["relevant"]]
        ctl = [lab for lab in labels if lab["control"]]
        irr = [lab for lab in labels if not lab["relevant"] and not lab["control"]]
        assert len(rel) >= 5, intent["key"]
        assert len(ctl) >= 3, intent["key"]
        assert len(irr) >= 3, intent["key"]
        assert intent["statement"].strip()


def test_two_directional_controls(fixture):
    """At least one posting is relevant for one direction and a negative
    control for another — a model cannot win by ranking one flavour of text
    first regardless of the query."""
    relevant_for = {(lab["posting"]) for lab in fixture["labels"] if lab["relevant"]}
    control_for = {(lab["posting"]) for lab in fixture["labels"] if lab["control"]}
    assert relevant_for & control_for


def test_posting_texts_frozen(fixture):
    for p in fixture["postings"]:
        assert p["text"].startswith(p["title"])
        assert len(p["text"]) > 200, p["key"]
