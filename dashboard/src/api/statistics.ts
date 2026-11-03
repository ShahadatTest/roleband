/* Statistics: header counts, demand, the overview, compensation, trends and velocity.
   One domain of the typed client; `index.ts` composes `api`. */

import type { Schemas } from "./schemas";
import { getJSON, qs } from "./transport";

/** What an Insights read is narrowed to: the companies side and the
 *  disciplines, sent as `?side=&family=`. `all` with no family narrows nothing. */
export interface InsightsScope {
  side: "all" | "yours" | "other";
  families: readonly string[];
}

const ALL_SCOPE: InsightsScope = { side: "all", families: [] };

/** `path` with the scope's parameters added; unchanged for a scope that
 *  narrows nothing, so an unscoped request is the plain route. */
export function scoped(path: string, scope: InsightsScope = ALL_SCOPE): string {
  const q = qs({ side: scope.side === "all" ? undefined : scope.side, family: [...scope.families] });
  return q ? `${path}${path.includes("?") ? "&" : "?"}${q}` : path;
}

/** `GET /api/stats`: the header counts. Today's new roles and reposts are counted
 *  apart so the "new signals" chip stays honest; `review_pending` is the review queue. */
export type Stats = Schemas["StatsResponse"];

/** One company on the Hiring tab: open roles, a place set once. */
export type HiringCompany = Schemas["HiringCompany"];
/** Roles open in one region, each once; `region_wide` names only the region. */
export type HiringRegion = Schemas["HiringRegion"];

/** A list row, then how often and how recently the posting changed. */
export type UpdatedOpenJob = Schemas["UpdatedOpenJob"];

/** `GET /api/demand`, the Hiring tab: where roles are open now, by company and
 *  place, each role once, and the persistent-role lists. */
export type Demand = Schemas["DemandResponse"];

export type OverviewKpis = Schemas["OverviewKpis"];
export type OverviewSkill = Schemas["OverviewSkill"];
export type OverviewCluster = Schemas["OverviewCluster"];
export type OverviewHardest = Schemas["OverviewHardest"];

/** `GET /api/statistics/overview`. `days <= 0` is all-time. */
export type StatisticsOverview = Schemas["StatisticsOverviewResponse"];

/** One group of the imputed total-comp estimate: dollars at the ends, interpolated
 *  percentiles between. A group is never empty, so every figure is present. */
export type CompSummary = Schemas["CompSummary"];
export type CompHistBin = Schemas["CompHistogramBin"];
export type CompLevel = Schemas["CompLevelSummary"];
export type CompCompany = Schemas["CompCompanySummary"];
export type CompFamily = Schemas["CompFamilySummary"];
export type CompSkill = Schemas["CompSkill"];

/** One pay band an employer actually printed, plus the open reqs sitting on it. */
export type DisclosedBand = Schemas["DisclosedBand"];

/**
 * Employer-disclosed base-salary bands. Distinct from every other field on
 * `CompensationStats`, which aggregates the *imputed total-comp* estimate — base
 * pay and total comp are different quantities and never share an axis.
 * `excluded.unclear` counts roles whose posting gave a range but never said
 * whether it bundles bonus/equity, so they cannot be placed on a base-pay scale.
 */
export type DisclosedBands = Schemas["DisclosedBands"];

/**
 * How many open roles state pay at all, for one grouping. `rate` is
 * `disclosed / checked` — NOT `disclosed / open`: `open - checked` roles are still
 * queued for the disclosure pass, and folding them in would report our own
 * extraction backlog as employer silence. `rate` is null (never 0) when nothing in
 * the group has been checked yet. Basis-independent; only band values are scoped.
 */
export type DisclosureGroup = Schemas["DisclosureCounts"];
export type DisclosureCompany = Schemas["DisclosureCompany"];
export type DisclosureLevel = Schemas["DisclosureLevel"];
export type DisclosureRates = Schemas["DisclosureRates"];

/** `GET /api/statistics/compensation`. */
export type CompensationStats = Schemas["CompensationStatsResponse"];

/** `GET /api/statistics/levels`: how every reviewed ladder names each level,
 *  followed or not. Reference data, so no scope or window. */
export type LevelGuide = Schemas["LevelGuideResponse"];
export type LevelGuideCompany = Schemas["LevelGuideCompany"];
/** One company's name for one level: `company_wide`, or one entry per track. */
export type LevelGuideCell = Schemas["LevelGuideCell"];
/** The label shown and every spelling of the rungs behind it. */
export type LevelGuideEntry = Schemas["LevelGuideEntry"];

/** A median package whose base, bonus and equity sum to `median_tc`. `split_source`
 *  says whether the split was MEASURED or ESTIMATED; never present a guess as an
 *  observation. */
export type CompPackage = Schemas["CompPackage"];

/** A trajectory company. Only a listed one names its `ticker`, so read it through
 *  `in`. A listed cash election (Netflix) carries ~0% equity and does not move with
 *  its stock at all. */
export type CompTrajectoryCompany = Schemas["TrajectoryPublicCompany"] | Schemas["TrajectoryPrivateCompany"];

/** `GET /api/statistics/comp-trajectory`. */
export type CompTrajectory = Schemas["CompTrajectoryResponse"];

export type CompTrendDim = CompTrends["dim"];
export type CompTrendPoint = Schemas["CompTrendPoint"];
export type CompTrendSeries = Schemas["CompTrendSeries"];

/** `GET /api/statistics/comp-trends`: one aligned series per key over a shared axis. */
export type CompTrends = Schemas["CompTrendsResponse"];

export type DisclosureTrendDim = DisclosureTrends["dim"];

/**
 * One day of pay transparency for one grouping. `rate` follows `DisclosureGroup`
 * (denominated in `checked`). `low_p50` / `high_p50` are the median published band,
 * pooled strictly within the response's `basis` and counted one vote per *distinct*
 * band; `reqs` carries the req count for context.
 */
export type DisclosureTrendPoint = Schemas["DisclosureTrendPoint"];
export type DisclosureTrendSeries = Schemas["DisclosureTrendSeries"];

/** `GET /api/statistics/disclosure-trends`. */
export type DisclosureTrends = Schemas["DisclosureTrendsResponse"];

/* `GET /api/statistics/velocity` wire types are aliases of the generated schemas
   (`VelocityOut` and its rows live beside the handler in `routers/statistics.py`). The window
   totals and each company row count `reposted` as well as opened, updated and closed. */
export type VelocityKpis = Schemas["VelocityKpis"];
export type VelocityAging = Schemas["VelocityAgingBand"];
export type VelocityCompany = Schemas["VelocityCompany"];
export type VelocityStats = Schemas["VelocityOut"];

export const statisticsApi = {
  demand: (scope?: InsightsScope) => getJSON<Demand>(scoped(`/api/demand`, scope)),
  statisticsOverview: (days = 30, scope?: InsightsScope) =>
    getJSON<StatisticsOverview>(scoped(`/api/statistics/overview?days=${days}`, scope)),
  /** The roles open now; no window. The trend routes carry time. */
  compensation: (scope?: InsightsScope) =>
    getJSON<CompensationStats>(scoped(`/api/statistics/compensation`, scope)),
  compTrajectory: (signal?: AbortSignal) =>
    getJSON<CompTrajectory>("/api/statistics/comp-trajectory", signal),
  levelGuide: (signal?: AbortSignal) => getJSON<LevelGuide>("/api/statistics/levels", signal),
  compTrends: (dim: CompTrendDim = "overall", days = 90, scope?: InsightsScope) =>
    getJSON<CompTrends>(scoped(`/api/statistics/comp-trends?dim=${dim}&days=${days}`, scope)),
  disclosureTrends: (dim: DisclosureTrendDim = "overall", days = 90, scope?: InsightsScope) =>
    getJSON<DisclosureTrends>(scoped(`/api/statistics/disclosure-trends?dim=${dim}&days=${days}`, scope)),
  velocity: (days = 30, scope?: InsightsScope) =>
    getJSON<VelocityStats>(scoped(`/api/statistics/velocity?days=${days}`, scope)),
};
