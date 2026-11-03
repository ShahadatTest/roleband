"""The disclosed-pay backfill saves per batch and resumes.

The extraction core commits nothing (the post pass's loop and this command own
the commits). The backfill hands it batches newest first and commits each, so
an interruption keeps every finished batch, and a rerun reads only what is
still owed. Real Postgres; the command's `session_scope` points at the scratch
database.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from tracker.db.models import Job
from tracker.workflows import backfill_disclosed_comp as backfill

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 4, tzinfo=UTC)
TEXT = "The base salary range for this role is $180,000 - $220,000 per year."


async def _seed(db_session, n: int) -> list[Job]:
    jobs = [
        Job(
            company="acme", req_id=f"r{i}", dedupe_key=f"acme:r{i}", title="Staff PM",
            url=f"https://careers.example.test/{i}", level_band="staff", status="open",
            first_seen=NOW, last_seen=NOW, description_text=TEXT, content_changed_at=NOW,
            locations=["Chicago, IL"],
        )
        for i in range(n)
    ]
    db_session.add_all(jobs)
    await db_session.commit()
    return jobs


async def _read(db_session) -> dict[str, bool]:
    db_session.expire_all()
    rows = (await db_session.execute(select(Job.req_id, Job.structured_at))).all()
    return {r.req_id: r.structured_at is not None for r in rows}


async def test_an_interrupted_backfill_keeps_its_finished_batches_and_resumes(db_session, scratch_scope, monkeypatch):
    await _seed(db_session, 5)
    real = backfill.extract_disclosed_comp
    calls = 0

    async def dies_on_the_third_batch(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise KeyboardInterrupt("app quit")
        return await real(*args, **kwargs)

    monkeypatch.setattr(backfill, "extract_disclosed_comp", dies_on_the_third_batch)
    with pytest.raises(KeyboardInterrupt):
        await backfill.run(open_only=True, force=False, limit=None, batch=2)
    # Newest first: r4, r3 then r2, r1 were written; r0 was the lost batch.
    assert await _read(db_session) == {"r0": False, "r1": True, "r2": True, "r3": True, "r4": True}

    monkeypatch.setattr(backfill, "extract_disclosed_comp", real)
    summary = await backfill.run(open_only=True, force=False, limit=None, batch=2)
    assert summary["processed"] == 1
    assert all((await _read(db_session)).values())


async def test_a_limit_counts_across_batches(db_session, scratch_scope, monkeypatch):
    await _seed(db_session, 5)
    summary = await backfill.run(open_only=True, force=False, limit=3, batch=2)
    assert summary["processed"] == 3
    assert sum((await _read(db_session)).values()) == 3


# --------------------------------------------------------------------------- #
# A forced re-read
# --------------------------------------------------------------------------- #

EARLIER = datetime(2026, 9, 1, tzinfo=UTC)


async def _seed_forced(db_session) -> dict[str, Job]:
    """A connector band (the text pass never reads it) and three text bands,
    each stamped by an earlier text read."""
    rows = {
        "connector": dict(disclosed_source="connector", disclosed_base_min=200_000,
                          disclosed_base_max=250_000, disclosed_currency="USD",
                          disclosed_pay_basis="base", disclosed_pay_period="year"),
        **{
            f"t{i}": dict(disclosed_source="text", disclosed_base_min=180_000,
                          disclosed_base_max=220_000, disclosed_currency="USD",
                          disclosed_pay_basis="base", disclosed_pay_period="year")
            for i in range(3)
        },
    }
    jobs = {
        key: Job(
            company="acme", req_id=key, dedupe_key=f"acme:{key}", title="Staff PM",
            url=f"https://careers.example.test/{key}", level_band="staff", status="open",
            first_seen=NOW, last_seen=NOW, description_text=TEXT, content_changed_at=EARLIER,
            locations=["Chicago, IL"], structured_at=EARLIER, structured_prompt_version="v-old",
            **columns,
        )
        for key, columns in rows.items()
    }
    db_session.add_all(jobs.values())
    await db_session.commit()
    return jobs


async def _stamps(db_session) -> dict[str, tuple]:
    db_session.expire_all()
    rows = (await db_session.execute(
        select(Job.req_id, Job.structured_at, Job.disclosed_base_min)
    )).all()
    return {r.req_id: (r.structured_at > EARLIER if r.structured_at else None, r.disclosed_base_min) for r in rows}


async def test_a_forced_limited_read_changes_only_what_it_reads(db_session, scratch_scope, monkeypatch):
    """A forced limited read must change only the rows it reads. Clearing
    stamps in advance would leave untouched text rows and unread connector
    bands unstamped, with no text pass able to restore the connector's stamp."""
    await _seed_forced(db_session)
    summary = await backfill.run(open_only=True, force=True, limit=1, batch=2)
    assert summary["processed"] == 1
    assert await _stamps(db_session) == {
        "connector": (False, 200_000),
        "t2": (True, 180_000),  # newest first: the one row read
        "t1": (False, 180_000),
        "t0": (False, 180_000),
    }


async def test_an_interrupted_forced_read_keeps_every_band_and_resumes(db_session, scratch_scope, monkeypatch):
    await _seed_forced(db_session)
    real = backfill.extract_disclosed_comp
    calls = 0

    async def dies_on_the_second_batch(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt("app quit")
        return await real(*args, **kwargs)

    monkeypatch.setattr(backfill, "extract_disclosed_comp", dies_on_the_second_batch)
    with pytest.raises(KeyboardInterrupt):
        await backfill.run(open_only=True, force=True, limit=None, batch=2)
    stamps = await _stamps(db_session)
    assert stamps["connector"] == (False, 200_000)
    assert [stamps[k] for k in ("t2", "t1", "t0")] == [(True, 180_000), (True, 180_000), (False, 180_000)]

    # The rerun names the moment the forced read began and reads the rest.
    started = await db_session.scalar(select(func.min(Job.structured_at)).where(Job.structured_at > EARLIER))
    monkeypatch.setattr(backfill, "extract_disclosed_comp", real)
    summary = await backfill.run(open_only=True, force=True, limit=None, batch=2, force_before=started)
    assert summary["processed"] == 1
    assert (await _stamps(db_session))["t0"] == (True, 180_000)


async def test_a_dry_run_counts_the_selection_and_writes_nothing(db_session, scratch_scope, monkeypatch):
    await _seed_forced(db_session)
    before = await _stamps(db_session)
    summary = await backfill.run(open_only=True, force=True, limit=None, dry_run=True)
    assert summary["owed"] == 3  # three text rows; the connector band is not the text pass's
    assert summary["processed"] == 0
    assert await _stamps(db_session) == before
