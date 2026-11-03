"""Postings a sync already read join the Board when the scope widens.

Invariants:

- I7 the gate over inventory rows is the ingest gate, row for row, over a
  generated population and scopes that exercise answers (any and narrowed,
  with level ranges), interests, "not interested in", place exceptions and
  learned exclusions;
- I9 promotion admits exactly: not gone, read by a scan within
  `inventory_promotion_fresh_hours`, company followed and active,
  not in `jobs`, passing the saved scope; an unplaced posting never passes;
- I10 a promoted job is open and in scope with no description, `first_seen`
  and `last_seen` from the inventory, one `added` event and one observation
  under the run that last read it;
- I11 the digest and "new today" never count a promoted posting as new;
- I12 a save that finds a run holding the lock promotes nothing, says
  pending, and the run's post pass promotes;
- I13 narrow then widen flips an existing job back and never duplicates it;
- a promotion failure never fails the save, and a save that promoted queues a
  sync of the companies it promoted from.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from tracker.config import get_settings
from tracker.db.inventory_store import (
    reclassify_inventory,
    reclassify_inventory_if_changed,
    write_inventory,
)
from tracker.db.models import (
    Job,
    JobLifecycleEvent,
    JobObservation,
    PostingInventory,
    ScrapeRun,
    SourceBinding,
    SyncScheduleState,
    TrackedCompany,
)
from tracker.db.queries.jobs import new_listing_clause
from tracker.db.queries.scope import job_scope_expr
from tracker.db.repo import ADDED_FROM_INVENTORY
from tracker.enrich.enricher import ScopeFilter, annotate, passes_filters, rule_excluded
from tracker.enrich.inventory import inventory_row
from tracker.notifications.digest import _candidate_stmt
from tracker.platform.locks import advisory_unlock, try_advisory_lock
from tracker.schema import RawJob
from tracker.scope import promotion
from tracker.taxonomy.role_answers import RoleAnswer
from tracker.workflows.post_passes import PostPassContext, _pass_inventory_promotion

#: `PUT /api/settings` starts the directory scan when the set is followed.
pytestmark = pytest.mark.usefixtures("no_escape")

#: Yesterday: promotion admits only a posting a scan read in the last
#: `inventory_promotion_fresh_hours`, so the rows here must be recent.
T0 = datetime.now(UTC).replace(microsecond=0) - timedelta(days=1)
COMPANY = "anthropic"  # a built-in on Greenhouse: the scheduler can queue it

# --------------------------------------------------------------------------- #
# I7: one gate for both tables
# --------------------------------------------------------------------------- #

TITLES = (
    "Staff Software Engineer", "Senior Engineering Manager", "Principal Product Manager",
    "Senior Data Scientist", "Staff Security Engineer, Detection", "Account Executive",
    "Director of Finance", "Barista", "Senior Technical Program Manager",
    "Staff Machine Learning Engineer, Ads",
)
PLACES = (["London, UK"], ["New York, NY"], ["Berlin, Germany"], ["Remote, US"], ["Multiple Locations"])
TEAMS = (None, "Ads", "Payments")


def _population() -> list[RawJob]:
    return [
        RawJob(company=COMPANY, req_id=f"r{i}", title=title, url=f"https://jobs.example.test/{i}",
               locations=list(places), team=team)
        for i, (title, places, team) in enumerate(itertools.product(TITLES, PLACES, TEAMS))
    ]


SCOPES = [
    dict(bands={"senior", "staff", "principal"}, locations={"uk"}, answers=(RoleAnswer("technical", None),)),
    dict(bands={"senior", "staff", "principal", "director_plus"}, locations={"united_states", "europe"},
         answers=(RoleAnswer("management", None), RoleAnswer("product_program", frozenset({"product_management"})))),
    dict(bands={"staff"}, locations={"europe", "london"}, excepted={"uk"},
         answers=(RoleAnswer("technical", frozenset({"software_engineering", "ml_ai_research"})),)),
    dict(bands={"senior", "staff"}, locations={"united_states", "uk"}, excepted={"new_york"},
         answers=(RoleAnswer("technical", None),), excluded_domains={"advertising"}),
    dict(bands={"senior", "staff", "principal"}, locations={"uk", "united_states"},
         answers=(RoleAnswer("technical", None), RoleAnswer("business_customer", None)),
         domains={"fintech_payments"}, exclusions={(COMPANY, "team", "payments")}),
]


def _filter(scope: dict) -> ScopeFilter:
    return ScopeFilter(
        enabled_bands=frozenset(scope["bands"]), enabled_roles=frozenset(), enabled_tracks=frozenset(),
        enabled_locations=frozenset(scope["locations"]), enabled_domains=frozenset(scope.get("domains", ())),
        company_exclusions=frozenset(scope.get("exclusions", ())),
        excluded_domains=frozenset(scope.get("excluded_domains", ())), answers=scope["answers"],
        excluded_locations=frozenset(scope.get("excepted", ())),
    )


async def _run(db_session) -> int:
    run = ScrapeRun(status="running")
    db_session.add(run)
    await db_session.flush()
    return run.id


async def _store(db_session, raws: list[RawJob], *, now=T0, company=COMPANY) -> int:
    run_id = await _run(db_session)
    rows = {raw.dedupe_key(): inventory_row(raw, annotate(raw)) for raw in raws}
    await write_inventory(
        db_session, run_id=run_id, company=company, binding_id=None, rows=rows,
        seen_keys=set(rows), authoritative=False, now=now, touch_hours=12,
    )
    await db_session.commit()
    return run_id


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", SCOPES, ids=[f"scope{i}" for i in range(len(SCOPES))])
async def test_the_gate_over_inventory_is_the_ingest_gate_row_for_row(db_session, scope):
    population = _population()
    await _store(db_session, population)
    gate = job_scope_expr(
        [], scope["bands"], [], scope["locations"], scope.get("domains", ()),
        frozenset(scope.get("exclusions", ())), excluded_domains=scope.get("excluded_domains", ()),
        answers=scope["answers"], excluded_locations=scope.get("excepted", ()), model=PostingInventory,
    )
    admitted = set((await db_session.scalars(select(PostingInventory.req_id).where(gate))).all())
    flt = _filter(scope)
    expected = {
        raw.req_id for raw in population
        if passes_filters(annotate(raw), flt) and not rule_excluded(raw, flt.company_exclusions)
    }
    assert admitted == expected
    # A scope that admits nothing, or everything, proves nothing.
    assert 0 < len(expected) < len(population)


# --------------------------------------------------------------------------- #
# Promotion through a real save
# --------------------------------------------------------------------------- #


def _raw(req: str, title: str = "Staff Software Engineer", places=("London, UK",), company=COMPANY) -> RawJob:
    return RawJob(company=company, req_id=req, title=title, url=f"https://jobs.example.test/{req}",
                  locations=list(places))


def _company(slug: str = COMPANY, *, enabled: bool = True, status: str = "active") -> TrackedCompany:
    return TrackedCompany(
        slug=slug, display=slug.title(), adapter="greenhouse", status=status, enabled=enabled,
        visible=True, source="catalog",
    )


SAVE = {
    "enabled_role_groups": [], "enabled_seniority_bands": ["staff"],
    "enabled_location_groups": ["uk"], "role_answers": [{"track": "technical", "roles": "any"}],
}


async def _save(api_client, **overrides):
    saved = await api_client.put("/api/settings", json={**SAVE, **overrides})
    assert saved.status_code == 200, saved.text
    return saved.json()


async def _jobs(db_session) -> dict[str, Job]:
    db_session.expire_all()
    return {job.req_id: job for job in (await db_session.scalars(select(Job))).all()}


@pytest.mark.asyncio
async def test_a_widening_save_admits_exactly_what_the_scope_keeps(api_client, db_session):
    db_session.add_all([_company(), _company("paused", enabled=False), _company("gone", status="inactive")])
    await db_session.commit()
    await _store(db_session, [
        _raw("keep"),
        _raw("pm", title="Staff Product Manager"),       # another kind of role
        _raw("nyc", places=("New York, NY",)),            # another place
        _raw("unplaced", places=("Multiple Locations",)),  # a place we cannot read
        _raw("left"),                                     # gone below
    ])
    await _store(db_session, [_raw("p1", company="paused")], company="paused")
    await _store(db_session, [_raw("g1", company="gone")], company="gone")
    await db_session.execute(update(PostingInventory).where(PostingInventory.req_id == "left").values(gone_at=T0))
    await db_session.commit()

    body = await _save(api_client)
    assert set(await _jobs(db_session)) == {"keep"}
    assert (body["promoted"], body["promotion_pending"]) == (1, False)
    assert body["on_board"] == 1, "the Board count includes what the save promoted"

    # Widening to product management admits the PM posting, and only it.
    body = await _save(api_client, role_answers=[
        {"track": "technical", "roles": "any"}, {"track": "product_program", "roles": "any"},
    ])
    assert body["promoted"] == 1
    assert set(await _jobs(db_session)) == {"keep", "pm"}


@pytest.mark.asyncio
async def test_only_a_posting_a_scan_read_recently_is_promoted(api_client, db_session):
    fresh_hours = get_settings().inventory_promotion_fresh_hours
    now = datetime.now(UTC)
    db_session.add(_company())
    await db_session.commit()
    await _store(db_session, [_raw("inside")], now=now - timedelta(hours=fresh_hours - 1))
    await _store(db_session, [_raw("outside")], now=now - timedelta(hours=fresh_hours + 1))

    await _save(api_client)
    assert set(await _jobs(db_session)) == {"inside"}


@pytest.mark.asyncio
async def test_a_re_followed_company_s_postings_wait_for_its_next_scan(api_client, db_session):
    """Unfollowed for twenty days, nothing was scanned or marked gone. Following
    again must not put those postings on the Board as open: some closed while
    nobody looked. The next scan reads what is still listed, and that is admitted."""
    now = datetime.now(UTC)
    db_session.add(_company(enabled=False))
    await db_session.commit()
    await _store(db_session, [_raw("still-listed"), _raw("closed-meanwhile")], now=now - timedelta(days=20))
    await db_session.execute(update(TrackedCompany).values(enabled=True))
    await db_session.commit()

    await _save(api_client)
    assert await _jobs(db_session) == {}

    await _store(db_session, [_raw("still-listed")], now=datetime.now(UTC))
    async with async_sessionmaker(db_session.bind, expire_on_commit=False)() as run_session:
        ctx = PostPassContext(session=run_session, touched_ids=[], per_source={}, settings=get_settings(), max_list=None)
        await _pass_inventory_promotion(ctx)
        await run_session.commit()
    assert set(await _jobs(db_session)) == {"still-listed"}


@pytest.mark.asyncio
async def test_a_promoted_job_is_a_listing_read_earlier_not_a_new_opening(api_client, db_session):
    db_session.add(_company())
    await db_session.commit()
    first_run = await _store(db_session, [_raw("keep")], now=T0)
    last_run = await _store(db_session, [_raw("keep")], now=T0 + timedelta(days=3))

    await _save(api_client)
    job = (await _jobs(db_session))["keep"]
    assert (job.status, job.in_scope) == ("open", True)
    assert job.first_seen == T0 and job.last_seen == T0 + timedelta(days=3)
    assert job.description_text is None and job.description_sections == []
    assert job.comp_median is None
    assert (job.family, job.level_band, job.location_groups) == (
        "software_engineering", "staff", annotate(_raw("keep")).location_groups,
    )
    events = (await db_session.scalars(select(JobLifecycleEvent).where(JobLifecycleEvent.job_id == job.id))).all()
    assert [(e.event_type, e.run_id, e.detail["basis"]) for e in events] == [(ADDED_FROM_INVENTORY, None, "inventory")]
    observations = (await db_session.scalars(select(JobObservation).where(JobObservation.job_id == job.id))).all()
    assert [(o.run_id, o.observed_at) for o in observations] == [(last_run, T0 + timedelta(days=3))]
    assert first_run != last_run

    # I11: not new today, not in the day's digest.
    day = events[0].created_at.date()
    assert job.arrival == "first_read"
    assert job.id not in set((await db_session.scalars(select(Job.id).where(new_listing_clause()))).all())
    assert job.id not in {j.id for j in (await db_session.scalars(_candidate_stmt(day, set()))).all()}


@pytest.mark.asyncio
async def test_narrow_then_widen_flips_the_existing_job_and_never_duplicates_it(api_client, db_session):
    db_session.add(_company())
    await db_session.commit()
    await _store(db_session, [_raw("keep")])
    await _save(api_client)
    await _save(api_client, enabled_location_groups=["united_states"])
    assert (await _jobs(db_session))["keep"].in_scope is False

    body = await _save(api_client)
    jobs = await _jobs(db_session)
    # Nothing pending either: a duplicate insert failing in the savepoint
    # would report 0 promoted as well.
    assert (body["promoted"], body["promotion_pending"], body["in_scope_changed"]) == (0, False, 1)
    assert list(jobs) == ["keep"] and jobs["keep"].in_scope is True


@pytest.mark.asyncio
async def test_a_save_during_a_run_promotes_nothing_and_the_run_promotes_at_its_end(api_client, db_session):
    db_session.add(_company())
    await db_session.commit()
    await _store(db_session, [_raw("keep")])
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    key = get_settings().advisory_lock_key
    async with factory() as run_session:
        assert await try_advisory_lock(run_session, key)
        try:
            body = await _save(api_client)
            assert (body["promoted"], body["promotion_pending"]) == (0, True)
            assert await _jobs(db_session) == {}
        finally:
            await advisory_unlock(run_session, key)

    async with factory() as run_session:
        ctx = PostPassContext(session=run_session, touched_ids=[], per_source={}, settings=get_settings(), max_list=None)
        await _pass_inventory_promotion(ctx)
        await run_session.commit()
    jobs = await _jobs(db_session)
    assert list(jobs) == ["keep"]
    assert ctx.touched_ids == [jobs["keep"].id], "every later pass covers the admitted row"
    assert ctx.results["inventory"]["promoted"] == 1


@pytest.mark.asyncio
async def test_a_promoted_posting_is_estimated_in_the_run_that_admits_it(api_client, db_session):
    """An admitted posting is a new row, and a new row is estimated in its
    run. Fail-first: it carried no estimate until its company's next scan."""
    from tracker.db.models import JobCompEstimate
    from tracker.plugins.reestimate import reestimate

    db_session.add(_company())
    await db_session.commit()
    await _store(db_session, [_raw("keep", places=("San Francisco, CA",))])
    await reestimate(db_session)  # applies our set; the next call finds it current
    assert (await reestimate(db_session)).current, "the estimate state is settled before the run"
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    key = get_settings().advisory_lock_key
    async with factory() as run_session:
        assert await try_advisory_lock(run_session, key)
        try:
            body = await _save(api_client, enabled_location_groups=["silicon_valley"])
            assert body["promotion_pending"] is True, "the run, not the save, admits it"
        finally:
            await advisory_unlock(run_session, key)

    async with factory() as run_session:
        ctx = PostPassContext(session=run_session, touched_ids=[], per_source={}, settings=get_settings(), max_list=None)
        await _pass_inventory_promotion(ctx)
        await run_session.commit()

    job = (await _jobs(db_session))["keep"]
    estimate = await db_session.get(JobCompEstimate, (job.id, "roleband"))
    assert job.comp_median is not None and estimate is not None
    assert estimate.comp_median == job.comp_median


@pytest.mark.asyncio
async def test_a_failed_promotion_never_fails_the_save(api_client, db_session, monkeypatch):
    db_session.add(_company())
    await db_session.commit()
    await _store(db_session, [_raw("keep")])

    async def broken(session, **_kwargs):
        await session.execute(text("SELECT 1/0"))

    monkeypatch.setattr(promotion, "promote_locked", broken)
    body = await _save(api_client)
    assert (body["promoted"], body["promotion_pending"]) == (0, True)
    assert (await api_client.get("/api/settings")).json()["enabled_location_groups"] == ["uk"]


@pytest.mark.asyncio
async def test_a_save_that_promoted_queues_a_sync_of_those_companies(api_client, db_session):
    db_session.add(_company())
    await db_session.commit()
    await _store(db_session, [_raw("keep")])

    await _save(api_client)
    db_session.expire_all()
    queued = (await db_session.execute(
        select(SourceBinding.company_slug, SyncScheduleState.manual_requested_at)
        .join(SourceBinding, SourceBinding.id == SyncScheduleState.binding_id)
        .where(SyncScheduleState.manual_requested_at.isnot(None))
    )).all()
    assert [slug for slug, _at in queued] == [COMPANY]


@pytest.mark.asyncio
async def test_inventory_rows_follow_a_classifier_change_before_promotion_reads_them(db_session):
    await _store(db_session, [_raw("keep")])
    # Filed under an older taxonomy: the stored family does not match.
    await db_session.execute(update(PostingInventory).values(family="design_ux", content_hash="stale"))
    await db_session.commit()

    assert await reclassify_inventory(db_session) == 1
    await db_session.commit()
    row = (await db_session.scalars(select(PostingInventory))).one()
    assert row.family == "software_engineering"
    assert row.content_hash == inventory_row(_raw("keep"), annotate(_raw("keep"))).content_hash
    assert await reclassify_inventory(db_session) == 0, "once caught up, it writes nothing"


@pytest.mark.asyncio
async def test_a_row_the_code_cannot_read_never_stops_the_reclassify(db_session, monkeypatch, caplog):
    """A stored value an enum has dropped must not fail the whole pass:
    promotion would never run, the fingerprint would never be recorded, and
    every run would re-derive everything again."""
    from tracker.db import inventory_store

    await _store(db_session, [_raw("keep"), _raw("odd")])
    await db_session.execute(update(PostingInventory).values(family="design_ux", content_hash="stale"))
    await db_session.execute(
        update(PostingInventory).where(PostingInventory.req_id == "odd").values(workplace_type="teleport")
    )
    await db_session.commit()
    monkeypatch.setattr(inventory_store, "classifier_fingerprint", lambda: "a newer taxonomy")

    with caplog.at_level("WARNING", logger="tracker.db.inventory_store"):
        assert await reclassify_inventory_if_changed(db_session) == 1
    await db_session.commit()

    families = dict((await db_session.execute(select(PostingInventory.req_id, PostingInventory.family))).all())
    assert families == {"keep": "software_engineering", "odd": "design_ux"}
    assert "skipped 1 rows it cannot read" in caplog.text
    # Recorded: the next run under this classifier reads nothing.
    assert await reclassify_inventory_if_changed(db_session) is None


@pytest.mark.asyncio
async def test_the_run_re_derives_the_inventory_only_after_a_classifier_change(db_session, monkeypatch):
    from tracker.db import inventory_store

    await _store(db_session, [_raw("keep")])
    assert await reclassify_inventory_if_changed(db_session) == 0, "a first run records the classifier"
    await db_session.execute(update(PostingInventory).values(family="design_ux", content_hash="stale"))
    await db_session.commit()
    assert await reclassify_inventory_if_changed(db_session) is None, "same classifier: nothing read"
    assert (await db_session.scalars(select(PostingInventory.family))).one() == "design_ux"

    monkeypatch.setattr(inventory_store, "classifier_fingerprint", lambda: "a newer taxonomy")
    assert await reclassify_inventory_if_changed(db_session) == 1
    await db_session.commit()
    assert (await db_session.scalars(select(PostingInventory.family))).one() == "software_engineering"


@pytest.mark.asyncio
async def test_a_user_directed_source_is_never_queued_by_a_save(monkeypatch):
    """Workday is collected only when the user asks, and a queued request
    is what lets the dispatcher collect it: a scope save never makes one."""
    from tracker.workflows import scheduler

    async def targets(_session):
        return {"nvidia": {"adapter": "workday"}, COMPANY: {"adapter": "greenhouse"}}

    queued: list[list[str]] = []

    async def queue(_session, companies, **_kwargs):
        queued.append(list(companies))
        return list(companies)

    monkeypatch.setattr(scheduler, "get_active_targets", targets)
    monkeypatch.setattr(scheduler, "queue_manual_reconciliation", queue)
    assert await scheduler.queue_promoted_reconciliation(None, ["nvidia", COMPANY, "unfollowed"]) == [COMPANY]
    assert queued == [[COMPANY]]
    queued.clear()
    assert await scheduler.queue_promoted_reconciliation(None, ["nvidia"]) == []
    assert queued == [], "nothing to queue is not a queue of everything"


@pytest.mark.asyncio
async def test_the_catalog_route_prices_the_cities_the_request_names(api_client):
    """`?cities=` reaches the read; nothing is saved."""
    london = "city_2643743"
    body = (await api_client.get("/api/scope/catalog", params=[("cities", london), ("cities", "uk")])).json()
    assert body["scope_cells"]["cities"] == [london]
    assert london not in body["settings"]["enabled_location_groups"]
    assert (await api_client.get("/api/scope/catalog")).json()["scope_cells"]["cities"] == []
