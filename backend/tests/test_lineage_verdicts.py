"""Relationship verdicts against a real database: one transaction, and an Undo that keeps later decisions.

A verdict and the lineage rebuild commit together: committing the verdict
first would leave a durable verdict behind a failed request when the rebuild
fails, and let two rebuilds publish an older snapshot last. Undo does not
restore or delete by id alone: a twin the verdict created and a person
confirmed again afterwards stays, and a counterpart decided again keeps its
later decision. Confirming onto an existing counterpart keeps its evidence and
decision history.

Every request goes through the real routes (`api_client`); every read-back is
a fresh session, so nothing is read from the handler's own identity map.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from tests.barriers import until_waiting
from tests.lineage_rows import (
    T0,
    duplicate_proposal,
    fresh_sessions,
    lineage_job,
    review_link,
    seed_pair,
    seed_rows,
    twin_proposal,
)
from tracker.api.routers import lineage as lineage_router
from tracker.db.models import Job, JobLineageLink, JobTwinLink
from tracker.lineage import detect
from tracker.lineage.review import _record_relationship_outcome


async def _read(db_session, model, row_id):
    async with fresh_sessions(db_session)() as session:
        return await session.get(model, row_id)


async def _twins(db_session) -> list[JobTwinLink]:
    async with fresh_sessions(db_session)() as session:
        return list((await session.scalars(select(JobTwinLink).order_by(JobTwinLink.id))).all())


async def _lineage_ids(db_session, *jobs: Job) -> list[int | None]:
    async with fresh_sessions(db_session)() as session:
        return [(await session.get(Job, job.id)).lineage_id for job in jobs]


# --- what a verdict writes, and the way back


@pytest.mark.asyncio
async def test_a_twin_verdict_rejects_the_proposal_and_creates_the_twin(api_client, db_session):
    older, newer = await seed_pair(db_session)
    (link,) = await seed_rows(db_session, duplicate_proposal(older, newer))

    body = await review_link(api_client, "duplicate", link.id, "twin")

    stored = await _read(db_session, JobLineageLink, link.id)
    (twin,) = await _twins(db_session)
    assert (stored.status, stored.evidence["review_outcome"]) == ("rejected", "twin")
    assert (body["decision"], body["twin_link_id"], body["kept"]) == ("twin", twin.id, [])
    assert (twin.job_a_id, twin.job_b_id, twin.status) == (older.id, newer.id, "confirmed")
    # The verdict remembers the row it created, as it left it, so Undo can tell.
    (entry,) = stored.evidence["undo"]["job_twin_link"]
    assert (entry["id"], entry["before"], entry["after"]["status"]) == (twin.id, None, "confirmed")


@pytest.mark.asyncio
async def test_confirming_a_twin_rejects_the_duplicate_counterpart(api_client, db_session):
    older, newer = await seed_pair(db_session)
    counterpart, twin = await seed_rows(
        db_session,
        duplicate_proposal(older, newer),
        twin_proposal(older, newer, evidence={"review_outcome": "different"}),
    )

    body = await review_link(api_client, "twin", twin.id, "confirmed")

    stored = await _read(db_session, JobTwinLink, twin.id)
    rejected = await _read(db_session, JobLineageLink, counterpart.id)
    assert (body["decision"], stored.status) == ("twin", "confirmed")
    assert stored.evidence["decision_history"][0]["decision"] == "different"
    assert (rejected.status, rejected.evidence["review_outcome"]) == ("rejected", "twin")
    assert rejected.evidence["reasons"] == ["close pair"]  # its own evidence stays
    (entry,) = stored.evidence["undo"]["job_lineage_link"]
    assert entry["before"]["status"] == "pending"  # as it was, not as it is now


@pytest.mark.asyncio
async def test_confirming_a_duplicate_rejects_the_twin_counterpart(api_client, db_session):
    older, newer = await seed_pair(db_session)
    link, counterpart = await seed_rows(db_session, duplicate_proposal(older, newer), twin_proposal(older, newer))

    body = await review_link(api_client, "duplicate", link.id, "confirmed")

    assert (body["decision"], body["twin_link_id"]) == ("duplicate", None)
    assert (await _read(db_session, JobTwinLink, counterpart.id)).status == "rejected"
    assert await _lineage_ids(db_session, older, newer) != [None, None]


@pytest.mark.asyncio
async def test_undo_reopens_the_link_and_puts_the_counterpart_back(api_client, db_session):
    older, newer = await seed_pair(db_session)
    link, counterpart = await seed_rows(db_session, duplicate_proposal(older, newer), twin_proposal(older, newer))
    await review_link(api_client, "duplicate", link.id, "confirmed")

    body = await review_link(api_client, "duplicate", link.id, "pending")

    stored = await _read(db_session, JobLineageLink, link.id)
    restored = await _read(db_session, JobTwinLink, counterpart.id)
    assert body == {
        "id": link.id, "status": "pending", "reviewed_at": None, "lineages": 0,
        "decision": None, "twin_link_id": None, "kept": [],
    }
    assert (stored.status, stored.reviewed_at) == ("pending", None)
    assert "review_outcome" not in stored.evidence and "undo" not in stored.evidence
    assert stored.evidence["reasons"] == ["close pair"]
    assert stored.evidence["decision_history"][0]["decision"] == "duplicate"
    assert (restored.status, restored.reviewed_at, restored.evidence) == ("pending", None, {"reasons": ["shared text"]})
    assert await _lineage_ids(db_session, older, newer) == [None, None]


@pytest.mark.asyncio
async def test_undoing_a_twin_verdict_deletes_the_twin_it_created(api_client, db_session):
    older, newer = await seed_pair(db_session)
    (link,) = await seed_rows(db_session, duplicate_proposal(older, newer))
    await review_link(api_client, "duplicate", link.id, "twin")

    await review_link(api_client, "duplicate", link.id, "pending")

    assert await _twins(db_session) == []
    assert (await _read(db_session, JobLineageLink, link.id)).status == "pending"


@pytest.mark.asyncio
async def test_undoing_a_duplicate_verdict_on_a_twin_removes_the_duplicate_it_created(api_client, db_session):
    older, newer = await seed_pair(db_session)
    (twin,) = await seed_rows(db_session, twin_proposal(older, newer))
    await review_link(api_client, "twin", twin.id, "duplicate")
    assert await _lineage_ids(db_session, older, newer) != [None, None]

    body = await review_link(api_client, "twin", twin.id, "pending")

    async with fresh_sessions(db_session)() as session:
        assert (await session.scalars(select(JobLineageLink))).all() == []
    assert (body["status"], body["decision"], body["lineages"], body["kept"]) == ("pending", None, 0, [])
    assert await _lineage_ids(db_session, older, newer) == [None, None]


@pytest.mark.asyncio
async def test_changing_a_verdict_unwinds_the_one_it_replaces(api_client, db_session):
    """`evidence["undo"]` is one slot; deciding again without unwinding would
    orphan the twin the first verdict created."""
    older, newer = await seed_pair(db_session)
    (link,) = await seed_rows(db_session, duplicate_proposal(older, newer))
    await review_link(api_client, "duplicate", link.id, "twin")

    await review_link(api_client, "duplicate", link.id, "confirmed")

    assert await _twins(db_session) == []
    stored = await _read(db_session, JobLineageLink, link.id)
    assert (stored.status, stored.evidence["undo"]) == ("confirmed", {"job_twin_link": []})


@pytest.mark.asyncio
async def test_undo_on_a_pending_link_changes_nothing(api_client, db_session):
    older, newer = await seed_pair(db_session)
    (link,) = await seed_rows(db_session, duplicate_proposal(older, newer))

    body = await review_link(api_client, "duplicate", link.id, "pending")

    assert (body["decision"], body["kept"]) == (None, [])
    assert (await _read(db_session, JobLineageLink, link.id)).evidence == {"reasons": ["close pair"]}


@pytest.mark.asyncio
async def test_unknown_verdicts_name_the_whole_vocabulary_and_change_nothing(api_client, db_session):
    older, newer = await seed_pair(db_session)
    link, twin = await seed_rows(db_session, duplicate_proposal(older, newer), twin_proposal(older, newer))

    lineage = await review_link(api_client, "duplicate", link.id, "undo", expected=422)
    twins = await review_link(api_client, "twin", twin.id, "undo", expected=422)

    assert [error["ctx"]["expected"] for error in lineage["detail"]] == ["'confirmed', 'rejected', 'twin' or 'pending'"]
    assert [error["ctx"]["expected"] for error in twins["detail"]] == ["'confirmed', 'rejected', 'duplicate' or 'pending'"]
    assert (await _read(db_session, JobLineageLink, link.id)).status == "pending"
    assert (await _read(db_session, JobTwinLink, twin.id)).status == "pending"


def test_relationship_outcome_history_only_records_actual_changes():
    unchanged = _record_relationship_outcome({"review_outcome": "duplicate"}, "duplicate")
    revised = _record_relationship_outcome(unchanged, "different")

    assert "decision_history" not in unchanged
    assert revised["review_outcome"] == "different"
    assert revised["decision_history"][0]["decision"] == "duplicate"


# --- an old Undo keeps a newer decision


@pytest.mark.asyncio
async def test_undo_keeps_a_twin_its_verdict_created_once_it_was_decided_again(api_client, db_session):
    older, newer = await seed_pair(db_session)
    (link,) = await seed_rows(db_session, duplicate_proposal(older, newer))
    created = (await review_link(api_client, "duplicate", link.id, "twin"))["twin_link_id"]
    # The person reviews that twin again, in History: not the same role after all.
    await review_link(api_client, "twin", created, "rejected")

    body = await review_link(api_client, "duplicate", link.id, "pending")

    (twin,) = await _twins(db_session)
    assert (twin.id, twin.status, twin.evidence["review_outcome"]) == (created, "rejected", "different")
    assert body["kept"] == [{"link": "twin", "id": created}]
    stored = await _read(db_session, JobLineageLink, link.id)
    assert stored.status == "pending"
    assert stored.evidence["decision_history"][-1]["kept"] == [{"link": "twin", "id": created}]


@pytest.mark.asyncio
async def test_undo_keeps_a_counterpart_confirmed_again_and_its_history(api_client, db_session):
    older, newer = await seed_pair(db_session)
    link, counterpart = await seed_rows(
        db_session, duplicate_proposal(older, newer), twin_proposal(older, newer)
    )
    await review_link(api_client, "duplicate", link.id, "confirmed")  # rejects the twin proposal
    # In History the person confirms that twin after all.
    await review_link(api_client, "twin", counterpart.id, "confirmed")

    body = await review_link(api_client, "duplicate", link.id, "pending")

    twin = await _read(db_session, JobTwinLink, counterpart.id)
    assert (twin.status, twin.evidence["review_outcome"]) == ("confirmed", "twin")
    # The rejection the duplicate verdict wrote onto it is its history now.
    assert [h["decision"] for h in twin.evidence["decision_history"]] == ["duplicate"]
    assert twin.evidence["reasons"] == ["shared text"]
    assert (await _read(db_session, JobLineageLink, link.id)).status == "pending"
    assert body["kept"] == [{"link": "twin", "id": counterpart.id}]


@pytest.mark.asyncio
async def test_confirming_onto_an_existing_twin_keeps_its_history(api_client, db_session):
    """A manual twin over a pending proposal that carries a withdrawn
    verdict's history confirms it and keeps that history. Over a person's
    standing "Different" it is refused (a manual route never
    rewrites a decision; the verdict commands, with their Undo, change it)."""
    older, newer = await seed_pair(db_session)
    (twin,) = await seed_rows(
        db_session,
        twin_proposal(
            older, newer, status="pending",
            evidence={"decision_history": [{"decision": "twin"}, {"decision": "different"}],
                      "reasons": ["shared text"]},
        ),
    )

    response = await api_client.post("/api/twins/links", json={"job_id": newer.id, "twin_job_id": older.id})

    assert response.status_code == 201, response.text
    stored = await _read(db_session, JobTwinLink, twin.id)
    assert (stored.status, stored.method, stored.evidence["review_outcome"]) == ("confirmed", "manual", "twin")
    assert [h["decision"] for h in stored.evidence["decision_history"]] == ["twin", "different"]
    assert stored.evidence["reasons"] == ["human-created twin relationship"]


@pytest.mark.asyncio
async def test_a_manual_twin_never_rewrites_a_standing_different(api_client, db_session):
    older, newer = await seed_pair(db_session)
    evidence = {"review_outcome": "different", "decision_history": [{"decision": "twin"}],
                "reasons": ["shared text"]}
    (twin,) = await seed_rows(
        db_session, twin_proposal(older, newer, status="rejected", reviewed_at=T0, evidence=evidence)
    )

    response = await api_client.post("/api/twins/links", json={"job_id": newer.id, "twin_job_id": older.id})

    assert response.status_code == 409, response.text
    stored = await _read(db_session, JobTwinLink, twin.id)
    assert (stored.status, stored.evidence) == ("rejected", evidence)


@pytest.mark.asyncio
async def test_undo_keeps_a_duplicate_its_twin_verdict_created_once_it_was_decided_again(api_client, db_session):
    older, newer = await seed_pair(db_session)
    (twin,) = await seed_rows(db_session, twin_proposal(older, newer))
    await review_link(api_client, "twin", twin.id, "duplicate")
    async with fresh_sessions(db_session)() as session:
        (created,) = (await session.scalars(select(JobLineageLink))).all()
    await review_link(api_client, "duplicate", created.id, "rejected")

    body = await review_link(api_client, "twin", twin.id, "pending")

    kept = await _read(db_session, JobLineageLink, created.id)
    assert (kept.status, kept.evidence["review_outcome"]) == ("rejected", "different")
    assert (await _read(db_session, JobTwinLink, twin.id)).status == "pending"
    assert body["kept"] == [{"link": "duplicate", "id": created.id}]


@pytest.mark.asyncio
async def test_a_second_undo_changes_nothing(api_client, db_session):
    older, newer = await seed_pair(db_session)
    (link,) = await seed_rows(db_session, duplicate_proposal(older, newer))
    created = (await review_link(api_client, "duplicate", link.id, "twin"))["twin_link_id"]
    await review_link(api_client, "twin", created, "rejected")
    await review_link(api_client, "duplicate", link.id, "pending")
    first = await _read(db_session, JobLineageLink, link.id)

    body = await review_link(api_client, "duplicate", link.id, "pending")

    again = await _read(db_session, JobLineageLink, link.id)
    assert [t.status for t in await _twins(db_session)] == ["rejected"]
    assert again.evidence == first.evidence
    assert body["kept"] == []


@pytest.mark.parametrize(("reviewed_later", "survives"), [(False, False), (True, True)])
@pytest.mark.asyncio
async def test_an_undo_recorded_before_this_change_keeps_a_row_reviewed_after_its_verdict(
    api_client, db_session, reviewed_later, survives
):
    """Stored verdicts carry `before` only. A row reviewed after the verdict was
    decided again; one reviewed at the verdict is the verdict's own and goes."""
    older, newer = await seed_pair(db_session)
    decided_at = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    twin_reviewed = decided_at + (timedelta(days=2) if reviewed_later else -timedelta(seconds=1))
    (twin,) = await seed_rows(
        db_session,
        twin_proposal(older, newer, status="confirmed", reviewed_at=twin_reviewed,
                       evidence={"review_outcome": "twin"}),
    )
    (link,) = await seed_rows(
        db_session,
        duplicate_proposal(
            older, newer, status="rejected", reviewed_at=decided_at,
            evidence={"review_outcome": "twin", "undo": {"job_twin_link": [{"id": twin.id, "before": None}]}},
        ),
    )

    body = await review_link(api_client, "duplicate", link.id, "pending")

    assert [t.id for t in await _twins(db_session)] == ([twin.id] if survives else [])
    assert body["kept"] == ([{"link": "twin", "id": twin.id}] if survives else [])


# --- a verdict and its projection commit together, one rebuild at a time


@pytest.mark.parametrize("fails", ["before_writing", "after_writing"])
@pytest.mark.asyncio
async def test_a_verdict_whose_projection_fails_is_not_recorded(api_client, db_session, monkeypatch, fails):
    older, newer = await seed_pair(db_session)
    link, counterpart = await seed_rows(db_session, duplicate_proposal(older, newer), twin_proposal(older, newer))
    real = detect.rebuild_lineage_projection

    async def broken(session):
        if fails == "after_writing":
            await real(session)
        raise RuntimeError("projection write failed")

    monkeypatch.setattr(lineage_router, "rebuild_lineage_projection", broken)
    with pytest.raises(RuntimeError, match="projection write failed"):
        await api_client.post(f"/api/lineage/links/{link.id}/review", json={"verdict": "confirmed"})

    stored = await _read(db_session, JobLineageLink, link.id)
    assert (stored.status, stored.reviewed_at, stored.evidence) == ("pending", None, {"reasons": ["close pair"]})
    assert (await _read(db_session, JobTwinLink, counterpart.id)).status == "pending"
    assert await _lineage_ids(db_session, older, newer) == [None, None]


@pytest.mark.asyncio
async def test_a_rebuild_that_read_older_links_cannot_publish_last(db_session):
    """Rebuild R1 reads the links, then pauses before writing. A verdict commits
    a new link and rebuild R2 starts. R2 must wait for R1 and then publish with
    the new link; without a lock R2 publishes first and R1's older snapshot
    overwrites it."""
    older, newer = await seed_pair(db_session)
    third, fourth = await seed_rows(db_session, lineage_job("c", 0), lineage_job("d", 10))
    await seed_rows(db_session, duplicate_proposal(older, newer, status="confirmed"))
    factory = fresh_sessions(db_session)
    gate, r1_waiting = asyncio.Event(), asyncio.Event()

    async with factory() as s1, factory() as s2:
        real_execute = s1.execute

        async def paused(statement, *args, **kwargs):
            if "UPDATE jobs" in str(statement) and not gate.is_set():
                r1_waiting.set()
                await gate.wait()
            return await real_execute(statement, *args, **kwargs)

        s1.execute = paused  # type: ignore[method-assign]

        async def r1():
            await detect.rebuild_lineage_projection(s1)
            await s1.commit()

        first = asyncio.create_task(r1())
        await asyncio.wait_for(r1_waiting.wait(), 10)

        s2.add(duplicate_proposal(third, fourth, status="confirmed"))
        await s2.commit()

        async def r2():
            await detect.rebuild_lineage_projection(s2)
            await s2.commit()

        second = asyncio.create_task(r2())
        await until_waiting(db_session.bind, second)
        r2_waited = not second.done()
        gate.set()
        await asyncio.wait_for(asyncio.gather(first, second), 20)

    assert r2_waited, "the second rebuild did not wait for the first"
    assert None not in await _lineage_ids(db_session, older, newer, third, fourth)
    async with factory() as session:
        assert (await session.scalar(text("SELECT count(*) FROM job_lineage"))) == 2
