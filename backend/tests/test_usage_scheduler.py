"""The scheduler sends after the run lock, on the tick's loop, and records a
crash once; a run's failure record survives the crash report
(docs/architecture.md).
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.usage_fixtures import share
from tracker.db.models import ScrapeRun, UsageEvent
from tracker.usage_stats.registry import Group
from tracker.workflows import run_persistence, scheduler
from tracker.workflows.collection_types import ScanMode

pytestmark = pytest.mark.usefixtures("no_escape")


def test_the_send_runs_on_the_ticks_loop_after_the_lock_is_released(monkeypatch) -> None:
    seen: dict[str, object] = {}
    held = {"lock": False}

    @contextlib.contextmanager
    def lock(_path):
        held["lock"] = True
        try:
            yield
        finally:
            held["lock"] = False

    async def sampled():
        seen["sample"] = asyncio.get_running_loop()

    async def ran(*, dry_run):
        seen["run"] = asyncio.get_running_loop()
        return {"ran": False, "work": [], "reason": "nothing due"}

    async def send():
        seen["send"] = asyncio.get_running_loop()
        seen["lock_held_during_send"] = held["lock"]
        return {"sent": 0, "reason": "nothing shared"}

    async def plugins():
        # Plugin runs start after `daily.lock` is released.
        seen["lock_held_during_plugins"] = held["lock"]
        return {"started": [], "waiting": None}

    monkeypatch.setattr(scheduler, "note_awake", sampled)
    monkeypatch.setattr(scheduler, "run_once", ran)
    monkeypatch.setattr(scheduler, "run_lock", lock)
    monkeypatch.setattr(scheduler, "usage_when_due", send)
    monkeypatch.setattr(scheduler, "enable_shared_pacing", lambda _path: None)
    monkeypatch.setattr(sys, "argv", ["tracker.scheduler"])

    scheduler.main(after_lock=[("plugins", plugins)])

    assert seen["sample"] is seen["run"] is seen["send"]
    assert seen["lock_held_during_send"] is False
    assert seen["lock_held_during_plugins"] is False


@pytest.mark.asyncio
async def test_a_dry_run_sends_nothing(monkeypatch) -> None:
    async def ran(*, dry_run):
        return {"ran": False, "work": [], "reason": "dry_run"}

    async def send():
        raise AssertionError("a dry run must not send")

    monkeypatch.setattr(scheduler, "run_once", ran)
    monkeypatch.setattr(scheduler, "run_lock", lambda _path: contextlib.nullcontext())
    monkeypatch.setattr(scheduler, "usage_when_due", send)
    result = await scheduler.tick(dry_run=True, after_lock=[("plugins", send)])
    assert "usage" not in result and "plugins" not in result


@pytest.mark.asyncio
async def test_a_failed_send_never_fails_the_tick(monkeypatch) -> None:
    async def broken(**_kwargs):
        raise RuntimeError("posthog is down")

    monkeypatch.setattr(scheduler, "flush_if_due", broken)
    result = await scheduler.usage_when_due()
    assert result == {"error": "RuntimeError: posthog is down"}


def _scope(db_session):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def scope():
        async with factory() as session:
            yield session

    return scope


async def _crashes(db_session) -> list[UsageEvent]:
    return list((await db_session.execute(select(UsageEvent).where(UsageEvent.name == "$exception"))).scalars())


@pytest.mark.asyncio
async def test_a_tick_crash_is_recorded_once(db_session, sharing_allowed, monkeypatch) -> None:
    await share(db_session, Group.CRASHES)
    await db_session.commit()
    monkeypatch.setattr(scheduler, "session_scope", _scope(db_session))

    await scheduler.usage_crash(KeyError("plan"))
    already = RuntimeError("the pipeline recorded this one")
    already._usage_recorded = True  # type: ignore[attr-defined]
    await scheduler.usage_crash(already)

    [row] = await _crashes(db_session)
    assert row.props["source"] == "scheduler"
    assert row.props["exception"]["type"] == "KeyError"


@pytest.mark.asyncio
async def test_a_tick_that_crashes_still_raises(monkeypatch) -> None:
    async def ran(*, dry_run):
        raise ValueError("planning broke")

    recorded: list[BaseException] = []

    async def crash(error):
        recorded.append(error)

    monkeypatch.setattr(scheduler, "note_awake", lambda: asyncio.sleep(0))
    monkeypatch.setattr(scheduler, "run_once", ran)
    monkeypatch.setattr(scheduler, "run_lock", lambda _path: contextlib.nullcontext())
    monkeypatch.setattr(scheduler, "usage_crash", crash)
    with pytest.raises(ValueError, match="planning broke"):
        await scheduler.tick(dry_run=False)
    assert [type(error) for error in recorded] == [ValueError]


async def _failed_run(db_session, exc: Exception) -> ScrapeRun:
    run = ScrapeRun(status="running")
    db_session.add(run)
    await db_session.commit()
    await run_persistence.record_run_failure(
        db_session,
        run.id,
        exc,
        per_source={},
        drift_all=[],
        totals={"seen": 0, "new": 0, "closed": 0},
        scan_mode=ScanMode.DISCOVERY,
    )
    return await db_session.get(ScrapeRun, run.id)


@pytest.mark.asyncio
async def test_a_run_crash_is_recorded_and_marked(db_session, sharing_allowed) -> None:
    await share(db_session, Group.CRASHES)
    await db_session.commit()
    exc = RuntimeError("collection broke")
    run = await _failed_run(db_session, exc)
    assert run.status == "error" and run.finished_at is not None
    [row] = await _crashes(db_session)
    assert row.props["source"] == "pipeline"
    assert getattr(exc, "_usage_recorded", False) is True


@pytest.mark.asyncio
async def test_a_broken_crash_report_never_costs_the_run_its_record(db_session, sharing_allowed, monkeypatch) -> None:
    await share(db_session, Group.CRASHES)
    await db_session.commit()

    async def broken(*_args, **_kwargs):
        raise RuntimeError("the outbox is unwell")

    monkeypatch.setattr(run_persistence, "record_exception", broken)
    run = await _failed_run(db_session, RuntimeError("collection broke"))
    assert run.status == "error"
    assert run.notes and "collection broke" in run.notes
    assert await _crashes(db_session) == []


@pytest.mark.asyncio
async def test_a_run_crash_without_crash_sharing_records_nothing(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE)
    await db_session.commit()
    await _failed_run(db_session, RuntimeError("collection broke"))
    assert await _crashes(db_session) == []


@pytest.mark.asyncio
async def test_a_broken_failure_notification_never_costs_the_run_its_record(
    db_session, sharing_allowed, monkeypatch
) -> None:
    """The fault that kills a run often kills the telling of it. Left in the
    open, that second failure escapes past the commit, so the run stays
    `running` until the reconciler notices and the original exception is lost
    behind it. Fail-first: without the savepoint the status is `running` and
    `notes` is empty."""
    await share(db_session, Group.CRASHES)
    await db_session.commit()
    calls: list[str] = []

    async def broken(*_args, **_kwargs):
        calls.append("tried")
        raise RuntimeError("the notifications table is unwell")

    monkeypatch.setattr(run_persistence, "generate_notifications", broken)
    run = await _failed_run(db_session, RuntimeError("collection broke"))
    assert calls, "the notification was attempted"
    assert run.status == "error" and run.finished_at is not None
    assert run.notes and "collection broke" in run.notes
    # The crash report beside it is unaffected: one failing write must not
    # take the other down with it.
    [crash] = await _crashes(db_session)
    assert crash.props["source"] == "pipeline"


@pytest.mark.asyncio
async def test_the_supervisor_s_scan_neither_samples_nor_sends(monkeypatch) -> None:
    """Both have their own supervised schedule, outside the preflight; a tick
    that still took them would sample twice and send behind the gate."""
    from tracker.platform import ratelimit
    from tracker.supervisor import entries

    called: list[str] = []

    async def sampled():
        called.append("sample")

    async def send():
        called.append("send")
        return {"sent": 0}

    async def ran(*, dry_run):
        return {"ran": False, "work": [], "reason": "nothing due"}

    monkeypatch.setattr(scheduler, "note_awake", sampled)
    monkeypatch.setattr(scheduler, "usage_when_due", send)
    monkeypatch.setattr(scheduler, "run_once", ran)
    monkeypatch.setattr(scheduler, "run_lock", lambda _path: contextlib.nullcontext())
    monkeypatch.setattr(ratelimit, "enable_shared_pacing", lambda _path: None)

    result = await entries.scan()
    assert called == []
    assert "usage" not in result

    await scheduler.tick(dry_run=False)
    assert called == ["sample", "send"], "the hand-run tick still does both"
