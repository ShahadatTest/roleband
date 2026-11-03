"""Persist generated notifications: dedupe-insert plus per-run generation queries."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from tracker.db.models import Job, JobLifecycleEvent, Notification, ScrapeRun, TrackedCompany
from tracker.db.queries.companies import display_names
from tracker.lineage.place_sets import still_listed_elsewhere
from tracker.notifications.channels import deliver
from tracker.notifications.coverage import generate_coverage_notifications
from tracker.notifications.digest import digest_days, generate_daily_digest
from tracker.notifications.events import classify_event
from tracker.notifications.pursuit_due import generate_pursuit_due_notifications
from tracker.notifications.run_result import classify_sync_result, classify_sync_started
from tracker.notifications.tracked import tracked_job_ids


async def _insert_notification(session: AsyncSession, values: dict) -> None:
    """Run/job notifications: write once, never overwrite.

    No `refresh`, so a re-run cannot re-ring a notification the user has already
    read. Goes through the channel seam like every other write.
    """

    await deliver(session, values)


async def generate_sync_started_notification(
    session: AsyncSession, run: ScrapeRun, sources: list[str]
) -> int:
    """Create the durable "running" notification for a newly opened run."""

    # Sweep carriers left behind by runs that died without a terminal pass (a
    # crash, a kill, a reconciled stale run). Without this the one category that
    # is supposed to be transient is the one that leaks, and the feed slowly
    # refills with "Sync started" rows for runs that ended days ago.
    await session.execute(
        delete(Notification).where(
            Notification.source_type == "run",
            Notification.category == "sync_started",
            Notification.source_id.in_(
                select(ScrapeRun.id).where(ScrapeRun.status != "running")
            ),
        )
    )

    classified = classify_sync_started(run, sources, names=await display_names(session))
    await _insert_notification(
        session,
        {
            "created_at": run.started_at or datetime.now(UTC),
            "priority": classified.priority,
            "category": classified.category,
            "title": classified.title,
            "body": classified.body,
            "job_id": None,
            "run_id": run.id,
            "source_type": "run",
            "source_id": run.id,
            "meta": classified.meta or {},
        },
    )
    return 1


async def _retire_sync_started(session: AsyncSession, run_id: int) -> None:
    """Drop the run's `sync_started` row once the run has a terminal outcome.

    `sync_started` is not a feed entry: it is the carrier the live progress
    panel reads (`meta.progress`, written by `update_sync_progress`, rendered by
    `sync-progress/SyncProgressPanel.tsx`). It has to exist WHILE the run is in
    flight and has no reason to exist afterwards; left behind, it would stand in
    the feed for a run that had already finished.

    Deleting it here, rather than never writing it, is what keeps the progress
    panel working while taking the residue out of the feed.
    """
    await session.execute(
        delete(Notification).where(
            Notification.source_type == "run",
            Notification.source_id == run_id,
            Notification.category == "sync_started",
        )
    )


async def generate_sync_result_notification(
    session: AsyncSession,
    run: ScrapeRun,
    *,
    failure: str | None = None,
    names: dict[str, str] | None = None,
) -> int:
    """Create the terminal notification for a run outcome, if it warrants one.

    Returns 0 for a clean run: `classify_sync_result` yields None there, because
    a sync that did exactly what it was supposed to do is not news. The
    `sync_started` carrier is retired either way.

    `failure` is the pipeline exception when there was one, passed in rather
    than sniffed out of `run.notes`. A run whose SOURCES were fine
    and whose derivation blew up keeps its `ok`/`partial` status, so the
    status alone cannot tell the classifier that anything went wrong, and a
    derivation failure must not go silent.

    `names` is the register's `slug -> display` when the caller already read
    it (`generate_notifications`); otherwise the run's own companies are read.
    """

    await _retire_sync_started(session, run.id)

    # The names the user knows its companies by, the ones Coverage copy uses.
    slugs = list(run.per_source or {})
    if names is None and slugs:
        rows = await session.execute(
            select(TrackedCompany.slug, TrackedCompany.display).where(TrackedCompany.slug.in_(slugs))
        )
        names = {slug: display for slug, display in rows.all() if display}
    classified = classify_sync_result(run, failure=failure, names=names)
    if classified is None:
        return 0
    await _insert_notification(
        session,
        {
            "created_at": run.finished_at or run.started_at or datetime.now(UTC),
            "priority": classified.priority,
            "category": classified.category,
            "title": classified.title,
            "body": classified.body,
            "job_id": None,
            "run_id": run.id,
            "source_type": "run",
            "source_id": run.id,
            "meta": classified.meta or {},
        },
    )
    return 1


async def update_sync_progress(session: AsyncSession, run_id: int, progress: dict) -> None:
    """Merge a live progress snapshot into the run's ``sync_started`` notification.

    JSONB ``||`` replaces only the ``progress`` key, so the sync_started meta
    written at run open (sources, started_at, sync_state) survives every update.
    A no-op when the notification is absent — progress is a display concern and
    must never fail a run.
    """
    await session.execute(
        text(
            "UPDATE notifications SET meta = meta || CAST(:payload AS jsonb) "
            "WHERE source_type = 'run' AND source_id = :run_id "
            "AND category = 'sync_started'"
        ),
        {"payload": json.dumps({"progress": progress}), "run_id": run_id},
    )


async def generate_notifications(
    session: AsyncSession,
    run: ScrapeRun,
    *,
    include_run: bool = True,
    failure: str | None = None,
) -> int:
    """Materialize this run's notifications across the three channels.

    The channels, and why they are separate:

    * **Tracked** -- per-role events for saved/pursued roles only. Interrupts,
      because the user committed to these. Gated by `tracked_job_ids`.
    * **Discovery** -- one fit-ranked digest row for the day. Ambient, because
      browsing has a daily rhythm, not a per-scrape one.
    * **Operations** -- the run's own outcome, and only when it was not clean.

    Mixing an ambient signal into an interrupt channel makes the feed
    unreadable: it gets cleared in bulk rather than read.

    Discovery micro-runs set ``include_run=False``: the digest and tracked events
    still land, but the feed gets no operational row for a provider probe.
    """

    tracked = await tracked_job_ids(session)
    # Every row this pass writes names a company as the user follows it
    # (`tracked_company.display`), read once for the whole pass.
    names = await display_names(session)
    # Per-role events are for tracked roles only (`classify_event`), so only
    # theirs load, with only the columns a notification names: a first scan
    # after Follow all opens thousands of roles and tracks a handful.
    rows = (
        (
            await session.execute(
                select(JobLifecycleEvent, Job)
                .join(Job, Job.id == JobLifecycleEvent.job_id)
                .where(JobLifecycleEvent.run_id == run.id, JobLifecycleEvent.job_id.in_(sorted(tracked)))
                .options(load_only(Job.id, Job.company, Job.title, Job.total_days_open, Job.lineage_role))
                .order_by(JobLifecycleEvent.id.asc())
            )
        ).all()
        if tracked
        else []
    )
    # Every event's time, tracked or not: the digest covers each local day the
    # run touched.
    touched_at = (
        await session.scalars(select(JobLifecycleEvent.created_at).where(JobLifecycleEvent.run_id == run.id))
    ).all()

    # A tracked posting that closed while its role stays listed at other places
    # is not a closed role. Asked once for the run's closings.
    elsewhere = await still_listed_elsewhere(
        session,
        (job.id for event, job in rows if event.event_type == "closed" and job.id in tracked),
    )

    attempted = 0
    for event, job in rows:
        classified = classify_event(
            event.event_type,
            event.detail or {},
            job,
            job.id in tracked,
            lineage_role=job.lineage_role,
            listed_elsewhere=[
                (p.id, (p.cities or p.locations or ("",))[0])
                for p in elsewhere.get(job.id, ())
            ]
            if event.event_type == "closed"
            else (),
            names=names,
        )
        if classified is None:
            continue
        attempted += 1
        await _insert_notification(
            session,
            {
                "created_at": event.created_at,
                "priority": classified.priority,
                "category": classified.category,
                "title": classified.title,
                "body": classified.body,
                "job_id": classified.job_id or job.id,
                "run_id": run.id,
                "source_type": "event",
                "source_id": event.id,
                "meta": classified.meta or {},
            },
        )

    # Discovery. Recomputed from the whole day, so this converges rather than
    # accumulating across the scheduler's runs of a day, and for every
    # local day this run actually touched, not just today: the scheduler runs
    # through the night, and a scrape spanning local midnight otherwise leaves
    # the roles it found before midnight in no digest at all.
    for target in digest_days(touched_at):
        attempted += await generate_daily_digest(session, tracked, day=target, names=names)

    # The follow-ups the user owes. Independent of what this run scraped, but
    # reconciled here because a scrape is the reliable heartbeat this tool has.
    attempted += await generate_pursuit_due_notifications(session, names=names)

    # Followed companies RoleBand cannot scan cleanly. Reconciled on
    # the same heartbeat: this run's per-company commits have already written
    # the health it reads.
    attempted += await generate_coverage_notifications(session)

    if not include_run:
        return attempted

    attempted += await generate_sync_result_notification(session, run, failure=failure, names=names)
    return attempted
