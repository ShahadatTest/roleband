"""A listing that served no postings, end to end.

Real collection, persistence, closure, health and scheduling against the
scratch database; only the board and the comp provider are stand-ins.

Two claims, kept apart because they fail in opposite directions:

1. **Zero rows never close anything**. Closure by absence on an empty listing
   is a separate contract that does not exist yet, so a listing that served
   nothing is never complete, whichever adapter read it. Otherwise an adapter
   that ends a zero-row listing without an empty guard keeps `list_complete`
   and a reconcile closes every open posting of the company.
2. **A board proven empty is a scan with no postings**, not a failure: no
   anomaly, no provider backoff, no catalog error, rechecked at the normal
   cadence. Read as failures, three of those quarantine the company and back
   off every company on its provider. It is still kept in view, because a
   moved board answers the same (Vercel). Every case has the unexplained zero
   beside it as the control, so a test that passed for both would be
   measuring nothing.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from tracker.config import Settings, get_settings
from tracker.connectors import ADAPTER_REGISTRY, BaseAdapter
from tracker.db.models import (
    Job,
    Notification,
    ProviderPressureState,
    ScrapeRun,
    ScrapeSourceRun,
    SourceBinding,
    SyncScheduleState,
    TrackedCompany,
)
from tracker.db.queries.binding_attention import (
    CAUSE_BOARD_MISSING,
    CAUSE_EMPTY_LISTING,
    binding_attention,
    followed_bindings,
)
from tracker.notifications.coverage import generate_coverage_notifications, rings
from tracker.notifications.run_result import classify_sync_result
from tracker.schema import RawJob
from tracker.workflows import pipeline, post_passes, scheduler

#: The shipped default (`Settings.coverage_stale_after_days`).
STALE_AFTER = timedelta(days=Settings.model_fields["coverage_stale_after_days"].default)

pytestmark = pytest.mark.asyncio


def posting(company: str, req_id: str) -> RawJob:
    return RawJob(
        company=company, req_id=req_id,
        title="Staff Product Manager",
        url=f"https://careers.example.test/{company}/{req_id}",
        locations=["San Francisco, CA, USA"],
        description_html="<p>Build distributed systems and mentor senior engineers.</p>",
    )


@pytest.fixture
def boards(scratch_scope, monkeypatch):
    """Per company: the keys the board lists and how its listing ends."""
    plans: dict[str, tuple[list[str], str]] = {}

    class Listing(BaseAdapter):
        async def fetch(self):
            keys, ending = plans[self.company]
            for key in keys:
                yield posting(self.company, key)
            if ending == "invalid":
                self.drift.invalidate_listing("non-200 job list", status=503)
            elif ending == "missing":
                self.drift.board_missing("non-200 job board", status=404)
            elif ending == "proven":
                self.drift.board_empty("jobs array present and empty")

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
    network = AsyncMock(side_effect=AssertionError("test attempted external HTTP"))
    monkeypatch.setattr(httpx.AsyncClient, "send", network)
    yield plans
    network.assert_not_awaited()


async def _statuses(session) -> dict[str, str]:
    return {j.req_id: j.status for j in (await session.scalars(select(Job))).all()}


async def _capability(session, company: str) -> str:
    return (await session.scalars(
        select(SourceBinding.closure_capability).where(SourceBinding.company_slug == company)
    )).one()


async def _last_source_run(session, company: str) -> ScrapeSourceRun:
    return (await session.scalars(
        select(ScrapeSourceRun)
        .where(ScrapeSourceRun.company_slug == company)
        .order_by(ScrapeSourceRun.id.desc())
        .limit(1)
    )).one()


async def test_a_listing_that_ends_silently_on_zero_rows_closes_nothing(db_session, boards):
    """The apple shape: a counted board that answered `totalRecords: 0` ends
    through `close_listing(declared=0, unique=0)`, which records nothing. The
    binding is healthy and authoritative after the first run, so only the
    zero-row rule stands between the second run and three closures."""
    boards["apple"] = (["a", "b", "c"], "complete")
    first = await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    assert first["per_source"]["apple"]["outcome"] == "ok"
    assert await _capability(db_session, "apple") == "authoritative"

    boards["apple"] = ([], "complete")
    second = await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    assert await _statuses(db_session) == {"a": "open", "b": "open", "c": "open"}
    assert second["closed"] == 0
    recorded = second["per_source"]["apple"]
    assert recorded["list_complete"] is False
    assert recorded["closure_eligible"] is False
    # It proved nothing, so it is the pathology every guarded adapter already
    # reports: the run cannot tell an empty board from a broken one.
    assert recorded["outcome"] == "failed"
    assert [alert["message"] for alert in recorded["drift"]] == ["listing yielded no postings"]


async def test_an_adapter_s_own_empty_guard_is_not_doubled(db_session, boards):
    """A listing the adapter already invalidated keeps its own message alone:
    the attention report reads the run's drift as the cause."""
    boards["apple"] = (["a"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    boards["apple"] = ([], "invalid")
    result = await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    assert await _statuses(db_session) == {"a": "open"}
    assert [alert["message"] for alert in result["per_source"]["apple"]["drift"]] == ["non-200 job list"]


# --------------------------------------------------------------------------- #
# 2. A board proven empty
# --------------------------------------------------------------------------- #


async def _standing(session, company: str = "apple") -> dict:
    row = (await session.execute(
        select(
            SourceBinding.closure_capability, SourceBinding.activated_at,
            TrackedCompany.role_catalog_status, TrackedCompany.role_catalog_error,
        )
        .join(TrackedCompany, TrackedCompany.slug == SourceBinding.company_slug)
        .where(SourceBinding.company_slug == company)
    )).one()
    return dict(row._mapping)


@pytest.mark.parametrize(
    ("ending", "outcome", "status", "catalog"),
    [
        ("proven", "empty", "ok", "ready"),
        # The control: the same zero, unexplained.
        ("complete", "failed", "error", "error"),
    ],
    ids=["proven-empty", "unexplained-zero"],
)
async def test_a_board_proven_empty_is_a_scan_with_no_postings(
    db_session, boards, ending, outcome, status, catalog
):
    boards["apple"] = (["a", "b"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    before = await _standing(db_session)
    assert (before["closure_capability"], before["role_catalog_status"]) == ("authoritative", "ready")

    boards["apple"] = ([], ending)
    result = await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    after = await _standing(db_session)
    recorded = result["per_source"]["apple"]

    assert recorded["outcome"] == outcome
    assert result["status"] == status
    # Never closure evidence, proven or not.
    assert await _statuses(db_session) == {"a": "open", "b": "open"}
    assert (recorded["list_complete"], recorded["closure_eligible"]) == (False, False)
    assert after["role_catalog_status"] == catalog
    if ending == "proven":
        assert recorded["empty_proven"] is True
        assert recorded["drift"] == [], "a proof is a log line, never an alert"
        # Inert: closure authority and the catalog did not move at all.
        assert after == before
        run = await db_session.get(ScrapeRun, result["run_id"])
        assert "apple=empty" in run.notes, "the run still names it"


async def test_an_empty_board_validates_no_binding(db_session, boards):
    """Not `OK`: an empty listing never validates a withheld binding."""
    boards["apple"] = (["a"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    binding = (await db_session.scalars(
        select(SourceBinding).where(SourceBinding.company_slug == "apple")
    )).one()
    binding.closure_capability = "none"
    binding.activated_at = None
    await db_session.commit()
    before = await _standing(db_session)

    boards["apple"] = ([], "proven")
    result = await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    assert result["per_source"]["apple"]["outcome"] == "empty"
    assert result["per_source"]["apple"]["binding_activation"].startswith("outcome=empty")
    assert await _standing(db_session) == before


@pytest.fixture
def scheduled(scratch_scope):
    return scratch_scope


@pytest.mark.parametrize(
    ("outcome", "stamps", "cadence", "pressure", "extra"),
    [
        ("empty", True, True, ("ready", 0), {}),
        # A `lossy` read (say one row unread) loses the same an hour later,
        # and a retry is a whole board re-read, so it waits for the cadence,
        # not the 900 s retry. It still never stamps freshness: its postings
        # cannot close.
        ("lossy", False, True, ("ready", 0), {}),
        # A read our host cut, asleep or with no network: retried
        # at the backoff like a failure, and no provider backs off for it.
        ("suspended", False, False, ("ready", 0), {}),
        # A board gone from its address must not put its whole provider in
        # backoff. The company's fact, not the provider's: checked again at
        # the cadence.
        ("failed", False, True, ("ready", 0), {"board_missing": True}),
        # The control: a failure still backs off, and its provider with it.
        ("failed", False, False, ("backoff", 1), {}),
    ],
    ids=["empty", "lossy", "suspended", "board-missing", "failed"],
)
async def test_a_settled_reconcile_is_rechecked_at_cadence_and_backs_off_no_provider(
    db_session, scheduled, outcome, stamps, cadence, pressure, extra
):
    """A proven-empty board answers the same in 900 s, and its provider served
    it perfectly: backing the provider off for it would hold back every other
    board there."""
    now = datetime.now(UTC)
    settings = get_settings()
    item = (await scheduler.plan_due_work(now))[0]
    stats = {"outcome": outcome, "list_complete": False, "closure_eligible": False, **extra}
    async with scheduled() as session:
        await scheduler.record_work_result(session, item, stats, now, settings)

    schedule = (await db_session.scalars(
        select(SyncScheduleState).where(SyncScheduleState.binding_id == item.binding_id)
    )).one()
    provider = await db_session.get(ProviderPressureState, item.provider_key)
    await db_session.refresh(schedule)
    await db_session.refresh(provider)
    backoff = timedelta(seconds=settings.sync_provider_backoff_seconds)
    assert (schedule.last_reconcile_at == now) is stamps
    if cadence:
        assert schedule.next_reconcile_at > now + backoff
        assert schedule.next_reconcile_at >= now + timedelta(
            seconds=settings.sync_reconcile_cadence_seconds
        ) - timedelta(hours=1)
        assert provider.cooldown_until is None
    else:
        assert schedule.next_reconcile_at == now + backoff
    assert (provider.state, provider.consecutive_pressure_events) == pressure


@pytest.mark.parametrize(
    ("activated", "stamps"),
    [
        # A first read that validates its binding waits for the cadence, not
        # the 900 s retry a failure gets: that second read would re-read each
        # board to learn nothing.
        (True, True),
        # The control: the same clean, complete listing on a binding it did NOT
        # validate (a recipe RoleBand has not validated) is still withheld.
        (False, False),
    ],
    ids=["validated", "still-withheld"],
)
async def test_a_first_read_that_validates_its_binding_has_read_the_board(
    db_session, scheduled, activated, stamps
):
    """The run that grants a binding authority never closes on it,
    yet it read the whole board: rechecked at the cadence and fresh from now,
    like a proven-empty board. The next read may close."""
    now = datetime.now(UTC)
    settings = get_settings()
    item = (await scheduler.plan_due_work(now))[0]
    stats = {
        "outcome": "ok", "list_complete": True, "closure_eligible": False,
        "binding_activated": activated,
    }
    async with scheduled() as session:
        await scheduler.record_work_result(session, item, stats, now, settings)

    schedule = (await db_session.scalars(
        select(SyncScheduleState).where(SyncScheduleState.binding_id == item.binding_id)
    )).one()
    await db_session.refresh(schedule)
    backoff = timedelta(seconds=settings.sync_provider_backoff_seconds)
    assert (schedule.last_reconcile_at == now) is stamps
    if stamps:
        assert schedule.next_reconcile_at >= now + timedelta(
            seconds=settings.sync_reconcile_cadence_seconds
        ) - timedelta(hours=1)
    else:
        assert schedule.next_reconcile_at == now + backoff


async def _flagged(db_session) -> list[dict]:
    rows = await followed_bindings(db_session, automatic=lambda *_: True)
    return binding_attention(rows, datetime.now(UTC), stale_after=STALE_AFTER)["items"]


async def test_the_attention_report_keeps_an_empty_board_in_view(db_session, boards):
    """Health-inert does not mean invisible: an abandoned board (Vercel's on
    Ashby) answers exactly like an empty one. Flagged from its first empty
    scan, with when the streak began and what it listed before; gone on the
    first scan that lists a posting again."""
    boards["apple"] = (["a", "b"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    assert await _flagged(db_session) == []

    boards["apple"] = ([], "proven")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    first_empty = (await _last_source_run(db_session, "apple")).started_at
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    (item,) = await _flagged(db_session)
    assert (item["company"], item["stale"], item["cause"]) == ("apple", False, CAUSE_EMPTY_LISTING)
    assert item["empty_since"] == first_empty
    assert (item["listed_before"], item["held_open"]) == (2, 2)
    assert rings(item), "rings at once for a followed company"

    boards["apple"] = (["a"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    assert await _flagged(db_session) == []


# --------------------------------------------------------------------------- #
# 3. A board gone from its address
# --------------------------------------------------------------------------- #


async def test_a_board_gone_from_its_address_is_told_once_by_coverage(db_session, boards):
    """A renamed board must not ring "Couldn't scan, nothing was updated" on
    every scan. The scan says nothing; Coverage rings at once,
    one row for the company, and nothing closes on a board that is not there."""
    boards["apple"] = (["a", "b"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    boards["apple"] = ([], "missing")
    result = await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    recorded = result["per_source"]["apple"]
    assert (recorded["outcome"], recorded["board_missing"]) == ("failed", True)
    assert await _statuses(db_session) == {"a": "open", "b": "open"}
    run = await db_session.get(ScrapeRun, result["run_id"])
    assert classify_sync_result(run) is None, "the scan does not repeat what Coverage tells"

    (item,) = await _flagged(db_session)
    assert (item["cause"], item["stale"], item["held_open"]) == (CAUSE_BOARD_MISSING, False, 2)
    assert rings(item), "rings at once: no number of days brings the page back"
    assert rings(item, burst=True) is False, "five boards gone together wait, like an outage"

    await generate_coverage_notifications(db_session)
    await generate_coverage_notifications(db_session)
    rows = (await db_session.scalars(
        select(Notification).where(Notification.category == "coverage")
    )).all()
    assert [(n.title, n.meta["cause"]) for n in rows] == [
        ("Apple's careers page is gone", CAUSE_BOARD_MISSING),
    ], "one row per company, however many passes"
    assert "Find its new careers page, or stop following Apple." in rows[0].body
    assert "2 roles stay as last seen until then." in rows[0].body


async def test_a_page_that_is_down_is_not_a_board_gone(db_session, boards):
    """The control: the same zero rows behind a 503 is a page not answering,
    which waits for the stale clock and still rings a failed scan."""
    boards["apple"] = (["a"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    boards["apple"] = ([], "invalid")
    result = await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    assert result["per_source"]["apple"]["board_missing"] is False
    run = await db_session.get(ScrapeRun, result["run_id"])
    notif = classify_sync_result(run)
    assert notif is not None and notif.category == "sync_failed"
    assert await _flagged(db_session) == [], "not stale yet, and not a board gone"
