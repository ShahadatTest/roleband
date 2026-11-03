"""The supervisor's store keeps its promises on real Postgres.

Requests are durable doorbells delivered at least once: equal requests coalesce
while queued, a claim and its run open together, a key never has two live runs
whoever races for it, a lost run's request comes back (a bounded number of times),
and a finished one never does. Retention keeps the runs that did work.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from tracker.db import job_store
from tracker.db.models import JobRequest, JobRun, JobStatus

pytestmark = pytest.mark.asyncio


async def _queued(session) -> list[JobRequest]:
    return list(
        await session.scalars(
            select(JobRequest).where(JobRequest.state == job_store.QUEUED).order_by(JobRequest.id)
        )
    )


async def test_equal_requests_coalesce_while_queued_and_differ_by_arguments(db_session):
    first = await job_store.ring(db_session, "scan", requested_by="sync")
    again = await job_store.ring(db_session, "scan", requested_by="first_scan")
    other = await job_store.ring(db_session, "reembed", requested_by="settings", args={"tier": "large"})
    other_args = await job_store.ring(db_session, "reembed", requested_by="settings", args={"tier": "small"})
    await db_session.commit()

    assert again.id == first.id
    assert first.requested_by == "sync", "the first ring is the request; later ones join it"
    assert other.id != other_args.id
    assert [r.key for r in await _queued(db_session)] == ["scan", "reembed", "reembed"]


async def test_a_claimed_request_no_longer_absorbs_new_rings(db_session):
    first = await job_store.ring(db_session, "scan", requested_by="sync")
    claimed = await job_store.claim(db_session, "scan")
    assert claimed is not None and claimed[0].id == first.id
    later = await job_store.ring(db_session, "scan", requested_by="sync")
    await db_session.commit()

    assert later.id != first.id, "a ring during a run asks for the next run"
    assert [r.id for r in await _queued(db_session)] == [later.id]


async def test_a_request_is_announced_only_when_its_transaction_commits(db_session):
    url = db_session.bind.url.set(drivername="postgresql")
    connection = await asyncpg.connect(
        dsn=url.render_as_string(hide_password=False).split("?")[0],
        **({"host": url.query["host"]} if "host" in url.query else {}),
    )
    heard: asyncio.Queue[str] = asyncio.Queue()
    await connection.add_listener(job_store.CHANNEL, lambda *args: heard.put_nowait(args[-1]))
    try:
        await job_store.ring(db_session, "prices", requested_by="settings")
        await asyncio.sleep(0.3)
        assert heard.empty(), "a request the listener cannot yet see must not wake it"
        await db_session.commit()
        assert await asyncio.wait_for(heard.get(), timeout=2) == "prices"
    finally:
        await connection.close()


async def test_a_claim_opens_the_run_and_links_it_to_its_request(db_session):
    request = await job_store.ring(db_session, "backup", requested_by="cli")
    claimed = await job_store.claim(db_session, "backup", code_version="abc123")
    await db_session.commit()

    assert claimed is not None
    claimed_request, run = claimed
    assert claimed_request.id == request.id
    assert claimed_request.state == job_store.CLAIMED
    assert claimed_request.attempts == 1
    assert (run.state, run.trigger, run.request_id, run.code_version) == (
        job_store.STARTING, "request", request.id, "abc123",
    )


async def test_a_key_with_a_live_run_is_not_claimed_and_its_request_waits(db_session):
    scheduled = await job_store.open_run(db_session, "scan", "scan", trigger="schedule")
    assert scheduled is not None
    request = await job_store.ring(db_session, "scan", requested_by="sync")
    await db_session.commit()

    assert await job_store.claim(db_session, "scan") is None
    assert await job_store.open_run(db_session, "scan", "scan", trigger="schedule") is None
    await db_session.commit()
    assert [r.id for r in await _queued(db_session)] == [request.id]


async def test_two_claimers_racing_for_one_key_open_one_run(db_session):
    """Two supervisors on one database: the second waits on the first's
    uncommitted run and then finds the key live, so it opens nothing."""
    await job_store.ring(db_session, "directory", requested_by="cli", args={"n": 1})
    await job_store.ring(db_session, "directory", requested_by="cli", args={"n": 2})
    await db_session.commit()

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as first, factory() as second:
        won = await job_store.claim(first, "directory")
        assert won is not None
        racing = asyncio.create_task(job_store.claim(second, "directory"))
        await asyncio.sleep(0.3)
        assert not racing.done(), "the second claimer must wait for the first's run to commit"
        await first.commit()
        assert await asyncio.wait_for(racing, timeout=5) is None
        await second.rollback()

    live = await db_session.scalar(
        select(func.count()).select_from(JobRun).where(JobRun.state.in_(job_store.LIVE))
    )
    assert live == 1
    assert len(await _queued(db_session)) == 1, "the loser's request is still queued"


async def test_a_run_that_exited_completes_its_request_whatever_its_exit_code(db_session):
    await job_store.ring(db_session, "scan", requested_by="sync")
    request, run = await job_store.claim(db_session, "scan")  # type: ignore[misc]
    await job_store.finish_run(
        db_session, run.id, state=job_store.EXITED, exit_code=1, result={"kind": "ran"}
    )
    await db_session.commit()

    await db_session.refresh(request)
    assert request.state == job_store.DONE
    assert request.ended_at is not None
    assert await _queued(db_session) == [], "a finished request is never replayed"


async def test_a_lost_run_queues_its_request_again_until_its_attempts_run_out(db_session):
    request = await job_store.ring(db_session, "plugins_due", requested_by="catch_up")
    await db_session.commit()

    for attempt in range(1, job_store.MAX_ATTEMPTS + 1):
        claimed = await job_store.claim(db_session, "plugins_due")
        assert claimed is not None, f"attempt {attempt} must find the request queued"
        await job_store.finish_run(db_session, claimed[1].id, state=job_store.LOST)
        await db_session.commit()
        await db_session.refresh(request)
        assert request.attempts == attempt

    assert request.state == job_store.FAILED
    assert await job_store.claim(db_session, "plugins_due") is None


async def test_a_lost_run_whose_twin_was_rung_meanwhile_merges_into_it(db_session):
    await job_store.ring(db_session, "scan", requested_by="sync")
    request, run = await job_store.claim(db_session, "scan")  # type: ignore[misc]
    twin = await job_store.ring(db_session, "scan", requested_by="sync")
    await job_store.finish_run(db_session, run.id, state=job_store.SPAWN_FAILED)
    await db_session.commit()

    await db_session.refresh(request)
    assert request.state == job_store.DONE
    assert request.note == f"merged into request {twin.id}"
    assert [r.id for r in await _queued(db_session)] == [twin.id]


async def test_a_cancelled_run_cancels_its_request(db_session):
    await job_store.ring(db_session, "reembed", requested_by="settings")
    request, run = await job_store.claim(db_session, "reembed")  # type: ignore[misc]
    await job_store.finish_run(db_session, run.id, state=job_store.RUN_CANCELLED, exit_code=-15)
    await db_session.commit()

    await db_session.refresh(request)
    assert request.state == job_store.CANCELLED


async def test_finishing_a_run_twice_changes_nothing(db_session):
    run = await job_store.open_run(db_session, "backup", "backup", trigger="schedule")
    await job_store.finish_run(db_session, run.id, state=job_store.EXITED, exit_code=0)
    await job_store.finish_run(db_session, run.id, state=job_store.LOST)
    await db_session.commit()

    await db_session.refresh(run)
    assert (run.state, run.exit_code) == (job_store.EXITED, 0)
    with pytest.raises(ValueError):
        await job_store.finish_run(db_session, run.id, state=job_store.RUNNING)


async def test_a_cancel_is_recorded_once_and_only_for_a_live_run(db_session):
    run = await job_store.open_run(db_session, "scan", "scan", trigger="request")
    await db_session.commit()

    assert await job_store.request_cancel(db_session, run.id, reason="sync_cancel") is True
    assert await job_store.request_cancel(db_session, run.id, reason="again") is False
    await job_store.finish_run(db_session, run.id, state=job_store.RUN_CANCELLED)
    await db_session.commit()
    await db_session.refresh(run)
    assert run.cancel_reason == "sync_cancel"

    ended = await job_store.open_run(db_session, "scan", "scan", trigger="request")
    await job_store.finish_run(db_session, ended.id, state=job_store.EXITED, exit_code=0)
    assert await job_store.request_cancel(db_session, ended.id, reason="late") is False


async def test_cancelling_queued_requests_spares_other_producers(db_session):
    """The header Cancel stops what Sync asked for, never a first scan's run."""
    sync = await job_store.ring(db_session, "scan", requested_by="sync", args={"from": "header"})
    first = await job_store.ring(db_session, "scan", requested_by="first_scan", args={"from": "add"})
    await db_session.commit()

    assert await job_store.cancel_queued(db_session, key="scan", requested_by="sync") == [sync.id]
    await db_session.commit()
    assert [r.id for r in await _queued(db_session)] == [first.id]
    with pytest.raises(ValueError):
        await job_store.cancel_queued(db_session)


async def test_progress_is_written_only_for_a_running_run(db_session):
    run = await job_store.open_run(db_session, "prices", "prices", trigger="request")
    await job_store.report_progress(db_session, run.id, done=1, total=66)
    await db_session.commit()
    await db_session.refresh(run)
    assert run.progress == {}, "a run still starting has no process to report from"

    await job_store.mark_running(db_session, run.id, pid=4242, pgid=4242, proc_started_at=None)
    await job_store.report_progress(db_session, run.id, done=12, total=66, note="Fetching prices")
    await db_session.commit()
    await db_session.refresh(run)
    assert (run.state, run.pid) == (job_store.RUNNING, 4242)
    assert run.progress == {"done": 12, "total": 66, "note": "Fetching prices"}


async def test_a_published_state_keeps_its_since_until_it_changes(db_session):
    t0 = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
    await job_store.publish(
        db_session, [job_store.Status("scan", "scan", "waiting", t0, reason="preflight_running")]
    )
    await job_store.publish(
        db_session,
        [job_store.Status("scan", "scan", "waiting", t0 + timedelta(minutes=5), reason="preflight_running")],
    )
    await db_session.commit()
    row = await db_session.get(JobStatus, "scan")
    assert row.since == t0, "an unchanged wait keeps the moment it began"

    await job_store.publish(
        db_session,
        [job_store.Status("scan", "scan", "waiting", t0 + timedelta(minutes=9), reason="preflight_failed")],
    )
    await db_session.commit()
    await db_session.refresh(row)
    assert (row.reason, row.since) == ("preflight_failed", t0 + timedelta(minutes=9))


async def _version(session, key: str) -> tuple[str, datetime]:
    """The row's tuple version (`xmin` moves with every rewrite) and its `updated_at`."""
    session.expire_all()
    row = (
        await session.execute(
            text("SELECT xmin::text, updated_at FROM job_status WHERE key = :key"), {"key": key}
        )
    ).one()
    return row[0], row[1]


SCAN_AT = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
SCAN = job_store.Status(
    "scan", "scan", "idle", SCAN_AT, next_at=SCAN_AT + timedelta(minutes=10), run_id=7,
    detail={"queued": 1, "last": {"kind": "ran", "reason": None}},
)


async def test_a_status_that_comes_out_the_same_is_not_rewritten(db_session):
    await job_store.publish(db_session, [SCAN])
    await db_session.commit()
    before = await _version(db_session, "scan")

    # Only `since` differs, and it is kept while the state holds; the detail's
    # keys come in another order, which is the same JSON value.
    again = replace(SCAN, since=SCAN_AT + timedelta(minutes=1),
                    detail={"last": {"reason": None, "kind": "ran"}, "queued": 1})
    await job_store.publish(db_session, [again])
    await db_session.commit()
    assert await _version(db_session, "scan") == before, "nothing changed, so nothing was written"


@pytest.mark.parametrize(
    "change",
    [
        {"state": "running"},
        {"reason": "preflight_running"},
        {"next_at": SCAN_AT + timedelta(minutes=20)},
        {"next_at": None},
        {"run_id": 8},
        {"detail": {"queued": 2, "last": {"kind": "ran", "reason": None}}},
    ],
    ids=["state", "reason", "next_at", "next_at cleared", "run_id", "detail"],
)
async def test_a_status_that_changed_in_any_published_field_is_written(db_session, change):
    await job_store.publish(db_session, [SCAN])
    await db_session.commit()
    before = await _version(db_session, "scan")

    await job_store.publish(db_session, [replace(SCAN, **change)])
    await db_session.commit()
    after = await _version(db_session, "scan")
    assert after[0] != before[0] and after[1] > before[1]
    row = await db_session.get(JobStatus, "scan")
    for field_name, value in change.items():
        assert getattr(row, field_name) == value


async def test_the_supervisor_row_is_written_every_time_because_it_is_the_heartbeat(db_session):
    beat = job_store.Status(job_store.SUPERVISOR_KEY, "supervisor", "running", SCAN_AT, detail={"pid": 1})
    await job_store.publish(db_session, [beat])
    await db_session.commit()
    before = await _version(db_session, job_store.SUPERVISOR_KEY)

    await job_store.publish(db_session, [beat])
    await db_session.commit()
    after = await _version(db_session, job_store.SUPERVISOR_KEY)
    assert after[0] != before[0] and after[1] > before[1]
    _, supervisor = await job_store.status_view(db_session, after[1] + job_store.SUPERVISOR_STALE_AFTER)
    assert supervisor["state"] == "running", "a heartbeat within the bound is not stale"


async def test_retention_keeps_more_working_runs_than_idle_ones_and_never_a_live_one(db_session):
    base = datetime(2026, 10, 1, tzinfo=UTC)
    for minute in range(8):
        run = await job_store.open_run(db_session, "scan", "scan", trigger="schedule")
        kind = "nothing_due" if minute % 2 else "ran"
        await job_store.finish_run(
            db_session, run.id, state=job_store.EXITED, exit_code=0, result={"kind": kind}
        )
        await db_session.execute(
            update(JobRun).where(JobRun.id == run.id).values(started_at=base + timedelta(minutes=minute))
        )
    live = await job_store.open_run(db_session, "scan", "scan", trigger="schedule")
    await db_session.execute(update(JobRun).where(JobRun.id == live.id).values(started_at=base))
    await db_session.commit()

    pruned = await job_store.prune(db_session, keep_runs=2, keep_no_op_runs=1)
    await db_session.commit()

    kept = list(await db_session.scalars(select(JobRun).order_by(JobRun.started_at, JobRun.id)))
    assert pruned.runs == 5
    assert [(r.result or {}).get("kind") for r in kept if r.state != job_store.STARTING] == [
        "ran", "ran", "nothing_due",
    ]
    assert [r.started_at.minute for r in kept if r.state != job_store.STARTING] == [4, 6, 7]
    assert any(r.id == live.id for r in kept), "a live run is never pruned"


async def test_retention_drops_requests_a_month_after_they_ended_and_keeps_queued_ones(db_session):
    now = datetime(2026, 10, 19, tzinfo=UTC)
    old = await job_store.ring(db_session, "backup", requested_by="cli", args={"n": 1})
    recent = await job_store.ring(db_session, "backup", requested_by="cli", args={"n": 2})
    waiting = await job_store.ring(db_session, "backup", requested_by="cli", args={"n": 3})
    await db_session.execute(
        update(JobRequest)
        .where(JobRequest.id == old.id)
        .values(state=job_store.DONE, ended_at=now - timedelta(days=31), requested_at=now - timedelta(days=40))
    )
    await db_session.execute(
        update(JobRequest)
        .where(JobRequest.id == recent.id)
        .values(state=job_store.DONE, ended_at=now - timedelta(days=2))
    )
    await db_session.execute(
        update(JobRequest).where(JobRequest.id == waiting.id).values(requested_at=now - timedelta(days=90))
    )
    await db_session.commit()

    assert (await job_store.prune(db_session, now)).requests == 1
    await db_session.commit()
    left = sorted(await db_session.scalars(select(JobRequest.id)))
    assert left == sorted([recent.id, waiting.id])
