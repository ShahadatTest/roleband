"""A backfill saves its progress per batch and resumes.

Run in one transaction, `python -m tracker.skills.backfill --open` would lose
every row to an app quit that SIGKILLs it. Each batch commits on its own: a run that dies keeps the
batches before the one it died in, and a rerun does only the rest. Real
commits on the scratch database; the "kill" is a failure raised after a batch
has written its rows, which rolls that batch back exactly as a dead connection
does.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from tracker.db.models import Job, JobQualification
from tracker.skills import backfill
from tracker.skills.extract import EXTRACTOR_VERSION

T0 = datetime(2026, 10, 3, tzinfo=UTC)

pytestmark = pytest.mark.asyncio


class Killed(RuntimeError):
    pass


def _job(n: int) -> Job:
    return Job(
        company="acme", req_id=f"r{n}", dedupe_key=f"acme:r{n}", title=f"Product Manager {n}",
        url=f"https://careers.example.test/{n}", status="open", in_scope=True,
        level_band="senior", level_confidence="confirmed", family="product_management",
        track="product_program", locations=["New York, NY, USA"], location_groups=["new_york"],
        domains=[], comp_currency="USD", first_seen=T0, last_seen=T0,
        description_sections=[{
            "key": "minimum_qualifications", "title": "Minimum Qualifications",
            "content": f"{n}+ years of product management experience",
        }],
    )


@pytest_asyncio.fixture
async def five_jobs(db_session, scratch_scope) -> list[int]:
    db_session.add_all([_job(n) for n in range(1, 6)])
    await db_session.commit()
    return list((await db_session.scalars(select(Job.id).order_by(Job.id))).all())


def _kill_after_writing(monkeypatch, dies_with: int) -> None:
    """The batch holding job `dies_with` writes its rows, then the run dies."""
    real = backfill.extract_requirements

    async def extract(session, job_ids, **kwargs):
        done = await real(session, job_ids, **kwargs)
        await session.flush()
        if dies_with in job_ids:
            raise Killed
        return done

    monkeypatch.setattr(backfill, "extract_requirements", extract)


async def _saved(db_session) -> list[str]:
    db_session.expire_all()
    rows = await db_session.scalars(select(Job.req_id).where(
        Job.requirements_extractor_version == EXTRACTOR_VERSION).order_by(Job.id))
    return list(rows.all())


async def test_a_run_that_dies_keeps_every_batch_before_the_one_it_died_in(db_session, five_jobs, monkeypatch):
    _kill_after_writing(monkeypatch, dies_with=five_jobs[2])
    with pytest.raises(Killed):
        await backfill.run(open_only=True, force=False, batch=2)
    assert await _saved(db_session) == ["r1", "r2"]
    rows = await db_session.scalar(select(func.count()).select_from(JobQualification))
    assert rows == 2  # the dead batch's rows rolled back with it


async def test_one_transaction_for_the_whole_run_loses_everything(db_session, five_jobs, monkeypatch):
    # Control: one transaction. The same failure keeps nothing.
    _kill_after_writing(monkeypatch, dies_with=five_jobs[2])
    with pytest.raises(Killed):
        await backfill.run(open_only=True, force=False, batch=len(five_jobs))
    assert await _saved(db_session) == []


async def test_a_rerun_does_only_what_the_dead_run_left(db_session, five_jobs, monkeypatch, capsys):
    # Only the extractor comes back: a blanket `monkeypatch.undo()` would also
    # lift the scratch scope and the live-database guard.
    real = backfill.extract_requirements
    _kill_after_writing(monkeypatch, dies_with=five_jobs[2])
    with pytest.raises(Killed):
        await backfill.run(open_only=True, force=False, batch=2)
    monkeypatch.setattr(backfill, "extract_requirements", real)
    result = await backfill.run(open_only=True, force=False, batch=2)
    assert result == {"jobs": 5, "processed": 3}
    assert await _saved(db_session) == ["r1", "r2", "r3", "r4", "r5"]
    assert f"saved 2/5 jobs (through id {five_jobs[1]})" in capsys.readouterr().out


async def test_a_forced_run_resumes_after_the_last_id_it_saved(db_session, five_jobs):
    await backfill.run(open_only=True, force=False, batch=2)
    result = await backfill.run(open_only=True, force=True, after=five_jobs[2], batch=2)
    assert result == {"jobs": 2, "processed": 2}


async def test_the_posting_carries_its_required_years_for_the_board(db_session, five_jobs):
    # Written with the rows, by the same definition Job detail shows.
    preferred_only = _job(6)
    preferred_only.description_sections = [{
        "key": "preferred_qualifications", "title": "Preferred Qualifications",
        "content": "12+ years of product management experience",
    }]
    db_session.add(preferred_only)
    await db_session.commit()
    await backfill.run(open_only=True, force=False, batch=2)
    db_session.expire_all()
    years = dict((await db_session.execute(select(Job.req_id, Job.required_years))).all())
    assert years == {"r1": 1.0, "r2": 2.0, "r3": 3.0, "r4": 4.0, "r5": 5.0, "r6": None}
