"""Ordering + serialization contract for the paginated notification feed."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from tracker.api.routers.notifications import _notification_ordering, _serialize_notification
from tracker.db.models import Notification


def _notification(**over) -> Notification:
    base = dict(
        id=1,
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        priority="high",
        category="high_comp_match",
        title="Comp up at Google",
        body=None,
        job_id=42,
        run_id=None,
        source_type="event",
        source_id=1,
        read_at=None,
        dismissed_at=None,
        meta={},
    )
    base.update(over)
    return Notification(**base)


def test_notification_serializes_linked_company_for_deep_link():
    """A job notification carries its company slug so the client can build the
    company-scoped position URL (/companies/:slug/jobs/:id); a run/health
    notification with no job has a null company."""
    job_notif = _notification(job_id=42)
    assert _serialize_notification(job_notif, "google")["company"] == "google"

    run_notif = _notification(job_id=None, category="sync_failed", source_type="run")
    assert _serialize_notification(run_notif, None)["company"] is None


def test_notification_feed_is_newest_first_before_priority():
    """A fresh normal sync result cannot be hidden by an old high-priority backlog."""
    sql = str(
        select(Notification.id)
        .order_by(*_notification_ordering())
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    order = sql.split("ORDER BY", 1)[1]

    assert order.startswith(" notifications.created_at DESC")
    assert "CASE WHEN (notifications.priority = 'high') THEN 0" in order
    assert order.rstrip().endswith("notifications.id DESC")


# ---- feed filters (search, category facet, facet counts) ----------------------

import asyncio  # noqa: E402

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import and_  # noqa: E402

from tracker.api.routers.notifications import (  # noqa: E402
    UNREAD_MAX_IDS,
    UnreadPayload,
    _feed_conditions,
    _like_term,
    notifications_unread,
)


def _where_sql(conds) -> str:
    sql = str(
        select(Notification.id)
        .where(and_(*conds))
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    return sql.split("WHERE", 1)[1]


def test_like_term_escapes_pattern_metacharacters():
    """A user typing `100%` or `sync_failed` searches for those characters, not
    for a wildcard: `%`, `_` and the escape itself are escaped, then wrapped."""
    assert _like_term("google") == "%google%"
    assert _like_term("100%") == "%100\\%%"
    assert _like_term("sync_failed") == "%sync\\_failed%"
    assert _like_term("a\\b") == "%a\\\\b%"


def test_search_matches_title_or_body_case_insensitively():
    where = _where_sql(_feed_conditions("all", None, None, "  Google "))
    # The dialect renders `%` doubled in a literal bind; the term is trimmed.
    assert "notifications.title ILIKE '%%Google%%' ESCAPE" in where
    assert "coalesce(notifications.body, '') ILIKE '%%Google%%' ESCAPE" in where
    assert " OR " in where
    # Whitespace-only is not a search.
    assert "ILIKE" not in _where_sql(_feed_conditions("all", None, None, "   "))


def test_category_is_a_list_and_absent_for_facet_counts():
    """Repeated `?category=` narrows with IN; the facet-count query passes None
    so an unselected category still reports what it would show."""
    where = _where_sql(_feed_conditions("unread", "high", ["sync_failed", "closed"], None))
    assert "notifications.category IN ('sync_failed', 'closed')" in where
    assert "notifications.read_at IS NULL" in where
    assert "notifications.priority = 'high'" in where

    facet = _where_sql(_feed_conditions("unread", "high", None, None))
    assert "category" not in facet
    assert "notifications.read_at IS NULL" in facet

    # A single category remains a valid filter.
    single = _where_sql(_feed_conditions("all", None, ["closed"], None))
    assert "notifications.category IN ('closed')" in single


def test_unknown_status_is_a_400():
    with pytest.raises(HTTPException) as err:
        _feed_conditions("archived", None, None, None)
    assert err.value.status_code == 400


def test_bulk_unread_is_bounded_and_empty_is_a_no_op():
    """The body is the ids `read_all` returned; more than one page's worth is
    not an undo. An empty list touches nothing — no session needed."""
    with pytest.raises(ValidationError):
        UnreadPayload(ids=list(range(UNREAD_MAX_IDS + 1)))
    UnreadPayload(ids=list(range(UNREAD_MAX_IDS)))

    result = asyncio.run(notifications_unread(UnreadPayload(ids=[]), session=None))
    assert result == {"updated": 0}


# ---- dismiss is reversible (HTTP, committed state) ---------------------------

import pytest_asyncio  # noqa: E402

from tracker.db.models import Job  # noqa: E402


@pytest_asyncio.fixture
async def feed_rows(db_session):
    """One read and one unread notification, one of them linked to a job."""
    job = Job(
        company="google", req_id="1", dedupe_key="google:1", title="Staff PM",
        url="https://example.test/jobs/1", status="open", in_scope=True,
        level_band="staff", family="product_management", track="product_program",
        first_seen=datetime.now(UTC), last_seen=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()
    # Explicit, ordered timestamps: the feed is newest-first, so a fixture that
    # let two rows share a wall-clock instant would assert on tie-break luck.
    now = datetime.now(UTC)
    rows = [
        Notification(
            created_at=now, priority="high", category="sync_failed",
            title="Sync failed", source_type="run", source_id=1,
        ),
        Notification(
            created_at=now - timedelta(hours=1), priority="normal", category="new_match",
            title="New match at Google", job_id=job.id, source_type="event", source_id=2,
            read_at=now,
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()
    return rows


@pytest.mark.asyncio
async def test_dismiss_then_restore_puts_the_row_back_in_the_feed(api_client, feed_rows):
    """The row action's Undo: dismissal is a timestamp, so restore clears it and
    the notification returns to the feed and to the unread count it was in."""
    target = feed_rows[0]
    before = (await api_client.get("/api/notifications")).json()
    assert [n["id"] for n in before["items"]] == [target.id, feed_rows[1].id]
    assert before["unread_count"] == 1

    dismissed = await api_client.post(f"/api/notifications/{target.id}/dismiss")
    assert dismissed.status_code == 200
    assert dismissed.json()["dismissed_at"] is not None
    gone = (await api_client.get("/api/notifications")).json()
    assert [n["id"] for n in gone["items"]] == [feed_rows[1].id]
    assert gone["total"] == 1
    assert gone["unread_count"] == 0

    restored = await api_client.post(f"/api/notifications/{target.id}/restore")
    assert restored.status_code == 200
    assert restored.json()["dismissed_at"] is None
    back = (await api_client.get("/api/notifications")).json()
    assert [n["id"] for n in back["items"]] == [target.id, feed_rows[1].id]
    assert back["total"] == 2
    assert back["unread_count"] == 1


@pytest.mark.asyncio
async def test_restore_leaves_read_state_alone_and_404s_for_an_unknown_row(api_client, feed_rows):
    """Dismissing a read notification never claimed it was unread, so putting it
    back must not resurrect it as new work."""
    read_row = feed_rows[1]
    await api_client.post(f"/api/notifications/{read_row.id}/dismiss")
    restored = await api_client.post(f"/api/notifications/{read_row.id}/restore")

    assert restored.json()["read_at"] is not None
    # And the company slug still resolves, so the restored row still deep-links.
    assert restored.json()["company"] == "google"
    assert (await api_client.get("/api/notifications")).json()["unread_count"] == 1

    assert (await api_client.post("/api/notifications/999999/restore")).status_code == 404
