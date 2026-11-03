"""Backfills save per batch: a run that dies keeps what it saved.

A backfill holding thousands of postings in one transaction loses every row
when the app quits. Every backfill that rewrites many rows goes through
`commit_in_batches`. Real commits on
the scratch database; the "kill" is a failure raised after a batch has written,
which rolls that batch back exactly as a dead connection does. The skills
backfill's own resume contract is `tests/test_skills_backfill.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from scripts import backfill_level_bands, backfill_notifications
from tracker.content import fingerprint_content
from tracker.db.models import Job, Notification, ScrapeRun
from tracker.db.session import commit_in_batches

pytestmark = pytest.mark.asyncio
T0 = datetime(2026, 10, 3, tzinfo=UTC)


class Killed(RuntimeError):
    pass


def _job(n: int, **over) -> Job:
    row = dict(
        company="acme", req_id=f"r{n}", dedupe_key=f"acme:r{n}", title=f"Senior Software Engineer {n}",
        url=f"https://careers.example.test/{n}", status="open", in_scope=True,
        level_band="mid", level_confidence="confirmed", level_basis="stated",
        family="software_engineering", track="technical", locations=["New York, NY, USA"],
        location_groups=["new_york"], domains=[], comp_currency="USD", first_seen=T0, last_seen=T0,
        description_text=f"Build systems {n}",
    )
    row.update(over)
    return Job(**row)


@pytest_asyncio.fixture
async def scoped(db_session, scratch_scope):
    """Every `session_scope` the code under test opens lands on the scratch DB."""
    return db_session


def _dies_on_batch(work, batch: int):
    """`work`, except that the `batch`-th call writes its rows and then the run dies."""
    calls = 0

    async def wrapped(session, ids):
        nonlocal calls
        calls += 1
        done = await work(session, ids)
        await session.flush()
        if calls == batch:
            raise Killed
        return done

    return wrapped


async def _seed(db_session, rows) -> list[int]:
    db_session.add_all(rows)
    await db_session.commit()
    return list((await db_session.scalars(select(Job.id).order_by(Job.id))).all())


async def _fingerprinted(db_session) -> int:
    db_session.expire_all()
    return await db_session.scalar(select(func.count()).select_from(Job).where(Job.content_hash.is_not(None)))


# --- the helper ------------------------------------------------------------------ #


async def test_a_run_that_dies_keeps_every_batch_before_the_one_it_died_in(scoped):
    ids = await _seed(scoped, [_job(n) for n in range(1, 6)])
    with pytest.raises(Killed):
        await commit_in_batches(ids, _dies_on_batch(fingerprint_content, 2), size=2, label="jobs", report=None)
    assert await _fingerprinted(scoped) == 2
    # Idempotent work resumes by itself: the rerun bumps only the three left.
    assert await commit_in_batches(ids, fingerprint_content, size=2, label="jobs", report=None) == 3


async def test_one_transaction_for_everything_keeps_nothing(scoped):
    # Negative control: a single transaction loses all rows when the batch fails.
    ids = await _seed(scoped, [_job(n) for n in range(1, 6)])
    with pytest.raises(Killed):
        await commit_in_batches(ids, _dies_on_batch(fingerprint_content, 1), size=len(ids), label="jobs",
                                report=None)
    assert await _fingerprinted(scoped) == 0


async def test_each_report_names_the_last_id_saved(scoped):
    ids = await _seed(scoped, [_job(n) for n in range(1, 4)])
    lines: list[str] = []
    await commit_in_batches(ids, fingerprint_content, size=2, label="jobs", report=lines.append)
    assert lines == [f"saved 2/3 jobs (through id {ids[1]})", f"saved 3/3 jobs (through id {ids[2]})"]


# --- the backfills on it ---------------------------------------------------------- #


async def test_level_bands_apply_keeps_saved_batches_and_a_rerun_finishes_the_scope(scoped, monkeypatch):
    # Stored as "mid", read as senior: every row is a pending level change.
    await _seed(scoped, [_job(n) for n in range(1, 6)])
    real = backfill_level_bands.set_job_levels
    calls = 0

    async def dies_on_second(session, changes):
        nonlocal calls
        calls += 1
        await real(session, changes)
        await session.flush()
        if calls == 2:
            raise Killed

    monkeypatch.setattr(backfill_level_bands, "set_job_levels", dies_on_second)
    with pytest.raises(Killed):
        await backfill_level_bands.backfill(apply=True, company=None, batch=2)
    scoped.expire_all()
    bands = list((await scoped.scalars(select(Job.level_band).order_by(Job.id))).all())
    assert bands == ["senior", "senior", "mid", "mid", "mid"]

    monkeypatch.setattr(backfill_level_bands, "set_job_levels", real)
    rescoped: list[bool] = []
    real_scope = backfill_level_bands.recompute_saved_scope

    async def recompute(session):
        rescoped.append(True)
        return await real_scope(session)

    monkeypatch.setattr(backfill_level_bands, "recompute_saved_scope", recompute)
    stats = await backfill_level_bands.backfill(apply=True, company=None, batch=2)
    assert stats["band_changed"] == 3
    scoped.expire_all()
    assert set((await scoped.scalars(select(Job.level_band))).all()) == {"senior"}
    # Nothing pending: the scope is still recomputed, so a run killed after its
    # last batch but before scope recomputation is finished by the rerun.
    await backfill_level_bands.backfill(apply=True, company=None, batch=2)
    assert rescoped == [True, True]


async def test_notifications_keep_the_runs_they_saved(scoped, monkeypatch):
    scoped.add_all([ScrapeRun(started_at=T0, finished_at=T0, status="error") for _ in range(4)])
    await scoped.commit()
    real = backfill_notifications.generate_notifications
    calls = 0

    async def dies_on_third(session, run, **kwargs):
        nonlocal calls
        calls += 1
        done = await real(session, run, **kwargs)
        await session.flush()
        if calls == 3:
            raise Killed
        return done

    monkeypatch.setattr(backfill_notifications, "generate_notifications", dies_on_third)
    with pytest.raises(Killed):
        await backfill_notifications.main(batch=2)
    scoped.expire_all()
    saved = set((await scoped.scalars(select(Notification.run_id))).all())
    first_two = list((await scoped.scalars(select(ScrapeRun.id).order_by(ScrapeRun.id).limit(2))).all())
    assert saved == set(first_two)
