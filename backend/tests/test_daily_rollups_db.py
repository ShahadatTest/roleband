"""A day's rollup is the whole of that day's input.

A pass that upserts only the groups present in its new input lets a group
whose last posting left scope, moved place or closed keep its earlier same-day
row: the comp trend pools its old value with the survivors, the skill trend
keeps its count. (Hiring reads roles live, and the demand rollup is history
only.) Every pass replaces its day. Real Postgres, the real passes through
`run_post_passes`, the real routes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from tests.factories import make_job
from tracker.analytics import demand as demand_module
from tracker.config import get_settings
from tracker.db.models import (
    CompMetric,
    CompSnapshot,
    DemandMetric,
    DisclosureSnapshot,
    JobCompEstimate,
    JobSkill,
    SkillConcept,
    SkillDemandDaily,
)
from tracker.workflows import post_passes
from tracker.workflows.post_passes import PostPassContext, run_post_passes

pytestmark = pytest.mark.asyncio

TODAY = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
YESTERDAY = TODAY - timedelta(days=1)
ROLLUPS = ("demand_metrics", "skill_demand", "comp_metrics", "disclosure_metrics")


@pytest.fixture(autouse=True)
def rollups_only(monkeypatch):
    monkeypatch.setattr(
        post_passes, "POST_PASSES", tuple(p for p in post_passes.POST_PASSES if p.name in ROLLUPS)
    )


async def _derive(db_session) -> None:
    await run_post_passes(PostPassContext(
        session=db_session, touched_ids=[], per_source={}, settings=get_settings(), max_list=None,
    ))


async def _seed(db_session):
    concept = SkillConcept(slug="rollup_python", display="Python", facet="technology",
                           category="programming", description="Python", taxonomy_version="t")
    a = make_job("a", comp_median=300_000, location_groups=["silicon_valley"],
             structured_at=TODAY, disclosed_base_min=250_000, disclosed_base_max=300_000,
             disclosed_currency="USD", disclosed_pay_basis="base", disclosed_pay_period="year")
    b = make_job("b", company="meta", dedupe_key="meta:b", comp_median=200_000,
             location_groups=["new_york"])
    db_session.add_all([concept, a, b])
    await db_session.flush()
    for job in (a, b):
        # Our own estimate, stored beside the job's copy: what the pay
        # rollups read.
        db_session.add(JobCompEstimate(job_id=job.id, source="roleband", comp_median=job.comp_median))
        db_session.add(JobSkill(job_id=job.id, concept_id=concept.id, importance_score=90,
                                importance_band="core", confidence="high", modality="required",
                                content_hash="h", extractor_version="v", taxonomy_version="t"))
    # Yesterday's rollup: the control no run today may touch.
    db_session.add_all([
        DemandMetric(metric_date=YESTERDAY, company="google", family="product_management",
                     location_group="silicon_valley", open_count=7, new_count=0, closed_count=0,
                     reposted_count=0, long_open_count=0),
        CompSnapshot(metric_date=YESTERDAY, company="google", level_band="staff",
                     family="product_management", comp_values=[999_000], source="roleband"),
        SkillDemandDaily(metric_date=YESTERDAY, company="google", family="product_management",
                         concept_id=concept.id, job_count=5),
    ])
    await db_session.commit()
    return a, b


async def _today(db_session, model, *columns):
    rows = (await db_session.execute(select(*columns).where(model.metric_date == TODAY))).all()
    return sorted(tuple(r) for r in rows)


async def _yesterday_untouched(db_session) -> None:
    assert (await db_session.scalars(
        select(DemandMetric.open_count).where(DemandMetric.metric_date == YESTERDAY))).all() == [7]
    assert (await db_session.scalars(
        select(CompSnapshot.comp_values).where(CompSnapshot.metric_date == YESTERDAY))).all() == [[999_000]]
    assert (await db_session.scalars(
        select(SkillDemandDaily.job_count).where(SkillDemandDaily.metric_date == YESTERDAY))).all() == [5]


async def test_a_second_run_the_same_day_keeps_no_group_that_left(db_session, api_client):
    a, b = await _seed(db_session)
    await _derive(db_session)
    assert await _today(db_session, DemandMetric, DemandMetric.company, DemandMetric.location_group) == [
        ("google", "silicon_valley"), ("meta", "new_york"),
    ], "the control: both postings are counted"

    a.in_scope = False            # leaves scope
    b.location_groups = ["seattle"]  # moves place
    await db_session.commit()
    await _derive(db_session)

    assert await _today(db_session, DemandMetric, DemandMetric.company, DemandMetric.location_group,
                        DemandMetric.open_count) == [("meta", "seattle", 1)]
    assert await _today(db_session, CompSnapshot, CompSnapshot.company, CompSnapshot.comp_values) == [
        ("meta", [200_000])]
    assert {r for r in await _today(db_session, CompMetric, CompMetric.count, CompMetric.p50)} == {(1, 200_000)}
    assert await _today(db_session, SkillDemandDaily, SkillDemandDaily.company, SkillDemandDaily.job_count) == [
        ("meta", 1)]
    assert {r[0] for r in await _today(db_session, DisclosureSnapshot, DisclosureSnapshot.company)} == {"meta"}
    await _yesterday_untouched(db_session)

    # Hiring counts roles live, not from this rollup: the role
    # that left scope is gone from it as well.
    demand = (await api_client.get("/api/demand")).json()
    assert [(c["company"], c["open"]) for c in demand["companies"]] == [("meta", 1)]
    trend = (await api_client.get("/api/statistics/comp-trends", params={"days": 0})).json()
    (market,) = trend["series"]
    assert market["points"][-1]["p50"] == 200_000  # not pooled with the 300,000 that left
    skills = (await api_client.get("/api/skills/trends", params={"days": 0})).json()
    assert [(s["term"], s["current"]) for s in skills["series"]] == [("rollup_python", 1)]


async def test_an_empty_day_is_today_and_empty_not_yesterday(db_session, api_client):
    a, b = await _seed(db_session)
    await _derive(db_session)
    a.in_scope = b.in_scope = False
    await db_session.commit()
    await _derive(db_session)

    for model in (DemandMetric, CompSnapshot, CompMetric, SkillDemandDaily, DisclosureSnapshot):
        assert await db_session.scalar(
            select(func.count()).select_from(model).where(model.metric_date == TODAY)) == 0, model
    await _yesterday_untouched(db_session)
    demand = (await api_client.get("/api/demand")).json()
    assert (demand["open_total"], demand["companies"]) == (0, [])


async def test_a_failed_rollup_keeps_the_day_it_would_have_replaced(db_session, monkeypatch):
    a, _b = await _seed(db_session)
    await _derive(db_session)
    before = await _today(db_session, DemandMetric, DemandMetric.company, DemandMetric.open_count)
    a.in_scope = False
    await db_session.commit()

    def broken_insert(*_args, **_kwargs):
        raise RuntimeError("insert failed after the day was cleared")

    monkeypatch.setattr(demand_module, "insert", broken_insert)
    with pytest.raises(RuntimeError, match="insert failed"):
        await _derive(db_session)
    assert await _today(db_session, DemandMetric, DemandMetric.company, DemandMetric.open_count) == before
