"""Golden-vector parity: the ONNX runtime must reproduce the torch reference.

The fixture supplies the MiniLM reference vectors.
This test pins the runtime in isolation from the model choice:
it always targets the MiniLM spec directly, whatever `embedding_model` is
configured, so it guards the ONNX path whichever model is configured.

Parity is a property of a real runtime, and a mocked subject would measure
nothing, so it needs the MiniLM artifacts. CI provisions them
(`python -m tracker.semantic.provision --model all-MiniLM-L6-v2 --tier fp32`)
and fails the skip there (`tests/skip_policy.py`); a machine without them skips.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from tracker.semantic import provision
from tracker.semantic.manifest import TIER_FP32, spec_for

GOLDEN = Path(__file__).parent / "fixtures" / "embedding_golden_minilm.json"

_SPEC = spec_for("all-MiniLM-L6-v2")

pytestmark = pytest.mark.skipif(
    not provision.is_ready(_SPEC, TIER_FP32),
    reason="MiniLM ONNX artifacts not provisioned locally",
)


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_onnx_matches_torch_reference():
    from tracker.semantic.encoder import OnnxEncoder

    encoder = OnnxEncoder(
        _SPEC,
        TIER_FP32,
        str(provision.artifact_path(_SPEC, _SPEC.tiers[TIER_FP32])),
        str(provision.artifact_path(_SPEC, _SPEC.tokenizer)),
    )
    golden = json.loads(GOLDEN.read_text())
    assert golden["model"] == "all-MiniLM-L6-v2"
    for case in golden["cases"]:
        vec = encoder.encode([case["text"]], kind="document")[0]
        ref = case["vector"]
        assert len(vec) == len(ref) == _SPEC.dim
        cos = _cos(vec, ref)
        assert cos >= 0.9999, f"parity broke: cosine {cos:.6f} on {case['text'][:60]!r}"
        assert math.isclose(_cos(vec, vec), 1.0, abs_tol=1e-6), "vectors must be L2-normalized"
