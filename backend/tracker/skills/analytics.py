"""Skills analytics: daily demand rollup + the pure trend/overlap transforms.

`compute_skill_demand` snapshots, per (company × family × concept), how many currently
open jobs carry a displayable requirement for that concept, into `skill_demand_daily`
(the Trends series). `build_trend_series` and `compute_overlap` are pure pivots behind
the Trends and Overlap endpoints — table-agnostic; they operate on rows the API feeds
them. Industries are excluded everywhere here: a business vertical is never a skill.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Job, JobSkill, SkillConcept, SkillDemandDaily
from tracker.db.queries.skills import ELIGIBLE_REQUIREMENT


async def compute_skill_demand(session: AsyncSession) -> int:
    """Recompute today's skill-demand slices from `job_skills`. Returns slices written.

    Counts a distinct open, in-scope job once per (company, family, concept) when it
    has an eligible requirement for that concept (`ELIGIBLE_REQUIREMENT`), the same
    rule as `/api/skills/top`. Summing `job_count` across a concept's
    slices never double-counts (a job has one company+family). REPLACES today's
    slices: a slice whose last posting left is gone from today, not
    kept at its old count. Earlier days are untouched.
    """
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    rows = (
        await session.execute(
            select(
                Job.company,
                Job.family,
                JobSkill.concept_id,
                func.count(func.distinct(JobSkill.job_id)).label("job_count"),
            )
            .select_from(JobSkill)
            .join(SkillConcept, SkillConcept.id == JobSkill.concept_id)
            .join(Job, Job.id == JobSkill.job_id)
            .where(Job.status == "open", Job.in_scope.is_(True), *ELIGIBLE_REQUIREMENT)
            .group_by(Job.company, Job.family, JobSkill.concept_id)
        )
    ).all()

    await session.execute(delete(SkillDemandDaily).where(SkillDemandDaily.metric_date == today))
    if rows:
        await session.execute(
            insert(SkillDemandDaily),
            [
                {"metric_date": today, "company": r.company, "family": r.family,
                 "concept_id": r.concept_id, "job_count": r.job_count}
                for r in rows
            ],
        )
    return len(rows)


#: A day whose skill mentions moved by this share against the day before is a
#: change in what is measured (a company set arriving, an extraction re-run),
#: not in demand, and is marked on the axis.
SET_CHANGE = 0.3


def build_trend_series(
    rows: Iterable[tuple[str, str, int]],
    *,
    terms: Sequence[str] | None = None,
    limit: int = 8,
    exclude: Collection[str] = (),
) -> tuple[list[str], list[dict]]:
    """Pivot dated (date, term, count) rows into a shared date axis + aligned series.

    Pure transform behind `GET /api/skills/trends`. `rows` are (date_iso, term,
    count) where `term` is a concept slug, EVERY concept of each day (the shares
    are over the day's whole). Returns `(dates, series)` where `dates` is the
    sorted union of all dates seen and each series' `points` are 0-filled across
    that axis (so sparklines need no gap handling). When `terms` is given those
    exact slugs are returned in order; otherwise the top `limit` by most-recent
    count, leaving out `exclude` (the competencies).

    Each point carries its `share` of the day's skill mentions: the
    raw count moves with whatever is measured, so a company set arriving or a
    re-extraction would read as a surge in demand.
    `current`/`delta` are the counts at the window's ends, kept for the ledger's
    roles; `current_share`/`share_delta` are the normalised reading.
    """
    rows = list(rows)
    dates: set[str] = set()
    by_term: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    for date_iso, term, count in rows:
        dates.add(date_iso)
        by_term.setdefault(term, {})[date_iso] = int(count)
        totals[date_iso] = totals.get(date_iso, 0) + int(count)
    axis = sorted(dates)
    latest = axis[-1] if axis else ""

    if terms is not None:
        chosen = [t for t in terms if t in by_term]
    else:
        chosen = sorted(
            (t for t in by_term if t not in exclude), key=lambda t: by_term[t].get(latest, 0), reverse=True
        )[:limit]

    series: list[dict] = []
    for t in chosen:
        counts = by_term[t]
        points = [
            {
                "date": d,
                "job_count": counts.get(d, 0),
                "share": round(counts.get(d, 0) / totals[d], 4) if totals.get(d) else 0.0,
            }
            for d in axis
        ]
        current = points[-1]["job_count"] if points else 0
        first = points[0]["job_count"] if points else 0
        current_share = points[-1]["share"] if points else 0.0
        first_share = points[0]["share"] if points else 0.0
        series.append({
            "term": t, "current": current, "delta": current - first,
            "current_share": current_share, "share_delta": round(current_share - first_share, 4),
            "points": points,
        })
    return axis, series


def set_changes(rows: Iterable[tuple[str, str, int]], threshold: float = SET_CHANGE) -> list[str]:
    """Days whose total skill mentions moved by `threshold` or more against the
    day before: the measured set changed there. Pure."""
    totals: dict[str, int] = {}
    for date_iso, _term, count in rows:
        totals[date_iso] = totals.get(date_iso, 0) + int(count)
    days = sorted(totals)
    return [
        d for prev, d in zip(days, days[1:], strict=False)
        if totals[prev] and abs(totals[d] / totals[prev] - 1) >= threshold
    ]


def compute_overlap(
    skill_sets: Mapping[str, Mapping[str, int]],
    ranked: Sequence[str],
    roles: Mapping[str, int] | None = None,
) -> list[dict]:
    """Pairwise cross-company skill similarity for the companies in `ranked` order.

    Pure transform behind `GET /api/skills/overlap`. `skill_sets` maps company ->
    {concept slug: roles naming it}; `roles` maps company -> its open roles (the
    largest count stands in when absent). Each company is a vector of its
    skills' role shares weighted by inverse document frequency across the
    compared companies, `ln((1 + C) / (1 + df))`, so a skill every company names
    weighs nothing, and `similarity` is the cosine of two vectors.
    Jaccard over the raw skill sets would score the shared generic skills as
    the overlap. `shared`/`union` still count the sets; `top_shared_terms` are the shared skills weighing most in both.
    Pairs with no shared skill are omitted; `a` precedes `b` in `ranked` order.
    """
    companies = len(ranked)
    df: Counter[str] = Counter()
    for c in ranked:
        df.update(skill_sets.get(c, {}).keys())
    idf = {t: math.log((1 + companies) / (1 + n)) for t, n in df.items()}

    def vector(c: str) -> dict[str, float]:
        counts = skill_sets.get(c, {})
        denom = (roles or {}).get(c) or max(counts.values(), default=1)
        return {t: (n / denom) * idf.get(t, 0.0) for t, n in counts.items()}

    vectors = {c: vector(c) for c in ranked}
    norms = {c: math.sqrt(sum(w * w for w in v.values())) for c, v in vectors.items()}
    pairs: list[dict] = []
    for i in range(len(ranked)):
        for j in range(i + 1, len(ranked)):
            a, b = ranked[i], ranked[j]
            va, vb = vectors[a], vectors[b]
            shared = set(va) & set(vb)
            if not shared:
                continue
            dot = sum(va[t] * vb[t] for t in shared)
            norm = norms[a] * norms[b]
            top_shared = sorted(shared, key=lambda t: (-(va[t] * vb[t]), t))[:5]
            pairs.append(
                {
                    "a": a,
                    "b": b,
                    "shared": len(shared),
                    "union": len(set(va) | set(vb)),
                    "similarity": round(dot / norm, 3) if norm else 0.0,
                    "top_shared_terms": top_shared,
                }
            )
    return pairs


def seriate(ranked: Sequence[str], pairs: Iterable[Mapping]) -> list[str]:
    """`ranked` reordered so similar companies sit side by side. Pure.

    Greedy nearest neighbour from the company most similar to the rest: a
    heatmap in this order shows its blocks; in volume order it is noise."""
    sim: dict[tuple[str, str], float] = {}
    for p in pairs:
        sim[(p["a"], p["b"])] = sim[(p["b"], p["a"])] = float(p["similarity"])
    left = list(ranked)
    if len(left) < 3:
        return left
    current = max(left, key=lambda c: (sum(sim.get((c, o), 0.0) for o in left if o != c), -left.index(c)))
    order = [current]
    left.remove(current)
    while left:
        current = max(left, key=lambda c: (sim.get((order[-1], c), 0.0), -ranked.index(c)))
        order.append(current)
        left.remove(current)
    return order


#: Skill categories that name what a role is expected to do, not a skill that
#: tells one role from another (Roadmapping, Stakeholder Management,
#: Cross-functional Collaboration, Mentorship). They are the most-named
#: concepts, so a ranking by count would say "roles need roadmapping" for
#: every slice. They are listed apart, never ranked with Python or Kubernetes.
COMPETENCY_CATEGORIES: frozenset[str] = frozenset({"process", "leadership", "collaboration"})

#: Prior strength, in roles, of the informative Dirichlet prior (Monroe,
#: Colaresi & Quinn 2008, "Fightin' Words"): a slice's share is shrunk toward
#: the market's by this many pseudo-roles, so 2 of 3 roles cannot read as a
#: skill 20 times as characteristic as the market.
PRIOR_ROLES = 20.0
#: A skill named by fewer roles in the slice is never ranked as distinctive.
MIN_DISTINCTIVE_ROLES = 3


def rank_skills(
    slice_counts: Mapping[str, int],
    slice_roles: int,
    market_counts: Mapping[str, int],
    market_roles: int,
    meta: Mapping[str, tuple[str, str]],
    *,
    narrowed: bool,
    limit: int = 30,
) -> dict:
    """Skills of a slice by how characteristic they are of it. Pure.

    `slice_counts` / `market_counts`: concept slug -> roles naming it, in the
    slice and in the whole market; `slice_roles` / `market_roles`: roles with
    at least one named skill (the denominators, so extraction coverage is not
    read as demand); `meta`: slug -> (display, category).

    Each concept carries its `share` of the slice's roles, its `market_share`,
    `lift` (the ratio) and `distinctiveness`: the z-score of the smoothed
    log-odds difference between the slice and the rest of the market, with an
    informative Dirichlet prior of `PRIOR_ROLES` pseudo-roles at the market's
    rate. A narrowed slice ranks skills by distinctiveness (among those named by
    `MIN_DISTINCTIVE_ROLES` roles or more, then the rest by share); the whole
    market, whose lift is 1 everywhere, ranks by share. Competencies
    (`COMPETENCY_CATEGORIES`) are returned apart, by share.
    """
    rest_roles = max(0, market_roles - slice_roles)
    rows = []
    for slug, n in slice_counts.items():
        if n <= 0 or slice_roles <= 0:
            continue
        display, category = meta.get(slug, (slug, ""))
        m = market_counts.get(slug, n)
        share = n / slice_roles
        market_share = m / market_roles if market_roles else share
        z = 0.0
        if narrowed and rest_roles > 0 and market_share > 0:
            prior = PRIOR_ROLES * market_share
            rest_n = max(0, m - n)
            a = (n + prior) / (slice_roles + PRIOR_ROLES)
            b = (rest_n + prior) / (rest_roles + PRIOR_ROLES)
            a, b = min(a, 1 - 1e-9), min(b, 1 - 1e-9)
            delta = math.log(a / (1 - a)) - math.log(b / (1 - b))
            z = delta / math.sqrt(1 / (n + prior) + 1 / (rest_n + prior))
        rows.append({
            "term": slug,
            "display": display,
            "category": category,
            "job_count": n,
            "share": round(share, 4),
            "market_share": round(market_share, 4),
            "lift": round(share / market_share, 2) if market_share else None,
            "distinctiveness": round(z, 2),
        })

    def by_share(r: dict) -> tuple:
        return (-r["job_count"], r["term"])

    competencies = sorted((r for r in rows if r["category"] in COMPETENCY_CATEGORIES), key=by_share)
    skills = [r for r in rows if r["category"] not in COMPETENCY_CATEGORIES]
    if narrowed:
        ranked = sorted(
            skills,
            key=lambda r: (r["job_count"] < MIN_DISTINCTIVE_ROLES, -r["distinctiveness"], *by_share(r)),
        )
    else:
        ranked = sorted(skills, key=by_share)
    return {
        "items": ranked[:limit],
        "competencies": competencies[:limit],
        "roles": slice_roles,
        "market_roles": market_roles,
        "narrowed": narrowed,
    }
