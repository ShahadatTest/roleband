"""The notification feed's response contract.

`tracker/api/schemas/notifications.py` declares what the seven routes send. These
tests hold it to its sources:

1. **The vocabulary it does not have**: no CHECK constraint bounds a category,
   priority or source type, so the model keeps them strings, and a row from a
   retired category is still served.
2. **The routes over real HTTP** against seeded Postgres rows
   (`tests/notification_contract_seed.py`): each shape's exact keys, the order
   of the feed, `meta` returned exactly as stored, filters that narrow the page
   but never the bell's counts, search terms that stay text, paging, the
   read-all undo and its cap, and every single-row action read back, with each
   refusal leaving the feed exactly as it was.
3. **Drift in both directions**: a key the serializer adds or drops without its
   model fails the response instead of vanishing from, or defaulting in, it.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi.exceptions import ResponseValidationError
from sqlalchemy import CheckConstraint, select

from tests.api_errors import said
from tests.notification_contract_seed import (
    SeededNotifications,
    seed_notification_contract,
    seed_unread_backlog,
)
from tracker.api.routers import notifications as notifications_router
from tracker.api.schemas import notifications as contract
from tracker.db.models import Notification

# --------------------------------------------------------------------------- #
# 1. Vocabulary
# --------------------------------------------------------------------------- #


def test_no_constraint_bounds_the_strings_the_model_leaves_open():
    assert not [c for c in Notification.__table__.constraints if isinstance(c, CheckConstraint)], (
        "a CHECK constraint now bounds a notification column: type that field as its Literal"
    )
    fields = contract.NotificationRow.model_fields
    assert {name: fields[name].annotation for name in ("priority", "category", "source_type")} == {
        "priority": str, "category": str, "source_type": str,
    }


# --------------------------------------------------------------------------- #
# 2. The routes over HTTP
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def seeded(db_session, api_client, no_escape) -> SeededNotifications:
    return await seed_notification_contract(db_session)


def _fields(model) -> set[str]:
    return set(model.model_fields)


async def _feed(api_client, query: str = "") -> dict:
    response = await api_client.get(f"/api/notifications{query}")
    assert response.status_code == 200, response.text
    return response.json()


def _ids(body: dict) -> list[int]:
    return [item["id"] for item in body["items"]]


async def _stored(db_session) -> dict[int, tuple]:
    rows = await db_session.execute(
        select(Notification.id, Notification.read_at, Notification.dismissed_at)
    )
    return {row.id: (row.read_at, row.dismissed_at) for row in rows}


async def _state(api_client, db_session) -> tuple[dict, dict]:
    return await _feed(api_client, "?limit=200"), await _stored(db_session)


@pytest.mark.asyncio
async def test_the_feed_sends_every_key_newest_first_with_meta_as_stored(api_client, db_session, seeded):
    body = await _feed(api_client)
    assert set(body) == _fields(contract.NotificationListResponse)
    assert all(set(item) == _fields(contract.NotificationRow) for item in body["items"])

    s = seeded
    assert _ids(body) == [s.failed, s.warning, s.closed, s.changed, s.pursuit, s.digest, s.legacy], (
        "newest first; at one timestamp, high before normal before low; dismissed rows never listed"
    )
    assert (body["total"], body["limit"], body["offset"]) == (7, 50, 0)
    assert (body["unread_count"], body["high_unread_count"]) == (4, 3)
    assert body["category_counts"] == {
        "sync_failed": 1, "sync_warning": 1, "closed": 1, "changed": 1,
        "pursuit_due": 1, "daily_digest": 1, "new_match": 1,
    }

    items = {item["id"]: item for item in body["items"]}
    assert {i: items[i]["company"] for i in items} == {
        s.failed: None, s.warning: None, s.closed: "acme", s.changed: "globex",
        s.pursuit: "acme", s.digest: None, s.legacy: "acme",
    }, "the linked job's company, and null with no job"
    stored_meta = dict((await db_session.execute(select(Notification.id, Notification.meta))).all())
    assert {i: items[i]["meta"] for i in items} == {i: stored_meta[i] for i in items}
    legacy = items[s.legacy]
    assert (legacy["category"], legacy["body"], legacy["meta"]) == ("new_match", None, {}), (
        "a retired category is still served"
    )
    warning = items[s.warning]
    assert (warning["created_at"], warning["read_at"], warning["dismissed_at"]) == (
        "2026-07-01T15:00:00Z", "2026-07-01T16:00:00Z", None,
    )
    assert isinstance(warning["run_id"], int) and warning["source_type"] == "run"
    assert (items[s.digest]["run_id"], items[s.digest]["job_id"], items[s.digest]["source_type"]) == (
        None, None, "digest",
    )


@pytest.mark.asyncio
async def test_an_empty_feed(api_client, db_session, no_escape):
    assert await _feed(api_client) == {
        "items": [], "total": 0, "limit": 50, "offset": 0,
        "unread_count": 0, "high_unread_count": 0, "category_counts": {},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected", "counted"),
    [
        ("?status=unread", ["failed", "closed", "pursuit", "legacy"],
         {"sync_failed", "closed", "pursuit_due", "new_match"}),
        ("?priority=high", ["failed", "closed", "pursuit"], {"sync_failed", "closed", "pursuit_due"}),
        ("?category=sync_failed&category=closed", ["failed", "closed"],
         {"sync_failed", "sync_warning", "closed", "changed", "pursuit_due", "daily_digest", "new_match"}),
        ("?status=unread&priority=high&category=closed", ["closed"], {"sync_failed", "closed", "pursuit_due"}),
        ("?q=acme", ["closed", "pursuit", "digest", "legacy"],
         {"closed", "pursuit_due", "daily_digest", "new_match"}),
        ("?q=%25", ["changed"], {"changed"}),
        ("?q=_", [], set()),
    ],
    ids=["unread", "high", "two_categories", "combined", "search", "percent_is_text", "underscore_is_text"],
)
async def test_filters_narrow_the_page_but_never_the_bell_counts(api_client, seeded, query, expected, counted):
    body = await _feed(api_client, query)
    assert _ids(body) == [getattr(seeded, name) for name in expected]
    assert body["total"] == len(expected)
    assert set(body["category_counts"]) == counted, "every filter but the category one"
    assert (body["unread_count"], body["high_unread_count"]) == (4, 3), "the bell's numbers are global"


@pytest.mark.asyncio
async def test_pages_slice_the_ordered_feed(api_client, seeded):
    page = await _feed(api_client, "?limit=2&offset=1")
    assert _ids(page) == [seeded.warning, seeded.closed]
    assert (page["total"], page["limit"], page["offset"]) == (7, 2, 1)
    beyond = await _feed(api_client, "?offset=7")
    assert (_ids(beyond), beyond["total"]) == ([], 7)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "status", "detail"),
    [("?status=bogus", 400, "status must be all or unread"), ("?limit=201", 422, None)],
)
async def test_a_refused_feed_query_keeps_its_status(api_client, seeded, query, status, detail):
    response = await api_client.get(f"/api/notifications{query}")
    assert response.status_code == status
    if detail is not None:
        assert said(response.json()) == {"detail": detail}


@pytest.mark.asyncio
async def test_read_all_hands_back_the_ids_that_undo_it(api_client, db_session, seeded):
    cleared = await api_client.post("/api/notifications/read_all")
    assert cleared.status_code == 200, cleared.text
    body = cleared.json()
    assert set(body) == _fields(contract.NotificationReadAllResponse)
    assert (body["updated"], body["undoable"]) == (4, True)
    assert set(body["ids"]) == {seeded.failed, seeded.closed, seeded.pursuit, seeded.legacy}
    assert (await _feed(api_client))["unread_count"] == 0

    assert (await api_client.post("/api/notifications/read_all")).json() == {
        "updated": 0, "undoable": True, "ids": [],
    }

    undone = await api_client.post("/api/notifications/unread", json={"ids": body["ids"]})
    assert undone.json() == {"updated": 4}
    after = {item["id"]: item for item in (await _feed(api_client))["items"]}
    assert all(after[i]["read_at"] is None for i in body["ids"])
    assert after[seeded.warning]["read_at"] == "2026-07-01T16:00:00Z", "a row read before the clear stays read"


@pytest.mark.asyncio
async def test_a_bulk_unread_moves_only_read_rows_still_in_the_feed(api_client, db_session, seeded):
    before = await _stored(db_session)
    response = await api_client.post(
        "/api/notifications/unread",
        json={"ids": [seeded.warning, seeded.closed, seeded.dismissed, 999_999]},
    )
    assert response.status_code == 200, response.text
    assert set(response.json()) == _fields(contract.NotificationUnreadResponse)
    assert response.json() == {"updated": 1}, "only the read, undismissed row moved"
    after = await _stored(db_session)
    assert after[seeded.warning] == (None, None)
    assert {i: v for i, v in after.items() if i != seeded.warning} == {
        i: v for i, v in before.items() if i != seeded.warning
    }

    assert (await api_client.post("/api/notifications/unread", json={"ids": []})).json() == {"updated": 0}
    too_many = await api_client.post("/api/notifications/unread", json={"ids": list(range(1, 502))})
    assert too_many.status_code == 422
    assert await _stored(db_session) == after


@pytest.mark.asyncio
@pytest.mark.parametrize(("backlog", "undoable"), [(500, True), (501, False)])
async def test_a_clear_too_large_to_undo_says_so(api_client, db_session, no_escape, backlog, undoable):
    await seed_unread_backlog(db_session, backlog)
    body = (await api_client.post("/api/notifications/read_all")).json()
    assert (body["updated"], body["undoable"], len(body["ids"])) == (backlog, undoable, backlog if undoable else 0)


@pytest.mark.asyncio
async def test_each_single_action_answers_with_the_row_it_changed(api_client, seeded):
    read = (await api_client.post(f"/api/notifications/{seeded.closed}/read")).json()
    assert set(read) == _fields(contract.NotificationRow)
    assert (read["id"], read["company"], read["dismissed_at"]) == (seeded.closed, "acme", None)
    assert read["read_at"] is not None

    unread = (await api_client.post(f"/api/notifications/{seeded.warning}/unread")).json()
    assert (unread["id"], unread["read_at"], unread["company"]) == (seeded.warning, None, None)

    dismissed = (await api_client.post(f"/api/notifications/{seeded.digest}/dismiss")).json()
    assert dismissed["dismissed_at"] is not None
    assert dismissed["read_at"] == "2026-07-01T18:00:00Z", "dismissing says nothing about reading"

    restored = (await api_client.post(f"/api/notifications/{seeded.dismissed}/restore")).json()
    assert (restored["id"], restored["dismissed_at"], restored["read_at"], restored["company"]) == (
        seeded.dismissed, None, None, "acme",
    )

    feed = await _feed(api_client)
    items = {item["id"]: item for item in feed["items"]}
    assert seeded.digest not in items and seeded.dismissed in items
    assert items[seeded.closed]["read_at"] == read["read_at"]
    assert items[seeded.warning]["read_at"] is None
    assert (feed["total"], feed["unread_count"]) == (7, 5)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "row", "status"),
    [
        ("read", "dismissed", 404), ("unread", "dismissed", 404),
        ("read", None, 404), ("unread", None, 404), ("dismiss", None, 404), ("restore", None, 404),
        ("read", "malformed", 422),
    ],
)
async def test_a_refused_single_action_changes_nothing(api_client, db_session, seeded, action, row, status):
    target = {None: "999999", "malformed": "abc"}.get(row) or str(getattr(seeded, row))
    before = await _state(api_client, db_session)
    response = await api_client.post(f"/api/notifications/{target}/{action}")
    assert response.status_code == status
    if status == 404:
        assert said(response.json()) == {"detail": "notification not found"}
    assert await _state(api_client, db_session) == before


# --------------------------------------------------------------------------- #
# 3. Drift
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "drift"),
    [
        ("GET", "/api/notifications", lambda row: {**row, "surprise": 1}),
        ("GET", "/api/notifications", lambda row: {k: v for k, v in row.items() if k != "company"}),
        ("POST", "/api/notifications/{closed}/read", lambda row: {**row, "surprise": 1}),
        ("POST", "/api/notifications/{closed}/dismiss", lambda row: {k: v for k, v in row.items() if k != "meta"}),
    ],
    ids=["feed_row_adds_a_key", "feed_row_drops_a_key", "read_row_adds_a_key", "dismiss_row_drops_a_key"],
)
async def test_serializer_drift_fails_the_response_instead_of_reshaping_it(
    api_client, seeded, monkeypatch, method, path, drift
):
    real = notifications_router._serialize_notification
    monkeypatch.setattr(
        notifications_router, "_serialize_notification", lambda *a, **kw: drift(real(*a, **kw))
    )
    with pytest.raises(ResponseValidationError):
        await api_client.request(method, path.format(closed=seeded.closed))
