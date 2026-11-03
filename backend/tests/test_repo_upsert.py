"""Persistence invariants for the scrape upsert path.

These pin the longitudinal-tracking contract that everything else builds on:
opened/changed/reopened lifecycle events, the append-only observation guarantee,
and source-local closure reconciliation. `upsert_job` / `close_missing` take the
company's existing jobs as an in-memory dict and never issue their own queries,
so a tiny fake session is enough — no live DB.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from tests.factories import make_enriched
from tracker.api.serializers.jobs import serialize_job
from tracker.connectors.detail import structure_job_detail
from tracker.connectors.listing.base import RateLimiter
from tracker.connectors.listing.workday import WorkdayAdapter
from tracker.db.models import Job, JobLifecycleEvent, JobObservation
from tracker.db.pay_band import CONNECTOR_READER_VERSION
from tracker.db.repo import apply_scope_state, close_missing, upsert_job
from tracker.schema import (
    AccessSurface,
    ClosureBasis,
    EnrichedJob,
    LevelBand,
    LevelConfidence,
    RawJob,
    SourceDisclosedComp,
    SourceJobFacts,
)
from tracker.source_review import SOURCE_REVIEWS


class FakeSession:
    """Collects added ORM objects; flush() assigns ids to new Jobs like the DB would."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self._next_id = 1

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if isinstance(obj, Job) and obj.id is None:
                obj.id = self._next_id
                self._next_id += 1

    async def refresh(self, obj, attribute_names=None, with_for_update=None) -> None:
        """The in-memory row is the stored one: nothing newer to read."""

    def of_type(self, cls):
        return [o for o in self.added if isinstance(o, cls)]


def _run():
    return SimpleNamespace(id=7)


@pytest.mark.asyncio
async def test_new_key_opens_job_and_emits_single_opened_event():
    session = FakeSession()
    enriched = make_enriched()

    job, is_new = await upsert_job(session, _run(), enriched, existing={})

    assert is_new is True
    assert job.status == "open"
    assert job.repost_count == 0
    assert job.first_seen == job.last_seen
    assert job.dedupe_key == "acme:1"

    events = session.of_type(JobLifecycleEvent)
    assert [e.event_type for e in events] == ["opened"]
    assert events[0].job_id == job.id
    assert events[0].run_id == 7


@pytest.mark.asyncio
async def test_existing_key_changed_title_emits_changed_not_opened():
    now = datetime.now(UTC)
    job = Job(
        id=42,
        company="acme",
        req_id="1",
        dedupe_key="acme:1",
        title="Staff Software Engineer",
        url="https://example.com/1",
        status="open",
        level_band="staff",
        family="swe",
        comp_median=500_000,
        first_seen=now - timedelta(days=10),
        last_seen=now - timedelta(days=1),
        total_days_open=1,
        repost_count=0,
    )
    enriched = make_enriched(title="Staff Software Engineer, Inference")

    updated, is_new = await upsert_job(
        session := FakeSession(), _run(), enriched, existing={"acme:1": job}
    )

    assert is_new is False
    assert updated is job
    assert updated.title == "Staff Software Engineer, Inference"

    events = session.of_type(JobLifecycleEvent)
    assert [e.event_type for e in events] == ["changed"]
    assert events[0].detail["title"] == {
        "from": "Staff Software Engineer",
        "to": "Staff Software Engineer, Inference",
    }
    # Aging clock accrues from the ORIGINAL first_seen, not this run.
    assert updated.total_days_open == 10


@pytest.mark.asyncio
async def test_closed_key_returning_reopens_and_bumps_repost_count_once():
    now = datetime.now(UTC)
    job = Job(
        id=42,
        company="acme",
        req_id="1",
        dedupe_key="acme:1",
        title="Staff Software Engineer",
        url="https://example.com/1",
        status="closed",
        closed_at=now - timedelta(days=2),
        level_band="staff",
        family="swe",
        comp_median=500_000,
        first_seen=now - timedelta(days=30),
        last_seen=now - timedelta(days=2),
        total_days_open=28,
        repost_count=2,
    )
    enriched = make_enriched()

    updated, is_new = await upsert_job(
        session := FakeSession(), _run(), enriched, existing={"acme:1": job}
    )

    assert is_new is False
    assert updated.status == "open"
    assert updated.closed_at is None
    assert updated.repost_count == 3  # bumped exactly once

    events = session.of_type(JobLifecycleEvent)
    assert [e.event_type for e in events] == ["reopened"]


# A Workday posting as the listing serves it: a relative "Posted" string and no
# absolute date, which only the detail read supplies (workday.py `hydrate`).
_WD_POSTING = {
    "title": "Senior Backend Platform Engineer",
    "externalPath": "/job/US-CA-Santa-Clara/Senior-Backend-Platform-Engineer_JR2021162",
    "locationsText": "US, CA, Santa Clara",
    "postedOn": "Posted 30+ Days Ago",
    "bulletFields": ["JR2021162"],
}


def _wd_detail(start_date: str) -> dict:
    return {
        "jobPostingInfo": {
            "jobDescription": "<p>Build large-scale platform systems.</p>",
            "location": "US, CA, Santa Clara",
            "startDate": start_date,
            "jobReqId": "JR2021162",
        }
    }


async def _workday_scan(detail: dict, *, read_detail: bool) -> EnrichedJob:
    """One scan of one posting, in collection's order: listing, the detail read
    only when the stored description is not fresh, then detail structuring."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            first_page = json.loads(request.content)["offset"] == 0
            return httpx.Response(
                200, json={"total": 1, "jobPostings": [_WD_POSTING] if first_page else []}
            )
        return httpx.Response(200, json=detail)

    adapter = WorkdayAdapter("nvidia")
    # The mock transport sends nothing out; this consent is the fixture's.
    adapter.collection_consent = SOURCE_REVIEWS["workday"].wall_fingerprint
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    raw = [job async for job in adapter.fetch()][0]
    if read_detail:
        await adapter.hydrate(raw)
    structure_job_detail(raw, adapter.drift, payload=raw.detail_payload, source="workday")
    return EnrichedJob(
        raw=raw,
        level_band=LevelBand.SENIOR,
        level_confidence=LevelConfidence.CONFIRMED,
        family="swe",
        location_groups=["silicon_valley"],
    )


@pytest.mark.asyncio
async def test_a_rescan_that_skips_the_detail_read_keeps_the_date_and_text_it_read():
    session = FakeSession()
    first, _ = await upsert_job(
        session, _run(), await _workday_scan(_wd_detail("2026-06-01"), read_detail=True), existing={}
    )
    assert first.posted_at is not None and first.posted_at.date() == date(2026, 6, 1)
    assert "platform systems" in (first.description_text or "")

    # Inside `description_refresh_days` collection skips the detail read, so
    # the listing's undated row is all this scan saw.
    skipped = await _workday_scan(_wd_detail("2026-06-01"), read_detail=False)
    assert skipped.raw.posted_at is None
    job, _ = await upsert_job(session, _run(), skipped, existing={first.dedupe_key: first})

    assert job.posted_at is not None and job.posted_at.date() == date(2026, 6, 1)
    assert "platform systems" in (job.description_text or "")

    # A scan that reads the detail again states the date anew, and wins.
    reread = await _workday_scan(_wd_detail("2026-07-15"), read_detail=True)
    job, _ = await upsert_job(session, _run(), reread, existing={job.dedupe_key: job})
    assert job.posted_at is not None and job.posted_at.date() == date(2026, 7, 15)


@pytest.mark.asyncio
async def test_a_read_that_names_no_rung_keeps_the_one_on_file():
    """A listing-only rescan and an incomplete detail parse both arrive with no
    rung, and neither withdrew the one a read did state. Overwriting also
    leaves `level_basis` saying `stated` beside nothing for relevel to read.
    Fail-first: the second upsert nulls the stored rung."""

    def row(raw_level: str | None) -> RawJob:
        return RawJob(
            company="apple",
            req_id="200123",
            title="Senior Software Engineer",
            url="https://jobs.apple.com/en-us/details/200123",
            locations=["Cupertino, CA"],
            raw_level=raw_level,
        )

    def enrich(raw: RawJob) -> EnrichedJob:
        return EnrichedJob(
            raw=raw,
            level_band=LevelBand.SENIOR,
            level_confidence=LevelConfidence.CONFIRMED,
            family="swe",
            location_groups=["silicon_valley"],
        )

    session = FakeSession()
    job, _ = await upsert_job(session, _run(), enrich(row("ICT4")), existing={})
    assert job.raw_level == "ICT4"

    job, _ = await upsert_job(session, _run(), enrich(row(None)), existing={job.dedupe_key: job})
    assert job.raw_level == "ICT4", "a read naming no rung withdrew the stored one"

    # A read that does state one still wins: this keeps a rung, it does not
    # freeze it.
    job, _ = await upsert_job(session, _run(), enrich(row("ICT5")), existing={job.dedupe_key: job})
    assert job.raw_level == "ICT5"


@pytest.mark.asyncio
async def test_a_listing_that_carries_empty_text_keeps_the_held_description():
    """Listing-carried sources mark their text complete on every scan, and a
    board can send a posting with its content empty. That says nothing about
    the posting, so the text a read did carry stays. A later listing with
    text still replaces it. Fail-first: the second upsert nulls the text."""

    def listed(html: str | None) -> EnrichedJob:
        raw = RawJob(company="acme", req_id="4021", title="Staff Software Engineer",
                     url="https://boards.example.test/acme/jobs/4021", locations=["Remote, US"],
                     description_html=html, description_complete=True)
        return EnrichedJob(raw=raw, level_band=LevelBand.STAFF, level_confidence=LevelConfidence.CONFIRMED,
                           family="swe", location_groups=["remote_us"])

    session = FakeSession()
    job, _ = await upsert_job(session, _run(), listed("<p>Own the build system.</p>"), existing={})
    held = (job.description_html, job.description_text, job.description_fetched_at)
    assert job.description_text == "Own the build system."

    for empty in ("", None, "<div> </div>"):
        job, _ = await upsert_job(session, _run(), listed(empty), existing={job.dedupe_key: job})
        assert (job.description_html, job.description_text, job.description_fetched_at) == held, repr(empty)

    job, _ = await upsert_job(session, _run(), listed("<p>Own the release train.</p>"),
                              existing={job.dedupe_key: job})
    assert job.description_text == "Own the release train."


@pytest.mark.asyncio
async def test_a_new_posting_with_no_rung_stores_none():
    """The guard above is "do not withdraw", not "never write": a first read
    that names no rung must still leave the column empty rather than unset."""
    raw = RawJob(
        company="apple", req_id="200999", title="Staff Engineer",
        url="https://jobs.apple.com/en-us/details/200999", locations=["Cupertino, CA"],
    )
    enriched = EnrichedJob(
        raw=raw, level_band=LevelBand.STAFF, level_confidence=LevelConfidence.CONFIRMED,
        family="swe", location_groups=["silicon_valley"],
    )
    job, _ = await upsert_job(FakeSession(), _run(), enriched, existing={})
    assert job.raw_level is None


@pytest.mark.asyncio
async def test_an_incomplete_parse_states_no_pay():
    """Its description is already kept out, so its band is a figure read off a
    page we decided not to believe, and it would be stored as the connector's.
    Fail-first: the incomplete read's band lands on the row."""

    def row(*, complete: bool, base_min: int) -> RawJob:
        return RawJob(
            company="kpmg",
            req_id="130000",
            title="Director, Technology Strategy",
            url="https://www.kpmguscareers.com/jobdetail/?jobId=130000",
            locations=["New York, NY"],
            description_html="<p>Lead technology strategy engagements.</p>",
            description_complete=complete,
            source_disclosed_comp=SourceDisclosedComp(
                base_min=base_min, base_max=base_min + 40_000, currency="USD",
                pay_basis="base", pay_period="year",
            ),
        )

    def enrich(raw: RawJob) -> EnrichedJob:
        return EnrichedJob(
            raw=raw,
            level_band=LevelBand.DIRECTOR_PLUS,
            level_confidence=LevelConfidence.CONFIRMED,
            family="swe",
            location_groups=["new_york"],
        )

    session = FakeSession()
    job, _ = await upsert_job(session, _run(), enrich(row(complete=True, base_min=180_000)), existing={})
    assert job.disclosed_base_min == 180_000

    partial = row(complete=False, base_min=90_000)
    job, _ = await upsert_job(session, _run(), enrich(partial), existing={job.dedupe_key: job})
    assert job.disclosed_base_min == 180_000, "an incomplete parse restated the band"
    assert job.disclosed_base_max == 220_000


@pytest.mark.parametrize(
    ("looked", "complete", "owner", "cleared"),
    [
        (True, True, "connector", True),
        # An incomplete read, or one that did not look where pay is printed,
        # says nothing about the pay.
        (True, False, "connector", False),
        (False, True, "connector", False),
        # A band the connector does not own is not its to clear.
        (True, True, "page", False),
    ],
    ids=["looked_and_found_none", "incomplete_read", "did_not_look", "page_band"],
)
@pytest.mark.asyncio
async def test_a_connector_clears_its_own_band_only_when_a_full_read_looked_and_found_none(
    looked, complete, owner, cleared,
):
    raw = RawJob(
        company="nvidia", req_id="JR200100", title="Senior Software Engineer",
        url="https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/JR200100",
        locations=["Santa Clara, CA"], description_html="<p>Build the inference stack.</p>",
        source_disclosed_comp=SourceDisclosedComp(
            base_min=184_000, base_max=287_500, currency="USD", pay_basis="base", pay_period="year",
        ),
    )
    enriched = EnrichedJob(
        raw=raw, level_band=LevelBand.SENIOR, level_confidence=LevelConfidence.CONFIRMED,
        family="swe", location_groups=["silicon_valley"],
    )
    session = FakeSession()
    job, _ = await upsert_job(session, _run(), enriched, existing={})
    job.disclosed_source = owner

    raw.source_disclosed_comp = None
    raw.pay_looked = looked
    raw.description_complete = complete
    job, _ = await upsert_job(session, _run(), enriched, existing={job.dedupe_key: job})

    if cleared:
        assert (job.disclosed_base_min, job.disclosed_base_max, job.disclosed_source) == (None, None, None)
        assert job.structured_prompt_version == CONNECTOR_READER_VERSION
    else:
        assert (job.disclosed_base_min, job.disclosed_base_max, job.disclosed_source) == (184_000, 287_500, owner)


@pytest.mark.asyncio
async def test_a_detail_dated_posting_keeps_its_date_until_a_read_restates_it():
    """KPMG, SuccessFactors, Avature, SmartRecruiters' page route: the listing
    row carries no payload and no date, and `hydrate` sets both."""

    def listing_row() -> RawJob:
        return RawJob(
            company="kpmg",
            req_id="130000",
            title="Director, Technology Strategy",
            url="https://www.kpmguscareers.com/jobdetail/?jobId=130000",
            locations=["New York, NY"],
            description_complete=False,
        )

    def enrich(raw: RawJob) -> EnrichedJob:
        return EnrichedJob(
            raw=raw,
            level_band=LevelBand.DIRECTOR_PLUS,
            level_confidence=LevelConfidence.CONFIRMED,
            family="swe",
            location_groups=["new_york"],
        )

    read = listing_row()
    read.description_html = "<p>Lead technology strategy engagements.</p>"
    read.description_complete = True
    read.posted_at = datetime(2026, 5, 4, tzinfo=UTC)
    session = FakeSession()
    job, _ = await upsert_job(session, _run(), enrich(read), existing={})

    job, _ = await upsert_job(session, _run(), enrich(listing_row()), existing={job.dedupe_key: job})
    assert job.posted_at == datetime(2026, 5, 4, tzinfo=UTC)

    # A read that states no date is the source's answer, not a skipped read.
    undated = listing_row()
    undated.description_html = "<p>Lead technology strategy engagements.</p>"
    undated.description_complete = True
    job, _ = await upsert_job(session, _run(), enrich(undated), existing={job.dedupe_key: job})
    assert job.posted_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "existing_factory",
    [
        pytest.param(lambda: {}, id="new-job"),
        pytest.param(
            lambda: {
                "acme:1": Job(
                    id=42,
                    company="acme",
                    req_id="1",
                    dedupe_key="acme:1",
                    title="Old title",
                    url="https://example.com/1",
                    status="open",
                    level_band="staff",
                    family="swe",
                    comp_median=400_000,
                    first_seen=datetime.now(UTC) - timedelta(days=5),
                    last_seen=datetime.now(UTC) - timedelta(days=1),
                    total_days_open=1,
                    repost_count=0,
                )
            },
            id="existing-job",
        ),
    ],
)
async def test_every_upsert_appends_exactly_one_observation_with_full_snapshot(
    existing_factory,
):
    session = FakeSession()
    enriched = make_enriched(title="Staff Software Engineer, Inference")

    job, _ = await upsert_job(session, _run(), enriched, existing=existing_factory())

    obs = session.of_type(JobObservation)
    assert len(obs) == 1
    o = obs[0]
    assert o.job_id == job.id
    assert o.run_id == 7
    assert o.title == "Staff Software Engineer, Inference"
    assert o.comp_median == 500_000
    # The audit payload carries the full enrichment snapshot, not just the columns.
    for key in (
        "title",
        "level_band",
        "level_confidence",
        "family",
        "locations",
        "location_groups",
        "comp_median",
        "comp_provenance",
        "comp_sources",
    ):
        assert key in o.payload


@pytest.mark.asyncio
async def test_upsert_never_writes_lineage_columns():
    """Layering guard: the scraper owns lifecycle; detection owns lineage_*."""
    session = FakeSession()
    job, _ = await upsert_job(session, _run(), make_enriched(), existing={})

    for attr in (
        "lineage_id",
        "lineage_seq",
        "lineage_role",
        "lineage_first_seen",
        "lineage_checked_at",
    ):
        assert getattr(job, attr, None) is None


def test_scope_state_changes_visibility_without_lifecycle_events():
    job = Job(
        id=42,
        company="acme",
        req_id="1",
        dedupe_key="acme:1",
        title="Staff Software Engineer",
        url="https://example.com/1",
        status="open",
        in_scope=True,
        level_band="staff",
        family="software_engineering",
        repost_count=3,
    )

    assert apply_scope_state({"acme:1": job}, {"acme:1": False}) == 1
    assert job.in_scope is False
    assert job.status == "open"
    assert job.repost_count == 3
    assert apply_scope_state({"acme:1": job}, {"acme:1": False}) == 0


@pytest.mark.asyncio
async def test_close_missing_closes_only_unseen_open_jobs_and_is_idempotent():
    now = datetime.now(UTC)

    def mk(req_id: str, status: str) -> Job:
        return Job(
            id=int(req_id),
            company="acme",
            req_id=req_id,
            dedupe_key=f"acme:{req_id}",
            title=f"Role {req_id}",
            url=f"https://example.com/{req_id}",
            status=status,
            closed_at=None if status == "open" else now - timedelta(days=3),
            level_band="staff",
            family="swe",
            first_seen=now - timedelta(days=10),
            last_seen=now - timedelta(days=1),
            total_days_open=9,
            repost_count=0,
        )

    seen_job = mk("1", "open")
    vanished_job = mk("2", "open")
    already_closed = mk("3", "closed")
    existing = {j.dedupe_key: j for j in (seen_job, vanished_job, already_closed)}
    seen_keys = {"acme:1"}

    session = FakeSession()
    closed = await close_missing(session, _run(), "acme", seen_keys, existing)

    assert closed == 1
    assert vanished_job.status == "closed"
    assert vanished_job.closed_at is not None
    assert seen_job.status == "open"  # still seen this run
    assert seen_job.closed_at is None
    events = session.of_type(JobLifecycleEvent)
    assert [e.event_type for e in events] == ["closed"]
    assert events[0].job_id == vanished_job.id

    # Second pass sees nothing new to close.
    session2 = FakeSession()
    closed_again = await close_missing(session2, _run(), "acme", seen_keys, existing)
    assert closed_again == 0
    assert session2.of_type(JobLifecycleEvent) == []


# -- Why a posting is closed, and on whose evidence -- #
#
# `closed_at` alone records only that a posting stopped being listed, never
# "time to fill" — an employer outcome nobody measured. These pin the record,
# so the claim is auditable instead of inferred from the fact that one closure
# path exists.


@pytest.mark.asyncio
async def test_a_closure_records_its_basis_and_the_run_that_evidenced_it():
    now = datetime.now(UTC)
    vanished = Job(
        id=2,
        company="acme",
        req_id="2",
        dedupe_key="acme:2",
        title="Role 2",
        url="https://example.com/2",
        status="open",
        level_band="staff",
        family="swe",
        first_seen=now - timedelta(days=10),
        last_seen=now - timedelta(days=1),
        total_days_open=9,
        repost_count=0,
    )
    existing = {"acme:2": vanished}

    session = FakeSession()
    closed = await close_missing(session, _run(), "acme", set(), existing)

    assert closed == 1
    assert vanished.closure_basis == ClosureBasis.ABSENT_FROM_COMPLETE_LISTING.value
    # The source/run linkage: the run also carries `per_source`, so one join
    # from a closed job reaches the source, its outcome, its `list_complete`
    # and the closure scope that authorized it.
    assert vanished.closure_run_id == 7
    # `closed_at` stays DETECTION time — when the posting was noticed gone, not
    # when the employer acted. The pair is the whole point: a timestamp whose
    # meaning is stated cannot be read back as a hiring conclusion.
    assert vanished.closed_at is not None


@pytest.mark.asyncio
async def test_every_closure_keeps_its_basis_in_the_append_only_history():
    """The row remembers ONE closure; a repeatedly re-listed posting has many."""
    now = datetime.now(UTC)
    job = Job(
        id=3,
        company="acme",
        req_id="3",
        dedupe_key="acme:3",
        title="Role 3",
        url="https://example.com/3",
        status="open",
        level_band="staff",
        family="swe",
        first_seen=now - timedelta(days=10),
        last_seen=now - timedelta(days=1),
        total_days_open=9,
        repost_count=0,
    )

    session = FakeSession()
    await close_missing(session, _run(), "acme", set(), {"acme:3": job})

    (event,) = session.of_type(JobLifecycleEvent)
    assert event.event_type == "closed"
    assert event.detail == {"basis": ClosureBasis.ABSENT_FROM_COMPLETE_LISTING.value}
    assert event.run_id == 7


@pytest.mark.asyncio
async def test_reopening_clears_the_basis_with_the_closure_it_belonged_to():
    """Evidence for a closure dies with the closure.

    A posting the source is listing right now, still carrying "absent from a
    complete listing", would assert that about its current state — and a reader
    filtering on the basis rather than on `status` would count it as closed.
    """
    now = datetime.now(UTC)
    job = Job(
        id=42,
        company="acme",
        req_id="1",
        dedupe_key="acme:1",
        title="Staff Software Engineer",
        url="https://example.com/1",
        status="closed",
        closed_at=now - timedelta(days=2),
        closure_basis=ClosureBasis.ABSENT_FROM_COMPLETE_LISTING.value,
        closure_run_id=6,
        level_band="staff",
        family="swe",
        comp_median=500_000,
        first_seen=now - timedelta(days=30),
        last_seen=now - timedelta(days=2),
        total_days_open=28,
        repost_count=2,
    )

    updated, _ = await upsert_job(FakeSession(), _run(), make_enriched(), {"acme:1": job})

    assert updated.status == "open"
    assert updated.closed_at is None
    assert updated.closure_basis is None
    assert updated.closure_run_id is None


@pytest.mark.asyncio
async def test_a_job_that_stays_open_is_never_given_a_basis():
    """Negative control. NULL on an open row means "has never closed", so a
    write that leaked onto a seen job would destroy that reading."""
    now = datetime.now(UTC)
    seen = Job(
        id=1,
        company="acme",
        req_id="1",
        dedupe_key="acme:1",
        title="Role 1",
        url="https://example.com/1",
        status="open",
        level_band="staff",
        family="swe",
        first_seen=now - timedelta(days=10),
        last_seen=now - timedelta(days=1),
        total_days_open=9,
        repost_count=0,
    )

    await close_missing(FakeSession(), _run(), "acme", {"acme:1"}, {"acme:1": seen})

    assert seen.status == "open"
    assert seen.closure_basis is None
    assert seen.closure_run_id is None


@pytest.mark.asyncio
async def test_a_job_outside_the_binding_scope_is_neither_closed_nor_evidenced():
    """The scope gate runs BEFORE any of this. A job the binding does not own
    must come out of the call completely untouched — a basis written next to a
    closure that never happened would be evidence for nothing."""
    now = datetime.now(UTC)
    unowned = Job(
        id=9,
        company="acme",
        req_id="9",
        dedupe_key="acme:9",
        title="Role 9",
        url="https://example.com/9",
        status="open",
        level_band="staff",
        family="swe",
        first_seen=now - timedelta(days=10),
        last_seen=now - timedelta(days=1),
        total_days_open=9,
        repost_count=0,
    )

    session = FakeSession()
    closed = await close_missing(
        session, _run(), "acme", set(), {"acme:9": unowned}, closable_job_ids=frozenset()
    )

    assert closed == 0
    assert unowned.status == "open"
    assert unowned.closure_basis is None
    assert unowned.closure_run_id is None
    assert session.of_type(JobLifecycleEvent) == []


def test_the_basis_vocabulary_has_exactly_the_paths_that_exist():
    """A vocabulary is a claim about the system, so it grows with the system.

    One closure path exists (`close_missing`, behind `scan_may_close`), so one
    member exists. A confirmed-empty board and an employer-reported outcome are
    not observed; adding their names would make the register of what RoleBand
    can observe read as larger than it is.
    """
    assert [b.value for b in ClosureBasis] == ["absent_from_complete_listing"]


# --------------------------------------------------------------------------- #
# The employer's dates: the first one kept, a re-dating recorded
# --------------------------------------------------------------------------- #


def _dated(posted_at: datetime | None, *, first_published_at: datetime | None = None) -> EnrichedJob:
    """One scan of the same posting, in the shape Greenhouse sends: its
    `first_published` feeds both `posted_at` and the stated facts."""
    enriched = make_enriched()
    enriched.raw.posted_at = posted_at
    enriched.raw.source_facts = SourceJobFacts(
        provider="greenhouse", access_surface=AccessSurface.PUBLIC_API, tenant_identity="acme",
        posting_id="1", first_published_at=first_published_at or posted_at,
    )
    return enriched


def _redated(session: FakeSession) -> list[JobLifecycleEvent]:
    return [e for e in session.of_type(JobLifecycleEvent) if e.event_type == "redated"]


@pytest.mark.asyncio
async def test_an_employer_re_dating_later_keeps_the_first_date_and_is_recorded():
    """Two scans: the board moved the posting's date from 1 June to 20 September.
    `posted_at` follows the board; the start of the listing does not move, so
    the age a person reads cannot shrink, and the move is kept as a fact."""
    first_date = datetime(2026, 6, 1, 13, 0, tzinfo=UTC)
    moved = datetime(2026, 9, 20, 13, 0, tzinfo=UTC)
    session = FakeSession()
    job, _ = await upsert_job(session, _run(), _dated(first_date), existing={})
    job.first_seen = datetime(2026, 8, 1, tzinfo=UTC)  # we started reading the board late
    age_before = serialize_job(job)["listed_days"]

    job, _ = await upsert_job(session, _run(), _dated(moved), existing={job.dedupe_key: job})

    assert job.posted_at == moved, "the current date is still the board's"
    assert job.first_posted_at == first_date
    served = serialize_job(job)
    assert served["listed_since"] == first_date and served["listed_basis"] == "employer"
    assert served["listed_days"] == age_before
    (event,) = _redated(session)
    assert event.detail == {"from": first_date.isoformat(), "to": moved.isoformat()}
    assert event.run_id == 7


@pytest.mark.asyncio
async def test_a_re_dating_earlier_lowers_the_first_date():
    session = FakeSession()
    job, _ = await upsert_job(session, _run(), _dated(datetime(2026, 6, 1, tzinfo=UTC)), existing={})

    job, _ = await upsert_job(
        session, _run(), _dated(datetime(2026, 4, 10, tzinfo=UTC)), existing={job.dedupe_key: job}
    )

    assert job.first_posted_at == datetime(2026, 4, 10, tzinfo=UTC)
    assert len(_redated(session)) == 1


@pytest.mark.asyncio
async def test_a_stated_first_publish_older_than_the_posting_date_is_the_first_date():
    """Some sources state both: the current date as `posted_at` and the first
    publication in the facts. The earlier one is the start."""
    session = FakeSession()
    job, _ = await upsert_job(
        session, _run(),
        _dated(datetime(2026, 9, 1, tzinfo=UTC), first_published_at=datetime(2026, 3, 3, tzinfo=UTC)),
        existing={},
    )
    assert job.first_posted_at == datetime(2026, 3, 3, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_garbage_date_is_never_a_first_date():
    """An epoch zero is a parse accident, not the employer's word: taken as the
    start it would call the posting 56 years old."""
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    session = FakeSession()
    job, _ = await upsert_job(session, _run(), _dated(epoch), existing={})
    assert job.first_posted_at is None

    job, _ = await upsert_job(
        session, _run(), _dated(datetime(2026, 6, 1, tzinfo=UTC)), existing={job.dedupe_key: job}
    )
    assert _redated(session) == [], "an epoch zero was no date to move"
    job, _ = await upsert_job(session, _run(), _dated(epoch), existing={job.dedupe_key: job})
    assert job.first_posted_at == datetime(2026, 6, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_the_same_date_restated_is_not_a_re_dating():
    """A board that re-serializes the same day in another timezone, or a scan
    that states no date at all, has not re-dated anything."""
    session = FakeSession()
    job, _ = await upsert_job(session, _run(), _dated(datetime(2026, 6, 1, 4, 0, tzinfo=UTC)), existing={})
    job, _ = await upsert_job(
        session, _run(), _dated(datetime(2026, 6, 1, 20, 0, tzinfo=UTC)), existing={job.dedupe_key: job}
    )
    undated = make_enriched()
    undated.raw.posted_at = None
    undated.raw.description_complete = True
    job, _ = await upsert_job(session, _run(), undated, existing={job.dedupe_key: job})

    assert _redated(session) == []
    assert job.first_posted_at == datetime(2026, 6, 1, 4, 0, tzinfo=UTC), "a withdrawn date keeps the first"
