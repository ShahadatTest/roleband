"""Queryless "Best matches": intent ranking on /api/jobs.

The load-bearing invariant: intent is a RANKING, never a gate. The ranked page
query carries exactly the `apply_job_filters` WHERE — no embedding predicate —
so unembedded rows stay in the set (NULLS LAST) and `total` is counted from the
same base as every other sort. And with no intent signal at all, sort=relevance
without a query uses the default ordering.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.dialects import postgresql

from tracker.api.routers.jobs import list_jobs
from tracker.config import get_settings
from tracker.db.models import AppSetting
from tracker.search.best_match import intent_ranked_stmt, why_world


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_intent_ranked_stmt_orders_by_cosine_and_never_gates():
    stmt = intent_ranked_stmt(
        {"status": "open", "company": ["google"]}, [0.1, 0.2], limit=50, offset=0
    )
    sql = _sql(stmt)
    where, order_by = sql.split("ORDER BY", 1)
    # Ranked by pgvector cosine distance, most similar first, with the stable
    # id tiebreaker that keeps pagination deterministic.
    assert "<=>" in sql
    assert "intent_distance ASC NULLS LAST, jobs.id DESC" in order_by
    # Never a gate: the WHERE is the shared filter set and nothing else — no
    # embedding predicate may sneak in and silently drop unembedded rows.
    assert "embedding" not in where.split("WHERE", 1)[1]
    assert "jobs.company IN" in where
    assert "jobs.status =" in where
    assert "LIMIT" in sql


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def one(self):
        return (0, 0)  # the combined count query: (total, placed_total)


class _Session:
    """Routes queries by compiled SQL: intent-embedding setting row, centroid
    reads, count, and the page query (captured for ordering assertions)."""

    def __init__(self, intent_value: dict | None):
        self.intent_value = intent_value
        self.page_stmts = []
        self.executed_stmts = []

    async def get(self, model, key):
        assert model is AppSetting
        if self.intent_value is None:
            return None
        return AppSetting(key=key, value=self.intent_value)

    async def scalar(self, stmt):
        return 0  # the count query

    async def scalars(self, stmt):
        sql = _sql(stmt)
        # The two centroid reads are the only queries that predicate on the
        # embedding column itself (the ranking must never — that's the test).
        if "jobs.embedding IS NOT NULL" in sql:
            return _Result([])  # no feedback signal
        self.page_stmts.append(stmt)
        return _Result([])

    async def execute(self, stmt):
        self.executed_stmts.append(stmt)
        return _Result([])


def _run(session) -> dict:
    return asyncio.run(list_jobs(session, [], sort="relevance", limit=50, offset=0))


def test_relevance_without_query_ranks_by_stored_intent_vector():
    session = _Session({
        "statement": "ai leadership",
        "model": get_settings().embedding_model,
        "vector": [1.0, 0.0],
    })
    response = _run(session)
    assert response["ranked_by"] == "intent"
    assert response["total"] == 0
    # One ranked page query, and the list's one count, which also counts the
    # rows whose level we place rather than spending a query on it.
    sqls = [_sql(stmt) for stmt in session.executed_stmts]
    assert [sql for sql in sqls if "<=>" in sql] and len([sql for sql in sqls if "<=>" in sql]) == 1
    (count,) = [sql for sql in sqls if "<=>" not in sql]
    assert "count(*) FILTER (WHERE" in count


def test_relevance_without_query_and_without_signal_falls_back():
    # Without a stored statement or feedback, relevance uses the default ordering.
    session = _Session(None)
    response = _run(session)
    assert "ranked_by" not in response
    (page,) = session.page_stmts
    sql = _sql(page)
    assert "<=>" not in sql
    assert "jobs.first_seen DESC" in sql.split("ORDER BY", 1)[1]


def test_why_world_prefers_the_ladder_then_the_advisory_then_stays_silent():
    # A slug, never a display name: the dashboard names it in the reader's
    # language.
    assert why_world(["ai_ml"], None) == "ai_ml"
    # Ladder wins over advisory when both exist.
    assert why_world(["logistics_fulfillment"], "ai_ml") == "logistics_fulfillment"
    # Unplaced rows fall to the advisory verdict.
    assert why_world(None, "security_privacy") == "security_privacy"
    # Neither -> no chip, never a guess; unknown slugs render nothing.
    assert why_world(None, None) is None
    assert why_world(["not_a_world"], None) is None
