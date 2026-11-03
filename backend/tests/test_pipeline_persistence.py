"""Real ingestion -> persistence -> closure, with offline source/provider edges.

Keep collection, enrichment, binding authority, upserts, history and run records
real. Derived post-passes have separate contracts; run the search-vector pass here
so the ingestion fixture also leaves queryable persisted rows.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select, update

from tracker.connectors import ADAPTER_REGISTRY, BaseAdapter
from tracker.db.models import (
    Job,
    JobLifecycleEvent,
    JobObservation,
    PostingInventory,
    RoleCatalog,
    ScrapeRun,
    ScrapeSourceRun,
    SourceBinding,
    TrackedCompany,
)
from tracker.schema import ClosureBasis, RawJob
from tracker.workflows import pipeline, post_passes
from tracker.workflows.collection_types import ScanMode

pytestmark = pytest.mark.asyncio


def posting(company: str, req_id: str) -> RawJob:
    return RawJob(
        company=company, req_id=req_id,
        title="Staff Product Manager" if company == "apple" else "Principal Product Manager",
        url=f"https://careers.example.test/{company}/{req_id}",
        locations=["San Francisco, CA, USA"],
        description_html="<p>Build distributed systems and mentor senior engineers.</p>",
    )


@pytest.fixture
def sources(scratch_scope, monkeypatch):
    """Mutable external listings; every database session stays in the scratch DB."""
    plans: dict[str, tuple[list[str], str]] = {}

    class Listing(BaseAdapter):
        async def fetch(self):
            keys, outcome = plans[self.company]
            for key in keys:
                yield posting(self.company, key)
            if outcome == "incomplete":
                self.drift.invalidate_listing("next page omitted its jobs array")
            elif outcome == "truncated":
                self.truncated = True
            elif outcome == "error":
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
    monkeypatch.setattr(post_passes, "POST_PASSES", tuple(
        p for p in post_passes.POST_PASSES if p.name == "search_vectors"
    ))
    for adapter in ADAPTER_REGISTRY:
        monkeypatch.setitem(ADAPTER_REGISTRY, adapter, Listing)
    network = AsyncMock(side_effect=AssertionError("pipeline test attempted external HTTP"))
    monkeypatch.setattr(httpx.AsyncClient, "send", network)
    yield plans
    network.assert_not_awaited()


async def _age_absence(db_session, hours: float = 21) -> None:
    """Move every recorded first miss `hours` back, as if the next scan ran a day
    later: a posting closes only on a second miss 20 h or more after its first
    ."""
    await db_session.execute(
        update(Job).where(Job.absent_since.isnot(None))
        .values(absent_since=Job.absent_since - timedelta(hours=hours))
    )
    await db_session.commit()


@pytest.mark.parametrize("mode,max_list,quality,may_close,observations,outcome", [
    (ScanMode.RECONCILE, None, "complete", True, 2, "ok"),
    (ScanMode.RECONCILE, 1, "complete", False, 1, "capped"),
    # An operator cap suppresses closure even if a tiny board finishes below it,
    # and the run is still `capped`: a test run is not evidence about the
    # source, whether or not the cap fired.
    (ScanMode.RECONCILE, 10, "complete", False, 2, "capped"),
    (ScanMode.RECONCILE, None, "incomplete", False, 2, "degraded"),
    (ScanMode.RECONCILE, None, "error", False, 2, "degraded"),
    (ScanMode.DISCOVERY, None, "complete", False, 1, "ok"),
])
async def test_only_authoritative_runs_close_missing_jobs_and_history_is_append_only(
    db_session, sources, mode, max_list, quality, may_close, observations, outcome
):
    sources["apple"] = (["seen", "missing"], "complete")
    first = await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    assert first["new"] == 2, first
    # The first of the two misses closure needs, a day before the run under test.
    sources["apple"] = (["seen"], "complete")
    assert (await pipeline.run_pipeline(companies=["apple"], hydrate=False))["closed"] == 0
    await _age_absence(db_session)
    history_query = select(
        JobObservation.id, JobObservation.job_id, JobObservation.run_id,
        JobObservation.observed_at, JobObservation.title,
    ).order_by(JobObservation.id)
    original = (await db_session.execute(history_query)).all()
    assert len(original) == 3

    sources["apple"] = (["new", "seen"], quality)
    result = await pipeline.run_pipeline(
        companies=["apple"], hydrate=False, max_list=max_list, scan_mode=mode
    )
    jobs = {j.req_id: j for j in (await db_session.scalars(select(Job))).all()}
    assert set(jobs) == {"seen", "missing", "new"}
    assert jobs["new"].status == jobs["seen"].status == "open"
    assert jobs["missing"].status == ("closed" if may_close else "open")
    assert result["new"] == 1
    assert result["closed"] == int(may_close)
    history = (await db_session.execute(history_query)).all()
    assert history[:len(original)] == original
    assert len([row for row in history if row.run_id == result["run_id"]]) == observations

    events = (await db_session.scalars(select(JobLifecycleEvent).where(
        JobLifecycleEvent.run_id == result["run_id"], JobLifecycleEvent.event_type == "closed",
    ))).all()
    assert [event.job_id for event in events] == ([jobs["missing"].id] if may_close else [])
    # Against a real database: the basis and the run that
    # evidenced it land on the row, and ONLY where a closure happened. Every
    # non-authoritative case above is also a negative control for the write.
    assert jobs["missing"].closure_basis == (
        ClosureBasis.ABSENT_FROM_COMPLETE_LISTING.value if may_close else None
    )
    assert jobs["missing"].closure_run_id == (result["run_id"] if may_close else None)
    assert [e.detail["basis"] for e in events] == (
        [ClosureBasis.ABSENT_FROM_COMPLETE_LISTING.value] if may_close else []
    )
    # Closed or not, a closure leaves no evidence behind and a hold keeps it.
    assert jobs["missing"].absent_scans == (0 if may_close else int(outcome != "degraded"))
    assert jobs["seen"].closure_basis is jobs["new"].closure_basis is None
    source_run = (await db_session.scalars(select(ScrapeSourceRun).where(
        ScrapeSourceRun.run_id == result["run_id"],
    ))).one()
    assert source_run.closure_eligible is may_close
    assert source_run.jobs_closed == int(may_close)
    if quality == "incomplete":
        assert source_run.list_complete is False
        assert source_run.drift
    if quality == "error":
        assert any("source disconnected" in error for error in source_run.errors)
    assert source_run.outcome == result["per_source"]["apple"]["outcome"] == outcome


async def _standing(session) -> dict:
    """apple's closure authority, read as columns so no cached entity can stand
    in for what the pipeline's own sessions committed."""
    row = (await session.execute(
        select(SourceBinding.closure_capability, SourceBinding.activated_at)
        .where(SourceBinding.company_slug == "apple")
    )).one()
    return dict(row._mapping)


@pytest.mark.parametrize("max_list", [10, None], ids=["capped_below_cap", "uncapped_control"])
async def test_a_capped_reconcile_never_grants_closure_authority(db_session, sources, max_list):
    """`capped` is an operator choice, never evidence, even when the board
    finishes under the cap.

    Otherwise `max_list=10` over a two-row board records `ok` and activates a
    withheld binding ("validated by a complete ok listing (scanned=2)"), so
    the next uncapped run closes on authority a test run granted. The uncapped
    control is the same board from the same standing: it must activate, or the
    capped half could pass against a pipeline that never activates anything.
    """
    sources["apple"] = (["one", "two"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    binding = (await db_session.scalars(
        select(SourceBinding).where(SourceBinding.company_slug == "apple")
    )).one()
    binding.closure_capability = "none"
    binding.activated_at = None
    await db_session.commit()
    before = await _standing(db_session)

    result = await pipeline.run_pipeline(companies=["apple"], hydrate=False, max_list=max_list)
    after = await _standing(db_session)
    recorded = result["per_source"]["apple"]

    if max_list is not None:
        # Authority first, because it is the defect; the recorded outcome is
        # only how the fix says so.
        assert after == before
        assert recorded["outcome"] == "capped"
        assert recorded["list_complete"] is True, "the listing did complete; only authority is refused"
        assert recorded["binding_activation"].startswith("outcome=capped")
        # The scheduler reads this flag, never the reason's wording.
        assert recorded["binding_activated"] is False
    else:
        assert recorded["outcome"] == "ok"
        assert after["closure_capability"] == "authoritative"
        assert after["activated_at"] is not None
        assert recorded["binding_activation"].startswith("validated by a complete ok")
        assert recorded["binding_activated"] is True


async def test_a_discovery_run_loads_each_companys_whole_rows_once(db_session, sources, monkeypatch):
    """The frontier is read as keys (`repo.load_open_keys`), so only the writer
    loads a company's whole rows, once per company, and the frontier still
    keeps every posting held open out of the probe."""
    for company in ("apple", "amazon"):
        sources[company] = (["seen"], "complete")
    await pipeline.run_pipeline(companies=list(sources), hydrate=False)
    loads: list[str] = []
    whole_rows = pipeline.load_company_jobs

    async def counted(session, company):
        loads.append(company)
        return await whole_rows(session, company)

    monkeypatch.setattr(pipeline, "load_company_jobs", counted)
    for company in ("apple", "amazon"):
        sources[company] = (["seen", "new"], "complete")
    result = await pipeline.run_pipeline(
        companies=list(sources), hydrate=False, scan_mode=ScanMode.DISCOVERY
    )

    assert result["new"] == 2
    assert sorted(loads) == ["amazon", "apple"]
    observed = (await db_session.scalars(
        select(Job.dedupe_key).join(JobObservation, JobObservation.job_id == Job.id)
        .where(JobObservation.run_id == result["run_id"])
    )).all()
    assert sorted(observed) == ["amazon:new", "apple:new"]


async def test_a_relisted_posting_sheds_the_evidence_for_a_closure_it_is_no_longer_in(
    db_session, sources
):
    """Close it, then serve it again — against a real database, three runs deep.

    A basis that outlives its closure is worse than an absent one: the row would
    carry evidence for a state it has left, and a reader filtering on
    `closure_basis` rather than on `status` would count a live posting as gone.
    The second closure must also re-evidence itself from the run that saw it,
    not from the first one.
    """
    sources["apple"] = (["seen", "flapping"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    sources["apple"] = (["seen"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    await _age_absence(db_session)
    closing = await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    await db_session.commit()
    job = (await db_session.scalars(
        select(Job).where(Job.dedupe_key == "apple:flapping")
    )).one()
    assert job.status == "closed"
    assert job.closure_basis == ClosureBasis.ABSENT_FROM_COMPLETE_LISTING.value
    assert job.closure_run_id == closing["run_id"]

    sources["apple"] = (["seen", "flapping"], "complete")
    reopening = await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    await db_session.commit()
    await db_session.refresh(job)
    assert job.status == "open"
    assert job.closed_at is None
    assert job.closure_basis is None
    assert job.closure_run_id is None
    assert job.repost_count == 1

    sources["apple"] = (["seen"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    await _age_absence(db_session)
    reclosing = await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    await db_session.commit()
    await db_session.refresh(job)
    assert job.status == "closed"
    assert job.closure_basis == ClosureBasis.ABSENT_FROM_COMPLETE_LISTING.value
    assert job.closure_run_id == reclosing["run_id"] != closing["run_id"]

    # The row remembers the current closure; the append-only history remembers
    # both, each with its own basis and its own run.
    closed_events = (await db_session.scalars(
        select(JobLifecycleEvent)
        .where(JobLifecycleEvent.job_id == job.id, JobLifecycleEvent.event_type == "closed")
        .order_by(JobLifecycleEvent.id)
    )).all()
    assert [e.run_id for e in closed_events] == [closing["run_id"], reclosing["run_id"]]
    assert {e.detail["basis"] for e in closed_events} == {
        ClosureBasis.ABSENT_FROM_COMPLETE_LISTING.value
    }
    # Each closure names its own first miss, never the earlier closure's.
    first_misses = [e.detail["first_missed_at"] for e in closed_events]
    assert len(set(first_misses)) == 2
    assert reopening["run_id"] not in [e.run_id for e in closed_events]


async def test_a_failed_source_preserves_its_jobs_without_suppressing_a_healthy_siblings_closures(
    db_session, sources
):
    for company in ("apple", "amazon"):
        sources[company] = (["seen", "missing"], "complete")
    first = await pipeline.run_pipeline(companies=list(sources), hydrate=False)
    assert first["new"] == 4, first
    # Both companies miss their posting once, a day before the run under test.
    for company in ("apple", "amazon"):
        sources[company] = (["seen"], "complete")
    await pipeline.run_pipeline(companies=list(sources), hydrate=False)
    await _age_absence(db_session)

    sources["apple"] = (["seen"], "complete")
    sources["amazon"] = (["new"], "error")
    result = await pipeline.run_pipeline(companies=list(sources), hydrate=False)
    rows = (await db_session.scalars(select(Job))).all()
    jobs = {j.dedupe_key: j.status for j in rows}
    # The failed scan started amazon's count again: two complete misses are
    # needed after it.
    assert {j.dedupe_key: j.absent_scans for j in rows}["amazon:missing"] == 0
    assert jobs == {
        "apple:seen": "open", "apple:missing": "closed",
        "amazon:seen": "open", "amazon:missing": "open", "amazon:new": "open",
    }
    assert result["closed"] == 1
    assert result["status"] == "partial"
    run = await db_session.get(ScrapeRun, result["run_id"])
    assert run.status == "partial"
    assert run.per_source["apple"]["closure_eligible"] is True
    assert run.per_source["amazon"]["closure_eligible"] is False
    assert run.per_source["amazon"]["errors"]


@pytest.mark.parametrize("entry", ["pipeline", "daily", "role_discovery"])
async def test_policy_denial_preserves_postings_history_authority_and_catalog(
    db_session, sources, monkeypatch, tmp_path, capsys, entry,
):
    from argparse import Namespace
    from unittest.mock import Mock

    from tracker.config import get_settings
    from tracker.workflows import daily, discover_roles

    sources["apple"] = (["seen", "missing"], "complete")
    sources["amazon"] = (["seen", "missing"], "complete")
    await pipeline.run_pipeline(companies=list(sources), hydrate=False)
    # amazon misses its posting once, a day before the run under test.
    sources["amazon"] = (["seen"], "complete")
    await pipeline.run_pipeline(companies=list(sources), hydrate=False)
    await _age_absence(db_session)

    async def protected_state():
        # Select columns rather than cached ORM entities: every read sees the
        # separately committed workflow session's actual persisted values.
        queries = [
            select(Job.id, Job.status, Job.first_seen, Job.last_seen, Job.closed_at)
            .where(Job.company == "apple").order_by(Job.id),
            select(JobObservation.__table__).join(Job).where(Job.company == "apple")
            .order_by(JobObservation.id),
            select(JobLifecycleEvent.__table__).join(Job).where(Job.company == "apple")
            .order_by(JobLifecycleEvent.id),
            select(SourceBinding.id, SourceBinding.status, SourceBinding.closure_capability).where(SourceBinding.company_slug == "apple"),
            select(RoleCatalog.__table__).where(RoleCatalog.company == "apple")
            .order_by(RoleCatalog.id),
            select(TrackedCompany.role_catalog_status, TrackedCompany.role_catalog_scanned_at,
                   TrackedCompany.role_catalog_error).where(TrackedCompany.slug == "apple"),
        ]
        return [(await db_session.execute(query)).all() for query in queries]

    before = await protected_state()
    assert all(before), "The preservation test must start with populated history/authority/catalog"
    monkeypatch.setattr(get_settings(), "sync_policy_denied_providers", frozenset({"apple", "meta"}))
    del sources["apple"]  # Accessing its external listing is now itself a test failure.
    sources["amazon"] = (["seen"], "complete")

    if entry == "role_discovery":
        monkeypatch.setattr(discover_roles, "_YIELD_WINDOW_SECONDS", 0)
        result = await discover_roles.discover(companies=["apple", "amazon"])
        denied = result["companies"]["apple"]
        assert denied["status"] == "unattempted"
        assert "policy" in denied["policy_reason"]
        assert result["companies"]["amazon"]["scanned"] == 1
    else:
        if entry == "daily":
            monkeypatch.setattr(daily, "DATA_DIR", tmp_path)
            monkeypatch.setattr(daily, "_parse_args", lambda: Namespace(
                company=["apple", "amazon"], max_list=None, no_hydrate=True,
                scan_mode="reconcile", verbose=False,
            ))
            monkeypatch.setattr(daily, "notify", Mock())
            assert await daily._main() == 0
            capsys.readouterr()
        else:
            await pipeline.run_pipeline(companies=["apple", "amazon"], hydrate=False)
        run = (await db_session.scalars(select(ScrapeRun).order_by(ScrapeRun.id.desc()))).first()
        denied = run.per_source["apple"]
        assert denied["outcome"] == "unattempted"
        assert denied["errors"] == denied["drift"] == []
        assert denied["scanned"] == denied["closed"] == 0
        assert denied["closure_eligible"] is False
        assert denied["list_complete"] is False
        assert denied["policy_provider"] == "apple"
        assert "policy" in denied["policy_reason"]
        assert run.per_source["amazon"]["closed"] == 1
        audit = (await db_session.scalars(select(ScrapeSourceRun).where(
            ScrapeSourceRun.run_id == run.id, ScrapeSourceRun.company_slug == "apple",
        ))).one()
        assert audit.outcome == "unattempted"
        assert audit.errors == audit.drift == []
        assert audit.stats["policy_reason"] == denied["policy_reason"]

    assert await protected_state() == before


# --------------------------------------------------------------------------- #
# Source facts. The archive is additive: it may not move an identity,
# rewrite an observation, or take a saved role with it.
# --------------------------------------------------------------------------- #


def _greenhouse_posting(req_id: str, *, internal: str, updated: str, tiers: list) -> RawJob:
    """Two of these share `internal` — which is exactly the shape that bites."""
    from datetime import UTC, datetime

    from tracker.schema import (
        AccessSurface,
        CompensationFacts,
        CompTier,
        RetrievalState,
        SourceJobFacts,
        SourceLocation,
    )

    job = posting("anthropic", req_id)
    job.source_facts = SourceJobFacts(
        provider="greenhouse",
        access_surface=AccessSurface.PUBLIC_API,
        tenant_identity="anthropic",
        posting_id=req_id,
        source_job_id=internal,
        requisition_label=f"REQ-{req_id}",
        first_published_at=datetime(2026, 6, 20, 13, tzinfo=UTC),
        source_updated_at=datetime.fromisoformat(updated),
        locations=[SourceLocation(label="San Francisco, CA", is_primary=True)],
        compensation=CompensationFacts(
            tiers=[CompTier(title=t) for t in tiers],
            state=RetrievalState.PRESENT if tiers else RetrievalState.NOT_REQUESTED,
            observed_at=datetime.now(UTC),
        ),
        observed_at=datetime.now(UTC),
    )
    return job


async def test_two_postings_of_one_job_stay_two_roles_and_keep_their_history(
    db_session, sources, monkeypatch,
):
    """Greenhouse's `internal_job_id` is evidence, never identity.

    On a real board many postings share one internal job id. Grouping by it — or letting it become the
    key — merges live roles and destroys the saved-role and observation history
    of everything it absorbs. This test writes the collision on purpose, saves
    one of the pair, and then re-scans with facts that have MOVED.
    """
    from tracker.db.models import Favorite

    listings = {
        "first": _greenhouse_posting(
            "8172510", internal="2785594", updated="2026-07-10T12:00:00+00:00", tiers=["SF"],
        ),
        "second": _greenhouse_posting(
            "8142770", internal="2785594", updated="2026-07-11T12:00:00+00:00", tiers=[],
        ),
    }

    class Board(BaseAdapter):
        async def fetch(self):
            for job in listings.values():
                yield job

    monkeypatch.setitem(ADAPTER_REGISTRY, "greenhouse", Board)
    sources["anthropic"] = ([], "complete")  # keyed target; Board serves the rows
    await pipeline.run_pipeline(companies=["anthropic"], hydrate=False)

    rows = (await db_session.scalars(
        select(Job).where(Job.company == "anthropic").order_by(Job.req_id)
    )).all()
    assert [job.req_id for job in rows] == ["8142770", "8172510"]
    assert [job.dedupe_key for job in rows] == ["anthropic:8142770", "anthropic:8172510"]
    # Both name the same underlying job, and that association is retained...
    assert {job.source_facts["source_job_id"] for job in rows} == {"2785594"}
    # ...without ever becoming the key that two rows would have to share.
    assert len({job.source_facts["posting_id"] for job in rows}) == 2
    assert [job.source_facts["requisition_label"] for job in rows] == [
        "REQ-8142770", "REQ-8172510",
    ]

    saved, other = rows[1], rows[0]
    db_session.add(Favorite(job_id=saved.id))
    await db_session.commit()
    identities = {job.req_id: job.id for job in rows}
    first_observations = [
        (obs.id, obs.payload.get("source_facts"))
        for obs in (await db_session.scalars(
            select(JobObservation).join(Job).where(Job.company == "anthropic")
            .order_by(JobObservation.id)
        )).all()
    ]
    assert len(first_observations) == 2
    assert first_observations[0][1]["compensation"]["state"] in {"present", "not_requested"}

    # The board moves: an update timestamp advances and a tier is now stated.
    listings["first"] = _greenhouse_posting(
        "8172510", internal="2785594", updated="2026-08-02T09:00:00+00:00", tiers=["SF", "NYC"],
    )
    await pipeline.run_pipeline(companies=["anthropic"], hydrate=False)
    db_session.expire_all()

    after = (await db_session.scalars(
        select(Job).where(Job.company == "anthropic").order_by(Job.req_id)
    )).all()
    assert {job.req_id: job.id for job in after} == identities  # every row keeps its id
    assert (await db_session.scalars(select(Favorite))).all()[0].job_id == identities["8172510"]
    assert other.id == identities["8142770"]

    # The row now says what the board says.
    current = {job.req_id: job.source_facts for job in after}
    assert current["8172510"]["source_updated_at"].startswith("2026-08-02")
    assert [t["title"] for t in current["8172510"]["compensation"]["tiers"]] == ["SF", "NYC"]

    # And the earlier observation still says what the board said THEN: an update
    # appends, it does not rewrite. Old and new values are retained separately.
    observations = (await db_session.scalars(
        select(JobObservation).join(Job).where(Job.company == "anthropic")
        .order_by(JobObservation.id)
    )).all()
    assert [(obs.id, obs.payload.get("source_facts")) for obs in observations[:2]] == (
        first_observations
    )
    assert len(observations) == 4
    latest = next(
        obs for obs in reversed(observations) if obs.job_id == identities["8172510"]
    )
    assert latest.payload["source_facts"]["source_updated_at"].startswith("2026-08-02")
    assert first_observations[0][1]["source_updated_at"].startswith("2026-07-1")


async def test_an_adapter_that_maps_no_facts_leaves_a_stored_record_alone(
    db_session, sources, monkeypatch,
):
    """Most adapters map nothing yet, and must not erase what one already wrote.

    `source_facts=None` means "this connector has no opinion", not "the source
    withdrew everything" — the difference between additive facts and a
    silent data loss on the first scan by an adapter that maps none.
    """
    with_facts = _greenhouse_posting(
        "8172510", internal="2785594", updated="2026-07-10T12:00:00+00:00", tiers=["SF"],
    )
    without = posting("anthropic", "8172510")
    assert without.source_facts is None
    served = [with_facts]

    class Board(BaseAdapter):
        async def fetch(self):
            for job in served:
                yield job

    monkeypatch.setitem(ADAPTER_REGISTRY, "greenhouse", Board)
    sources["anthropic"] = ([], "complete")
    await pipeline.run_pipeline(companies=["anthropic"], hydrate=False)

    served[:] = [without]
    await pipeline.run_pipeline(companies=["anthropic"], hydrate=False)
    db_session.expire_all()

    job = (await db_session.scalars(
        select(Job).where(Job.req_id == "8172510")
    )).one()
    assert job.source_facts["posting_id"] == "8172510"
    # The observation, unlike the row, records honestly that this run saw none.
    newest = (await db_session.scalars(
        select(JobObservation).where(JobObservation.job_id == job.id)
        .order_by(JobObservation.id.desc())
    )).first()
    assert newest.payload["source_facts"] is None


async def test_a_newly_seeded_binding_cannot_close_on_the_run_that_validates_it(
    db_session, sources
):
    """The first reconcile of a company with standing history.

    The defect: a `plan_binding_seeds` that hands every new binding
    `stable`/`authoritative` lets a board token nobody has checked close
    real postings on its very first complete listing. A wrong-but-live token
    answers 200 with somebody else's board and passes every run-quality gate
    there is.

    Two open jobs are inserted with no binding and no identity — the shape a
    company has when it is onboarded onto history, or re-added after removal.
    The first complete listing omits one of them. It must stay open, and the
    same listing must close it on the next run, once the binding it validated
    holds authority. Against an authoritative seed the first run would close it.
    """
    now = datetime.now(UTC)
    for req_id in ("kept", "vanished"):
        db_session.add(Job(
            company="apple", req_id=req_id, dedupe_key=f"apple:{req_id}",
            title="Staff Product Manager", url=f"https://careers.example.test/apple/{req_id}",
            level_band="staff", family="product_management", track="product_program",
            locations=["San Francisco, CA, USA"], location_groups=["silicon_valley"],
            status="open", in_scope=True, first_seen=now - timedelta(days=30), last_seen=now,
        ))
    await db_session.commit()

    sources["apple"] = (["kept"], "complete")
    first = await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    binding = (await db_session.scalars(
        select(SourceBinding).where(SourceBinding.company_slug == "apple")
    )).one()
    await db_session.refresh(binding)
    jobs = {j.req_id: j.status for j in (await db_session.scalars(select(Job))).all()}

    assert first["closed"] == 0, "a binding must not close on the run that validates it"
    assert jobs["vanished"] == "open"
    # Suppressed, and recorded as suppressed: "closed nothing" and "was not
    # allowed to close anything" must never look the same in the audit.
    assert first["per_source"]["apple"]["closure_eligible"] is False
    assert "closure_capability=none" in first["per_source"]["apple"]["closure_scope"]
    # ...and the same run granted the authority, from its own complete listing.
    assert binding.closure_capability == "authoritative"
    assert binding.activated_at is not None
    assert first["per_source"]["apple"]["binding_activation"].startswith("validated by a complete ok")

    second = await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    # The activating run was not evidence; this is the first miss.
    assert second["closed"] == 0
    await _age_absence(db_session)
    third = await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    jobs = {j.req_id: j.status for j in (await db_session.scalars(select(Job))).all()}

    assert third["closed"] == 1
    assert jobs["vanished"] == "closed"
    assert jobs["kept"] == "open"
    # Activation is a one-time grant, not re-decided every night: re-stamping
    # would destroy the one thing `activated_at` exists to answer.
    activated_at = binding.activated_at
    await db_session.refresh(binding)
    assert binding.activated_at == activated_at
    assert "binding_activation" not in second["per_source"]["apple"]


async def test_role_discovery_asks_for_the_saved_places_and_the_answered_ones(sources, db_session, monkeypatch):
    """"Count now" asks each source for the saved places, as the scrape does,
    plus the places being answered and not yet saved. Passing none, a source
    that lists only asked-for places would read the shipped defaults, whatever
    was saved."""
    from tracker.settings_store import set_enabled_locations
    from tracker.workflows import discover_roles

    await set_enabled_locations(db_session, ["uk"])
    await db_session.commit()
    sources["amazon"] = (["seen"], "complete")
    asked = []
    real = discover_roles.build_adapter

    def recording(*args, **kwargs):
        asked.append(kwargs.get("location_groups"))
        return real(*args, **kwargs)

    monkeypatch.setattr(discover_roles, "build_adapter", recording)
    monkeypatch.setattr(discover_roles, "_YIELD_WINDOW_SECONDS", 0)

    await discover_roles.discover(companies=["amazon"])
    await discover_roles.discover(companies=["amazon"], locations=["singapore", "not_a_place"])
    assert asked == [frozenset({"uk"}), frozenset({"uk", "singapore"})]


@pytest.mark.parametrize("entry", ["scan", "role_discovery"])
async def test_a_scan_counts_postings_it_cannot_place_apart_from_ones_it_cannot_sort(
    entry, sources, db_session, monkeypatch,
):
    """Both collecting paths record why the catalog dropped a posting:
    "unplaced" (no place we can read) and "unsorted" (a place but
    no role family), as two numbers, never one read as "unplaced"."""
    import sys

    from tracker.workflows import discover_roles

    module = sys.modules[__name__]
    real = module.posting

    def shaped(company: str, req_id: str) -> RawJob:
        raw = real(company, req_id)
        if req_id.startswith("unsorted"):
            # Left out of every family.
            raw.title = "Clinical Specialist, Mental Health"
        if req_id.startswith("unplaced"):
            raw.locations = ["Atlantis Base 7"]
        return raw

    monkeypatch.setattr(module, "posting", shaped)
    sources["amazon"] = (["kept", "unsorted-1", "unsorted-2", "unplaced-1"], "complete")
    if entry == "scan":
        await pipeline.run_pipeline(companies=["amazon"], hydrate=False)
    else:
        monkeypatch.setattr(discover_roles, "_YIELD_WINDOW_SECONDS", 0)
        await discover_roles.discover(companies=["amazon"])

    row = (await db_session.execute(
        select(TrackedCompany.role_catalog_unplaced, TrackedCompany.role_catalog_unsorted)
        .where(TrackedCompany.slug == "amazon")
        .execution_options(populate_existing=True)
    )).one()
    assert (row.role_catalog_unplaced, row.role_catalog_unsorted) == (1, 2)


# --------------------------------------------------------------------------- #
# "Count now" fills the posting inventory
# --------------------------------------------------------------------------- #


async def _inventory(db_session) -> dict[str, tuple]:
    rows = (await db_session.execute(
        select(PostingInventory.req_id, PostingInventory.gone_at, PostingInventory.last_seen_run_id)
        .where(PostingInventory.company == "amazon")
        .execution_options(populate_existing=True)
    )).all()
    return {row.req_id: (row.gone_at, row.last_seen_run_id) for row in rows}


async def test_a_count_keeps_what_it_read_and_never_marks_a_posting_gone(sources, db_session, monkeypatch):
    """Even an uncapped count that lists the whole board is never evidence
    that a posting went: only a sync marks gone. A row a sync read keeps
    naming that sync's run; a row only the count read names none."""
    from sqlalchemy import update

    from tracker.workflows import discover_roles

    sources["amazon"] = (["a", "b"], "complete")
    sync = await pipeline.run_pipeline(companies=["amazon"], hydrate=False)
    assert await _inventory(db_session) == {"a": (None, sync["run_id"]), "b": (None, sync["run_id"])}
    # Old enough that the count's upsert rewrites "a" rather than skipping it.
    await db_session.execute(
        update(PostingInventory).where(PostingInventory.req_id == "a")
        .values(last_seen_at=datetime.now(UTC) - timedelta(days=3))
    )
    await db_session.commit()

    sources["amazon"] = (["a", "c"], "complete")
    monkeypatch.setattr(discover_roles, "_YIELD_WINDOW_SECONDS", 0)
    await discover_roles.discover(companies=["amazon"], max_list=None)

    assert await _inventory(db_session) == {
        "a": (None, sync["run_id"]),  # rewritten, still the sync's
        "b": (None, sync["run_id"]),  # not listed by the count, and not gone
        "c": (None, None),            # read only by the count
    }

    # The next sync names "c" at once, inside the touch window, so it is
    # promotable from that sync on rather than a touch window later.
    later = await pipeline.run_pipeline(companies=["amazon"], hydrate=False)
    assert (await _inventory(db_session))["c"] == (None, later["run_id"])


async def test_a_failed_inventory_write_costs_the_count_nothing(sources, db_session, monkeypatch):
    from tracker.workflows import discover_roles

    async def broken(*_args, **_kwargs):
        raise RuntimeError("inventory exploded")

    sources["amazon"] = (["a"], "complete")
    monkeypatch.setattr(discover_roles, "write_inventory", broken)
    monkeypatch.setattr(discover_roles, "_YIELD_WINDOW_SECONDS", 0)
    result = await discover_roles.discover(companies=["amazon"])

    assert result["companies"]["amazon"]["status"] == "ready"
    assert await db_session.scalar(
        select(RoleCatalog.count).where(RoleCatalog.company == "amazon")
    ) == 1
    assert await _inventory(db_session) == {}


async def test_a_count_with_the_inventory_off_writes_none(sources, db_session, monkeypatch):
    from tracker.config import get_settings
    from tracker.workflows import discover_roles

    sources["amazon"] = (["a"], "complete")
    monkeypatch.setattr(get_settings(), "inventory_enabled", False)
    monkeypatch.setattr(discover_roles, "_YIELD_WINDOW_SECONDS", 0)
    await discover_roles.discover(companies=["amazon"])
    assert await _inventory(db_session) == {}


async def _catalog(db_session, company: str) -> tuple:
    rows = (await db_session.execute(
        select(RoleCatalog.role_group, RoleCatalog.band_counts, RoleCatalog.count)
        .where(RoleCatalog.company == company).order_by(RoleCatalog.id)
        .execution_options(populate_existing=True)
    )).all()
    status = await db_session.scalar(
        select(TrackedCompany.role_catalog_status).where(TrackedCompany.slug == company)
        .execution_options(populate_existing=True)
    )
    return status, [tuple(row) for row in rows]


@pytest.mark.parametrize("cut", ["incomplete", "truncated", "bounded"])
async def test_a_count_cut_short_leaves_a_ready_catalog_as_it_was(sources, db_session, monkeypatch, cut):
    """A read that lost a page, met a page ceiling or ran into our time bound
    saw part of the board. Stored as ready, its tallies would replace the
    whole board's with a fraction of them."""
    from tracker.platform.clock import BOUNDED
    from tracker.workflows import discover_roles

    monkeypatch.setattr(discover_roles, "_YIELD_WINDOW_SECONDS", 0)
    sources["amazon"] = (["a", "b", "c"], "complete")
    await discover_roles.discover(companies=["amazon"], max_list=None)
    ready = await _catalog(db_session, "amazon")
    assert ready[0] == "ready" and sum(count for *_, count in ready[1]) == 3

    if cut == "bounded":
        calls = iter(range(10))
        monkeypatch.setattr(discover_roles, "bound_fired", lambda _deadline: BOUNDED if next(calls) == 1 else None)
        sources["amazon"] = (["a", "b", "c"], "complete")
    else:
        sources["amazon"] = (["a"], cut)
    result = await discover_roles.discover(companies=["amazon"], max_list=None)

    assert result["companies"]["amazon"]["status"] == "ready"
    assert await _catalog(db_session, "amazon") == ready


async def test_a_count_that_reached_the_board_s_end_replaces_the_catalog(sources, db_session, monkeypatch):
    """The control: a whole read is the board as it is now."""
    from tracker.workflows import discover_roles

    monkeypatch.setattr(discover_roles, "_YIELD_WINDOW_SECONDS", 0)
    sources["amazon"] = (["a", "b", "c"], "complete")
    await discover_roles.discover(companies=["amazon"], max_list=None)
    sources["amazon"] = (["a"], "complete")
    await discover_roles.discover(companies=["amazon"], max_list=None)

    status, rows = await _catalog(db_session, "amazon")
    assert status == "ready" and sum(count for *_, count in rows) == 1
