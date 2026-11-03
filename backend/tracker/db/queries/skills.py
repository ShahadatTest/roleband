"""The skills leaderboard read.

Two surfaces build from it — `/api/skills/top` and the statistics overview's
"grounded skills". A read that more than one surface builds from is not a route
helper, so it lives beside the other owned reads and both routers import it
from here.

What counts is narrow on purpose: only evidence-grounded requirements on open,
in-scope roles, at high confidence, above the `context` band, on an active
concept that is not an industry — a business vertical is never a skill.
`ELIGIBLE_REQUIREMENT` holds that rule for every read that counts skills.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Job, JobSkill, SkillConcept
from tracker.db.queries.jobs import exclude_hidden

#: Which of a role's requirements count as its skills, wherever skills are
#: counted: the leaderboard, overlap, the skills that pay, a group's labels and
#: the daily demand rollup. Which roles count (open, in scope, visible) is each
#: read's own. A single posting's requirements (Job detail) keep industries,
#: so that read does not use it.
ELIGIBLE_REQUIREMENT = (
    JobSkill.confidence == "high",
    JobSkill.importance_band != "context",
    SkillConcept.status == "active",
    SkillConcept.facet != "industry",
)


def top_skills_stmt(
    hidden: list[str],
    *,
    company: list[str] | None = None,
    family: list[str] | None = None,
    location_group: list[str] | None = None,
    limit: int = 30,
    narrowed: Sequence = (),
) -> Select:
    """Leaderboard query over evidence-grounded `job_skills`. Only active,
    high-confidence, non-context skill concepts count, and industries are excluded —
    a business vertical is never a skill.
    """
    job_count = func.count(func.distinct(JobSkill.job_id))
    stmt = exclude_hidden(
        select(
            SkillConcept.slug,
            SkillConcept.display,
            SkillConcept.category,
            job_count.label("job_count"),
            func.avg(JobSkill.importance_score).label("avg_importance"),
        )
        .select_from(JobSkill)
        .join(SkillConcept, SkillConcept.id == JobSkill.concept_id)
        .join(Job, Job.id == JobSkill.job_id)
        .where(Job.status == "open", Job.in_scope.is_(True), *ELIGIBLE_REQUIREMENT),
        hidden,
    )
    if company:
        stmt = stmt.where(Job.company.in_(company))
    if family:
        stmt = stmt.where(Job.family.in_(family))
    if location_group:
        stmt = stmt.where(Job.location_groups.overlap(location_group))
    if narrowed:  # an Insights scope's conditions
        stmt = stmt.where(*narrowed)

    return (
        stmt.group_by(SkillConcept.slug, SkillConcept.display, SkillConcept.category)
        .order_by(job_count.desc())
        .limit(limit)
    )


async def top_skills(
    session: AsyncSession,
    hidden: list[str],
    *,
    company: list[str] | None = None,
    family: list[str] | None = None,
    location_group: list[str] | None = None,
    limit: int = 30,
    narrowed: Sequence = (),
) -> list[dict]:
    """Most-emphasized skills across currently-open jobs.

    `job_count` = distinct open jobs with a displayable requirement for the concept.
    """
    stmt = top_skills_stmt(
        hidden, company=company, family=family, location_group=location_group, limit=limit,
        narrowed=narrowed,
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "term": slug,
            "display": display,
            "category": category,
            "job_count": jc,
        }
        for slug, display, category, jc, _importance in rows
    ]



async def skill_role_counts(
    session: AsyncSession, hidden: list[str], conds: Sequence = ()
) -> tuple[dict[str, int], int, dict[str, tuple[str, str]]]:
    """`(roles per concept, roles naming any concept, slug -> (display, category))`
    over the eligible requirements of `top_skills_stmt`, narrowed by `conds`.

    The denominator is the roles with at least one named skill, not every open
    role, so a company whose postings are not read yet is not read as one whose
    roles ask for nothing."""
    eligible = [Job.status == "open", Job.in_scope.is_(True), *ELIGIBLE_REQUIREMENT, *conds]
    base = (
        select(SkillConcept.slug, SkillConcept.display, SkillConcept.category, JobSkill.job_id)
        .select_from(JobSkill)
        .join(SkillConcept, SkillConcept.id == JobSkill.concept_id)
        .join(Job, Job.id == JobSkill.job_id)
        .where(*eligible)
    )
    base = exclude_hidden(base, hidden).subquery()
    rows = (
        await session.execute(
            select(base.c.slug, base.c.display, base.c.category, func.count(func.distinct(base.c.job_id)))
            .group_by(base.c.slug, base.c.display, base.c.category)
        )
    ).all()
    roles = await session.scalar(select(func.count(func.distinct(base.c.job_id)))) or 0
    counts = {slug: int(n) for slug, _, _, n in rows}
    meta = {slug: (display, category) for slug, display, category, _ in rows}
    return counts, int(roles), meta
