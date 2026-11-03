"""A machine relationship is reconsidered when what decided it changes.

The detector's candidates are gated on family, band and places and scored on
title, places, stated pay and place sets. Re-checking a posting only when it is
re-embedded or the detector version moves, over the run's touched rows alone,
would let a relevel moving a band (no scrape, no new vector) leave a repost
link standing between postings that cannot be candidates any more. Real
Postgres, fixed vectors, the real lineage pass with an empty touched set: the
change happens between scans.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from tests.factories import make_job
from tracker.config import get_settings
from tracker.db.models import JobLineageLink
from tracker.lineage import detect
from tracker.workflows.post_passes import PostPassContext, _pass_lineage

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


def _vector() -> list[float]:
    return [1.0] + [0.0] * (get_settings().embedding_dim - 1)


async def _lineage_pass(db_session) -> None:
    ctx = PostPassContext(
        session=db_session, touched_ids=[], per_source={"google": {"errors": []}},
        settings=get_settings(), max_list=None,
    )
    await _pass_lineage(ctx)
    await db_session.commit()


async def _pair(db_session, *, decided: str | None = None):
    """A closed posting and its repost: same company, title, band, place."""
    prior = make_job("prior", title="Staff Product Manager, Cloud", status="closed", embedding=_vector(),
                 first_seen=NOW - timedelta(days=30), closed_at=NOW - timedelta(days=10))
    current = make_job("current", title=prior.title, embedding=_vector(), first_seen=NOW - timedelta(days=5),
                   embedded_at=NOW - timedelta(days=5))
    db_session.add_all([prior, current])
    await db_session.commit()
    await detect.detect_lineage(db_session, [prior.id, current.id])  # the detector links them
    await db_session.commit()
    await db_session.refresh(prior)
    await db_session.refresh(current)
    assert await _links(db_session) == [(current.id, prior.id, "pending")]
    if decided is not None:
        await db_session.execute(
            update(JobLineageLink).values(status=decided, reviewed_at=NOW)
        )
        await db_session.commit()
    await db_session.refresh(prior)
    await db_session.refresh(current)
    return prior, current


async def _links(db_session) -> list[tuple[int, int, str]]:
    rows = (await db_session.execute(
        select(JobLineageLink.job_id, JobLineageLink.prior_job_id, JobLineageLink.status)
    )).all()
    return sorted(tuple(r) for r in rows)


@pytest.mark.parametrize(
    ("side", "change"),
    [
        ("current", {"level_band": "principal"}),                     # an atlas relevel
        ("current", {"family": "program_management"}),
        ("current", {"location_groups": ["new_york"], "locations": ["New York, NY, USA"]}),
        ("current", {"disclosed_base_min": 400_000, "disclosed_base_max": 450_000,
                     "disclosed_currency": "USD", "disclosed_pay_period": "year"}),
        ("prior", {"level_band": "principal"}),                       # reaches the successor
    ],
    ids=["band", "family", "place", "pay", "predecessor_band"],
)
async def test_a_changed_input_withdraws_the_machine_link_without_a_rescan(db_session, side, change):
    prior, current = await _pair(db_session)
    if change.get("disclosed_base_min"):
        prior.disclosed_base_min, prior.disclosed_base_max = 150_000, 180_000  # disjoint bands
        prior.disclosed_currency, prior.disclosed_pay_period = "USD", "year"
    for column, value in change.items():
        setattr(prior if side == "prior" else current, column, value)
    await db_session.commit()

    await _lineage_pass(db_session)
    assert await _links(db_session) == []


@pytest.mark.parametrize("decided", ["confirmed", "rejected"])
async def test_a_person_decision_survives_a_changed_input(db_session, decided):
    prior, current = await _pair(db_session, decided=decided)
    current.level_band = "principal"
    await db_session.commit()
    await _lineage_pass(db_session)
    assert await _links(db_session) == [(current.id, prior.id, decided)]


async def test_a_change_that_decides_nothing_does_no_work(db_session):
    """The control: what a scan moves on every read (last seen, the estimate)
    is not a detector input, so nothing is re-checked."""
    _prior, current = await _pair(db_session)
    checked = current.lineage_checked_at
    assert checked is not None
    current.last_seen = NOW
    current.comp_median = 321_000
    await db_session.commit()
    assert (await detect.detect_lineage(db_session, None))["processed"] == 0
    await db_session.refresh(current)
    assert current.lineage_checked_at == checked
    assert len(await _links(db_session)) == 1


async def test_a_bounded_catch_up_resumes_where_it_stopped(db_session, monkeypatch):
    prior, current = await _pair(db_session)
    other = make_job("other", title=prior.title, embedding=_vector(), first_seen=NOW - timedelta(days=4))
    db_session.add(other)
    current.level_band = "principal"
    await db_session.commit()
    monkeypatch.setattr(get_settings(), "lineage_max_per_run", 1)
    await _lineage_pass(db_session)  # one row this run
    await _lineage_pass(db_session)  # the rest the next
    assert (await detect.detect_lineage(db_session, None))["processed"] == 0
    await db_session.refresh(current)
    assert current.lineage_input_key is not None


@pytest.mark.parametrize(
    ("status", "evidence"),
    [("confirmed", {}), ("rejected", {"review_outcome": "different"})],
    ids=["twins_confirmed", "same_opening_rejected"],
)
async def test_a_person_saying_two_postings_are_not_one_opening_withdraws_the_pending_link(
    db_session, status, evidence,
):
    """The candidate query reads twin verdicts, so a verdict recorded after
    the detector linked the pair decides the link, but only once the pair is
    re-checked. Fail-first: the verdict was not in the change key, so neither
    posting was re-checked and the pending link stayed."""
    from tracker.db.models import JobTwinLink

    prior, current = await _pair(db_session)
    db_session.add(JobTwinLink(job_a_id=prior.id, job_b_id=current.id, method="human", confidence="auto",
                               status=status, detector_version="test", evidence=evidence, reviewed_at=NOW))
    await db_session.commit()

    await _lineage_pass(db_session)
    assert await _links(db_session) == []


async def test_a_twin_link_that_says_nothing_about_the_opening_re_checks_nothing(db_session):
    """The control: a pending twin suggestion is no verdict, so it leaves
    the key, and the link, as they were."""
    from tracker.db.models import JobTwinLink

    prior, current = await _pair(db_session)
    checked = current.lineage_checked_at
    db_session.add(JobTwinLink(job_a_id=prior.id, job_b_id=current.id, method="embedding", confidence="suspected",
                               status="pending", detector_version="test", evidence={}))
    await db_session.commit()
    assert (await detect.detect_lineage(db_session, None))["processed"] == 0
    await db_session.refresh(current)
    assert current.lineage_checked_at == checked
    assert await _links(db_session) == [(current.id, prior.id, "pending")]
