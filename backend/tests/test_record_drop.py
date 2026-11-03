"""A record we could not read is not a source we cannot trust.

A Workday listing can serve a few of its postings as stubs carrying only
`bulletFields`. Routing such a row through `invalidate_listing` says two things
at once — "absence is not closure evidence" AND "this source is broken". The
first is true of one bad row; the second is not. With `errors=[]` and no cap,
`classify_source_outcome` would read the incomplete-but-error-free listing as
`degraded`, and three of those quarantine a binding whose only exit is a fully
clean run.

These tests lock the split: `drop_record` keeps closure suppressed (the loss is
real) while keeping it *countable*, so proportionality is expressible one layer
up. The pipeline-level assertions matter as much as the unit ones — the rule
lives in the seam between the detector and the outcome derivation.
"""

from __future__ import annotations

import json

import httpx
import pytest

from tests.factories import scope_filter
from tracker.config import get_settings
from tracker.connectors.listing.base import RateLimiter
from tracker.connectors.listing.workday import WorkdayAdapter, WorkdayBoard
from tracker.connectors.recipes.outcome import SourceOutcome, classify_source_outcome
from tracker.platform.drift import SchemaDriftDetector
from tracker.source_review import SOURCE_REVIEWS


def _consented(adapter):
    """Workday is walled, so the adapter
    refuses before it requests anything. The consent is this fixture's, never a
    user's: the transport is a mock and no request leaves the process."""
    adapter.collection_consent = SOURCE_REVIEWS["workday"].wall_fingerprint
    return adapter

# -- the detector's two loss channels --------------------------------------- #


def test_a_dropped_record_suppresses_closure_but_stays_countable():
    drift = SchemaDriftDetector("workday:nvidia")
    drift.drop_record("posting missing externalPath/title/reqId", keys=["bulletFields"])

    # The loss is real, so absence still cannot close a job...
    assert drift.listing_complete is False
    # ...but it is bounded, and nothing claims the listing itself failed.
    assert drift.records_dropped == 1
    assert drift.listing_invalidated is False
    assert len(drift.alerts) == 1, "the operator still sees it"


def test_a_listing_invalidation_is_not_countable_loss():
    """A non-200 page costs an unknown slice of the board. It must never look
    like `n` dropped rows, or proportionality would be applied to it."""
    drift = SchemaDriftDetector("workday:nvidia")
    drift.invalidate_listing("non-200 jobs search", status=503)

    assert drift.listing_complete is False
    assert drift.listing_invalidated is True
    assert drift.records_dropped == 0


def test_listing_complete_is_derived_from_every_loss_channel():
    """Assigned rather than derived, a new loss channel could forget to close
    the closure gate. Both channels, independently, must close it."""
    assert SchemaDriftDetector("s").listing_complete is True

    dropped = SchemaDriftDetector("s")
    dropped.drop_record("bad row")
    assert dropped.listing_complete is False

    invalidated = SchemaDriftDetector("s")
    invalidated.require(False, "missing 'total' count")
    assert invalidated.listing_complete is False


def test_note_alone_never_touches_the_closure_gate():
    """Detail-side drift (a job page missing its JSON-LD) says nothing about
    whether the *listing* enumerated the board."""
    drift = SchemaDriftDetector("meta:meta")
    drift.note("job page missing JobPosting JSON-LD", req="1573144064246233")

    assert drift.listing_complete is True
    assert drift.records_dropped == 0


# -- the adapter that serves stubs -------------------------------- #


_GOOD = {
    "title": "Senior Verification Engineer - Hardware",
    "externalPath": "/job/US-CA-Santa-Clara/Senior-Verification-Engineer_JR2019800-1",
    "locationsText": "US, CA, Santa Clara",
    "postedOn": "Posted 30+ Days Ago",
    "bulletFields": ["JR2019800"],
}
#: The stub shape: one key, no title, no path. It still names
#: its requisition, which is what makes it presence rather than loss.
_STUB = {"bulletFields": ["JR2018566"]}
#: A row that identifies nothing at all. This is the drop channel's real case:
#: with no req id its absence proves nothing, so the loss is genuine.
_ANON = {"locationsText": "US, CA, Santa Clara", "postedOn": "Posted Today"}


def _good(n: int) -> dict:
    return dict(_GOOD, bulletFields=[f"JR{n}"])


def _workday(pages: dict[int, dict], requests: list[int] | None = None) -> WorkdayAdapter:
    seen_offsets = requests if requests is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = json.loads(request.content or b"{}").get("offset", 0)
        seen_offsets.append(offset)
        return httpx.Response(200, json=pages.get(offset, {"total": 0, "jobPostings": []}))

    adapter = _consented(WorkdayAdapter("nvidia"))
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    return adapter


async def _drain(adapter: WorkdayAdapter) -> list:
    return [
        job
        async for job in adapter._fetch_term("https://x/jobs", WorkdayBoard("h", "t", "s"), "Santa Clara", set())
    ]


@pytest.mark.asyncio
async def test_an_unidentifiable_row_is_dropped_not_treated_as_a_broken_listing():
    """One unreadable row inside a page that otherwise parsed. The other 19
    postings on that page are still collected — the row is skipped, not the
    page — and the source is not accused of drifting."""
    page = {"total": 20, "jobPostings": [_ANON] + [_good(i) for i in range(19)]}
    adapter = _workday({0: page})

    jobs = await _drain(adapter)

    assert len(jobs) == 19, "the readable rows on the page are still collected"
    assert adapter.drift.records_dropped == 1
    assert adapter.drift.listing_invalidated is False, "one bad row is not a broken listing"
    assert adapter.drift.listing_complete is False, "the lost row still blocks closure"


@pytest.mark.asyncio
async def test_a_clean_workday_page_records_no_loss_at_all():
    """The control. Without it, an adapter that dropped every row would satisfy
    the test above just as well."""
    page = {"total": 3, "jobPostings": [_good(i) for i in range(3)]}
    adapter = _workday({0: page})

    jobs = await _drain(adapter)

    assert len(jobs) == 3
    assert adapter.drift.records_dropped == 0
    assert adapter.drift.alerts == []
    assert adapter.drift.listing_complete is True


@pytest.mark.asyncio
async def test_a_non_200_page_still_invalidates_the_whole_listing():
    """The channel that must NOT have been widened. A lost page is unbounded
    loss and stays the source's pathology."""

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        # Retain retry exhaustion without elapsed backoff; test_platform.py
        # owns timing. This test owns lost-page classification.
        return httpx.Response(503, json={}, headers={"Retry-After": "0"})

    adapter = _consented(WorkdayAdapter("nvidia"))
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)

    jobs = await _drain(adapter)

    assert jobs == []
    assert len(seen) == get_settings().scraper_max_retries + 1
    assert adapter.drift.listing_invalidated is True
    assert adapter.drift.records_dropped == 0
    assert classify_source_outcome(
        {
            "scanned": 0,
            "errors": [],
            "list_complete": adapter.drift.listing_complete,
            "records_dropped": adapter.drift.records_dropped,
            "listing_invalidated": adapter.drift.listing_invalidated,
        }
    ) is SourceOutcome.FAILED


@pytest.mark.asyncio
async def test_an_unidentifiable_row_classifies_lossy_end_to_end():
    """The seam the rule lives in: detector state -> the stats dict the pipeline
    records -> the outcome derivation. Asserted together, because each half is
    individually defensible and only the pair is the rule.

    100 postings, 1 of them unreadable: a ratio at the boundary.
    """
    postings = [_ANON] + [_good(i) for i in range(99)]
    pages = {
        off: {"total": 100, "jobPostings": postings[off : off + 20]} for off in range(0, 100, 20)
    }
    adapter = _workday(pages)

    jobs = await _drain(adapter)
    assert len(jobs) == 99, "one row dropped, the rest of the board collected"

    stats = {
        "scanned": len(jobs),
        "kept": len(jobs),
        "errors": [],
        "capped": False,
        "bounded": False,
        "truncated": False,
        "list_complete": adapter.drift.listing_complete,
        "records_dropped": adapter.drift.records_dropped,
        "listing_invalidated": adapter.drift.listing_invalidated,
    }
    assert classify_source_outcome(stats) is SourceOutcome.LOSSY


# -- presence is not loss ---------------------------------------- #
#
# A tenant can serve stubs that LAST: `JR2021715` ("Principal Product Manager,
# AI Frameworks") comes back as `{"bulletFields": ["JR2021715"]}` on every run,
# stable across refetches, and a direct `searchText=JR2021715` returns the same
# stub. Dropped, such rows would clear `list_complete` on every run, suppress
# closure for every healthy posting on the board, and in numbers cross the 1%
# ratio into an anomaly. Nothing closure depends on is lost — the row names its
# own requisition.
#
# The page shapes below are real payloads, mocked. The hold is not permanent:
# a withdrawn row is simply absent, and closes on the next reconcile like any
# other.


def test_a_present_only_row_is_recorded_without_recording_a_loss():
    drift = SchemaDriftDetector("workday:nvidia")
    drift.observe_present("nvidia:JR2021715", "posting served without title/externalPath")

    assert drift.present_only == {"nvidia:JR2021715"}
    # The whole point: the board WAS enumerated, so absence stays usable.
    assert drift.listing_complete is True
    assert drift.records_dropped == 0
    assert drift.listing_invalidated is False
    assert len(drift.alerts) == 1, "the operator still sees it"
    assert drift.alerts[0]["key"] == "nvidia:JR2021715"


def test_the_same_row_met_in_two_queries_is_one_observation():
    """Workday is scanned once per location term and the terms overlap — nvidia
    meets each stub under both "United States" and "Santa Clara". Counting
    sightings rather than postings would count each bad row twice and double
    the ratio the anomaly threshold is measured against."""
    drift = SchemaDriftDetector("workday:nvidia")
    drift.observe_present("nvidia:JR2021715", "served without title/externalPath")
    drift.observe_present("nvidia:JR2021715", "served without title/externalPath")

    assert drift.present_only == {"nvidia:JR2021715"}
    assert len(drift.alerts) == 1


def test_presence_and_loss_are_independent_channels():
    """A run can meet both, and the presence half must not quietly reopen the
    closure gate that the real loss closed."""
    drift = SchemaDriftDetector("workday:nvidia")
    drift.observe_present("nvidia:JR1", "served without title/externalPath")
    drift.drop_record("posting missing externalPath/title/reqId", keys=["locationsText"])

    assert drift.records_dropped == 1
    assert drift.listing_complete is False


@pytest.mark.asyncio
async def test_a_named_stub_keeps_the_listing_complete():
    """The same page as the drop test, one field different — the row names its
    requisition — and the verdict about the *board* inverts."""
    page = {"total": 20, "jobPostings": [_STUB] + [_good(i) for i in range(19)]}
    adapter = _workday({0: page})

    jobs = await _drain(adapter)

    assert len(jobs) == 19, "the stub is still not a posting we can build"
    assert adapter.drift.present_only == {"nvidia:JR2018566"}
    assert adapter.drift.records_dropped == 0
    assert adapter.drift.listing_complete is True, "we did enumerate the board"


@pytest.mark.asyncio
async def test_a_named_stub_never_reaches_the_anomaly_ratio():
    """End to end through the derivation that scores the anomaly. The stub page
    is `ok`, never `lossy` (health-inert but closure-suppressing), however many
    stubs the tenant serves."""
    postings = [dict(_STUB, bulletFields=[f"JRSTUB{i}"]) for i in range(24)]
    postings += [_good(i) for i in range(76)]
    pages = {
        off: {"total": 100, "jobPostings": postings[off : off + 20]} for off in range(0, 100, 20)
    }
    adapter = _workday(pages)

    jobs = await _drain(adapter)
    assert len(jobs) == 76

    stats = {
        "scanned": len(jobs),
        "kept": len(jobs),
        "errors": [],
        "capped": False,
        "bounded": False,
        "truncated": False,
        "list_complete": adapter.drift.listing_complete,
        "records_dropped": adapter.drift.records_dropped,
        "listing_invalidated": adapter.drift.listing_invalidated,
    }
    assert classify_source_outcome(stats) is SourceOutcome.OK


@pytest.mark.asyncio
async def test_a_stub_holds_its_job_open_while_the_rest_of_the_board_closes():
    """The contract, at the seam that decides a job's fate.

    Three open jobs: one served normally, one served as a stub, one genuinely
    gone from the listing. Only the third may close. Both halves are the test —
    without the vanished job, an implementation that simply never closes
    anything would pass.
    """
    from types import SimpleNamespace

    from tracker.db.models import Job
    from tracker.db.repo import close_missing
    from tracker.platform.ratelimit import RateLimiterPool
    from tracker.schema import RawJob
    from tracker.workflows import collection as collection_module

    class _StubServingAdapter:
        """Yields JR1 as a posting and reports JR2 as present-but-unbuildable."""

        def __init__(self) -> None:
            self.drift = SchemaDriftDetector("workday:nvidia")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def fetch(self):
            yield RawJob(
                company="nvidia",
                req_id="JR1",
                title="Principal Product Manager",
                url="https://example.test/JR1",
                locations=["Santa Clara, CA"],
            )
            self.drift.observe_present(
                "nvidia:JR2", "posting served without title/externalPath"
            )

    class _FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []

        def add(self, obj: object) -> None:
            self.added.append(obj)

    empty_scope = scope_filter(bands=(), roles=(), tracks=(), locations=(), domains=())
    collection = await collection_module.collect_source(
        "nvidia",
        # NVIDIA's DECLARED source is Workday, which is walled — the gate
        # resolves the company's own provider, so a
        # fake adapter cannot present a walled company as an unwalled source.
        {"adapter": "fake", "consent": SOURCE_REVIEWS["workday"].wall_fingerprint},
        empty_scope,
        object(),
        max_list=None,
        hydrate=False,
        limiter_pool=RateLimiterPool(),
        adapter_factory=lambda *args, **kwargs: _StubServingAdapter(),
    )

    # Closure authority survives the stub.
    assert collection.list_complete is True
    assert collection.stats["records_dropped"] == 0

    def mk(req_id: str) -> Job:
        return Job(
            id=abs(hash(req_id)) % 1000,
            company="nvidia",
            req_id=req_id,
            dedupe_key=f"nvidia:{req_id}",
            title=f"Role {req_id}",
            url=f"https://example.test/{req_id}",
            status="open",
        )

    served, stubbed, vanished = mk("JR1"), mk("JR2"), mk("JR3")
    existing = {j.dedupe_key: j for j in (served, stubbed, vanished)}

    closed = await close_missing(
        _FakeSession(), SimpleNamespace(id=1), "nvidia", collection.seen_keys, existing
    )

    assert closed == 1
    assert vanished.status == "closed", "a req really absent from the listing still closes"
    assert stubbed.status == "open", "a req the listing named is not gone"
    assert served.status == "open"
