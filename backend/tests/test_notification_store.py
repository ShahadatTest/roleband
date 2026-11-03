"""Integration tests for notification materialization. Real Postgres, real SQL.

These cover what the pure classifier tests structurally cannot: ON CONFLICT
convergence, the DELETE that retracts a stale alert, and the end-to-end claim
that an untracked lifecycle event writes no row at all. Every one of these
behaviours is a SQL statement, so a faked session would be testing the mock.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import func, select

from tracker.connectors.recipes.outcome import classify_source_outcome
from tracker.db.models import (
    Favorite,
    Job,
    JobLifecycleEvent,
    JobLineage,
    Notification,
    Pursuit,
    ScrapeRun,
    TrackedCompany,
)
from tracker.notifications import (
    generate_notifications,
    generate_pursuit_due_notifications,
    generate_sync_started_notification,
    overdue_pursuit_clause,
    tracked_job_ids,
)
from tracker.workflows.collection_types import empty_stats

pytestmark = pytest.mark.asyncio

# Local noon today. The digest keys on the machine's LOCAL calendar day (see
# `digest.local_today`), so a hardcoded UTC instant would drift in and out of
# "today" depending on the runner's offset: a UTC-midnight boundary puts the
# fixture events in tomorrow on a UTC+2 host.
_LOCAL_TZ = datetime.now().astimezone().tzinfo
TODAY = datetime.now(_LOCAL_TZ).date()
NOW = datetime.combine(TODAY, time(12, 0), tzinfo=_LOCAL_TZ).astimezone(UTC)


async def _job(session, *, company="google", title="Staff PM", **kw) -> Job:
    job = Job(
        company=company,
        title=title,
        url=kw.pop("url", f"https://example.test/{company}/{title}"),
        level_band=kw.pop("level_band", "L6"),
        req_id=kw.pop("req_id", f"r-{title}-{company}"),
        dedupe_key=kw.pop("dedupe_key", f"k-{title}-{company}"),
        status=kw.pop("status", "open"),
        first_seen=NOW - timedelta(days=5),
        last_seen=NOW,
        total_days_open=5,
        repost_count=0,
        in_scope=kw.pop("in_scope", True),
        **kw,
    )
    session.add(job)
    await session.flush()
    return job


async def _run(session, *, status="ok") -> ScrapeRun:
    run = ScrapeRun(
        status=status,
        started_at=NOW - timedelta(minutes=5),
        finished_at=NOW,
        jobs_seen=1,
        jobs_new=1,
        jobs_closed=0,
        per_source={"google": {"scanned": 1, "kept": 1, "new": 1, "closed": 0, "errors": []}},
        drift_alerts=[],
    )
    session.add(run)
    await session.flush()
    return run


async def _event(session, run, job, event_type, detail=None, at=NOW):
    if event_type == "opened":
        # A scan's creation event is the role's first sighting, as the writer stores it.
        job.first_seen = at
    ev = JobLifecycleEvent(
        job_id=job.id, run_id=run.id, event_type=event_type, detail=detail or {}, created_at=at
    )
    session.add(ev)
    await session.flush()
    return ev


async def _categories(session) -> dict[str, int]:
    rows = (
        await session.execute(select(Notification.category, func.count()).group_by(Notification.category))
    ).all()
    return dict(rows)


# --------------------------------------------------------------------------
# The gate, end to end
# --------------------------------------------------------------------------


async def test_untracked_closure_writes_no_notification(db_session):
    """An untracked role's closure must not interrupt the user."""
    run = await _run(db_session)
    job = await _job(db_session, title="Untracked PM")
    await _event(db_session, run, job, "closed")

    await generate_notifications(db_session, run, include_run=False)

    assert (await _categories(db_session)).get("closed") is None


async def test_saved_role_closure_does_notify(db_session):
    run = await _run(db_session)
    job = await _job(db_session, title="Saved PM")
    db_session.add(Favorite(job_id=job.id))
    await db_session.flush()
    await _event(db_session, run, job, "closed")

    await generate_notifications(db_session, run, include_run=False)

    row = (
        await db_session.scalars(select(Notification).where(Notification.category == "closed"))
    ).one()
    assert row.priority == "high"
    assert row.job_id == job.id


async def test_pursued_role_is_tracked_even_without_a_favorite(db_session):
    """"Tracked" is saved OR in the pipeline. A pursuit is not necessarily a
    favorite, and gating on favorites alone would silence the user's most
    committed work."""
    job = await _job(db_session, title="Pursued PM")
    db_session.add(Pursuit(job_id=job.id, stage="interviewing", priority=3))
    await db_session.flush()

    assert await tracked_job_ids(db_session) == {job.id}


async def test_tracked_set_widens_across_repost_lineage(db_session):
    """A repost is a NEW row with a new req_id. Without lineage widening the
    successor of a saved role is an untracked stranger and rings nothing."""
    original = await _job(db_session, title="Orig", dedupe_key="k1", req_id="r1")
    successor = await _job(db_session, title="Repost", dedupe_key="k2", req_id="r2")
    lineage = JobLineage(
        company="google", root_job_id=original.id, first_seen=NOW, last_seen=NOW
    )
    db_session.add(lineage)
    await db_session.flush()

    original.lineage_id = lineage.id
    successor.lineage_id = lineage.id
    db_session.add(Favorite(job_id=original.id))
    await db_session.flush()

    assert await tracked_job_ids(db_session) == {original.id, successor.id}


# --------------------------------------------------------------------------
# Digest convergence across repeated scheduler passes
# --------------------------------------------------------------------------


async def test_digest_converges_to_one_row_across_repeated_runs(db_session):
    """Repeated runs recompute one digest row rather than append another."""
    for i in range(3):
        run = await _run(db_session)
        job = await _job(db_session, title=f"Role {i}", dedupe_key=f"k{i}", req_id=f"r{i}")
        await _event(db_session, run, job, "opened")
        await generate_notifications(db_session, run, include_run=False)

    digests = (
        await db_session.scalars(
            select(Notification).where(Notification.category == "daily_digest")
        )
    ).all()
    assert len(digests) == 1
    assert digests[0].meta["count"] == 3
    assert digests[0].title == "3 new roles for you today"


async def test_a_run_reads_whole_rows_only_for_the_roles_it_tracks(db_session):
    """Untracked roles reach the user through the digest, so the per-role pass
    reads only tracked roles' events, and never a description or a vector."""
    from sqlalchemy import event as sa_event

    run = await _run(db_session)
    saved = await _job(db_session, title="Saved", dedupe_key="s1", req_id="s1")
    db_session.add(Favorite(job_id=saved.id))
    await _event(db_session, run, saved, "closed")
    for i in range(5):
        other = await _job(db_session, title=f"Other {i}", dedupe_key=f"o{i}", req_id=f"o{i}")
        await _event(db_session, run, other, "opened")
    await db_session.flush()

    joined: list[tuple[int, list[str]]] = []

    def record(_conn, cursor, statement, _parameters, _context, _executemany):
        if "FROM job_lifecycle_events JOIN jobs" in statement:
            joined.append((cursor.rowcount, [column[0] for column in cursor.description or ()]))

    engine = db_session.bind.sync_engine
    sa_event.listen(engine, "after_cursor_execute", record)
    try:
        await generate_notifications(db_session, run, include_run=False)
    finally:
        sa_event.remove(engine, "after_cursor_execute", record)

    assert [rows for rows, _ in joined] == [1], "only the tracked role's event is read with its role"
    assert not [name for name in joined[0][1] if "description" in name or "embedding" in name]
    assert (await _categories(db_session)).get("closed") == 1
    digest = (
        await db_session.scalars(select(Notification).where(Notification.category == "daily_digest"))
    ).one()
    assert digest.meta["count"] == 5, "the untracked roles still reach the digest"


async def test_a_day_past_the_ranking_ceiling_still_counts_every_role_and_company(db_session, monkeypatch):
    """Ranking reads a capped sample; the count and the companies it names do
    not stop at the cap."""
    from tracker.notifications import digest as digest_module

    monkeypatch.setattr(digest_module, "_DIGEST_SCAN_LIMIT", 2)
    run = await _run(db_session)
    for i, company in enumerate(("google", "google", "openai")):
        job = await _job(db_session, company=company, title=f"Role {i}", dedupe_key=f"c{i}", req_id=f"c{i}")
        await _event(db_session, run, job, "opened")
    await generate_notifications(db_session, run, include_run=False)

    digest = (
        await db_session.scalars(select(Notification).where(Notification.category == "daily_digest"))
    ).one()
    assert (digest.meta["count"], digest.meta["companies"]) == (3, ["google", "openai"])
    assert digest.title == "3 new roles for you today"
    assert len(digest.meta["top"]) == 2, "the ranked sample itself stays capped"


async def test_digest_refresh_does_not_re_ring_a_read_row(db_session):
    """Re-marking the digest unread on every scrape would make it a per-run
    interrupt."""
    run = await _run(db_session)
    job = await _job(db_session, title="First", dedupe_key="k1", req_id="r1")
    await _event(db_session, run, job, "opened")
    await generate_notifications(db_session, run, include_run=False)

    digest = (
        await db_session.scalars(
            select(Notification).where(Notification.category == "daily_digest")
        )
    ).one()
    read_stamp = NOW
    digest.read_at = read_stamp
    first_created = digest.created_at
    await db_session.flush()

    run2 = await _run(db_session)
    job2 = await _job(db_session, title="Second", dedupe_key="k2", req_id="r2")
    await _event(db_session, run2, job2, "opened")
    await generate_notifications(db_session, run2, include_run=False)

    await db_session.refresh(digest)
    assert digest.meta["count"] == 2
    assert digest.read_at == read_stamp
    assert digest.created_at == first_created


async def test_tracked_role_is_not_double_reported_in_the_digest(db_session):
    """A tracked role already got its own row; counting it again in the digest
    would report one event twice."""
    run = await _run(db_session)
    job = await _job(db_session, title="Saved PM")
    db_session.add(Favorite(job_id=job.id))
    await db_session.flush()
    await _event(db_session, run, job, "opened")

    await generate_notifications(db_session, run, include_run=False)

    assert (await _categories(db_session)).get("daily_digest") is None


async def test_out_of_scope_role_never_reaches_the_digest(db_session):
    """The digest must not advertise a role the Board would not display."""
    run = await _run(db_session)
    job = await _job(db_session, title="Out of scope", in_scope=False)
    await _event(db_session, run, job, "opened")

    await generate_notifications(db_session, run, include_run=False)

    assert (await _categories(db_session)).get("daily_digest") is None


# --------------------------------------------------------------------------
# Sync carrier lifecycle
# --------------------------------------------------------------------------


async def test_sync_started_is_retired_when_the_run_finishes(db_session):
    """A sync carrier exists for live progress and must not outlive its run."""
    run = await _run(db_session, status="ok")
    run.status = "running"
    await db_session.flush()
    db_session.add(TrackedCompany(slug="google", display="Google Careers", adapter="google", status="active",
                                  enabled=True, visible=True, source="builtin"))
    await db_session.flush()
    await generate_sync_started_notification(db_session, run, ["google"])
    assert (await _categories(db_session)).get("sync_started") == 1
    started = await db_session.scalar(select(Notification).where(Notification.category == "sync_started"))
    assert started.body == "Scanning 1 company: Google Careers.", "the name the person follows it by"

    run.status = "ok"
    await db_session.flush()
    await generate_notifications(db_session, run, include_run=True)

    cats = await _categories(db_session)
    assert cats.get("sync_started") is None
    assert cats.get("sync_success") is None  # a clean run says nothing at all


async def test_orphaned_carrier_from_a_crashed_run_is_swept(db_session):
    """A run killed before its terminal pass leaves a carrier behind. The one
    category that is supposed to be transient must not be the one that leaks."""
    dead = await _run(db_session, status="error")
    dead.status = "running"
    await db_session.flush()
    await generate_sync_started_notification(db_session, dead, ["google"])
    dead.status = "error"  # reconciled by the watchdog, no terminal pass ran
    await db_session.flush()

    live = await _run(db_session)
    live.status = "running"
    await db_session.flush()
    await generate_sync_started_notification(db_session, live, ["apple"])

    rows = (
        await db_session.scalars(
            select(Notification).where(Notification.category == "sync_started")
        )
    ).all()
    assert [r.source_id for r in rows] == [live.id]


async def test_failed_run_still_reports_once(db_session):
    run = await _run(db_session, status="error")
    run.per_source = {"google": {"scanned": 0, "kept": 0, "errors": ["TimeoutError"]}}
    await db_session.flush()

    await generate_notifications(db_session, run, include_run=True)

    cats = await _categories(db_session)
    assert cats.get("sync_failed") == 1
    assert cats.get("scraper_health") is None  # the duplicate row is gone


async def test_a_run_that_ran_out_of_time_names_companies_as_the_user_knows_them(db_session):
    """The run-result copy names companies by `tracked_company.display`, the
    name Coverage copy uses, not by slug: "piedpiper" is not a company anyone
    follows by that name."""
    db_session.add(TrackedCompany(slug="piedpiper", display="Pied Piper", adapter="ashby", status="active",
                                  enabled=True, visible=True, source="catalog"))
    run = await _run(db_session, status="partial")
    deferred = {
        **empty_stats(), "unattempted": True, "errors": ["TimeoutError: collection timed out"],
        "deferred_reason": "run deadline reached before this company started",
    }
    run.per_source = {
        "google": {**empty_stats(), "scanned": 1, "kept": 1, "list_complete": True, "outcome": "ok"},
        "piedpiper": {**deferred, "outcome": classify_source_outcome(deferred).value},
    }
    await db_session.flush()

    await generate_notifications(db_session, run, include_run=True)

    row = (await db_session.scalars(select(Notification).where(Notification.source_type == "run"))).one()
    assert (row.category, row.priority, row.title) == (
        "sync_unfinished", "low", "Scan ran out of time before 1 company",
    )
    assert "Not reached before the scan ran out of time: Pied Piper." in row.body
    assert "piedpiper" not in row.body


async def test_every_row_of_a_pass_names_the_company_as_the_user_follows_it(db_session):
    """Per-role titles, the digest lead and a reminder read the register's name
    (`tracked_company.display`), the one Coverage copy uses. "acme-labs" is
    added by its careers link, so no table in code knows it as "ACME Labs"."""
    db_session.add(TrackedCompany(slug="acme-labs", display="ACME Labs", adapter="ashby", status="active",
                                  enabled=True, visible=True, source="url"))
    run = await _run(db_session)
    saved = await _job(db_session, company="acme-labs", title="Staff PM")
    db_session.add(Favorite(job_id=saved.id))
    pursued = await _job(db_session, company="acme-labs", title="Group PM")
    db_session.add(Pursuit(job_id=pursued.id, stage="applied", priority=1, next_action="Email Sam",
                           next_action_due=datetime.now(UTC) - timedelta(days=2)))
    fresh = await _job(db_session, company="acme-labs", title="Director of Product")
    await db_session.flush()
    await _event(db_session, run, saved, "closed")
    await _event(db_session, run, fresh, "opened")

    await generate_notifications(db_session, run, include_run=False)

    titles = {
        row.category: (row.title, row.body)
        for row in await db_session.scalars(select(Notification))
    }
    assert titles["closed"][0] == "ACME Labs closed a role you saved"
    assert titles["pursuit_due"][0] == "Follow up with ACME Labs · 2d overdue"
    assert titles["daily_digest"][1] == "Director of Product at ACME Labs"


async def test_a_stopped_scan_rings_scan_stopped_never_couldnt_scan(db_session):
    """What `POST /api/sync/cancel` writes for a scan stopped before any
    company was saved, through the pass that turns it into the bell's row."""
    from tracker.connectors.recipes.outcome import STOPPED_BY_USER_NOTE, cancelled_run_status

    run = await _run(db_session, status=cancelled_run_status([]))
    run.per_source = {}
    run.notes = STOPPED_BY_USER_NOTE
    await db_session.flush()

    await generate_notifications(db_session, run, include_run=True)

    row = (await db_session.scalars(select(Notification).where(Notification.source_type == "run"))).one()
    assert (row.category, row.priority, row.title, row.body) == (
        "sync_unfinished", "low", "Scan stopped", "You stopped it before it scanned any company.",
    )
    assert (run.status, run.notes) == ("error", "cancelled by user"), "the run's own record is unchanged"


# --------------------------------------------------------------------------
# Pursuit follow-ups: assert, then retract
# --------------------------------------------------------------------------


async def test_overdue_pursuit_notifies(db_session):
    job = await _job(db_session, title="Staff PM")
    db_session.add(
        Pursuit(
            job_id=job.id,
            stage="interviewing",
            priority=1,
            next_action="Email the recruiter",
            next_action_due=datetime.now(UTC) - timedelta(days=3),
        )
    )
    await db_session.flush()

    assert await generate_pursuit_due_notifications(db_session) == 1
    row = (
        await db_session.scalars(
            select(Notification).where(Notification.category == "pursuit_due")
        )
    ).one()
    assert row.priority == "high"
    assert "Email the recruiter" in row.body


@pytest.mark.parametrize(
    ("stage", "owed"),
    [("applied", True), ("interviewing", True), ("offer", True),
     ("rejected", False), ("withdrawn", False)],
)
async def test_a_follow_up_due_exactly_now_is_owed_in_every_live_stage(db_session, stage, owed):
    """The two product decisions inside `overdue_pursuit_clause`, pinned where
    they are made.

    Neither is visible to the surfaces that COMPARE against the clause: MCP and
    the notification pass read the same expression, so a test that checks
    they agree moves with it and can never see the boundary slip. `offer` is not
    terminal — an outstanding offer is the point at which a missed follow-up
    costs the most — and the boundary is `<=`, so a follow-up due exactly on the
    clock is owed rather than owed a moment later.
    """
    now = datetime.now(UTC)
    job = await _job(db_session, title=f"Staff PM {stage}")
    db_session.add(
        Pursuit(job_id=job.id, stage=stage, priority=1,
                next_action="Email the recruiter", next_action_due=now)
    )
    await db_session.flush()

    counted = await db_session.scalar(
        select(func.count(Pursuit.id)).where(overdue_pursuit_clause(now))
    )
    assert counted == (1 if owed else 0)


async def test_a_pursuit_with_no_follow_up_date_owes_nothing(db_session):
    """`next_action_due IS NULL` is "no follow-up scheduled", not "overdue since
    the beginning of time" — the third decision in the clause."""
    now = datetime.now(UTC)
    job = await _job(db_session, title="Staff PM")
    db_session.add(Pursuit(job_id=job.id, stage="applied", priority=1, next_action_due=None))
    await db_session.flush()

    assert await db_session.scalar(
        select(func.count(Pursuit.id)).where(overdue_pursuit_clause(now))
    ) == 0


async def test_pursuit_not_yet_due_is_silent(db_session):
    job = await _job(db_session, title="Staff PM")
    db_session.add(
        Pursuit(
            job_id=job.id,
            stage="applied",
            priority=3,
            next_action="Follow up",
            next_action_due=datetime.now(UTC) + timedelta(days=2),
        )
    )
    await db_session.flush()

    assert await generate_pursuit_due_notifications(db_session) == 0


async def test_actioned_pursuit_retracts_its_alert(db_session):
    """An alert that outlives its cause is worse than no alert."""
    job = await _job(db_session, title="Staff PM")
    pursuit = Pursuit(
        job_id=job.id,
        stage="interviewing",
        priority=1,
        next_action="Email the recruiter",
        next_action_due=datetime.now(UTC) - timedelta(days=3),
    )
    db_session.add(pursuit)
    await db_session.flush()
    await generate_pursuit_due_notifications(db_session)

    pursuit.next_action_due = datetime.now(UTC) + timedelta(days=7)
    await db_session.flush()
    await generate_pursuit_due_notifications(db_session)

    assert (await _categories(db_session)).get("pursuit_due") is None


async def test_terminal_stage_stops_nagging(db_session):
    job = await _job(db_session, title="Staff PM")
    pursuit = Pursuit(
        job_id=job.id,
        stage="interviewing",
        priority=1,
        next_action="Email the recruiter",
        next_action_due=datetime.now(UTC) - timedelta(days=3),
    )
    db_session.add(pursuit)
    await db_session.flush()
    await generate_pursuit_due_notifications(db_session)

    pursuit.stage = "rejected"
    await db_session.flush()
    await generate_pursuit_due_notifications(db_session)

    assert (await _categories(db_session)).get("pursuit_due") is None


async def test_an_outstanding_offer_still_needs_following_up(db_session):
    """`offer` is deliberately not terminal: it is where a missed follow-up
    costs the most."""
    job = await _job(db_session, title="Staff PM")
    db_session.add(
        Pursuit(
            job_id=job.id,
            stage="offer",
            priority=1,
            next_action="Respond to the offer",
            next_action_due=datetime.now(UTC) - timedelta(days=1),
        )
    )
    await db_session.flush()

    assert await generate_pursuit_due_notifications(db_session) == 1


async def test_repeated_passes_do_not_multiply_the_alert(db_session):
    job = await _job(db_session, title="Staff PM")
    db_session.add(
        Pursuit(
            job_id=job.id,
            stage="applied",
            priority=1,
            next_action="Follow up",
            next_action_due=datetime.now(UTC) - timedelta(days=1),
        )
    )
    await db_session.flush()

    for _ in range(3):
        await generate_pursuit_due_notifications(db_session)

    assert (await _categories(db_session)).get("pursuit_due") == 1


async def test_read_all_never_hands_back_more_ids_than_unread_will_accept(db_session):
    """`read_all`'s ids ARE the Undo, so the two endpoints are one contract.

    `/unread` caps its body at `UNREAD_MAX_IDS` because "a page can't have
    marked more than this in one click", while `read_all` marks every unread row
    there is. Handing all of them back would make the client post a body the
    server rejects with 422 above the cap, so the bigger the clear, the more
    certainly Undo would fail, and large clears happen. Either the ids are usable as
    an undo or they are not offered; a body that 422s is the one thing they must
    never be.
    """
    from tracker.api.routers.notifications import (
        UNREAD_MAX_IDS,
        UnreadPayload,
        notifications_read_all,
        notifications_unread,
    )

    over = UNREAD_MAX_IDS + 20
    for i in range(over):
        db_session.add(
            Notification(
                created_at=NOW,
                priority="normal",
                category="daily_digest",
                title=f"row {i}",
                source_type="digest",
                source_id=i,
            )
        )
    await db_session.flush()

    result = await notifications_read_all(session=db_session)
    assert result["updated"] == over

    # Whatever came back must be a body `/unread` accepts. Validating it is the
    # assertion -- ValidationError here is the defect.
    payload = UnreadPayload(ids=result["ids"])
    assert len(payload.ids) <= UNREAD_MAX_IDS

    # And when the ids cannot represent the whole clear, none are offered:
    # restoring 500 of 520 silently is worse than declining to undo.
    assert result["ids"] == []
    assert result["undoable"] is False

    restored = await notifications_unread(payload, session=db_session)
    assert restored == {"updated": 0}


async def test_read_all_is_undoable_at_or_below_the_cap(db_session):
    """The ordinary case still round-trips: clear, then restore every row."""
    from tracker.api.routers.notifications import (
        UnreadPayload,
        notifications_read_all,
        notifications_unread,
    )

    for i in range(5):
        db_session.add(
            Notification(
                created_at=NOW,
                priority="normal",
                category="daily_digest",
                title=f"row {i}",
                source_type="digest",
                source_id=i,
            )
        )
    await db_session.flush()

    cleared = await notifications_read_all(session=db_session)
    assert cleared["updated"] == 5
    assert cleared["undoable"] is True
    assert len(cleared["ids"]) == 5

    restored = await notifications_unread(UnreadPayload(ids=cleared["ids"]), session=db_session)
    assert restored == {"updated": 5}

    still_unread = await db_session.scalar(
        select(func.count()).select_from(Notification).where(Notification.read_at.is_(None))
    )
    assert still_unread == 5

async def test_a_run_crossing_local_midnight_reconciles_both_days(db_session):
    """A scrape that spans local midnight must not orphan the earlier day.

    The scheduler runs through the night, so this is a nightly occurrence rather
    than an edge case. Events written at 23:58 belong to yesterday's digest and
    events written at 00:02 to today's; reconciling only `local_today()` leaves
    the first group in NO digest at all -- yesterday's row was computed before
    those roles existed, and nothing recomputes it.
    """

    yesterday = TODAY - timedelta(days=1)
    late = datetime.combine(yesterday, time(23, 58), tzinfo=_LOCAL_TZ).astimezone(UTC)
    early = datetime.combine(TODAY, time(0, 2), tzinfo=_LOCAL_TZ).astimezone(UTC)

    run = await _run(db_session)
    night = await _job(db_session, title="Night Role", req_id="r-night", dedupe_key="k-night")
    morning = await _job(db_session, title="Morning Role", req_id="r-morn", dedupe_key="k-morn")
    await _event(db_session, run, night, "opened", at=late)
    await _event(db_session, run, morning, "opened", at=early)

    await generate_notifications(db_session, run, include_run=False)

    digests = (
        await db_session.scalars(
            select(Notification).where(Notification.category == "daily_digest")
        )
    ).all()
    assert {d.source_id for d in digests} == {yesterday.toordinal(), TODAY.toordinal()}, (
        "the run reconciled only one calendar day, so the roles discovered on the "
        "other side of local midnight appear in no digest"
    )
