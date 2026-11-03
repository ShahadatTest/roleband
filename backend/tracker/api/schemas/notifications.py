"""Response contracts for the notification feed.

Every shape here is built by our code, so every model forbids unknown keys: a key
the serializer adds without its model is a 500 a test catches, never output that
silently fails to arrive.

One field is open on purpose. `meta` is JSONB whose keys depend on the category
that wrote it: a sync result with its diagnostics, the live progress a running
sync merges in with raw SQL, a daily digest, a lifecycle event, a pursuit
reminder, and whatever a retired category left behind. It is served exactly as
stored and declared as a JSON object, not typed per category: a dozen writers
build it, and each dashboard reader narrows the keys it uses.

No Literal types. The table has no CHECK constraint and no Python constant names
the categories, priorities or source types, and rows from retired categories
(`new_match`, `sync_success`, `scraper_health`) are still stored and served.

Fields are declared in the order `_serialize_notification` and the handlers build
them, so the response keeps its key order byte for byte.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tracker.api.schemas.base import Built
from tracker.api.schemas.text_class import text


class SaySentence(Built):
    """One message the client says: a catalog key and the values it is said
    with (`tracker/notifications/say.py`). A value is a string, a number, a
    nested sentence or `{"date": "YYYY-MM-DD"}`."""

    k: str = Field(json_schema_extra=text("code"))
    p: dict[str, Any]


class NotificationSay(Built):
    """A notification's words as keys: its title, and its body's
    sentences in order; a string sentence is third-party text shown as written."""

    title: SaySentence
    body: list[SaySentence | str] | None = Field(json_schema_extra=text("content"))


class NotificationRow(Built):
    """One notification, as the feed lists it and every single-row action answers.
    `title` and `body` are the English stored when it was written: the client
    says `meta.say` when it can and shows these otherwise."""

    id: int
    created_at: datetime
    priority: str
    category: str
    title: str = Field(json_schema_extra=text("record"))
    body: str | None = Field(json_schema_extra=text("record"))
    job_id: int | None
    # The linked job's company slug, so a click can build the company-scoped
    # position URL; null for a notification with no job.
    company: str | None
    run_id: int | None
    source_type: str
    read_at: datetime | None
    dismissed_at: datetime | None
    meta: dict[str, Any]


class NotificationListResponse(Built):
    """`GET /api/notifications`: one page, newest first. `total` and
    `category_counts` follow the filters (the counts ignore the category filter
    itself); `unread_count` and `high_unread_count` are global."""

    items: list[NotificationRow]
    total: int
    limit: int
    offset: int
    unread_count: int
    high_unread_count: int
    category_counts: dict[str, int]


class NotificationReadAllResponse(Built):
    """`POST /api/notifications/read_all`: `ids` carries the whole clear back to
    `/unread`, or is empty with `undoable` false when the clear is too large."""

    updated: int
    undoable: bool
    ids: list[int]


class NotificationUnreadResponse(Built):
    """`POST /api/notifications/unread`: how many rows actually moved."""

    updated: int
