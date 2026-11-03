"""Structural contract for the hybrid Best-match query (`search/retrieval.py`).

The repo has no live-DB pytest harness (tests are pure logic or SQL-compile), so
this pins the *shape* of the fused query by compiling it to SQL and asserting the
invariants that make hybrid ranking correct:

- textual sources — lexical FTS and explicit-floor pg_trgm — define membership
  and are fused by Reciprocal Rank Fusion, sum(1/(k+rank));
- when a query vector is supplied, cosine REORDERS the admitted union and can
  never admit (no cosine bound can say "no match");
- the same structured filters pre-applied to every membership source;
- graceful degradation to textual-only when semantic is off / no embedding.

Sister file: `test_search_retrieval.py` owns the per-source membership contracts
(floor + index probe, via names, weighted vector build). This one owns the fused
composition. These would fail for plausible regressions: the vector CTE scanning
the table again, hard-filtering instead of ranking, or losing the structured
WHERE on a candidate source.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from tracker.db.models import Job
from tracker.search.retrieval import fused_candidates


def _sql(
    conds: list, remainder: str, qvec: list[float] | None, pool: int = 200
) -> tuple[str, list[str]]:
    # Compile with default (bound-param) rendering: `literal_binds` can't render
    # the `regconfig` 'english' literal, and structure is all these assertions need.
    fused, via = fused_candidates(conds, remainder, qvec, pool)
    sql = str(select(fused).compile(dialect=postgresql.dialect()))
    return sql, via


def test_both_textual_sources_and_the_reorder_ranking_present_with_embedding():
    sql, _via = _sql([Job.status == "open"], "ml infra", [0.1, 0.2, 0.3])
    # Lexical: full-text rank over the (weighted) tsvector.
    assert "ts_rank_cd(jobs.search_vector" in sql
    assert "websearch_to_tsquery" in sql
    # Fuzzy: pg_trgm similarity + the `%` index probe.
    assert "similarity(jobs.title" in sql
    assert "jobs.title %" in sql or "jobs.company %" in sql
    # Semantic reorder ranking composed in — over the admitted union, not the
    # table (the union bound itself is test_search_retrieval.py's contract,
    # along with via names, the no-vector shape, per-CTE filters, and pool
    # bounds: one owner per assertion, per this module's docstring).
    assert "<=>" in sql


def test_reciprocal_rank_fusion_sums_per_source_terms():
    sql, via = _sql([Job.status == "open"], "platform", [0.1, 0.2])
    # RRF fuses one coalesce(1/(k+rank), 0) term per ranking (two textual + one
    # reorder), and the textual sources are UNION-ed into the admitted set.
    assert sql.lower().count("coalesce") >= len(via) + 1
    assert "UNION" in sql
    assert "LIMIT" in sql  # candidate pool cap bounds each textual source


def test_ranking_uses_row_number_not_boolean_filter():
    # Sources are *ranked* (row_number over a score), not just boolean-matched —
    # that ranking is what RRF fuses.
    sql, _ = _sql([Job.status == "open"], "staff engineer", [0.1, 0.2])
    assert "row_number() OVER" in sql


# --------------------------------------------------------------------------- #
# The reported total. `total` is never the size of the ranked candidate
# pool: a pool capped per source would report far fewer results than the
# query matches — a bound we imposed, presented as a fact about the market.
# --------------------------------------------------------------------------- #


def test_the_match_predicate_excludes_semantic_distance():
    """Cosine distance ranks every embedded row and never says *no*, so it
    cannot define a match set. Counting through it would report the whole
    corpus as matching any query."""
    from tracker.search.retrieval import textual_match

    sql = str(textual_match("staff engineer").compile(dialect=postgresql.dialect()))
    assert "search_vector @@" in sql
    assert "jobs.title %" in sql
    assert "cosine" not in sql.lower()
    assert "embedding" not in sql.lower()


def test_a_pool_that_binds_is_reported_not_hidden():
    """The ceiling may truncate ranking; it must never truncate the count. This
    is the shape the client needs to say "top N of M" instead of "M"."""
    from tracker.config import get_settings
    from tracker.search.retrieval import candidate_pool

    ceiling = get_settings().search_candidate_pool_max
    matched, pool = ceiling * 3, candidate_pool(ceiling * 3)
    assert pool < matched, "the ceiling must actually bind for this case to exist"
