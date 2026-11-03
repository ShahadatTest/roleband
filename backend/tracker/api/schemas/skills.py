"""Response contracts for the skills and cluster routes.

`GET /api/skills/top`, `/api/skills/trends`, `/api/skills/overlap`, `/api/clusters`
and `/api/clusters/{cluster_id}`.

- Shapes the handlers and `skills.analytics` build forbid unknown keys, declared
  in the order they are written. A cluster's top terms are read back from
  `clusters.top_terms` (JSONB) as the clustering pass stored them, so
  `ClusterTerm` admits a key it does not name and declares its keys in the order
  Postgres serves a JSONB object: shorter keys first (`term`, `weight`, `display`).
- A trend point and a leaderboard count are integers; a skill's specificity, a
  pair's similarity and a term's weight are rounded floats.
- Companies, concept slugs, families and categories stay `str`: database strings.
  One key set per route, so no unions.
"""

from __future__ import annotations

from pydantic import Field

from tracker.api.schemas.base import Built, Stored
from tracker.api.schemas.jobs import JobRow
from tracker.api.schemas.text_class import text


class TopSkill(Built):
    """A concept in a slice of open roles: how many roles name it, its
    share of the slice's roles and of the market's, the ratio, and how
    characteristic of the slice it is (`skills.analytics.rank_skills`)."""

    term: str
    category: str
    job_count: int
    share: float
    market_share: float
    lift: float | None
    #: z-score of the smoothed log-odds, slice against the rest of the market; 0
    #: for the whole market.
    distinctiveness: float


class TopSkillsResponse(Built):
    """`GET /api/skills/top`: a narrowed slice by distinctiveness, the whole market
    by share; competencies apart; industries and deprecated concepts never appear."""

    items: list[TopSkill]
    #: Process, leadership and collaboration concepts: what roles expect, listed apart.
    competencies: list[TopSkill]
    #: Roles naming any skill, in the slice and in the whole market.
    roles: int
    market_roles: int
    narrowed: bool


class SkillTrendPoint(Built):
    date: str
    job_count: int
    #: Of the day's skill mentions.
    share: float


class SkillTrendSeries(Built):
    """One skill over the shared axis, zero on a day without a slice."""

    term: str
    current: int
    delta: int
    current_share: float
    share_delta: float
    points: list[SkillTrendPoint]


class SkillTrendsResponse(Built):
    """`GET /api/skills/trends`. `days <= 0` is all history."""

    days: int
    dates: list[str]
    series: list[SkillTrendSeries]
    #: Days the measured set changed (mentions moved 30% or more in a day): a
    #: company set arriving or a re-extraction, never demand.
    set_changes: list[str]


class OverlapCompany(Built):
    company: str
    skill_count: int
    open: int


class OverlapPair(Built):
    """Two companies sharing at least one skill; `a` precedes `b` in the order shown."""

    a: str
    b: str
    shared: int
    union: int
    #: Cosine of the two companies' skill vectors, each skill a role share weighted
    #: by rarity across the companies compared, 0 to 1.
    similarity: float
    #: Slugs of the skills both name most, which the client names.
    top_shared: list[str]


class SkillOverlapResponse(Built):
    """`GET /api/skills/overlap`: the floor a skill must clear per company, echoed."""

    companies: list[OverlapCompany]
    pairs: list[OverlapPair]
    min_jobs: int


class ClusterTerm(Stored):
    """A characteristic skill of a cluster's members, as the clustering pass stored it."""

    term: str
    weight: float


class ClusterSummary(Built):
    """A cluster with its company mix. With companies hidden, `size` counts the visible mix."""

    id: int
    family_hint: str | None = Field(json_schema_extra=text("code"))
    size: int
    top_terms: list[ClusterTerm]
    companies: dict[str, int]


class ClusterListResponse(Built):
    """`GET /api/clusters`: largest first; `model_version` is null with no clusters."""

    items: list[ClusterSummary]
    model_version: str | None


class ClusterDetailResponse(Built):
    """`GET /api/clusters/{cluster_id}`: the open members, most central first, as list rows."""

    id: int
    family_hint: str | None = Field(json_schema_extra=text("code"))
    size: int
    top_terms: list[ClusterTerm]
    items: list[JobRow]
