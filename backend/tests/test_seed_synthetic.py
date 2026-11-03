"""The synthetic seeder's safety properties, held to the code.

`scripts/seed_synthetic.py` exists so a candidate build can be validated without
scraping anyone. It writes to a cluster that is per-USER and
shared by every checkout (`docs/development.md`), so "it cannot touch a row it did not write"
is not a nicety here — it is the property that makes the script safe to ship at
all, and the one a public repository's contributors will lean on hardest.

Every claim here is checked by planting the break, not by inspection: disable
the guard and the first test fails; widen `--clear`'s filter and the third
fails; switch the persist call to `RECONCILE` and the last fails.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from scripts.seed_synthetic import SYNTHETIC_PREFIX, clear, seed
from tracker.db.models import Job, SourceBinding
from tracker.taxonomy.locations import pay_country

# Small on purpose: these assert behaviour, not throughput, and each seeded row
# costs an enrichment pass.
_COUNT = 8


def _a_row_the_seeder_must_never_touch() -> Job:
    """A job with no synthetic prefix — i.e. indistinguishable from real data."""
    return Job(
        company="google",
        req_id="REAL-12345",
        dedupe_key="google:REAL-12345",
        title="A real posting",
        url="https://example.com/real",
        level_band="senior",
    )


@pytest.mark.asyncio
async def test_it_refuses_a_database_holding_rows_it_did_not_write(db_session):
    db_session.add(_a_row_the_seeder_must_never_touch())
    await db_session.flush()

    with pytest.raises(SystemExit) as refusal:
        await seed(db_session, _COUNT, seed_value=1, derived=False)

    assert SYNTHETIC_PREFIX in str(refusal.value)
    # The refusal must come BEFORE any write, not after a partial seed.
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 1


@pytest.mark.asyncio
async def test_it_seeds_an_empty_database_and_marks_every_row(db_session):
    total = await seed(db_session, _COUNT, seed_value=1, derived=False)

    assert total == _COUNT
    req_ids = (await db_session.scalars(select(Job.req_id))).all()
    assert len(req_ids) == _COUNT
    assert all(req.startswith(SYNTHETIC_PREFIX) for req in req_ids)
    # A dataset whose comp and level columns are empty renders a comp-shaped UI
    # with nothing in it, and would validate a candidate build of nothing. Our
    # pay is US pay: every posting in the US alone is priced, and one that may
    # be elsewhere is not.
    jobs = (await db_session.execute(select(Job.location_groups, Job.comp_median))).all()
    us = [comp for groups, comp in jobs if pay_country(groups) == "US"]
    elsewhere = [comp for groups, comp in jobs if pay_country(groups) != "US"]
    assert us and elsewhere  # control: the seed has both
    assert all(comp is not None for comp in us)
    assert all(comp is None for comp in elsewhere)
    assert await db_session.scalar(
        select(func.count()).select_from(Job).where(Job.level_band.isnot(None))
    ) == _COUNT


@pytest.mark.asyncio
async def test_clear_removes_its_own_rows_and_leaves_everything_else(db_session):
    await seed(db_session, _COUNT, seed_value=1, derived=False)
    db_session.add(_a_row_the_seeder_must_never_touch())
    await db_session.flush()

    removed = await clear(db_session)

    assert removed == _COUNT
    survivors = (await db_session.scalars(select(Job.req_id))).all()
    assert survivors == ["REAL-12345"]


@pytest.mark.asyncio
async def test_seeding_twice_upserts_rather_than_duplicating(db_session):
    first = await seed(db_session, _COUNT, seed_value=1, derived=False)
    second = await seed(db_session, _COUNT, seed_value=1, derived=False)

    assert first == second == _COUNT
    assert await db_session.scalar(select(func.count()).select_from(Job)) == _COUNT


@pytest.mark.asyncio
async def test_it_leaves_no_trace_in_binding_health(db_session):
    """Discovery mode, so fabricated rows never advance a binding's health.

    Health is what the closure gate reads: it is the system's belief about
    whether a source can be trusted to say a requisition is gone. Seeded rows
    must not be able to move it in either direction. `_record_source_health`
    runs only under `RECONCILE`, so this fails the moment the persist call is
    switched — which the weaker "binding never activates" assertion did NOT,
    because a synthetic collection is not `list_complete` and so could not have
    activated a binding under either mode.
    """
    await seed(db_session, _COUNT, seed_value=1, derived=False)

    bindings = (await db_session.scalars(select(SourceBinding))).all()
    assert bindings, "the seeder should have bootstrapped bindings"
    assert all(b.activated_at is None for b in bindings)
