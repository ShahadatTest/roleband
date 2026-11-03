"""One rule for what two postings may be to each other.

The manual twin route checks what the verdict commands check: a manual twin
never overrides a person's "Different". Every writer orients a pair the same
way, by `(first_seen, id)`. The detector honours a twin-queue verdict, so after
a person says "Related roles" or "Different" a re-detection does not propose
the pair again. Real Postgres through the real routes; read-backs in fresh sessions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.lineage_rows import review_link, seed_pair, twin_proposal
from tests.place_set_rows import place_set_job
from tracker.db.models import JobTwinLink
from tracker.lineage.detect import fetch_candidates
from tracker.lineage.pairs import prior_and_later
from tracker.lineage.score import HUMAN_SAID_NOT_ONE_OPENING

pytestmark = pytest.mark.asyncio


async def _read(db_session, model):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as session:
        return list((await session.scalars(select(model).order_by(model.id))).all())


async def test_equal_first_seen_orients_by_id_whatever_the_argument_order():
    """Equal first-seen times orient by id, so two writers naming the pair in
    opposite orders write one edge, never two opposite ones."""
    seen = datetime(2026, 7, 1, tzinfo=UTC)
    low = SimpleNamespace(id=4, first_seen=seen, company="hex")
    high = SimpleNamespace(id=9, first_seen=seen, company="hex")
    assert prior_and_later(low, high) == (low, high)
    assert prior_and_later(high, low) == (low, high)
    earlier = SimpleNamespace(id=12, first_seen=seen - timedelta(days=1), company="hex")
    assert prior_and_later(low, earlier) == (earlier, low)


async def test_a_manual_twin_never_overrides_a_different_verdict(api_client, db_session):
    older, newer = await seed_pair(db_session)
    proposal = twin_proposal(older, newer)
    db_session.add(proposal)
    await db_session.commit()
    await review_link(api_client, "twin", proposal.id, "rejected")

    created = await api_client.post(
        "/api/twins/links", json={"job_id": older.id, "twin_job_id": newer.id}
    )
    assert created.status_code == 409, created.text
    (row,) = await _read(db_session, JobTwinLink)
    assert row.status == "rejected"


@pytest.mark.parametrize(
    ("status", "outcome", "gated"),
    [
        ("confirmed", "twin", True),
        ("rejected", "different", True),
        # "The same opening": the person CONFIRMED a lineage; the detector
        # proposing it again is a no-op, and gating it would let it choose a
        # second predecessor instead.
        ("rejected", "duplicate", False),
        ("pending", None, False),
    ],
)
async def test_the_detector_reads_a_twin_queue_verdict(db_session, status, outcome, gated):
    london = await place_set_job(db_session, 1, "London")
    bristol = await place_set_job(db_session, 2, "Bristol")
    a, b = sorted((london.id, bristol.id))
    db_session.add(
        JobTwinLink(
            job_a_id=a, job_b_id=b, method="content_overlap", confidence="suspected",
            status=status, detector_version="twins/test",
            evidence={"review_outcome": outcome} if outcome else {},
            reviewed_at=datetime.now(UTC) - timedelta(hours=1) if outcome else None,
        )
    )
    await db_session.commit()

    scored = {sc.candidate.prior_job_id: sc for sc in await fetch_candidates(db_session, bristol, k=5)}
    verdict = scored[london.id].verdict
    if gated:
        assert verdict.decision == "reject"
        assert verdict.reasons == [HUMAN_SAID_NOT_ONE_OPENING]
    else:
        assert HUMAN_SAID_NOT_ONE_OPENING not in verdict.reasons
