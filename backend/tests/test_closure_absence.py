"""Closure by absence needs two misses, against the real pipeline.

A posting closes only when two complete listings at least
`closure_second_miss_min_hours` apart have not listed it, with no failed,
degraded or blocked scan of its company between them. A posting a failed scan
hides is typically not listed in the very next complete scan either, so the
reset on a failed scan (rule 3) is the part that holds it open, not the second
miss.

Time is moved by `_age_absence`, which shifts every recorded first miss into
the past exactly as a day between scans would; nothing else is faked.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select, update

from tracker.connectors import ADAPTER_REGISTRY, BaseAdapter
from tracker.connectors.recipes.outcome import RESETS_ABSENCE, SourceOutcome
from tracker.db.models import Job, JobLifecycleEvent
from tracker.db.repo import Absence, count_miss
from tracker.schema import ClosureBasis, RawJob
from tracker.workflows import pipeline, post_passes
from tracker.workflows.collection_types import ScanMode

pytestmark = pytest.mark.asyncio

DAY = timedelta(hours=21)


def posting(req_id: str) -> RawJob:
    return RawJob(
        company="apple", req_id=req_id, title="Staff Product Manager",
        url=f"https://careers.example.test/apple/{req_id}",
        locations=["San Francisco, CA, USA"],
        description_html="<p>Build distributed systems and mentor senior engineers.</p>",
    )


@pytest.fixture
def board(scratch_scope, monkeypatch):
    """apple's listing, set per run: (listed req_ids, quality, present-only req_ids)."""
    plan: dict[str, object] = {"keys": [], "quality": "complete", "present": []}

    class Listing(BaseAdapter):
        async def fetch(self):
            for key in plan["keys"]:
                yield posting(key)
            for key in plan["present"]:
                self.drift.observe_present(f"apple:{key}", "row named its requisition only")
            if plan["quality"] == "error":
                raise RuntimeError("source disconnected after its first page")

    class Compensation:
        def __init__(self, *_providers) -> None:
            pass

        async def resolve(self, _context):
            return None, []

        def reset(self, _providers, *, fingerprint):
            self.fingerprint = fingerprint

        async def aclose(self):
            pass

    monkeypatch.setattr(pipeline, "CompResolver", Compensation)
    monkeypatch.setattr(post_passes, "POST_PASSES", ())
    for adapter in ADAPTER_REGISTRY:
        monkeypatch.setitem(ADAPTER_REGISTRY, adapter, Listing)
    network = AsyncMock(side_effect=AssertionError("pipeline test attempted external HTTP"))
    monkeypatch.setattr(httpx.AsyncClient, "send", network)

    async def scan(keys, quality="complete", *, present=(), **kwargs):
        plan.update(keys=list(keys), quality=quality, present=list(present))
        return await pipeline.run_pipeline(companies=["apple"], hydrate=False, **kwargs)

    yield scan
    network.assert_not_awaited()


async def _age_absence(db_session, by: timedelta = DAY) -> None:
    await db_session.execute(
        update(Job).where(Job.absent_since.isnot(None))
        .values(absent_since=Job.absent_since - by)
    )
    await db_session.commit()


async def _gone(db_session) -> Job:
    db_session.expire_all()
    return (await db_session.scalars(select(Job).where(Job.req_id == "gone"))).one()


async def test_one_miss_holds_and_a_second_a_day_later_closes_with_its_evidence(db_session, board):
    await board(["kept", "gone"])

    missed = await board(["kept"])
    job = await _gone(db_session)
    assert (job.status, job.absent_scans) == ("open", 1)
    assert missed["closed"] == 0
    # The shadow record: what the listing missed, and what one miss would close.
    stats = missed["per_source"]["apple"]
    assert (stats["absence_open"], stats["absence_missed"]) == (2, 1)
    assert stats["absence_missing_share"] == 0.5
    assert (stats["absence_second_miss"], stats["closure_one_miss"]) == (0, 1)
    first_missed_at = job.absent_since

    await _age_absence(db_session)
    closing = await board(["kept"])
    job = await _gone(db_session)
    assert job.status == "closed"
    assert closing["closed"] == 1
    assert job.closure_basis == ClosureBasis.ABSENT_FROM_COMPLETE_LISTING.value
    assert job.closure_run_id == closing["run_id"]
    # A closure leaves no evidence on the row; the event keeps the first miss.
    assert (job.absent_scans, job.absent_since) == (0, None)
    event = (await db_session.scalars(select(JobLifecycleEvent).where(
        JobLifecycleEvent.job_id == job.id, JobLifecycleEvent.event_type == "closed",
    ))).one()
    assert event.run_id == closing["run_id"]
    assert event.detail["first_missed_at"] == (first_missed_at - DAY).isoformat()
    kept = (await db_session.scalars(select(Job).where(Job.req_id == "kept"))).one()
    assert (kept.status, kept.absent_scans) == ("open", 0)


async def test_two_misses_too_close_together_hold_and_the_gap_counts_from_the_first(
    db_session, board
):
    await board(["kept", "gone"])
    await board(["kept"])
    first = (await _gone(db_session)).absent_since

    await _age_absence(db_session, timedelta(hours=10))
    soon = await board(["kept"])
    job = await _gone(db_session)
    assert soon["closed"] == 0
    assert (job.status, job.absent_scans) == ("open", 1)
    # Anchored at the first miss, not moved by the second.
    assert job.absent_since == first - timedelta(hours=10)

    # 21 h after the first miss, 11 h after the second: closes.
    await _age_absence(db_session, timedelta(hours=11))
    assert (await board(["kept"]))["closed"] == 1


@pytest.mark.parametrize("anomaly,expected", [
    pytest.param(dict(keys=["kept"], quality="error"), "degraded", id="degraded"),
    pytest.param(dict(keys=[], quality="error"), "failed", id="failed"),
])
async def test_a_failed_scan_between_misses_starts_the_count_again(
    db_session, board, anomaly, expected
):
    """Replay: anomaly, clean miss, anomaly, clean miss. Stays open.

    A plain two-miss rule closes on the last scan; the reset is what holds it
    (mutation: drop it and this test fails on the final assertion).
    """
    await board(["kept", "gone"])

    first = await board(**anomaly)
    assert first["per_source"]["apple"]["outcome"] == expected
    await board(["kept"])
    assert (await _gone(db_session)).absent_scans == 1
    await _age_absence(db_session)
    second = await board(**anomaly)
    assert second["per_source"]["apple"]["outcome"] == expected
    assert (await _gone(db_session)).absent_scans == 0
    await _age_absence(db_session)

    last = await board(["kept"])
    job = await _gone(db_session)
    assert last["closed"] == 0
    assert (job.status, job.absent_scans) == ("open", 1)
    # The control: the same pair of clean misses with no anomaly between closes.
    await _age_absence(db_session)
    assert (await board(["kept"]))["closed"] == 1


@pytest.mark.parametrize("bound", [
    pytest.param({"max_list": 10}, id="capped"),
    pytest.param({"scan_mode": ScanMode.DISCOVERY}, id="discovery"),
    # A discovery probe that FAILS must not reset the count it never counted.
    pytest.param({"scan_mode": ScanMode.DISCOVERY, "quality": "error"}, id="failed-discovery"),
])
async def test_a_scan_that_is_not_evidence_neither_counts_nor_resets(db_session, board, bound):
    await board(["kept", "gone"])
    await board(["kept"])
    first = (await _gone(db_session)).absent_since
    await _age_absence(db_session)

    bounded = await board(["kept"], **bound)
    job = await _gone(db_session)
    assert bounded["closed"] == 0
    assert bounded["per_source"]["apple"]["absence_missed"] == 0
    assert (job.status, job.absent_scans, job.absent_since) == ("open", 1, first - DAY)

    # Neither did it reset: the next complete miss is the second.
    assert (await board(["kept"]))["closed"] == 1


@pytest.mark.parametrize("relist", [
    pytest.param({"keys": ["kept", "gone"]}, id="listed"),
    pytest.param({"keys": ["kept"], "present": ["gone"]}, id="present_only"),
    pytest.param({"keys": ["kept", "gone"], "max_list": 10}, id="listed_by_a_capped_scan"),
])
async def test_a_posting_seen_again_starts_its_count_again(db_session, board, relist):
    await board(["kept", "gone"])
    await board(["kept"])
    await _age_absence(db_session)

    await board(**relist)
    assert (await _gone(db_session)).absent_scans == 0
    await _age_absence(db_session)

    held = await board(["kept"])
    job = await _gone(db_session)
    assert held["closed"] == 0
    assert (job.status, job.absent_scans) == ("open", 1)


async def test_a_second_miss_counts_only_from_the_gap_after_the_first():
    now = datetime(2026, 10, 2, 12, tzinfo=UTC)
    gap = timedelta(hours=20)
    assert count_miss(Absence(), now=now, min_gap=gap) == Absence(1, now)
    first = Absence(1, now - timedelta(hours=19, minutes=59))
    assert count_miss(first, now=now, min_gap=gap) == first
    exact = Absence(1, now - gap)
    assert count_miss(exact, now=now, min_gap=gap) == Absence(2, now - gap)
    assert count_miss(exact, now=now, min_gap=gap).closes
    # Held at two by health, a later miss keeps the original anchor.
    assert count_miss(Absence(2, now - gap), now=now, min_gap=gap) == Absence(2, now - gap)


async def test_only_the_source_misbehaving_starts_the_count_again():
    """Our own bounds, a lossy read, an empty board and an unattempted source
    say nothing against the board, so they neither count nor reset."""
    expected = {
        SourceOutcome.DEGRADED: True, SourceOutcome.FAILED: True, SourceOutcome.BLOCKED: True,
        SourceOutcome.OK: False, SourceOutcome.CAPPED: False, SourceOutcome.BOUNDED: False,
        SourceOutcome.TRUNCATED: False, SourceOutcome.SUSPENDED: False,
        SourceOutcome.LOSSY: False, SourceOutcome.EMPTY: False,
        SourceOutcome.UNATTEMPTED: False,
    }
    assert set(expected) == set(SourceOutcome)
    assert {outcome for outcome, resets in expected.items() if resets} == RESETS_ABSENCE
