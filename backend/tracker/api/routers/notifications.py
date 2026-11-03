"""Notification feed: list, read/unread, dismiss."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.api.deps import Offset, SessionDep
from tracker.api.errors import ErrorCode, api_error
from tracker.api.schemas.notifications import (
    NotificationListResponse,
    NotificationReadAllResponse,
    NotificationRow,
    NotificationUnreadResponse,
)
from tracker.db.models import Job, Notification

router = APIRouter()

# A bulk unread carries the ids `read_all` handed back, so this bound is ONE
# contract across the two endpoints, not a limit each may reason about alone.
# `read_all` clears every unread row there is, not a page, and the feed can
# hold thousands. Above the cap `read_all` therefore declines to offer an undo rather than handing back a body `/unread`
# answers with a 422: a partial restore is worse than an honest refusal.
UNREAD_MAX_IDS = 500

# LIKE metacharacters, escaped with a backslash so a term is text, never a pattern.
_LIKE_ESCAPE = "\\"


class UnreadPayload(BaseModel):
    ids: list[int] = Field(max_length=UNREAD_MAX_IDS)


def _like_term(q: str) -> str:
    """`%term%` with the user's `%`, `_` and `\\` escaped for `ilike(escape=_LIKE_ESCAPE)`."""
    escaped = (
        q.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"


def _feed_conditions(
    status: str,
    priority: str | None,
    categories: list[str] | None,
    q: str | None,
) -> list:
    """WHERE for the feed. The facet-count query calls this with `categories=None`
    so every other condition applies and the category facet itself does not."""
    conds = [Notification.dismissed_at.is_(None)]
    if status == "unread":
        conds.append(Notification.read_at.is_(None))
    elif status != "all":
        raise api_error(400, ErrorCode.INVALID_INPUT, "status must be all or unread")
    if priority:
        conds.append(Notification.priority == priority)
    term = (q or "").strip()
    if term:
        pattern = _like_term(term)
        conds.append(
            or_(
                Notification.title.ilike(pattern, escape=_LIKE_ESCAPE),
                func.coalesce(Notification.body, "").ilike(pattern, escape=_LIKE_ESCAPE),
            )
        )
    if categories:
        conds.append(Notification.category.in_(categories))
    return conds


def _serialize_notification(n: Notification, company: str | None = None) -> dict:
    return {
        "id": n.id,
        "created_at": n.created_at,
        "priority": n.priority,
        "category": n.category,
        "title": n.title,
        "body": n.body,
        "job_id": n.job_id,
        # Company slug of the linked job, so a notification click can build the
        # company-scoped position URL (/companies/:slug/jobs/:id) directly. Null
        # for run/health notifications that have no job.
        "company": company,
        "run_id": n.run_id,
        "source_type": n.source_type,
        "read_at": n.read_at,
        "dismissed_at": n.dismissed_at,
        "meta": n.meta or {},
    }


async def _company_for_job(session: AsyncSession, job_id: int | None) -> str | None:
    """Resolve a notification's linked-job company slug (null when unlinked)."""
    if job_id is None:
        return None
    return await session.scalar(select(Job.company).where(Job.id == job_id))


def _notification_ordering() -> tuple:
    """Newest notification first; priority only resolves simultaneous rows.

    The feed is paginated (15 in the bell, 100 in the center). Priority-first
    ordering can permanently bury a fresh normal-priority sync result behind an
    older high-priority backlog.
    """
    priority_rank = case(
        (Notification.priority == "high", 0),
        (Notification.priority == "normal", 1),
        else_=2,
    )
    return (Notification.created_at.desc(), priority_rank.asc(), Notification.id.desc())


@router.get("/api/notifications", response_model=NotificationListResponse)
async def notifications(
    session: SessionDep,
    status: str = "all",
    priority: str | None = None,
    category: Annotated[list[str] | None, Query()] = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Offset = 0,
) -> dict:
    conds = _feed_conditions(status, priority, category, q)

    base = select(Notification).where(and_(*conds))
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    # The bell's numbers: global, so they never move under a search or a lens.
    unread_count = await session.scalar(
        select(func.count()).where(
            Notification.dismissed_at.is_(None),
            Notification.read_at.is_(None),
        )
    )
    high_unread_count = await session.scalar(
        select(func.count()).where(
            Notification.dismissed_at.is_(None),
            Notification.read_at.is_(None),
            Notification.priority == "high",
        )
    )
    # Facet counts: every other condition applies, the category facet itself
    # does not, so an unselected category still says how many it would show.
    facet_rows = (
        await session.execute(
            select(Notification.category, func.count())
            .where(and_(*_feed_conditions(status, priority, None, q)))
            .group_by(Notification.category)
        )
    ).all()
    category_counts = {cat: int(n) for cat, n in facet_rows}

    rows = (
        await session.scalars(
            base.order_by(*_notification_ordering())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    # Batch-resolve the linked-job company slug for the page (one query) so each
    # notification can build its company-scoped position URL client-side.
    job_ids = {n.job_id for n in rows if n.job_id is not None}
    company_by_job: dict[int, str] = {}
    if job_ids:
        company_by_job = dict(
            (await session.execute(
                select(Job.id, Job.company).where(Job.id.in_(job_ids))
            )).all()
        )
    return {
        "items": [_serialize_notification(n, company_by_job.get(n.job_id)) for n in rows],
        "total": total or 0,
        "limit": limit,
        "offset": offset,
        "unread_count": unread_count or 0,
        "high_unread_count": high_unread_count or 0,
        "category_counts": category_counts,
    }


@router.post("/api/notifications/read_all", response_model=NotificationReadAllResponse)
async def notifications_read_all(session: SessionDep) -> dict:
    now = datetime.now(UTC)
    rows = (
        await session.scalars(
            select(Notification).where(
                Notification.dismissed_at.is_(None),
                Notification.read_at.is_(None),
            )
        )
    ).all()
    for row in rows:
        row.read_at = now
    await session.commit()
    # The ids are the way back: the client's Undo posts them to /unread. They are
    # offered only when they can carry the WHOLE clear -- `undoable` says so
    # explicitly rather than leaving the client to infer it from a list length,
    # because "fewer ids than rows" and "no undo" must not look the same.
    undoable = len(rows) <= UNREAD_MAX_IDS
    return {
        "updated": len(rows),
        "undoable": undoable,
        "ids": [row.id for row in rows] if undoable else [],
    }


@router.post("/api/notifications/unread", response_model=NotificationUnreadResponse)
async def notifications_unread(payload: UnreadPayload, session: SessionDep) -> dict:
    """Bulk unread — the undo of `read_all`. One UPDATE; dismissed rows and rows
    already unread are left alone, so `updated` counts what actually moved."""
    if not payload.ids:
        return {"updated": 0}
    result = await session.execute(
        update(Notification)
        .where(
            Notification.id.in_(payload.ids),
            Notification.dismissed_at.is_(None),
            Notification.read_at.is_not(None),
        )
        .values(read_at=None)
    )
    await session.commit()
    return {"updated": result.rowcount}


@router.post("/api/notifications/{notification_id}/read", response_model=NotificationRow)
async def notification_read(notification_id: int, session: SessionDep) -> dict:
    row = await session.get(Notification, notification_id)
    if row is None or row.dismissed_at is not None:
        raise api_error(404, ErrorCode.NOTIFICATION_NOT_FOUND, "notification not found")
    row.read_at = datetime.now(UTC)
    await session.commit()
    return _serialize_notification(row, await _company_for_job(session, row.job_id))


@router.post("/api/notifications/{notification_id}/unread", response_model=NotificationRow)
async def notification_unread(notification_id: int, session: SessionDep) -> dict:
    row = await session.get(Notification, notification_id)
    if row is None or row.dismissed_at is not None:
        raise api_error(404, ErrorCode.NOTIFICATION_NOT_FOUND, "notification not found")
    row.read_at = None
    await session.commit()
    return _serialize_notification(row, await _company_for_job(session, row.job_id))


@router.post("/api/notifications/{notification_id}/dismiss", response_model=NotificationRow)
async def notification_dismiss(notification_id: int, session: SessionDep) -> dict:
    row = await session.get(Notification, notification_id)
    if row is None:
        raise api_error(404, ErrorCode.NOTIFICATION_NOT_FOUND, "notification not found")
    row.dismissed_at = datetime.now(UTC)
    await session.commit()
    return _serialize_notification(row, await _company_for_job(session, row.job_id))


@router.post("/api/notifications/{notification_id}/restore", response_model=NotificationRow)
async def notification_restore(notification_id: int, session: SessionDep) -> dict:
    """The undo of `dismiss`. Dismissal is a timestamp, not a delete, so the way
    back is to clear it -- and read state is deliberately untouched, because
    dismissing a row never claimed anything about whether it had been read."""
    row = await session.get(Notification, notification_id)
    if row is None:
        raise api_error(404, ErrorCode.NOTIFICATION_NOT_FOUND, "notification not found")
    row.dismissed_at = None
    await session.commit()
    return _serialize_notification(row, await _company_for_job(session, row.job_id))
