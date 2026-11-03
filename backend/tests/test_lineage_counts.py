"""Lineage-aware counting predicates: routing + compiled SQL shape."""

from __future__ import annotations

from sqlalchemy.dialects import postgresql

from tracker.lineage.counts import (
    EFFECTIVE_FIRST_SEEN_SQL,
    event_bucket,
    is_new_job_clause,
    is_repost_job_clause,
)


def _sql(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect(),
                              compile_kwargs={"literal_binds": True}))


def test_event_bucket_routes_a_creation_by_role_and_by_the_new_rule():
    for created in ("opened", "added"):
        assert event_bucket(created, None, new_listing=True) == "new_count"
        assert event_bucket(created, "original", new_listing=True) == "new_count"
        assert event_bucket(created, "repost", new_listing=True) == "reposted_count"
        assert event_bucket(created, "duplicate") == "reposted_count"


def test_a_creation_the_board_does_not_call_new_is_no_new_demand():
    """A first read's find, or a posting listed long before we stored it, is
    created today and still not new demand."""
    assert event_bucket("opened", None) is None
    assert event_bucket("added", "original", new_listing=False) is None


def test_a_place_set_later_member_books_nothing():
    for kind in ("opened", "added", "reopened"):
        assert event_bucket(kind, None, later_in_place_set=True, new_listing=True) is None


def test_event_bucket_closed_and_reopened():
    assert event_bucket("closed", None) == "closed_count"
    assert event_bucket("reopened", None) == "reposted_count"
    assert event_bucket("changed", None) is None


def test_reposted_count_has_two_sources():
    # Both a same-req_id reopened event and a new-req_id repost opening feed the
    # same counter, which is why demand.py must accumulate (+=) rather than assign.
    assert event_bucket("reopened", None) == "reposted_count"
    assert event_bucket("opened", "repost") == "reposted_count"


def test_new_clause_matches_standalone_and_original_only():
    sql = _sql(is_new_job_clause())
    assert "lineage_role IS NULL" in sql
    assert "'original'" in sql


def test_repost_clause_matches_successor_roles():
    sql = _sql(is_repost_job_clause())
    assert "'repost'" in sql and "'duplicate'" in sql


def test_effective_first_seen_uses_coalesce():
    assert EFFECTIVE_FIRST_SEEN_SQL == "coalesce(j.lineage_first_seen, j.first_seen)"
