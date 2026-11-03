"""The relevance gate (`scripts.eval_relevance.gate_failures`) judges each
intent, not only the macro average.

Pure: compares saved results, loads no model. The inputs are the two committed
results, MiniLM (the earlier model) and DenseOn (the production model and the
baseline), whose totals improved while logistics_ops got worse: the case a
macro-only gate passes.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.eval_relevance import gate_failures

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def minilm() -> dict:
    return json.loads((FIXTURES / "relevance_eval_baseline_minilm.json").read_text())


@pytest.fixture(scope="module")
def denseon() -> dict:
    return json.loads((FIXTURES / "relevance_eval_baseline_denseon.json").read_text())


def test_the_baseline_passes_against_itself(denseon) -> None:
    assert gate_failures(denseon, denseon) == []


def test_a_better_macro_cannot_hide_one_intent_getting_worse(minilm, denseon) -> None:
    # DenseOn beats MiniLM on both totals, which alone would pass a totals-only gate...
    assert denseon["macro_auc"] > minilm["macro_auc"]
    assert denseon["total_control_violations"] < minilm["total_control_violations"]
    # ...yet logistics_ops doubled its control violations and lost AUC.
    failures = gate_failures(denseon, minilm)
    assert "logistics_ops: control_violations 25 > 12" in failures
    assert "logistics_ops: auc 0.8719 < 0.9563" in failures
    assert not any(f.startswith(("macro_auc", "total_control_violations")) for f in failures)
    assert not any(f.startswith(("ai_frontier", "security_leadership", "media_streaming")) for f in failures)


def test_a_worse_model_fails_on_the_totals_too(minilm, denseon) -> None:
    failures = gate_failures(minilm, denseon)
    assert "macro_auc 0.9108 < 0.9421" in failures
    assert "total_control_violations 53 > 41" in failures
    assert "cloud_platform: control_violations 37 > 16" in failures


def test_one_extra_violation_in_one_intent_fails(denseon) -> None:
    result = copy.deepcopy(denseon)
    result["intents"]["security_leadership"]["control_violations"] += 1
    result["total_control_violations"] += 1
    assert gate_failures(result, denseon) == [
        "total_control_violations 42 > 41",
        "security_leadership: control_violations 1 > 0",
    ]


def test_an_intent_missing_from_the_result_fails(denseon) -> None:
    result = copy.deepcopy(denseon)
    del result["intents"]["media_streaming"]
    assert gate_failures(result, denseon) == ["media_streaming: missing from the result"]


def test_another_fixture_version_is_not_comparable(denseon) -> None:
    result = copy.deepcopy(denseon)
    result["fixture_version"] = 2
    (failure,) = gate_failures(result, denseon)
    assert "not comparable" in failure
