/* Skills: the leaderboard, trends, overlap and clusters.
   One domain of the typed client; `index.ts` composes `api`. */

import type { Schemas } from "./schemas";
import { qs, getJSON } from "./transport";
import { type InsightsScope, scoped } from "./statistics";

/** A cluster's characteristic skill, as the clustering pass stored it. */
export type ClusterTerm = Schemas["ClusterTerm"];

/** A cluster with its visible company mix; `size` counts that mix once a company is hidden. */
export type ClusterSummary = Schemas["ClusterSummary"];

export type ClusterList = Schemas["ClusterListResponse"];

/** A cluster's open members, most central first. */
export type ClusterDetail = Schemas["ClusterDetailResponse"];

export type TrendPoint = Schemas["SkillTrendPoint"];

export type SkillSeries = Schemas["SkillTrendSeries"];

export type SkillTrends = Schemas["SkillTrendsResponse"];

export type OverlapCompany = Schemas["OverlapCompany"];

export type OverlapPair = Schemas["OverlapPair"];

export type SkillsOverlap = Schemas["SkillOverlapResponse"];

export interface TrendsQuery {
  company?: string[];
  family?: string[];
  term?: string[];
  days?: number;
  limit?: number;
}

/** A concept by the open roles requiring it; `specificity` is their mean importance, 0 to 1. */
export type TopSkill = Schemas["TopSkill"];

export type TopSkills = Schemas["TopSkillsResponse"];

export interface SkillsQuery {
  company?: string[];
  family?: string[];
  location_group?: string[];
  limit?: number;
}

export const skillsApi = {
  skillsTop: (q: SkillsQuery = {}, signal?: AbortSignal, scope?: InsightsScope) =>
    getJSON<TopSkills>(scoped(`/api/skills/top?${qs(q)}`, scope), signal),
  skillTrends: (q: TrendsQuery = {}, scope?: InsightsScope) =>
    getJSON<SkillTrends>(scoped(`/api/skills/trends?${qs(q)}`, scope)),
  skillsOverlap: (
    minJobs = 2, limitCompanies = 12, signal?: AbortSignal, scope?: InsightsScope, companies: readonly string[] = [],
  ) =>
    getJSON<SkillsOverlap>(
      scoped(`/api/skills/overlap?${qs({ min_jobs: minJobs, limit_companies: limitCompanies, company: [...companies] })}`, scope),
      signal,
    ),
  clusters: (scope?: InsightsScope) => getJSON<ClusterList>(scoped(`/api/clusters`, scope)),
  cluster: (id: number) => getJSON<ClusterDetail>(`/api/clusters/${id}`),
};
