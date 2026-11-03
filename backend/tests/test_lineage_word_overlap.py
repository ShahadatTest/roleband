"""The detector reads both descriptions and demotes a title-only match.

`score.py` decides; this pins that `detect_lineage` feeds it the word overlap
from the stored text, end to end over the database, so a generic title over
two different jobs reaches the review queue instead of merging on its own.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tests.company_contract_seed import company_job
from tracker.config import get_settings
from tracker.db.models import Job, JobLineageLink
from tracker.lineage.detect import detect_lineage

NOW = datetime.now(UTC)
TITLE = "Senior Technical Program Manager"
BATTERY = (
    "Lead battery benchmarking programs across cell suppliers. Define test plans for "
    "thermal runaway, cycle life and charge rates; coordinate laboratory schedules."
)
CERTIFICATION = (
    "Drive regulatory certification for consumer devices in new markets. Own submissions "
    "to standards bodies, compliance evidence and launch readiness reviews."
)


def _vector(cosine: float) -> list[float]:
    """A unit vector at `cosine` to the first axis."""
    dim = get_settings().embedding_dim
    vec = [0.0] * dim
    vec[0], vec[1] = cosine, math.sqrt(1 - cosine * cosine)
    return vec


async def _detect(db_session, newer_text: str) -> JobLineageLink:
    prior = company_job("acme", "prior", title=TITLE, description_text=BATTERY, status="closed",
                 first_seen=NOW - timedelta(days=60), last_seen=NOW - timedelta(days=30),
                 closed_at=NOW - timedelta(days=30), embedding=_vector(1.0), embedded_at=NOW)
    newer = company_job("acme", "newer", title=TITLE, description_text=newer_text,
                 first_seen=NOW - timedelta(days=5), last_seen=NOW,
                 embedding=_vector(0.93), embedded_at=NOW)
    db_session.add_all([prior, newer])
    await db_session.commit()
    await detect_lineage(db_session, [newer.id])
    return (await db_session.scalars(select(JobLineageLink).where(JobLineageLink.job_id == newer.id))).one()


@pytest.mark.asyncio
async def test_a_generic_title_over_different_work_goes_to_review(db_session):
    link = await _detect(db_session, CERTIFICATION)
    assert (link.confidence, link.status, link.method) == ("suspected", "pending", "title+embedding")
    assert any("of their words" in reason for reason in link.evidence["reasons"])


@pytest.mark.asyncio
async def test_the_same_title_over_the_same_work_still_merges_on_its_own(db_session):
    link = await _detect(db_session, BATTERY + " Report weekly to the hardware leads.")
    assert (link.confidence, link.status) == ("auto", "pending")


@pytest.mark.asyncio
async def test_re_detection_keeps_a_verdict_somebody_took_back(db_session):
    """Undo returns a link to `pending` and leaves the decision it withdrew in
    `evidence.decision_history`. A detection pass deletes every pending link
    for the job and replaces the evidence of the ones it proposes again, so
    that record has to survive both writes or a scrape erases it. Fail-first:
    `decision_history` is absent after the second pass.
    """
    link = await _detect(db_session, BATTERY)
    assert link.status == "pending"

    # What `review.py` leaves behind once a verdict is taken back.
    link.evidence = {
        **link.evidence,
        "decision_history": [{"decision": "duplicate", "changed_at": NOW.isoformat()}],
    }
    await db_session.commit()

    # A later scrape re-embeds the posting, which is one of the things that
    # makes the detector read it again (`_stale_clause`). The pass then deletes
    # its own pending proposals and writes the ones its rules still make.
    job = await db_session.get(Job, link.job_id)
    job.embedded_at = NOW + timedelta(days=1)
    await db_session.commit()
    summary = await detect_lineage(db_session, [link.job_id])
    await db_session.commit()
    assert summary["processed"] == 1, "the pass skipped the job, so this proves nothing"

    again = (
        await db_session.scalars(select(JobLineageLink).where(JobLineageLink.job_id == link.job_id))
    ).one()
    assert again.status == "pending"
    assert [h["decision"] for h in again.evidence["decision_history"]] == ["duplicate"]
    # The detector still owns everything else it writes.
    assert again.evidence["reasons"], "the fresh evidence is still the detector's"


@pytest.mark.asyncio
async def test_re_detection_still_withdraws_an_ordinary_proposal(db_session):
    """The negative control for the guard above: a pending proposal carrying no
    history is still the detector's to withdraw when its rules stop making it."""
    link = await _detect(db_session, BATTERY)
    # A third posting the current rules do not pair with this one: different
    # title, orthogonal vector.
    unrelated = company_job("acme", "unrelated", title="Warehouse Operations Lead",
                     description_text=CERTIFICATION, status="closed",
                     first_seen=NOW - timedelta(days=90), last_seen=NOW - timedelta(days=80),
                     closed_at=NOW - timedelta(days=80), embedding=_vector(0.0), embedded_at=NOW)
    db_session.add(unrelated)
    await db_session.commit()
    stale = JobLineageLink(
        job_id=link.job_id, prior_job_id=unrelated.id, relation="duplicate",
        method="title+embedding", score=1.0, confidence="suspected", status="pending",
        detector_version="lineage/old", evidence={"reasons": ["an older rule"]},
    )
    db_session.add(stale)
    await db_session.commit()
    stale_prior = stale.prior_job_id

    job = await db_session.get(Job, link.job_id)
    job.embedded_at = NOW + timedelta(days=1)
    await db_session.commit()
    summary = await detect_lineage(db_session, [link.job_id])
    await db_session.commit()
    assert summary["processed"] == 1, "the pass skipped the job, so this proves nothing"

    priors = set(
        (await db_session.scalars(
            select(JobLineageLink.prior_job_id).where(JobLineageLink.job_id == link.job_id)
        )).all()
    )
    assert stale_prior not in priors, "a proposal with no history is still withdrawn"
