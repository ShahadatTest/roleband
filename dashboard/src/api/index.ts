// Typed client for the tracker API (proxied to the FastAPI backend).
//
// Wire types for routes that declare a response model are DERIVED from
// `api.gen.ts`, which is generated from the server's OpenAPI schema — never
// restated here. Change the Pydantic model, regenerate (backend
// `scripts.export_openapi`, then `npm run gen:api`), and every consumer that
// disagrees stops compiling. `src/test/api-contract.types.ts` checks the
// client returns exactly what those operations declare. The hand-written interfaces left in
// the domain modules are client-side query and view types, or describe a
// route that still returns an unmodelled dict.
//
// The client is split by domain: each module under this directory
// holds its routes' wire types and methods, `transport.ts` the request
// boundary, and this file composes the one `api` object every screen calls.
// Importers write `../api`.

import { jobsApi } from "./jobs";
import { opsApi } from "./ops";
import { statisticsApi } from "./statistics";
import { skillsApi } from "./skills";
import { lineageApi } from "./lineage";
import { companiesApi } from "./companies";
import { notificationsApi } from "./notifications";
import { scopeApi } from "./scope";
import { intelligenceApi } from "./intelligence";
import { profileApi } from "./profile";
import { recipesApi } from "./recipes";
import { usageApi } from "./usage";
import { pluginsApi } from "./plugins";
import { startupApi } from "./startup";

export const api = {
  ...startupApi,
  ...jobsApi,
  ...opsApi,
  ...statisticsApi,
  ...skillsApi,
  ...lineageApi,
  ...companiesApi,
  ...notificationsApi,
  ...scopeApi,
  ...intelligenceApi,
  ...profileApi,
  ...recipesApi,
  ...usageApi,
  ...pluginsApi,
};

export { ApiError, isNotFound } from "./transport";
export { DEFAULT_FILTERS } from "./jobs";
export { PRICE_FEED_KEY_URL } from "./companies";
export type {
  CompComponent, CompProvenance, CompSource, CompareSelection, DisclosedComp, DismissResult,
  Facets, Filters, ImportanceBand, Job, JobCompPackage, JobCompPolicy, JobCompReconciliation,
  JobDescriptionSection, JobDetail, JobDetailRow, JobList, JobQualification, JobRequirements,
  JobSkill, JobSkillEvidence, JobSort, JobViewResult, LifecycleEvent, ListingEvent, ListingHistory, ParsedQuery,
  RelevanceReview, RequirementModality, SimilarJob, SimilarJobs, SortOrder,
} from "./jobs";
export type {
  ScheduleBinding, SchedulePlan, SchedulePlanUpdate, ScheduleProvider, ScheduleTimeUpdate, ScheduleUpcomingRun,
  ScheduleWindow, SourceOutcome, SyncCancelResult, SyncResult,
  SyncSchedule, SyncTarget, SyncTargets, SystemStatus,
} from "./ops";
export type {
  CompCompany, CompFamily, CompHistBin, CompLevel, CompPackage, CompSkill, CompSummary,
  CompTrajectory, CompTrajectoryCompany, CompTrendDim, CompTrendPoint, CompTrendSeries, CompTrends,
  CompensationStats, Demand, InsightsScope, DisclosedBand, LevelGuide, LevelGuideCell, LevelGuideCompany, LevelGuideEntry, DisclosedBands, DisclosureCompany, HiringCompany, HiringRegion,
  DisclosureGroup, DisclosureLevel, DisclosureRates, DisclosureTrendDim, DisclosureTrendPoint,
  DisclosureTrendSeries, DisclosureTrends, OverviewCluster, OverviewHardest, OverviewKpis,
  OverviewSkill, StatisticsOverview, Stats, UpdatedOpenJob, VelocityAging, VelocityCompany,
  VelocityKpis, VelocityStats,
} from "./statistics";
export type {
  ClusterDetail, ClusterList, ClusterSummary, ClusterTerm, OverlapCompany, OverlapPair,
  SkillSeries, SkillTrends, SkillsOverlap, SkillsQuery, TopSkill, TopSkills, TrendPoint,
  TrendsQuery,
} from "./skills";
export type {
  DecidedQuery, DecidedReviewItem, DescriptionDiffEvidence, DuplicateLLMAssessment, DuplicateProposal,
  DuplicateReviewItem, DuplicateReviewList, DuplicateReviewSummaryList, DuplicateVerdictResult,
  LineageDetail, LineageDiff, LineageLink,
  LineageMember, LineageReviewItem, LineageVerdict, PlaceSetDecision,
  PlaceSetDetail, PlaceSetMember, TwinDetail, TwinMember,
  TwinProposal, TwinReviewItem, TwinReviewList, TwinReviewSummaryList, TwinVerdict, TwinVerdictResult,
} from "./lineage";
export type {
  AddCompanyPayload, BoardSearch, CompanyBenefitGroup, CompanyBenefitItem, CompanyCard,
  CompanyCompLevel, CompanyConnectorState, CompanyConsent, CompanyDirectoryMatch, CompanyDirectorySearch, CompanyDirectoryStatus,
  CompanyDiscoveryCompany, CompanyDiscoverySector,
  CompanyDiscoveryState, CompanyList, CompanyLocation, CompanyNames, CompanyOpenCounts, CompanyPrices,
  CompanyProfileDetail, CompanyProfileFieldWrite, CompanyProfileList, CompanyProfileSummary,
  DataHealth, FieldCandidate, FieldConflict, Freshness, PriceBar, PriceFeedState, ProfileField, ReviewItem,
  MovedBoard, ReviewReason, TrackedCompany,
} from "./companies";
export type { Notification, NotificationList, NotificationParams } from "./notifications";
export type {
  DecoderCell, LocaleSettings, ProfileState, RetentionChoice, RetentionState, RetentionUpdate,
  PlaceResult, PlaceSearch, ScopeAxes, ScopeCatalog, ScopeCatalogCompany, ScopePreview, ScopeCategory, ScopeCells,
  ScopeDomain, ScopeLevel, ScopeLocation, ScopeRefreshResult, ScopeRoleGroup, ScopeRule, UnionResult,
  ScopeRulePayload, ScopeSettingsPayload, ScopeSettingsSaveResult, ScopeTrack,
  StoredPersonaProfile,
} from "./scope";
export type {
  AgentAccessState, CloudLLMProfile, CloudLLMProfileInput, CloudLLMState, CloudLLMTestResult,
  IntelligenceAvailability, IntelligenceExtracted, IntelligenceFit, IntelligenceFitBand,
  IntentStatementResult,
  IntelligenceFitBandPreview, IntelligenceRouting, IntelligenceStatus, IntelligenceTestResult,
  IntelligenceTier, LocalLLMMetrics, LocalLLMParameters, LocalLLMProfile, LocalLLMProfileInput,
  LocalLLMState, LocalLLMTestResult, LocalServerControlResult, LocalServerStatus, MatchingStatus,
  MatchingStopResult, MatchingTier, MatchingTierOption, ProviderOrigin,
} from "./intelligence";
export type {
  PayFloor, ProfileSuggestion, ProfileSuggestionBasis, PursuitInfo, PursuitListItem, PursuitStage,
} from "./profile";
export type {
  RecipeBinding, RecipeCheck, RecipeDetail, RecipeList, RecipePreviewJob, RecipeRevision,
  RecipeSummary, SavedRecipeVersion,
} from "./recipes";
export type {
  UsageConsent, UsageGroup, UsageGroupState, UsagePreview, UsageSent, UsageState, UsageStatus,
} from "./usage";
export type {
  CapabilityView, PluginActionResult, PluginApproval, PluginDetail, PluginRefreshResult, PluginRemoveDataResult,
  PluginRobots, PluginRobotsSite, PluginRunOutcome, PluginRunView, PluginSchedule, PluginSlot, PluginView,
  PluginsResponse, ReferenceView,
} from "./plugins";
