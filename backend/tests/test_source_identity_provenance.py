"""Every posting records the binding it was seen under, and who may close it.

Closure scope reads `job_source_identities`: a binding may close the postings
it owns, and a posting owned by another LIVE binding is the rebind case
nothing closes. Written as the posting is persisted, so the rule decides on
what this run actually read rather than on an empty table.

A retired binding owns nothing. When a company moves boards its old binding
is retired, and the postings it listed must still close by the ordinary
two-miss rule once the new board validates, which is what
`company_store.record_board_move` promises.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tracker.company_store import record_board_move
from tracker.db.binding import resolve_closure_scope
from tracker.db.models import (
    JobObservation,
    JobSourceIdentity,
    ScrapeRun,
    SourceBinding,
    TrackedCompany,
)
from tracker.db.repo import load_company_jobs, upsert_job
from tracker.schema import EnrichedJob, LevelBand, LevelConfidence, RawJob, WorkplaceType

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 1, tzinfo=UTC)
COMPANY = "hex-technologies"


def _enriched(req_id: str, title: str = "Staff Engineer") -> EnrichedJob:
    raw = RawJob(
        company=COMPANY, req_id=req_id, title=title,
        url=f"https://boards.example.test/{req_id}", locations=["London, UK"],
        workplace_type=WorkplaceType.ONSITE,
    )
    return EnrichedJob(
        raw=raw, level_band=LevelBand.STAFF, level_confidence=LevelConfidence.CONFIRMED,
        family="software_engineering", location_groups=["london"],
    )


async def _seed(db) -> SourceBinding:
    db.add(TrackedCompany(
        slug=COMPANY, display="Hex Technologies", adapter="greenhouse",
        board_token="hextechnologies", status="active", enabled=True, visible=True,
        source="directory-set", role_catalog_status="done",
    ))
    await db.flush()
    binding = SourceBinding(
        company_slug=COMPANY, connector_kind="adapter", connector_id="greenhouse",
        status="stable", closure_capability="authoritative",
    )
    db.add(binding)
    await db.flush()
    return binding


async def _run(db) -> ScrapeRun:
    run = ScrapeRun(status="running")
    db.add(run)
    await db.flush()
    return run


async def _identities(db) -> list[tuple[int, str]]:
    rows = (await db.execute(
        select(JobSourceIdentity.binding_id, JobSourceIdentity.source_key)
        .order_by(JobSourceIdentity.id))).all()
    return [tuple(r) for r in rows]


async def test_a_new_posting_records_the_binding_it_was_seen_under(db_session):
    """Fail-first: nothing wrote the table, so both the alias and the
    observation's provenance were absent on every posting ever persisted."""
    binding = await _seed(db_session)
    run = await _run(db_session)

    job, is_new = await upsert_job(
        db_session, run, _enriched("JR1"), {}, binding_id=binding.id
    )
    await db_session.commit()

    assert is_new
    assert await _identities(db_session) == [(binding.id, f"{COMPANY}:JR1")]
    obs = (await db_session.scalars(select(JobObservation))).one()
    identity = (await db_session.scalars(select(JobSourceIdentity))).one()
    assert (obs.binding_id, obs.source_identity_id) == (binding.id, identity.id)
    assert identity.job_id == job.id


async def test_a_re_seen_posting_keeps_one_alias_and_moves_its_last_seen(db_session):
    """The alias is the posting's identity under this board, not one row per
    sighting; the observation beside it is the append-only half."""
    binding = await _seed(db_session)
    run = await _run(db_session)
    await upsert_job(db_session, run, _enriched("JR1"), {}, binding_id=binding.id)
    await db_session.commit()
    first = (await db_session.scalars(select(JobSourceIdentity))).one()
    seen_first = first.first_seen

    existing = await load_company_jobs(db_session, COMPANY)
    await upsert_job(db_session, run, _enriched("JR1", "Staff Engineer II"), existing,
                     binding_id=binding.id)
    await db_session.commit()

    again = (await db_session.scalars(select(JobSourceIdentity))).all()
    assert len(again) == 1, "a second sighting is not a second alias"
    assert again[0].first_seen == seen_first, "the alias keeps when this board first said it"
    assert again[0].last_seen >= seen_first
    assert len((await db_session.scalars(select(JobObservation))).all()) == 2


async def test_a_posting_with_no_binding_in_scope_records_no_provenance(db_session):
    """A backfill or a company with no binding row records nothing rather than
    a binding it was not read under."""
    await _seed(db_session)
    run = await _run(db_session)
    await upsert_job(db_session, run, _enriched("JR9"), {})
    await db_session.commit()

    assert await _identities(db_session) == []
    obs = (await db_session.scalars(select(JobObservation))).one()
    assert (obs.binding_id, obs.source_identity_id) == (None, None)


async def test_the_old_board_s_postings_still_close_after_a_move(db_session):
    """`record_board_move` promises the old board's postings close by the
    ordinary two-miss rule once the new board validates. The aliases the old
    binding owns must not put them outside the new binding's scope, or no
    listing could ever close them. Fail-first, once identities exist: the
    moved company's postings are owned by a retired binding and the new
    binding's closure scope is empty."""
    old = await _seed(db_session)
    run = await _run(db_session)
    job, _ = await upsert_job(db_session, run, _enriched("JR1"), {}, binding_id=old.id)
    await db_session.commit()

    assert await record_board_move(db_session, COMPANY, adapter="ashby", board_token="hex")
    await db_session.commit()
    new = (await db_session.scalars(select(SourceBinding).where(
        SourceBinding.company_slug == COMPANY, SourceBinding.status == "stable"))).one()
    # The new board earns authority by listing completely.
    new.closure_capability = "authoritative"
    await db_session.commit()

    scope = await resolve_closure_scope(
        db_session, COMPANY, open_jobs=[job], listing_is_authoritative=True
    )
    assert job.id in scope.speaks_for, scope.reason
    assert scope.may_close, scope.reason


async def test_a_posting_another_live_binding_owns_is_not_closed(db_session):
    """The rebind guard the retired case must not widen: a second binding that
    is still live owns the posting, so this one does not speak for it."""
    await _seed(db_session)
    run = await _run(db_session)
    job, _ = await upsert_job(db_session, run, _enriched("JR1"), {})
    other = SourceBinding(
        company_slug=COMPANY, connector_kind="adapter", connector_id="ashby",
        status="proposed", closure_capability="none",
    )
    db_session.add(other)
    await db_session.flush()
    db_session.add(JobSourceIdentity(
        binding_id=other.id, job_id=job.id, source_key=f"{COMPANY}:JR1", first_seen=NOW,
    ))
    await db_session.commit()

    scope = await resolve_closure_scope(
        db_session, COMPANY, open_jobs=[job], listing_is_authoritative=True
    )
    assert job.id not in scope.speaks_for, scope.reason
