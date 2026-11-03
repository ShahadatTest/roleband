"""Semantic embedding tests.

Uses the real local model (cached, offline). Skips cleanly if the model can't be
loaded without network, so the default suite stays green on a fresh machine.
"""

from __future__ import annotations

import pytest


def _model_available() -> bool:
    try:
        from tracker.semantic.embed import get_model

        get_model()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _model_available(), reason="embedding model not available offline"
)


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_embedding_has_expected_dim():
    from tracker.config import get_settings
    from tracker.semantic.embed import embed_texts

    vecs = embed_texts(["Staff engineer building distributed systems"])
    assert len(vecs) == 1
    assert len(vecs[0]) == get_settings().embedding_dim  # 384


def test_paraphrase_is_closer_than_unrelated():
    from tracker.semantic.embed import embed_texts

    a, b, c = embed_texts(
        [
            "Build and operate distributed systems at scale",
            "Work on large-scale infrastructure and reliability",
            "Design brand marketing campaigns and social content",
        ]
    )
    # Vectors are normalized, so dot product == cosine similarity.
    assert _cos(a, b) > _cos(a, c)


def test_empty_input_returns_empty():
    from tracker.semantic.embed import embed_texts

    assert embed_texts([]) == []
