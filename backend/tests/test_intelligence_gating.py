"""Extraction gating — the pure predicate and the compiled SQL clause.

Mirrors the embedding gate: re-run when never processed, content changed since the
last pass (content_changed_at > structured_at), or the prompt version moved.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects import postgresql

from tracker.intelligence.extract import is_stale
from tracker.intelligence_runtime.disclosed_comp import stale_clause

V = "disclosed_comp/v1"
T0 = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
LATER = T0 + timedelta(hours=1)


def test_never_processed_is_stale():
    assert is_stale(structured_at=None, content_changed_at=T0, structured_version=None, active_version=V) is True


def test_content_changed_since_pass_is_stale():
    # content_changed_at bumped strictly after structured_at => content changed.
    assert is_stale(structured_at=T0, content_changed_at=LATER, structured_version=V, active_version=V) is True


def test_prompt_version_bump_is_stale():
    assert is_stale(structured_at=T0, content_changed_at=T0, structured_version="old", active_version=V) is True


def test_fresh_is_not_stale():
    assert is_stale(structured_at=LATER, content_changed_at=T0, structured_version=V, active_version=V) is False


def test_equal_timestamps_do_not_rerun():
    # Same-pass case: structured_at == content_changed_at must NOT re-trigger (strict >).
    assert is_stale(structured_at=T0, content_changed_at=T0, structured_version=V, active_version=V) is False


def test_null_content_changed_at_with_processed_is_not_stale():
    assert is_stale(structured_at=T0, content_changed_at=None, structured_version=V, active_version=V) is False


def test_stale_clause_sql_has_all_three_conditions():
    sql = str(
        stale_clause(V).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "structured_at IS NULL" in sql
    assert "jobs.content_changed_at > jobs.structured_at" in sql
    assert "structured_prompt_version" in sql


def test_a_band_a_connector_wrote_is_never_stale_for_the_text_pass():
    """Whatever moved, the text pass cannot re-derive a figure read from
    a structured field, so it is never handed one (the SQL and the mirror)."""
    for structured_at, changed, version in ((None, T0, None), (T0, LATER, V), (T0, T0, "old")):
        assert is_stale(structured_at=structured_at, content_changed_at=changed, structured_version=version,
                        active_version=V, disclosed_source="connector") is False
        assert is_stale(structured_at=structured_at, content_changed_at=changed, structured_version=version,
                        active_version=V, disclosed_source="text") is True
    sql = str(stale_clause(V).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "jobs.disclosed_source IS DISTINCT FROM 'connector'" in sql
