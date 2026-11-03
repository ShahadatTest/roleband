"""Response contracts for the statistics and demand routes.

`GET /api/stats`, the Statistics overview, compensation, stock trajectory, equity
validation, the comp and disclosure trends, the level guide, and `/api/demand`. The velocity route
declares its own models beside its handler.

- **Every shape here is one our code builds**, so every model forbids unknown
  keys, declared in the order the builders write them. A row that names its
  group before its figures (`{"company": ..., **summary}`) is built from a key
  mixin listed LAST among the bases: Pydantic collects the last base's fields
  first.
- **Numbers keep the type the builders give them.** Percentiles are linear
  interpolations and always floats, even over one value; counts, dollars and
  histogram edges are integers; shares and rates are rounded floats.
- **Literals where our code owns the vocabulary**: the trend dimensions each
  handler accepts, the split and bonus sources `analytics.comp_split` and
  `comp_residual` name, the pooled disclosure basis, and the `USD` the payloads
  state. Companies, level bands and families stay `str`: they are database strings.
- One key set per route, so no unions. A disclosure-trend point for a day a
  series has no cell is assembled with `date` last, and arrives with `date`
  first like every other point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field
from pydantic.json_schema import SkipJsonSchema

from tracker.api.schemas.base import Built
from tracker.api.schemas.jobs import JobRow
from tracker.api.schemas.plugins import ReferenceChangeView
from tracker.api.schemas.text_class import text

# Held to their sources by `tests/test_api_statistics_contract.py`.
CompTrendDim = Literal["overall", "company", "level", "family"]
DisclosureTrendDim = Literal["overall", "company", "level"]
SplitSource = Literal["measured", "heuristic", "mixed"]
ModelSource = Literal["measured", "heuristic"]
BonusSource = Literal["stated", "modeled"]


class _CompanyKey(Built):
    company: str


class _LevelBandKey(Built):
    level_band: str


class _FamilyKey(Built):
    family: str


# --------------------------------------------------------------------------- #
# `GET /api/stats` and the overview
# --------------------------------------------------------------------------- #


class StatsResponse(Built):
    """The header counts. "Today" starts at the user's local midnight."""

    open_total: int
    #: The roles the Board lights as new (`queries.jobs.new_listing_clause`):
    #: listed in the last `NEW_LISTING_DAYS` days, whatever the field's name.
    new_today: int
    reposted_today: int
    closed_today: int
    saved_total: int
    review_pending: int
    notif_unread: int
    #: Unread high-priority notifications: the bell turns red while any are.
    notif_high_unread: int
    by_company: dict[str, int]


class OverviewKpis(Built):
    open_total: int
    #: Roles first seen in the window that opened while their company was
    #: read, not reposts, never a first read's finds.
    new_count: int
    #: Roles a company's first read found in the window: already listed then
    #: (`schema.Arrival`).
    first_scan_count: int
    closed_count: int
    companies: int
    saved_total: int


class OverviewSkill(Built):
    term: str
    category: str
    job_count: int


class OverviewCluster(Built):
    id: int
    #: The role group most members share; null when none does.
    family_hint: str | None = Field(json_schema_extra=text("code"))
    #: Up to three skill slugs that name it, strongest first.
    terms: list[str]
    size: int


class OverviewHardest(Built):
    """The open role listed the longest, by the age one posting shows."""

    id: int
    title: str = Field(json_schema_extra=text("content"))
    company: str
    #: The row's own `listed_days` (serialize_job), never our first-sighting clock.
    listed_days: int | None


class StatisticsOverviewResponse(Built):
    """`GET /api/statistics/overview`. `days <= 0` is all-time. The one-line
    brief is the dashboard's, said from these facts."""

    days: int
    kpis: OverviewKpis
    top_skills: list[OverviewSkill]
    top_clusters: list[OverviewCluster]
    #: The three open roles listed longest, plausible ages only.
    longest_open: list[OverviewHardest]


# --------------------------------------------------------------------------- #
# Compensation
# --------------------------------------------------------------------------- #


class CompCoverage(Built):
    with_comp: int
    total_open: int
    pct: float


class CompSummary(Built):
    """`comp_stats._summary`: dollars at the ends, interpolated percentiles between."""

    count: int
    min: int
    max: int
    p25: float
    p50: float
    p75: float
    p90: float


class CompHistogramBin(Built):
    lo: int
    hi: int
    count: int


class CompLevelSummary(CompSummary, _LevelBandKey):
    """`level_band` first, then the summary."""


class CompCompanySummary(CompSummary, _CompanyKey):
    """`company` first, then the summary."""


class CompFamilySummary(CompSummary, _FamilyKey):
    """`family` first, then the summary; the client names the family."""


class CompSkill(Built):
    """A skill named by enough priced roles; `premium` is what they pay over like
    roles, same level and discipline; `count` is the roles behind it."""

    term: str
    count: int
    p50: float
    premium: float


class DisclosedBand(Built):
    company: str
    level_band: str
    low: int
    high: int
    reqs: int


class DisclosedExclusions(Built):
    unclear: int
    total: int
    #: Base bands in another currency; the axis is US dollars, nothing is converted.
    not_usd: int
    #: Base bands stated per hour or month, or whose period reads `unclear`.
    not_yearly: int
    implausible: int


class DisclosedBands(Built):
    """Distinct base-salary bands employers printed, with the reqs on each."""

    bands: list[DisclosedBand]
    reqs: int
    companies: int
    excluded: DisclosedExclusions
    truncated: bool


class DisclosureCounts(Built):
    """`rate` is `disclosed / checked`, null while nothing in the group is checked."""

    open: int
    checked: int
    disclosed: int
    rate: float | None


class DisclosureCompany(DisclosureCounts, _CompanyKey):
    """`company` first, then the counts."""


class DisclosureLevel(DisclosureCounts, _LevelBandKey):
    """`level_band` first (`""` when unclassified), then the counts."""


class DisclosureRates(Built):
    overall: DisclosureCounts
    by_company: list[DisclosureCompany]
    by_level: list[DisclosureLevel]


class BaseCoverage(Built):
    """How many open roles have an estimated base only, of all open ones."""

    with_base: int
    total_open: int


class BaseEstimates(Built):
    """Roles priced by their base alone (`comp_component = "base"`): no total exists,
    so they are summarised apart from the totals and never on their axis."""

    min_roles: int
    coverage: BaseCoverage
    overall: CompSummary | None
    by_level: list[CompLevelSummary]
    by_company: list[CompCompanySummary]
    by_family: list[CompFamilySummary]


class CompensationStatsResponse(Built):
    """`GET /api/statistics/compensation`: the estimate's spread beside what employers printed.

    A snapshot of the roles open now: no window. The Window lens moves
    the trend routes beside it, never this population."""

    #: The fewest priced roles a level, company or discipline needs.
    min_roles: int
    coverage: CompCoverage
    overall: CompSummary | None
    histogram: list[CompHistogramBin]
    by_level: list[CompLevelSummary]
    by_company: list[CompCompanySummary]
    by_family: list[CompFamilySummary]
    by_skill: list[CompSkill]
    disclosed: DisclosedBands
    disclosure: DisclosureRates
    base_estimates: BaseEstimates
    currency: Literal["USD"]


# --------------------------------------------------------------------------- #
# Stock trajectory and equity validation
# --------------------------------------------------------------------------- #


class EquityAssumptions(Built):
    """`comp_split.equity_assumptions`: the heuristic's knobs, by level band."""

    bonus_pct: float
    equity_by_band: dict[str, float]


class CompPackage(Built):
    """A median package: base, bonus and equity always sum to `median_tc`."""

    count: int
    median_tc: int
    base: int
    bonus: int
    equity: int
    equity_pct: float
    split_source: SplitSource


class TrajectoryPrivateCompany(CompPackage, _CompanyKey):
    """`company` first, then its package and equity vehicle."""

    equity_vehicle: str | None


class TrajectoryPublicCompany(TrajectoryPrivateCompany):
    """A listed company also names its ticker."""

    ticker: str | None


class CompTrajectoryResponse(Built):
    """`GET /api/statistics/comp-trajectory`."""

    currency: Literal["USD"]
    assumptions: EquityAssumptions
    overall: CompPackage | None
    public: list[TrajectoryPublicCompany]
    private: list[TrajectoryPrivateCompany]


class ImpliedDollars(Built):
    low: int
    mid: int
    high: int


class ImpliedShares(Built):
    low: float
    mid: float
    high: float


class EquityResidualGroup(Built):
    """One (company, band): the equity a stated base implies, against the modeled share."""

    company: str
    band: str
    reqs: int
    bands: int
    comp_medians: list[int]
    implied_equity: ImpliedDollars
    implied_pct: ImpliedShares
    modeled_pct: float
    model_source: ModelSource
    bonus_source: BonusSource
    residual_vs_model_pct: float
    consistent: bool


class EquityResidualCoverage(Built):
    rows: int
    used_reqs: int
    distinct_bands: int
    companies: dict[str, int]


class EquityResidualExclusions(Built):
    basis_not_base: int
    not_usd: int
    not_yearly: int
    stale_version: int
    implausible: int
    #: Rows whose (company, band) the answering plugin's rows do not split: no
    #: modeled share to check them against. Zero while ours answers.
    unsplit: int


class SourceComparisonGroup(Built):
    """An external source's realized equity share for one (company, band), against the model."""

    company: str
    band: str
    n: int
    n_estd: int
    source_eq_share: float
    source_eq_share_estd: float | None
    model_stock_pct: float | None
    delta_estd_vs_model: float | None


class SourceComparisonCoverage(Built):
    observations: int
    bands: int


class ReportedComparison(Built):
    """The latest self-reported snapshot a plugin published, compared with the model;
    `snapshot_date` is null and `sources` empty when no plugin answers."""

    #: The plugins whose observations are compared.
    sources: list[str]
    groups: list[SourceComparisonGroup]
    coverage: SourceComparisonCoverage
    snapshot_date: str | None


class EquityValidationResponse(Built):
    """`GET /api/statistics/equity-validation`."""

    groups: list[EquityResidualGroup]
    coverage: EquityResidualCoverage
    excluded: EquityResidualExclusions
    assumptions: EquityAssumptions
    reported: ReportedComparison


# --------------------------------------------------------------------------- #
# Trends
# --------------------------------------------------------------------------- #


class CompTrendPoint(Built):
    """One day of one series; every percentile null on a day the series has no values."""

    date: str
    p25: float | None
    p50: float | None
    p75: float | None
    p90: float | None


class CompTrendSeries(Built):
    key: str
    count: int
    points: list[CompTrendPoint]


class CompTrendsResponse(Built):
    """`GET /api/statistics/comp-trends`: one aligned series per key over a shared axis."""

    dim: CompTrendDim
    days: int
    dates: list[str]
    series: list[CompTrendSeries]
    #: Reference switches inside the window: drawn as
    #: markers, so a step in the series reads as a change of sources.
    reference_changes: list[ReferenceChangeView]


class DisclosureTrendPoint(Built):
    date: str
    open: int
    checked: int
    disclosed: int
    rate: float | None
    bands: int
    reqs: int
    low_p50: float | None
    high_p50: float | None


class DisclosureTrendSeries(Built):
    key: str
    checked: int
    disclosed: int
    points: list[DisclosureTrendPoint]


class DisclosureCohort(Built):
    """The companies read on the window's first day, which the `cohort` series follows."""

    since: str
    companies: int


class DisclosureTrendsResponse(Built):
    """`GET /api/statistics/disclosure-trends`; band medians pool only `basis`.

    `cohort` is set when the company set changed inside the window: the series
    keyed `cohort` then follows only the companies of its first day."""

    dim: DisclosureTrendDim
    days: int
    basis: Literal["base"]
    dates: list[str]
    series: list[DisclosureTrendSeries]
    cohort: DisclosureCohort | None


# --------------------------------------------------------------------------- #
# `GET /api/demand`
# --------------------------------------------------------------------------- #


class HiringCompany(Built):
    """One company's open roles, a place set once, and its motion."""

    company: str
    open: int
    #: New by the Board's rule (`queries.jobs.new_listing_clause`).
    new_today: int
    closed_today: int


class HiringCountry(Built):
    key: str
    open: int


class HiringRegion(Built):
    """Roles open in a region, each once (`analytics.hiring`)."""

    key: str
    open: int
    #: Of `open`, the roles that name only the region ("Remote - EMEA"), so no
    #: country in it: counted here, never in each country.
    region_wide: int
    countries: list[HiringCountry]


class UpdatedOpenJob(JobRow):
    """A list row, then how often and how recently the posting changed."""

    update_count: int
    last_updated_at: datetime


class DemandResponse(Built):
    """`GET /api/demand`, the Hiring tab: where roles are open now, by company and
    place, today's openings and closings, and the three persistent-role lists.

    Read live from the roles Insights describes, never by summing the
    `demand_metrics` rollup, whose slices count a posting once per place group."""

    open_total: int
    #: New by the Board's rule and in scope, not reposts, a place set once.
    new_today: int
    #: Closed today, a place set once.
    closed_today: int
    companies: list[HiringCompany]
    regions: list[HiringRegion]
    #: Roles whose places name nothing a region holds ("Remote", "Anywhere").
    unplaced: int
    #: Share of the open roles that the employer dated (`analytics.age_basis`).
    #: None when nothing is open.
    employer_dated_share: float | None
    #: Ordered by `listed_days`, the age each row shows, longest first; only
    #: ages within `PLAUSIBLE_LISTING_DAYS`.
    longest_open: list[JobRow]
    #: Open roles listed longer than that: a stale or evergreen date, left out
    #: of `longest_open` and counted here.
    listed_over_a_year: int
    most_reposted: list[JobRow]
    most_updated_open: list[UpdatedOpenJob]


class LevelGuideEntry(Built):
    """One label of the level guide and every spelling of the rungs behind
    it, so a search finds a rung the label hides (66 inside "65–67")."""

    label: str = Field(json_schema_extra=text("content"))
    spellings: list[str] = Field(json_schema_extra=text("content"))


class LevelGuideCell(Built):
    """How one company names one level: one entry for every function, or one
    per track. Exactly one key is present (`response_model_exclude_unset`)."""

    company_wide: LevelGuideEntry | SkipJsonSchema[None] = None
    per_track: dict[str, LevelGuideEntry] | SkipJsonSchema[None] = None


class LevelGuideCompany(Built):
    slug: str
    #: The company's titles state no level beyond these (`Ladder.flat`): a
    #: level with no cell is unstated, not skipped.
    flat: bool
    levels: dict[str, LevelGuideCell]


class LevelGuideUnguided(Built):
    """A company the app names that has no level guide of its own."""

    slug: str
    #: The company whose ladder this one shares (Google DeepMind reads
    #: Google's); null when none does.
    same_as: str | None


class LevelGuideResponse(Built):
    """`GET /api/statistics/levels`: every reviewed ladder, A to Z by slug,
    and the catalog companies without one."""

    companies: list[LevelGuideCompany]
    unguided: list[LevelGuideUnguided]
    #: Track slug -> the levels a role of that track can hold, lowest first
    #: (a manager is never an intern), as the Profile rail gates them.
    tracks: dict[str, list[str]]
