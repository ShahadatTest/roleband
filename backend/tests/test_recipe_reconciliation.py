"""Source changes preserve posting identity and never turn a switch into closure."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from tests.test_recipe_adapter import RECIPE
from tests.test_recipe_dispatch import ROBOTS_OK, _serve
from tracker.company_store import CompanyConflict
from tracker.config import get_settings
from tracker.db import reconciliation as store
from tracker.db.models import (
    BindingReconciliationDecision,
    Job,
    JobLifecycleEvent,
    JobObservation,
    JobSourceIdentity,
    ScrapeRun,
    SourceBinding,
    TrackedCompany,
)
from tracker.db.recipe_store import activate_revision, record_validation, save_draft_revision
from tracker.db.repo import load_company_jobs, upsert_job
from tracker.schema import EnrichedJob, LevelBand, LevelConfidence, RawJob
from tracker.workflows.collection_types import ScanMode, SourceCollection, empty_stats
from tracker.workflows.recipe_preview import shadow_document
from tracker.workflows.run_persistence import persist_source

pytestmark = pytest.mark.usefixtures("no_escape")


def enriched(req_id, url, title="Staff Eng"):
    return EnrichedJob(raw=RawJob(company="demo", req_id=req_id, title=title, url=url,
                                 locations=["London"]), level_band=LevelBand.STAFF,
                       level_confidence=LevelConfidence.CONFIRMED, family="software_engineering",
                       location_groups=["london"])


async def seed(db, postings=None):
    db.add(TrackedCompany(slug="demo", display="Demo", adapter="greenhouse", board_token="demo",
                          status="active", enabled=True, visible=True))
    await db.flush()
    old = SourceBinding(company_slug="demo", connector_kind="adapter", connector_id="greenhouse",
                        status="stable", closure_capability="authoritative")
    run = ScrapeRun(status="running")
    db.add_all([old, run])
    revision = await save_draft_revision(db, slug=RECIPE["id"], document=RECIPE)
    await activate_revision(db, recipe_id=revision.recipe_id, revision_id=revision.id)
    await record_validation(db, revision_id=revision.id,
                            evidence={"passed": True, "validated_at": datetime.now(UTC).isoformat()})
    await db.flush()
    for posting in postings or [enriched("old-id", "https://careers.demo.com/j/1")]:
        await upsert_job(db, run, posting, {}, binding_id=old.id)
    await db.commit()
    return old, revision, run


async def proposal(db, revision, jobs=None):
    jobs = jobs or [{"req_id": "new-id", "title": "Staff Eng", "url": "https://careers.demo.com/j/1",
                     "locations": ["London"], "posted_at": None}]
    return await store.propose(db, "demo", recipe_slug=RECIPE["id"], revision_id=revision.id,
                               jobs=jobs, evidence={"passed": True, "found": len(jobs)})


async def persist(db, run, postings):
    stats = empty_stats()
    stats.update(scanned=len(postings), kept=len(postings))
    collection = SourceCollection(company="demo", enriched=postings,
                                  seen_keys={e.raw.dedupe_key() for e in postings},
                                  stats=stats, drift=[], list_complete=True)
    await persist_source(db, run, "demo", collection, provider_key="recipe",
                         scan_mode=ScanMode.RECONCILE, max_list=None, touched_ids=[])
    await db.flush()
    return stats


@pytest.mark.asyncio
async def test_rebind_keeps_job_id_observations_and_rollback_closes_nothing(db_session):
    db = db_session
    old, revision, run = await seed(db)
    original = (await db.scalars(select(Job))).one()
    original_id, original_key = original.id, original.dedupe_key
    comparison = await proposal(db, revision)
    assert comparison["ready"]
    assert old.status == "stable"
    assert await db.scalar(select(func.count()).select_from(JobSourceIdentity)) == 1
    assert await db.scalar(select(func.count()).select_from(JobObservation)) == 1

    binding_id = comparison["binding_id"]
    await store.activate(db, "demo", binding_id)
    await db.commit()
    stats = await persist(db, run, [enriched("new-id", original.url)])
    assert stats["closed"] == 0 and stats["new"] == 0
    assert stats["closure_eligible"] is False
    assert await db.scalar(select(func.count()).select_from(Job)) == 1
    observations = (await db.scalars(select(JobObservation).order_by(JobObservation.id))).all()
    assert [o.job_id for o in observations] == [original_id, original_id]
    assert [o.binding_id for o in observations] == [old.id, binding_id]
    assert original.dedupe_key == original_key
    assert (await load_company_jobs(db, "demo"))["demo:new-id"].id == original_id
    await db.commit()

    await store.rollback(db, "demo", binding_id, reason="The adapter remains the preferred source")
    await db.commit()
    assert old.closure_capability == "none"
    # Even a complete empty first scan cannot use authority the old binding earned before the switch.
    original.absent_scans = 2
    original.absent_since = datetime.now(UTC) - timedelta(days=3)
    stats = await persist(db, run, [])
    assert stats["closed"] == 0 and original.status == "open"
    assert (await db.get(TrackedCompany, "demo")).board_token == "demo"
    assert not (await db.scalars(select(JobLifecycleEvent).where(JobLifecycleEvent.event_type == "closed"))).all()
    decisions = (await db.scalars(select(BindingReconciliationDecision.decision))).all()
    assert {"shadow", "exact_auto", "retire_binding", "activate", "rollback"} <= set(decisions)


@pytest.mark.asyncio
async def test_title_and_location_never_auto_link_and_review_is_one_to_one(db_session):
    db = db_session
    _, revision, _ = await seed(db, [enriched("a", "https://old.test/a"), enriched("b", "https://old.test/b")])
    jobs = [{"req_id": key, "title": "Staff Eng", "url": f"https://new.test/{key}", "locations": ["London"]}
            for key in ("x", "y")]
    comparison = await proposal(db, revision, jobs)
    binding = comparison["binding_id"]
    assert not comparison["ready"] and len(comparison["unresolved_job_ids"]) == 2
    assert "exact_auto" not in [r["decision"] for r in comparison["decisions"]]
    with pytest.raises(CompanyConflict, match="every posting"):
        await store.activate(db, "demo", binding)
    a, b = comparison["unresolved_job_ids"]
    await store.review(db, "demo", binding, decision="map", source_key="demo:x", job_id=a, reason="Compared posting bodies")
    with pytest.raises(CompanyConflict, match="only once"):
        await store.review(db, "demo", binding, decision="map", source_key="demo:y", job_id=a, reason="Duplicate target")
    with pytest.raises(CompanyConflict, match="shadow listing"):
        await store.review(db, "demo", binding, decision="map", source_key="demo:y", job_id=999999, reason="Outside this company")
    await store.review(db, "demo", binding, decision="retire", source_key=None, job_id=b, reason="No counterpart on the proposed board")
    result = await store.review(db, "demo", binding, decision="new", source_key="demo:y", job_id=None, reason="A separate new posting")
    assert result["ready"]
    await store.activate(db, "demo", binding)
    from tracker.db.binding import resolve_closure_scope
    new = await db.get(SourceBinding, binding)
    new.closure_capability = "authoritative"
    jobs = (await db.scalars(select(Job))).all()
    scope = await resolve_closure_scope(db, "demo", open_jobs=jobs, listing_is_authoritative=True)
    assert a in scope.closable_job_ids and b not in scope.closable_job_ids
    assert all(job.status == "open" for job in jobs), "retirement records identity review, never source absence"


def test_exact_matches_refuse_duplicate_urls_and_conflicting_ids():
    old = [{"job_id": 1, "req_id": "a", "url": "https://careers.test/a"},
           {"job_id": 2, "req_id": "b", "url": "https://careers.test/b"}]
    assert store.exact_matches(old, [{"source_key": "x", "req_id": "a", "url": "https://careers.test/b"}]) == {}
    assert store.exact_matches(old, [{"source_key": k, "req_id": k, "url": "https://careers.test/a"} for k in ("x", "y")]) == {}
    assert store.exact_matches(old, [{"source_key": "x", "req_id": "z", "url": "https://CAREERS.test/a#apply"}]) == {"x": (1, "canonical_url")}
    assert store.exact_matches(old, [{"source_key": "x", "req_id": "z", "url": "https://careers.test/a?different=1"}]) == {}


@pytest.mark.asyncio
async def test_stale_or_conflicting_proposals_cannot_activate(db_session):
    db = db_session
    _, revision, _ = await seed(db)
    comparison = await proposal(db, revision)
    binding = comparison["binding_id"]
    job = (await db.scalars(select(Job))).one()
    job.url = "https://careers.demo.com/changed"
    await db.flush()
    with pytest.raises(CompanyConflict, match="stale"):
        await store.activate(db, "demo", binding)
    await store.rollback(db, "demo", binding, reason="Read a fresh listing")
    assert (await db.get(TrackedCompany, "demo")).adapter == "greenhouse"
    with pytest.raises(CompanyConflict, match="incomplete"):
        await store.propose(db, "demo", recipe_slug=RECIPE["id"], revision_id=revision.id,
                            jobs=[], evidence={"passed": False, "found": 0})


@pytest.mark.asyncio
async def test_shadow_reads_every_posting_without_writes_and_api_round_trip(api_client, db_session, monkeypatch):
    db = db_session
    await seed(db)
    page = "<html><body>" + "".join(
        f'<article class="job" data-id="J{i}"><h2>Staff Eng</h2><a href="/j/{i}">apply</a></article>'
        for i in range(1, 8)) + "</body></html>"
    _serve(monkeypatch, {"https://careers.demo.com/jobs": page, "https://careers.demo.com/robots.txt": ROBOTS_OK})
    check = await shadow_document(RECIPE)
    assert check.passed and len(check.jobs) == check.found == 7
    assert await db.scalar(select(func.count()).select_from(BindingReconciliationDecision)) == 0
    assert await db.scalar(select(func.count()).select_from(Job)) == 1
    result = await api_client.post("/api/companies/demo/recipe-rebind", json={"recipe": RECIPE["id"]})
    assert result.status_code == 201, result.text
    body = result.json()
    path = f"/api/companies/demo/recipe-rebind/{body['binding_id']}"
    assert (await api_client.get(path)).json() == body
    assert (await api_client.post(path + "/activate")).status_code == 409
    for key in body["unresolved_source_keys"]:
        response = await api_client.post(path + "/decisions", json={"decision": "new", "source_key": key, "reason": "A separate posting"})
        assert response.status_code == 200, response.text
    assert response.json()["ready"]
    assert (await api_client.post(path + "/activate")).status_code == 200
    assert (await api_client.post(path + "/rollback", json={"reason": "Restore the adapter"})).status_code == 200
    assert (await api_client.get(path.replace("demo", "another-company"))).status_code == 404


@pytest.mark.asyncio
async def test_activation_cannot_race_a_running_collection(db_session):
    from sqlalchemy.ext.asyncio import AsyncSession

    db = db_session
    _, revision, _ = await seed(db)
    comparison = await proposal(db, revision)
    await db.commit()
    async with AsyncSession(db.bind) as other:
        await other.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": get_settings().advisory_lock_key})
        with pytest.raises(CompanyConflict, match="collection is running"):
            await store.activate(db, "demo", comparison["binding_id"])


@pytest.mark.asyncio
async def test_scope_widening_never_promotes_a_reviewed_alias_as_a_second_job(api_client, db_session):
    from tests.test_scope_promotion import SAVE
    from tracker.db.inventory_store import write_inventory
    from tracker.db.repo import refresh_listed_rungs
    from tracker.enrich.enricher import annotate
    from tracker.enrich.inventory import inventory_row

    db = db_session
    _, revision, run = await seed(db)
    original_id = await db.scalar(select(Job.id))
    comparison = await proposal(db, revision)
    binding = comparison["binding_id"]
    await store.activate(db, "demo", binding)
    raws = [RawJob(company="demo", req_id=key, title="Staff Software Engineer",
                   url=f"https://careers.demo.com/{key}", locations=["London, UK"])
            for key in ("new-id", "separate")]
    raws[0].raw_level = "Staff"
    rows = {raw.dedupe_key(): inventory_row(raw, annotate(raw)) for raw in raws}
    await write_inventory(db, company="demo", binding_id=binding, run_id=run.id,
                          rows=rows, seen_keys=set(rows), authoritative=False,
                          now=datetime.now(UTC), touch_hours=12)
    assert await refresh_listed_rungs(db) == [original_id]
    assert await db.scalar(select(Job.raw_level).where(Job.id == original_id)) == "Staff"
    await db.commit()
    result = await api_client.put("/api/settings", json=SAVE)
    assert result.status_code == 200, result.text
    assert result.json()["promoted"] == 1, "the separate posting joins; the reviewed alias is already held"
    jobs = (await db.scalars(select(Job).order_by(Job.id))).all()
    assert len(jobs) == 2 and jobs[0].id == original_id
    assert {job.req_id for job in jobs} == {"old-id", "separate"}


@pytest.mark.asyncio
async def test_a_reappearing_closed_posting_reuses_its_history_after_rebind(db_session):
    db = db_session
    _, revision, run = await seed(db)
    original = (await db.scalars(select(Job))).one()
    original.status = "closed"
    await db.commit()
    comparison = await proposal(db, revision)
    assert comparison["ready"]
    await store.activate(db, "demo", comparison["binding_id"])
    await db.commit()
    stats = await persist(db, run, [enriched("new-id", original.url)])
    assert stats["new"] == 0 and original.status == "open"
    assert await db.scalar(select(func.count()).select_from(Job)) == 1
    assert [job_id for job_id in (await db.scalars(select(JobObservation.job_id))).all()] == [original.id, original.id]


@pytest.mark.asyncio
async def test_an_old_parser_validation_cannot_authorize_a_source_switch(db_session):
    from tracker.connectors.extract import extractor_fingerprint
    from tracker.db.binding import resolve_closure_scope

    db = db_session
    _, revision, _ = await seed(db)
    comparison = await proposal(db, revision)
    binding = comparison["binding_id"]
    current = dict(revision.validation)
    revision.validation = {**current, "extractor_version": extractor_fingerprint()["extractor_version"] - 1}
    await db.flush()
    with pytest.raises(CompanyConflict, match="validation"):
        await store.activate(db, "demo", binding)
    revision.validation = current
    await db.flush()
    await store.activate(db, "demo", binding)
    new = await db.get(SourceBinding, binding)
    new.closure_capability = "authoritative"
    revision.validation = {**current, "parser": "different engine"}
    await db.flush()
    jobs = (await db.scalars(select(Job))).all()
    scope = await resolve_closure_scope(db, "demo", open_jobs=jobs, listing_is_authoritative=True)
    assert not scope.may_close and "different extractor" in scope.reason
