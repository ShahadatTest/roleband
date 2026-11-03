"""The delivery seam actually delivers.

`CHANNELS` must be a real dispatch point: if `digest` and `pursuit_due` each
built their own `insert` instead of dispatching through the map, a channel
registered here — the motivating case is macOS push via `tracker.osnotify` —
would fire for run health and job events and stay **silent for the daily
digest and pursuit reminders**, which are the two categories anyone adds a
push channel for.

That is invisible to every other test in this suite, because all of them assert
on the rows in the table and the rows are always written. It is only visible
from the seam, so this file registers a recording channel and asserts what
reaches it.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import select

from tracker.db.models import Job, JobLifecycleEvent, Notification, Pursuit, ScrapeRun
from tracker.notifications import (
    channels,
    generate_notifications,
    generate_pursuit_due_notifications,
)

pytestmark = pytest.mark.asyncio

_LOCAL_TZ = datetime.now().astimezone().tzinfo
TODAY = datetime.now(_LOCAL_TZ).date()
NOW = datetime.combine(TODAY, time(12, 0), tzinfo=_LOCAL_TZ).astimezone(UTC)


@pytest.fixture
def recorder(monkeypatch):
    """A second channel, registered the way a real one would be."""

    seen: list[dict] = []

    async def _record(session, values, *, refresh=()):
        seen.append({"source_type": values["source_type"], "category": values["category"]})

    monkeypatch.setitem(channels.CHANNELS, "recorder", _record)
    return seen


async def _job(session, **kw) -> Job:
    job = Job(
        company=kw.pop("company", "google"),
        title=kw.pop("title", "Staff PM"),
        url=kw.pop("url", "https://example.test/google/staff-pm"),
        level_band="L6",
        req_id=kw.pop("req_id", "r-1"),
        dedupe_key=kw.pop("dedupe_key", "k-1"),
        status="open",
        first_seen=NOW - timedelta(days=5),
        last_seen=NOW,
        total_days_open=5,
        repost_count=0,
        in_scope=True,
    )
    session.add(job)
    await session.flush()
    return job


async def _run(session) -> ScrapeRun:
    run = ScrapeRun(
        status="ok",
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


async def test_a_registered_channel_receives_the_digest_and_pursuit_categories(
    db_session, recorder
):
    """The assertion the seam exists for.

    `daily_digest` and `pursuit_due` must dispatch through it too. A channel
    that only ever hears about runs and job events is not a notification
    channel.
    """

    run = await _run(db_session)
    # Two jobs, and they must be different ones: `_candidate_stmt` excludes
    # TRACKED ids from the digest so a role does not get announced twice, so a
    # single job carrying the pursuit would produce no digest at all.
    discovered = await _job(db_session, title="Staff PM", req_id="r-1", dedupe_key="k-1")
    pursued = await _job(
        db_session,
        title="Group PM",
        url="https://example.test/google/group-pm",
        req_id="r-2",
        dedupe_key="k-2",
    )
    # Discovered now: its creation event is its first sighting, as the writer stores it.
    discovered.first_seen = NOW
    db_session.add(
        JobLifecycleEvent(
            job_id=discovered.id, run_id=run.id, event_type="opened", detail={}, created_at=NOW
        )
    )
    db_session.add(
        Pursuit(
            job_id=pursued.id,
            stage="applied",
            priority=3,
            next_action="Follow up",
            next_action_due=NOW - timedelta(days=2),
        )
    )
    await db_session.flush()

    # `include_run=False` still runs the digest pass; the pursuit pass is its
    # own entry point, exactly as the scheduler calls them.
    await generate_notifications(db_session, run, include_run=False)
    await generate_pursuit_due_notifications(db_session)

    delivered = {row["source_type"] for row in recorder}
    assert "digest" in delivered, (
        "the daily digest did not reach the channel seam — it is writing its own "
        "insert, so a registered channel is silent for it"
    )
    assert "pursuit" in delivered, (
        "pursuit reminders did not reach the channel seam — same defect, and it "
        "is the category a push channel is most often added for"
    )


async def test_every_row_in_the_table_was_delivered_through_the_seam(db_session, recorder):
    """No write may bypass the seam.

    Comparing what the channel heard against what actually landed is what makes
    this hold for a category nobody thought to name here: a fourth writer added
    later fails this without anyone editing the list above.
    """

    run = await _run(db_session)
    job = await _job(db_session)
    job.first_seen = NOW  # opened now, as the writer stores a creation
    db_session.add(
        JobLifecycleEvent(
            job_id=job.id, run_id=run.id, event_type="opened", detail={}, created_at=NOW
        )
    )
    await db_session.flush()
    await generate_notifications(db_session, run, include_run=True)

    in_table = {
        (row.source_type, row.category)
        for row in (await db_session.scalars(select(Notification))).all()
    }
    heard = {(row["source_type"], row["category"]) for row in recorder}
    assert in_table, "fixture wrote no notifications at all"
    assert in_table <= heard, (
        f"these rows were written without going through the channel seam: {in_table - heard}"
    )
