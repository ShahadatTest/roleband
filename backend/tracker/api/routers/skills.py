"""Skills analytics: leaderboard, trends, overlap, and semantic clusters.

Every route declares its response in `api/schemas/skills.py`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from tracker.api.deps import InsightsScopeDep, OffBoardDep, SessionDep, WindowDays
from tracker.api.errors import ErrorCode, api_error
from tracker.api.schemas.skills import (
    ClusterDetailResponse,
    ClusterListResponse,
    SkillOverlapResponse,
    SkillTrendsResponse,
    TopSkillsResponse,
)
from tracker.api.serializers.jobs import serialize_job
from tracker.db.models import (
    Cluster,
    Job,
    JobSkill,
    SkillConcept,
    SkillDemandDaily,
)
from tracker.db.queries.jobs import exclude_hidden, row_context
from tracker.db.queries.skills import ELIGIBLE_REQUIREMENT, skill_role_counts
from tracker.skills.analytics import (
    COMPETENCY_CATEGORIES,
    build_trend_series,
    compute_overlap,
    rank_skills,
    seriate,
    set_changes,
)

router = APIRouter()


def _terms(stored: list[dict] | None) -> list[dict]:
    """A cluster's stored top terms without their stored English names: each is
    its `term`, which the client names from its catalog. Any other
    stored key is kept, as `ClusterTerm` keeps it."""
    return [{k: v for k, v in t.items() if k != "display"} for t in stored or []]


@router.get("/api/skills/top", response_model=TopSkillsResponse)
async def skills_top(
    session: SessionDep,
    hidden: OffBoardDep,
    scope: InsightsScopeDep,
    company: Annotated[list[str] | None, Query()] = None,
    family: Annotated[list[str] | None, Query()] = None,
    location_group: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 30,
) -> dict:
    """The Skills tab: a slice's skills by how characteristic they are
    of it, against the whole market; the whole market by share; competencies
    apart, industries excluded."""
    slice_conds: list = [*scope.conds()]
    if company:
        slice_conds.append(Job.company.in_(company))
    if family:
        slice_conds.append(Job.family.in_(family))
    if location_group:
        slice_conds.append(Job.location_groups.overlap(location_group))
    market_counts, market_roles, meta = await skill_role_counts(session, hidden)
    narrowed = bool(slice_conds)
    if narrowed:
        slice_counts, slice_roles, _ = await skill_role_counts(session, hidden, slice_conds)
    else:
        slice_counts, slice_roles = market_counts, market_roles
    ranked = rank_skills(
        slice_counts, slice_roles, market_counts, market_roles, meta, narrowed=narrowed, limit=limit
    )
    # Each skill is its `term`; the client names it from its catalog.
    for key in ("items", "competencies"):
        ranked[key] = [{k: v for k, v in skill.items() if k != "display"} for skill in ranked[key]]
    return ranked


@router.get("/api/skills/trends", response_model=SkillTrendsResponse)
async def skills_trends(
    session: SessionDep,
    hidden: OffBoardDep,
    scope: InsightsScopeDep,
    company: Annotated[list[str] | None, Query()] = None,
    family: Annotated[list[str] | None, Query()] = None,
    term: Annotated[list[str] | None, Query()] = None,
    days: WindowDays = 90,
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
) -> dict:
    """Skill demand over time from the `skill_demand_daily` V2 rollup.

    Returns a shared, sorted `dates` axis and one aligned `series` per skill (0-filled
    on days with no slice), so the client can draw sparklines without post-processing.
    When `term` (concept slug) is omitted the top `limit` skills by their most-recent
    count are chosen; otherwise exactly the requested slugs are returned. `days<=0`
    means all history. Series exclude industries (they never enter the rollup).

    History accrues one slice-set per pipeline run from the first run that extracted
    skills, so a young install's series are near-flat; the client shows an accruing note.
    """
    cutoff = None if days <= 0 else (
        datetime.now(UTC) - timedelta(days=days)
    ).replace(hour=0, minute=0, second=0, microsecond=0)

    stmt = (
        select(
            SkillDemandDaily.metric_date,
            SkillConcept.slug,
            SkillConcept.display,
            SkillConcept.category,
            func.sum(SkillDemandDaily.job_count).label("n"),
        )
        .join(SkillConcept, SkillConcept.id == SkillDemandDaily.concept_id)
    )
    if cutoff is not None:
        stmt = stmt.where(SkillDemandDaily.metric_date >= cutoff)
    if hidden:
        stmt = stmt.where(SkillDemandDaily.company.notin_(hidden))
    stmt = stmt.where(*scope.conds(company=SkillDemandDaily.company, family=SkillDemandDaily.family))
    if company:
        stmt = stmt.where(SkillDemandDaily.company.in_(company))
    if family:
        stmt = stmt.where(SkillDemandDaily.family.in_(family))
    # Every concept of each day, even when `term` names a few: a share is of the
    # day's whole; the builder picks the named terms.
    stmt = stmt.group_by(
        SkillDemandDaily.metric_date, SkillConcept.slug, SkillConcept.display, SkillConcept.category
    )
    rows = (await session.execute(stmt)).all()

    dated = [(r.metric_date.date().isoformat(), r.slug, r.n) for r in rows]
    axis, series = build_trend_series(
        dated,
        terms=term,
        limit=limit,
        exclude={r.slug for r in rows if r.category in COMPETENCY_CATEGORIES},
    )

    return {"days": days, "dates": axis, "series": series, "set_changes": set_changes(dated)}


@router.get("/api/skills/overlap", response_model=SkillOverlapResponse)
async def skills_overlap(
    session: SessionDep,
    hidden: OffBoardDep,
    scope: InsightsScopeDep,
    min_jobs: Annotated[int, Query(ge=1)] = 2,
    limit_companies: Annotated[int, Query(ge=1, le=50)] = 12,
    company: Annotated[list[str] | None, Query()] = None,
) -> dict:
    """Cross-company skill similarity over currently-open roles.

    A company's skill set = skill concepts required in at least `min_jobs` of its
    open roles (the floor trims one-off mentions that inflate spurious overlap;
    industries and competencies are excluded: a vertical is not a skill, and what
    every role is expected to do is overlap every company shares). Each pair
    is scored by the cosine of rarity-weighted skill vectors (`compute_overlap`).
    The companies are those named in `company`, else the top `limit_companies` by
    open roles in the scope, shown in an order that puts similar ones together.
    """
    rows = (
        await session.execute(
            exclude_hidden(
                select(
                    Job.company,
                    SkillConcept.slug,
                    SkillConcept.display,
                    func.count(func.distinct(JobSkill.job_id)).label("n"),
                )
                .select_from(JobSkill)
                .join(SkillConcept, SkillConcept.id == JobSkill.concept_id)
                .join(Job, Job.id == JobSkill.job_id)
                .where(
                    Job.status == "open",
                    Job.in_scope.is_(True),
                    *ELIGIBLE_REQUIREMENT,
                    SkillConcept.category.notin_(COMPETENCY_CATEGORIES),
                    *scope.conds(),
                ),
                hidden,
            ).group_by(Job.company, SkillConcept.slug, SkillConcept.display)
        )
    ).all()

    open_counts = dict(
        (
            await session.execute(
                exclude_hidden(
                    select(Job.company, func.count()).where(
                        Job.status == "open", Job.in_scope.is_(True), *scope.conds()
                    ), hidden
                ).group_by(Job.company)
            )
        ).all()
    )

    # company -> {concept slug: job_count} above the mention floor.
    skills: dict[str, dict[str, int]] = {}
    for company_slug, slug, _display, n in rows:
        if n >= min_jobs:
            skills.setdefault(company_slug, {})[slug] = int(n)

    if company:
        ranked = [c for c in dict.fromkeys(company) if c in skills][:limit_companies]
    else:
        ranked = sorted(
            skills.keys(), key=lambda c: (-open_counts.get(c, 0), c)
        )[:limit_companies]

    companies = [
        {"company": c, "skill_count": len(skills[c]), "open": int(open_counts.get(c, 0))}
        for c in ranked
    ]

    pairs = compute_overlap(skills, ranked, {c: open_counts.get(c, 0) for c in ranked})
    for p in pairs:
        # Slugs: the client names each skill from its catalog.
        p["top_shared"] = p.pop("top_shared_terms")
    order = {c: i for i, c in enumerate(seriate(ranked, pairs))}
    companies.sort(key=lambda row: order[row["company"]])

    return {"companies": companies, "pairs": pairs, "min_jobs": min_jobs}


@router.get("/api/clusters", response_model=ClusterListResponse)
async def clusters(session: SessionDep, hidden: OffBoardDep, scope: InsightsScopeDep) -> dict:
    """All semantic clusters with size, label, top skills, and company mix."""
    rows = (await session.scalars(select(Cluster).order_by(Cluster.size.desc()))).all()

    # Company breakdown per cluster in one pass.
    mix_rows = (
        await session.execute(
            exclude_hidden(
                select(Job.cluster_id, Job.company, func.count()).where(
                    Job.cluster_id.isnot(None),
                    Job.status == "open",
                    Job.in_scope.is_(True),
                    *scope.conds(),
                ),
                hidden,
            ).group_by(Job.cluster_id, Job.company)
        )
    ).all()
    mix: dict[int, dict[str, int]] = {}
    for cid, company, n in mix_rows:
        mix.setdefault(cid, {})[company] = n

    # The size shown is the members shown: open, in scope, visible. Not
    # `Cluster.size`, which the pass counted and a scope save or a hidden
    # company has since moved. A cluster with no such member drops out.
    def _size(c) -> int:
        return sum(mix.get(c.id, {}).values())

    items = [
        {
            "id": c.id,
            "family_hint": c.family_hint,
            "size": _size(c),
            "top_terms": _terms(c.top_terms),
            "companies": mix.get(c.id, {}),
        }
        for c in rows
        if _size(c) > 0
    ]
    items.sort(key=lambda it: it["size"], reverse=True)

    return {
        "items": items,
        "model_version": rows[0].model_version if rows else None,
    }


@router.get("/api/clusters/{cluster_id}", response_model=ClusterDetailResponse)
async def cluster_detail(cluster_id: int, session: SessionDep, hidden: OffBoardDep) -> dict:
    c = await session.get(Cluster, cluster_id)
    if c is None:
        raise api_error(404, ErrorCode.CLUSTER_NOT_FOUND, "cluster not found")
    members = (
        await session.scalars(
            exclude_hidden(
                select(Job).where(
                    Job.cluster_id == cluster_id,
                    Job.status == "open",
                    Job.in_scope.is_(True),
                ),
                hidden,
            ).order_by(Job.cluster_distance.asc())  # most central first
        )
    ).all()
    ctx = await row_context(session, list(members), unfollowed=hidden.unfollowed, standing=False)
    return {
        "id": c.id,
        "family_hint": c.family_hint,
        "size": len(members),
        "top_terms": _terms(c.top_terms),
        "items": [serialize_job(j, **ctx) for j in members],
    }
