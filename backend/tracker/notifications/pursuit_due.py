"""Overdue follow-ups on active pursuits (`pursuits.next_action_due`).

The one notification whose absence costs the user an opportunity: a follow-up
they owe and forgot.

Reconciled, not appended. Each pass rewrites the set of open `pursuit_due` rows
to match reality: overdue pursuits get a row, pursuits that are not overdue any
more (actioned, rescheduled, or advanced to a terminal stage) lose theirs. That is
what makes it safe to run on every scrape -- the alternative, insert-and-dedupe,
would leave a stale "3d overdue" row standing after the user had already done the
thing, and an alert that outlives its cause is worse than no alert.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Job, Notification, Pursuit
from tracker.db.queries.companies import display_names
from tracker.notifications import say as S
from tracker.notifications.channels import deliver
from tracker.notifications.events import ClassifiedNotif, _said
from tracker.notifications.render import company_namer
from tracker.platform.locks import advisory_xact_lock

#: Stages where a follow-up is not owed, from the stage vocabulary in
#: `agents/pursuits.py::PursuitStage`. `offer` is deliberately NOT terminal:
#: an outstanding offer is the point at which a missed follow-up costs the most.
TERMINAL_STAGES = frozenset({"rejected", "withdrawn"})


def classify_pursuit_due(
    company: str,
    title: str,
    stage: str,
    next_action: str | None,
    days_overdue: int,
    *,
    names: Mapping[str, str] | None = None,
) -> ClassifiedNotif:
    """The follow-up you owe on a role you are actively pursuing.

    The highest-value notification in a job-seeker tool: a missed follow-up
    (`pursuits.next_action_due`) is the expensive failure mode in this
    product.
    """
    return ClassifiedNotif(
        priority="high",
        category="pursuit_due",
        meta={
            "company": company,
            "stage": stage,
            "days_overdue": days_overdue,
            "next_action": next_action,
            "say": _said(
                S.say(
                    "notif-follow-up",
                    company=company_namer(names)(company),
                    when=S.say("notif-due-today") if days_overdue <= 0 else S.say("notif-overdue", days=days_overdue),
                ),
                S.say(
                    "notif-follow-up-body",
                    action=next_action or S.say("notif-no-next-action"),
                    title=title,
                    stage=stage,
                ),
            ),
        },
    )


def classify_pursuit_quiet(
    company: str,
    title: str,
    stage: str,
    days_quiet: int,
    *,
    names: Mapping[str, str] | None = None,
) -> ClassifiedNotif:
    """A pursuit at a waiting stage that has gone quiet: no follow-up date
    and no activity for longer than its stage waits (`pursuit_due.QUIET_AFTER_DAYS`).
    A reminder, like an overdue follow-up, and filed with them."""
    return ClassifiedNotif(
        priority="normal",
        category="pursuit_due",
        meta={
            "company": company,
            "stage": stage,
            "days_quiet": days_quiet,
            "say": _said(
                S.say("notif-gone-quiet", company=company_namer(names)(company), days=days_quiet),
                S.say("notif-gone-quiet-body", title=title, stage=stage),
            ),
        },
    )


def overdue_pursuit_clause(now: datetime):
    """One definition of "a follow-up is owed", for every surface that counts them.

    Three decisions live in here and none of them is obvious enough to restate:
    a pursuit with no `next_action_due` owes nothing; `<=` means a follow-up due
    exactly now IS owed; and `offer` is not terminal. Every counter, the MCP
    radar summary included, reads it here, so none can miss the overdue
    follow-up the product considers most expensive.
    """
    return and_(
        Pursuit.next_action_due.isnot(None),
        Pursuit.next_action_due <= now,
        Pursuit.stage.not_in(TERMINAL_STAGES),
    )


#: How long a pursuit may wait at a stage with no follow-up date and no activity
#: before it has gone quiet: an application usually hears back within three
#: weeks, an interview loop within two. Stages not named here never go quiet.
QUIET_AFTER_DAYS: dict[str, int] = {"applied": 21, "interviewing": 12}


#: No stage goes quiet sooner: a weekend must not use one up.
QUIET_FLOOR_DAYS = 5


def quiet_after(stage: str) -> timedelta | None:
    days = QUIET_AFTER_DAYS.get(stage)
    return timedelta(days=max(QUIET_FLOOR_DAYS, days)) if days is not None else None


#: One reconcile at a time: the run's finalization, a pursuit write
#: (dashboard or agent) and the idle tick all reconcile, and two of them
#: touching the reminder rows in opposite orders would deadlock.
PURSUIT_DUE_LOCK_KEY = 91246


async def generate_pursuit_due_notifications(
    session: AsyncSession, *, names: dict[str, str] | None = None
) -> int:
    """Reconcile `pursuit_due` rows against currently-overdue pursuits.

    Callers: every run's finalization, every pursuit write (HTTP
    and MCP, in the write's transaction, so ending a pursuit retracts its
    reminder with the write), and the scheduler's idle tick, so a follow-up
    that falls due rings with no scan. Serialized by `PURSUIT_DUE_LOCK_KEY`.
    `names` is the register's `slug -> display`, read here when not passed.
    """
    await advisory_xact_lock(session, PURSUIT_DUE_LOCK_KEY)
    now = datetime.now(UTC)

    rows = (
        await session.execute(
            select(Pursuit, Job)
            .join(Job, Job.id == Pursuit.job_id)
            .where(overdue_pursuit_clause(now))
            .order_by(Pursuit.next_action_due.asc())
        )
    ).all()

    overdue_ids = {pursuit.id for pursuit, _ in rows}
    if names is None and rows:
        names = await display_names(session)

    # Retract first. A pursuit that was actioned since the last pass must lose
    # its row in the same transaction that would otherwise re-assert it.
    stale = delete(Notification).where(Notification.source_type == "pursuit")
    if overdue_ids:
        stale = stale.where(Notification.source_id.not_in(overdue_ids))
    await session.execute(stale)

    written = 0
    for pursuit, job in rows:
        due = pursuit.next_action_due
        days_overdue = max(0, (now - due).days) if due else 0
        classified = classify_pursuit_due(
            job.company, job.title, pursuit.stage, pursuit.next_action, days_overdue, names=names
        )
        # A row that stands for an EARLIER follow-up (another due time) is not
        # this one: delete it, so the new debt rings unread instead of
        # inheriting the read or dismissed state the person gave the old one.
        # The same due time keeps its row, and the person's word.
        await session.execute(
            delete(Notification).where(
                Notification.source_type == "pursuit",
                Notification.source_id == pursuit.id,
                Notification.category == classified.category,
                Notification.meta["due_at"].astext.is_distinct_from(
                    due.isoformat() if due else None
                ),
            )
        )
        # Refreshed in place so the row ages with the debt ("2d overdue" becomes
        # "3d overdue") without re-ringing: `created_at` and `read_at` are not
        # refreshable, so one forgotten follow-up is one notification, not one
        # a day.
        await deliver(
            session,
            {
                "created_at": now,
                "priority": classified.priority,
                "category": classified.category,
                "title": classified.title,
                "body": classified.body,
                "job_id": job.id,
                "run_id": None,
                "source_type": "pursuit",
                "source_id": pursuit.id,
                "meta": {
                    **(classified.meta or {}),
                    "due_at": due.isoformat() if due else None,
                },
            },
            refresh=("title", "body", "meta"),
        )
        written += 1
    return written + await _reconcile_quiet(session, now, names)


async def _reconcile_quiet(session: AsyncSession, now: datetime, names: dict[str, str] | None) -> int:
    """Reconcile the quiet-pursuit rows (`source_type` "quiet"): a pursuit at a waiting stage with no
    follow-up date and no activity (`updated_at`) for longer than its stage
    waits. One row per silence: keyed by the last activity, so it rings once,
    and again only after new activity has gone quiet in turn; activity, a
    follow-up date or another stage retracts it."""
    rows = (
        await session.execute(
            select(Pursuit, Job)
            .join(Job, Job.id == Pursuit.job_id)
            .where(Pursuit.stage.in_(list(QUIET_AFTER_DAYS)), Pursuit.next_action_due.is_(None))
        )
    ).all()
    quiet = [(p, j) for p, j in rows if now - p.updated_at >= quiet_after(p.stage)]  # type: ignore[operator]
    since = {p.id: p.updated_at.isoformat() for p, _ in quiet}

    current = delete(Notification).where(Notification.source_type == "quiet")
    if since:
        # A row stands only for the silence it was raised for.
        keep = [
            (Notification.source_id == pid) & (Notification.meta["since"].astext == at)
            for pid, at in since.items()
        ]
        current = current.where(not_(or_(*keep)))
    await session.execute(current)

    if quiet and names is None:
        names = await display_names(session)
    for pursuit, job in quiet:
        classified = classify_pursuit_quiet(
            job.company, job.title, pursuit.stage, (now - pursuit.updated_at).days, names=names
        )
        await deliver(
            session,
            {
                "created_at": now,
                "priority": classified.priority,
                "category": classified.category,
                "title": classified.title,
                "body": classified.body,
                "job_id": job.id,
                "run_id": None,
                "source_type": "quiet",
                "source_id": pursuit.id,
                "meta": {**(classified.meta or {}), "since": since[pursuit.id]},
            },
            refresh=("title", "body", "meta"),
        )
    return len(quiet)
