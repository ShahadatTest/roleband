"""`/api/status.jobs` and `.supervisor`: what every supervised job is doing, or
why it waits, as the supervisor published it.

A running job carries its run's progress; an idle job whose last run was refused
or held says why; work a job left for later says how much and until when; a
supervisor whose heartbeat is over 90 s old makes every job say
`supervisor_stale`, with the requests still queued counted afresh.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tracker.db import job_store
from tracker.db.models import JobRun, JobStatus

pytestmark = pytest.mark.asyncio


async def _status(api_client) -> dict:
    response = await api_client.get("/api/status")
    assert response.status_code == 200, response.text
    return response.json()


async def _publish(db_session, *statuses: job_store.Status) -> None:
    await job_store.publish(db_session, statuses)
    await db_session.commit()


async def test_a_running_job_shows_its_progress_and_an_idle_one_why_it_did_nothing(api_client, db_session):
    now = datetime.now(UTC)
    run = JobRun(job="directory", key="directory", trigger="schedule", state="running",
                 progress={"done": 40, "total": 120, "note": "boards"})
    db_session.add(run)
    await db_session.commit()
    await _publish(
        db_session,
        job_store.Status(key="directory", job="directory", state="running", since=now, run_id=run.id),
        job_store.Status(key="prices", job="prices", state="idle", since=now,
                         next_at=now + timedelta(minutes=40),
                         detail={"last": {"kind": "waiting", "reason": "rate_limited"},
                                 "waiting": {"count": 12, "until": (now + timedelta(minutes=40)).isoformat()}}),
        job_store.Status(key="scan", job="scan", state="waiting", reason="preflight_failed", since=now,
                         detail={"queued": 1, "last": {"kind": "ran", "reason": None}}),
        job_store.Status(key=job_store.SUPERVISOR_KEY, job="supervisor", state="running", since=now),
    )
    body = await _status(api_client)
    jobs = {job["key"]: job for job in body["jobs"]}
    assert body["supervisor"]["state"] == "running"
    assert jobs["directory"]["progress"] == {"done": 40, "total": 120}
    assert (jobs["prices"]["reason"], jobs["prices"]["waiting"]["count"]) == ("rate_limited", 12)
    assert jobs["prices"]["waiting"]["until"] is not None
    assert (jobs["scan"]["reason"], jobs["scan"]["queued"]) == ("preflight_failed", 1)
    assert jobs["directory"]["waiting"] is None and jobs["scan"]["progress"] is None


async def test_an_idle_job_whose_last_turn_was_simply_empty_gives_no_reason(api_client, db_session):
    """A rehearsal's dry run, or a tick with nothing due, is not a reason to show."""
    now = datetime.now(UTC)
    await _publish(
        db_session,
        job_store.Status(key="scan", job="scan", state="idle", since=now,
                         detail={"last": {"kind": "nothing_due", "reason": "dry_run"}}),
        job_store.Status(key=job_store.SUPERVISOR_KEY, job="supervisor", state="running", since=now),
    )
    [job] = (await _status(api_client))["jobs"]
    assert job["reason"] is None


async def test_a_stale_supervisor_makes_every_job_wait_on_it_and_counts_what_is_queued(api_client, db_session):
    long_ago = datetime.now(UTC) - timedelta(minutes=10)
    await _publish(
        db_session,
        job_store.Status(key="scan", job="scan", state="idle", since=long_ago),
        job_store.Status(key=job_store.SUPERVISOR_KEY, job="supervisor", state="running", since=long_ago),
    )
    await db_session.execute(
        JobStatus.__table__.update().values(updated_at=long_ago)
    )
    await job_store.ring(db_session, "scan", requested_by="sync")
    await db_session.commit()
    body = await _status(api_client)
    assert body["supervisor"]["state"] == "stale"
    [scan] = body["jobs"]
    assert (scan["reason"], scan["queued"]) == ("supervisor_stale", 1)


async def test_a_supervisor_in_maintenance_says_so(api_client, db_session):
    now = datetime.now(UTC)
    await _publish(db_session, job_store.Status(key="scan", job="scan", state="idle", since=now))
    await job_store.publish_paused(db_session, now, detail={})
    await db_session.commit()
    body = await _status(api_client)
    assert body["supervisor"]["state"] == "maintenance"
    assert [(job["state"], job["reason"]) for job in body["jobs"]] == [("disabled", "maintenance")]
