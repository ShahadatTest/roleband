"""The standing intent vector.

Pure math first — the combination is intent = statement + centroid(positive)
- centroid(negative), each term normalized, the sum re-normalized — then the
shape of the centroid queries and the composed loader against a fake session.
These would fail for the plausible regressions: a sign flip on the dismissed
term, an unnormalized term dominating by magnitude, favorites double-counting
a pursued job, or the loader gating on rows that lack embeddings.
"""

from __future__ import annotations

import asyncio
import math

from sqlalchemy.dialects import postgresql

from tracker.semantic.intent import (
    build_intent_vector,
    centroid,
    combine_intent_vector,
    negative_embeddings_stmt,
    normalized,
    positive_embeddings_stmt,
)


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


# --------------------------------------------------------------------------- #
# Pure combination math
# --------------------------------------------------------------------------- #


def test_normalized_unit_length_and_zero_vector_is_none():
    out = normalized([3.0, 4.0])
    assert out == [0.6, 0.8]
    assert normalized([0.0, 0.0]) is None
    assert normalized([]) is None


def test_centroid_is_component_mean_and_empty_is_none():
    assert centroid([[1.0, 0.0], [0.0, 1.0]]) == [0.5, 0.5]
    assert centroid([]) is None


def test_no_signal_at_all_yields_none():
    assert combine_intent_vector(None, [], []) is None


def test_statement_only_is_the_normalized_statement():
    out = combine_intent_vector([2.0, 0.0], [], [])
    assert out == [1.0, 0.0]


def test_result_is_normalized():
    out = combine_intent_vector([1.0, 0.0], [[0.0, 1.0]], [])
    assert out is not None
    assert math.isclose(sum(x * x for x in out), 1.0, rel_tol=1e-9)


def test_dismissed_centroid_subtracts():
    # Statement points at X; dismissals also point at X with a Y component.
    # The negative term must pull the intent AWAY from the dismissed direction:
    # a job resembling the dismissals ranks below one resembling the statement.
    statement = [1.0, 0.0]
    dismissed = [[1.0, 1.0]]
    out = combine_intent_vector(statement, [], dismissed)
    assert out is not None
    dismissed_like = _unit([1.0, 1.0])
    statement_like = [1.0, 0.0]
    assert _cos(out, statement_like) > _cos(out, dismissed_like)
    # And the dismissed direction scores strictly worse than under the
    # statement alone — the subtraction did something.
    assert _cos(out, dismissed_like) < _cos(statement, dismissed_like)


def test_terms_are_normalized_before_combining():
    # A huge-magnitude favorites centroid must not drown the statement: each
    # term enters as a unit vector, so statement [1,0] + favorites [0,1000]
    # lands on the diagonal, not on the favorites axis.
    out = combine_intent_vector([1.0, 0.0], [[0.0, 1000.0]], [])
    assert out is not None
    assert math.isclose(out[0], out[1], rel_tol=1e-9)


def test_exact_cancellation_is_none_not_a_zero_vector():
    # Statement and dismissed centroid identical → zero sum → no direction.
    assert combine_intent_vector([1.0, 0.0], [], [[1.0, 0.0]]) is None


# --------------------------------------------------------------------------- #
# Centroid query shape
# --------------------------------------------------------------------------- #


def _compiled(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_positive_stmt_unions_favorites_and_pursuits_and_skips_unembedded():
    sql = _compiled(positive_embeddings_stmt())
    assert "favorites" in sql
    assert "pursuits" in sql
    # UNION (not UNION ALL): a favorited job that became a pursuit counts once.
    assert "UNION" in sql and "UNION ALL" not in sql
    assert "jobs.embedding IS NOT NULL" in sql


def test_negative_stmt_reads_dismissed_feedback_and_skips_unembedded():
    sql = _compiled(negative_embeddings_stmt())
    assert "job_feedback" in sql
    assert "verdict" in sql
    assert "jobs.embedding IS NOT NULL" in sql


# --------------------------------------------------------------------------- #
# Composed loader
# --------------------------------------------------------------------------- #


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    """Routes the two centroid queries by table name in the compiled SQL."""

    def __init__(self, positive_rows, negative_rows):
        self.positive_rows = positive_rows
        self.negative_rows = negative_rows

    async def scalars(self, stmt):
        sql = _compiled(stmt)
        if "job_feedback" in sql:
            return _Result(self.negative_rows)
        assert "favorites" in sql
        return _Result(self.positive_rows)


def test_build_intent_vector_composes_all_three_terms():
    session = _Session(
        positive_rows=[[0.0, 2.0], [0.0, 4.0]],  # centroid → +Y
        negative_rows=[[6.0, 0.0]],  # → -X
    )
    out = asyncio.run(build_intent_vector(session, [1.0, 0.0]))
    assert out is not None
    # statement(+X) + positive(+Y) - dismissed(+X) = +Y exactly.
    assert math.isclose(out[0], 0.0, abs_tol=1e-9)
    assert math.isclose(out[1], 1.0, rel_tol=1e-9)


def test_build_intent_vector_without_any_signal_is_none():
    assert asyncio.run(build_intent_vector(_Session([], []), None)) is None


def test_build_intent_vector_feedback_only_still_ranks():
    # The negative signal alone must produce a direction: away from what was
    # dismissed.
    out = asyncio.run(build_intent_vector(_Session([], [[1.0, 0.0]]), None))
    assert out == [-1.0, 0.0]
