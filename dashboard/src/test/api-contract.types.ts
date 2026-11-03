/* Compile-time contract checks for the modelled routes: jobs, scope,
   settings and profile, tracked companies, profile suggestions,
   notifications, the status and sync routes, the lineage and twin routes, the
   plugin routes (`PluginRouteContract`), the AI settings, matching, self-test,
   fit and agent routes, the local and cloud model connection routes, the
   company-profile routes and company card, the statistics and demand routes,
   the skills and cluster routes, the pursuit routes, the similar-postings and
   facets routes, the connector schedule read and move, and the velocity route.

   `tsc -b` (the first step of `npm run build`) type-checks every file under
   src/, so these hold without a test runner: when one stops being true, the
   build fails. Nothing imports this file, so it adds no bytes to the bundle.

   What they prove:
   - Each modelled route's client method returns EXACTLY the operation's
     generated 200 response, compared both ways, so the client cannot drift back
     to a hand-written lookalike of the wire.
   - Each save sends EXACTLY the request body its route parses.
   - Each client method that sends a query sends only keys its route reads,
     each with a value the route accepts, so a sort key or a filter the route
     does not know does not compile.
   - A full detail response is usable wherever a list row (`Job`) is expected.
   - A value of the wrong wire type, or one missing a key the server always
     sends, does not compile. `@ts-expect-error` fails the build if that error
     ever goes away, which is what would happen if a type decayed to a loose one. */

import type { operations } from "../api.gen";
import {
  api,
  type AgentAccessState,
  type CloudLLMTestResult,
  type ClusterDetail,
  type ClusterSummary,
  type CompanyCard,
  type CompanyDiscoveryCompany,
  type CompanyPrices,
  type CompanyProfileDetail,
  type CompensationStats,
  type CompTrajectory,
  type CompTrends,
  type DecidedQuery,
  type Demand,
  type DuplicateVerdictResult,
  type Facets,
  type IntelligenceStatus,
  type IntelligenceTestResult,
  type Job,
  type JobDetail,
  type JobSort,
  type LineageDetail,
  type LocalLLMProfile,
  type LocalLLMTestResult,
  type LocalServerControlResult,
  type LocalServerStatus,
  type MatchingStopResult,
  type Notification,
  type OverlapPair,
  type ProfileSuggestion,
  type PursuitInfo,
  type PursuitListItem,
  type ScheduleBinding,
  type ScopeAxes,
  type ScopeLocation,
  type SimilarJob,
  type SimilarJobs,
  type SkillTrends,
  type SyncResult,
  type SystemStatus,
  type TopSkill,
  type TwinProposal,
  type VelocityCompany,
} from "../api";
import { jobFixture, statusFixture } from "./fixtures";

type Equals<A, B> =
  (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Expect<T extends true> = T;
// `never` when an operation declares no JSON 200, so an Equals against it fails
// rather than passing on a type TypeScript could not resolve.
type Ok<Op extends keyof operations> = operations[Op] extends {
  responses: { 200: { content: { "application/json": infer Body } } };
}
  ? Body
  : never;
// The same for a route that answers 201 Created.
type Created<Op extends keyof operations> = operations[Op] extends {
  responses: { 201: { content: { "application/json": infer Body } } };
}
  ? Body
  : never;
// The same for a JSON request body.
type Sends<Op extends keyof operations> = operations[Op] extends {
  requestBody: { content: { "application/json": infer Body } };
}
  ? Body
  : never;
type Returns<F extends (...args: never[]) => unknown> = Awaited<ReturnType<F>>;
// The query a route parses; `never` for a route that reads none.
type Query<Op extends keyof operations> = operations[Op] extends {
  parameters: { query?: infer Params };
}
  ? NonNullable<Params>
  : never;
// A params object as `qs` writes it: null is never sent, and an empty string
// is sent only for a key the caller opts in (`status` on the job list, whose
// route takes any string).
type OnTheWire<P> = { [K in keyof P]: Exclude<P[K], "" | null> };
// Every key of `P` is one the route reads, and every value, as sent, is one
// the route accepts.
type ReadBy<P, Op extends keyof operations> = keyof P extends keyof Query<Op>
  ? OnTheWire<P> extends Query<Op>
    ? true
    : false
  : false;
type ParamsOf<F extends (...args: never[]) => unknown> = NonNullable<Parameters<F>[0]>;

export type QueryContract = [
  Expect<ReadBy<ParamsOf<typeof api.jobs>, "list_jobs_api_jobs_get">>,
  Expect<ReadBy<ParamsOf<typeof api.lineageReview>, "lineage_review_api_lineage_review_get">>,
  Expect<ReadBy<ParamsOf<typeof api.twinReview>, "twin_review_api_twins_review_get">>,
  // The Decided reads build their query in the client (`detail=false`, the summary form).
  Expect<ReadBy<DecidedQuery, "lineage_review_api_lineage_review_get">>,
  Expect<ReadBy<DecidedQuery, "twin_review_api_twins_review_get">>,
  Expect<ReadBy<ParamsOf<typeof api.skillsTop>, "skills_top_api_skills_top_get">>,
  Expect<ReadBy<ParamsOf<typeof api.skillTrends>, "skills_trends_api_skills_trends_get">>,
  Expect<ReadBy<ParamsOf<typeof api.notifications>, "notifications_api_notifications_get">>,
];

// @ts-expect-error: a sort key the job list does not publish does not compile.
export const retiredSort: JobSort = "date_added";

// @ts-expect-error: nor does a params key the route does not read.
export type UnreadParam = Expect<ReadBy<ParamsOf<typeof api.jobs> & { posted_within: number }, "list_jobs_api_jobs_get">>;

// @ts-expect-error: nor a value the route would refuse.
export type RefusedValue = Expect<ReadBy<{ limit: string }, "list_jobs_api_jobs_get">>;

export type JobRouteContract = [
  Expect<Equals<Returns<typeof api.jobs>, Ok<"list_jobs_api_jobs_get">>>,
  Expect<Equals<Returns<typeof api.job>, Ok<"get_job_api_jobs__job_id__get">>>,
  Expect<Equals<Returns<typeof api.markJobViewed>, Ok<"mark_job_viewed_api_jobs__job_id__view_post">>>,
  Expect<Equals<Returns<typeof api.readPostingPage>, Ok<"read_posting_page_on_open_api_jobs__job_id__posting_page_post">>>,
  Expect<Equals<Returns<typeof api.jobHistory>, Ok<"get_listing_history_api_jobs__job_id__history_get">>>,
  Expect<Equals<Returns<typeof api.setFavorite>, Ok<"add_favorite_api_jobs__job_id__favorite_put">>>,
  Expect<Equals<Returns<typeof api.setFavorite>, Ok<"remove_favorite_api_jobs__job_id__favorite_delete">>>,
  Expect<Equals<Returns<typeof api.dismissJob>, Ok<"set_feedback_api_jobs__job_id__feedback_put">>>,
  Expect<Equals<Returns<typeof api.undismissJob>, Ok<"clear_feedback_api_jobs__job_id__feedback_delete">>>,
  Expect<Equals<Returns<typeof api.compareSelection>, Ok<"get_compare_selection_api_compare_selection_get">>>,
  Expect<JobDetail extends Job ? true : false>,
];

export type ScopeRouteContract = [
  Expect<Equals<Returns<typeof api.scopeCatalog>, Ok<"scope_catalog_api_scope_catalog_get">>>,
  Expect<Equals<Returns<typeof api.scopeSettings>, Ok<"get_settings_ep_api_settings_get">>>,
  Expect<Equals<Returns<typeof api.refreshScopeCatalog>, Ok<"refresh_scope_catalog_api_scope_refresh_post">>>,
  Expect<Equals<Returns<typeof api.saveSettings>, Ok<"put_settings_ep_api_settings_put">>>,
  Expect<Equals<Returns<typeof api.previewScope>, Ok<"preview_scope_ep_api_scope_preview_post">>>,
  Expect<Equals<Returns<typeof api.profile>, Ok<"get_profile_ep_api_profile_get">>>,
  Expect<Equals<Returns<typeof api.scopeRules>, Ok<"list_scope_rules_api_scope_rules_get">>>,
  Expect<Equals<Returns<typeof api.createScopeRule>, Ok<"create_scope_rule_api_scope_rules_post">>>,
  Expect<Equals<Returns<typeof api.deleteScopeRule>, Ok<"delete_scope_rule_api_scope_rules__rule_id__delete">>>,
  Expect<Equals<Parameters<typeof api.saveSettings>[0], Sends<"put_settings_ep_api_settings_put">>>,
  Expect<Equals<Parameters<typeof api.createScopeRule>[0], Sends<"create_scope_rule_api_scope_rules_post">>>,
  Expect<Equals<Returns<typeof api.retention>, Ok<"get_retention_ep_api_settings_retention_get">>>,
  Expect<Equals<Returns<typeof api.saveRetention>, Ok<"put_retention_ep_api_settings_retention_put">>>,
  Expect<Equals<Parameters<typeof api.saveRetention>[0], Sends<"put_retention_ep_api_settings_retention_put">>>,
  Expect<Equals<Returns<typeof api.locale>, Ok<"get_locale_ep_api_settings_locale_get">>>,
  Expect<Equals<Returns<typeof api.saveLocale>, Ok<"put_locale_ep_api_settings_locale_put">>>,
  Expect<Equals<Parameters<typeof api.saveLocale>[0], Sends<"put_locale_ep_api_settings_locale_put">>>,
  Expect<Equals<Returns<typeof api.priceFeed>, Ok<"get_price_feed_ep_api_settings_price_feed_get">>>,
  Expect<Equals<Returns<typeof api.savePriceFeedKey>, Ok<"put_price_feed_ep_api_settings_price_feed_put">>>,
  Expect<Equals<Returns<typeof api.removePriceFeedKey>, Ok<"delete_price_feed_ep_api_settings_price_feed_delete">>>,
];

export type CompanyRouteContract = [
  Expect<Equals<Returns<typeof api.companies>, Ok<"list_companies_api_companies_get">>>,
  Expect<Equals<Returns<typeof api.searchCompanyDirectory>, Ok<"companies_directory_api_companies_directory_get">>>,
  Expect<Equals<Returns<typeof api.companyDirectoryStatus>, Ok<"companies_directory_status_api_companies_directory_status_get">>>,
  Expect<Equals<Returns<typeof api.followCompanyDirectory>, Ok<"follow_companies_directory_api_companies_directory_follow_put">>>,
  Expect<Equals<Returns<typeof api.companyDiscovery>, Ok<"companies_discovery_api_companies_discovery_get">>>,
  Expect<Equals<Returns<typeof api.companyOpenCounts>, Ok<"companies_open_counts_api_companies_open_counts_get">>>,
  Expect<Equals<Returns<typeof api.setCompanySelection>, Ok<"update_company_selection_api_companies_selection_put">>>,
  Expect<Equals<Returns<typeof api.addCompany>, Created<"create_company_api_companies_post">>>,
  Expect<Equals<Returns<typeof api.updateCompany>, Ok<"update_company_api_companies__slug__patch">>>,
  Expect<Equals<Parameters<typeof api.addCompany>[0], Sends<"create_company_api_companies_post">>>,
  Expect<Equals<Parameters<typeof api.updateCompany>[1], Sends<"update_company_api_companies__slug__patch">>>,
];

export type ProfileSuggestionRouteContract = [
  Expect<Equals<Returns<typeof api.profileSuggestions>, Ok<"list_profile_suggestions_api_profile_suggestions_get">>>,
  Expect<Equals<Returns<typeof api.payFloor>, Ok<"read_pay_floor_api_profile_pay_floor_get">>>,
  Expect<Equals<Returns<typeof api.savePayFloor>, Ok<"save_pay_floor_api_profile_pay_floor_put">>>,
  Expect<Equals<Returns<typeof api.clearPayFloor>, Ok<"remove_pay_floor_api_profile_pay_floor_delete">>>,
  Expect<Equals<
    Returns<typeof api.acceptProfileSuggestion>,
    Ok<"accept_profile_suggestion_api_profile_suggestions__suggestion_id__accept_post">
  >>,
  Expect<Equals<
    Returns<typeof api.dismissProfileSuggestion>,
    Ok<"dismiss_profile_suggestion_api_profile_suggestions__suggestion_id__dismiss_post">
  >>,
];

export type NotificationRouteContract = [
  Expect<Equals<Returns<typeof api.notifications>, Ok<"notifications_api_notifications_get">>>,
  Expect<Equals<Returns<typeof api.markNotificationRead>, Ok<"notification_read_api_notifications__notification_id__read_post">>>,
  Expect<Equals<Returns<typeof api.markNotificationRead>, Ok<"notification_unread_api_notifications__notification_id__unread_post">>>,
  Expect<Equals<Returns<typeof api.markAllNotificationsRead>, Ok<"notifications_read_all_api_notifications_read_all_post">>>,
  Expect<Equals<Returns<typeof api.markNotificationsUnread>, Ok<"notifications_unread_api_notifications_unread_post">>>,
  Expect<Equals<Returns<typeof api.dismissNotification>, Ok<"notification_dismiss_api_notifications__notification_id__dismiss_post">>>,
  Expect<Equals<Returns<typeof api.restoreNotification>, Ok<"notification_restore_api_notifications__notification_id__restore_post">>>,
];

export type OpsRouteContract = [
  Expect<Equals<Returns<typeof api.status>, Ok<"status_api_status_get">>>,
  Expect<Equals<Returns<typeof api.sync>, Ok<"sync_api_sync_post">>>,
  Expect<Equals<Returns<typeof api.syncTargets>, Ok<"sync_targets_api_sync_targets_get">>>,
  Expect<Equals<Returns<typeof api.cancelSync>, Ok<"cancel_sync_api_sync_cancel_post">>>,
];

export type ScheduleRouteContract = [
  Expect<Equals<Returns<typeof api.schedule>, Ok<"schedule_api_schedule_get">>>,
  Expect<Equals<Returns<typeof api.updateSchedule>, Ok<"update_schedule_time_api_schedule__binding_id__patch">>>,
  Expect<Equals<Parameters<typeof api.updateSchedule>[1], Sends<"update_schedule_time_api_schedule__binding_id__patch">>>,
];

declare const scheduledBinding: ScheduleBinding;
// @ts-expect-error — a binding status the schedule serializer does not name does not compile.
export const unknownScheduleStatus: ScheduleBinding = { ...scheduledBinding, status: "stale" };

export type LineageRouteContract = [
  Expect<Equals<Returns<typeof api.lineage>, Ok<"job_lineage_api_jobs__job_id__lineage_get">>>,
  // A review route answers the full list, or the summary form with `detail=false`:
  // the queue reads the one and Decided the other, and together they are its answer.
  Expect<Equals<
    Returns<typeof api.lineageReview> | Returns<typeof api.lineageReviewHistory>,
    Ok<"lineage_review_api_lineage_review_get">
  >>,
  Expect<Equals<
    Returns<typeof api.lineageReviewHistory>,
    Exclude<Ok<"lineage_review_api_lineage_review_get">, Returns<typeof api.lineageReview>>
  >>,
  Expect<Equals<Returns<typeof api.reviewLineageLink>, Ok<"review_lineage_link_api_lineage_links__link_id__review_post">>>,
  Expect<Equals<{ verdict: Parameters<typeof api.reviewLineageLink>[1] }, Sends<"review_lineage_link_api_lineage_links__link_id__review_post">>>,
  Expect<Equals<
    Returns<typeof api.twinReview> | Returns<typeof api.twinReviewHistory>,
    Ok<"twin_review_api_twins_review_get">
  >>,
  Expect<Equals<
    Returns<typeof api.twinReviewHistory>,
    Exclude<Ok<"twin_review_api_twins_review_get">, Returns<typeof api.twinReview>>
  >>,
  Expect<Equals<Returns<typeof api.reviewTwinLink>, Ok<"review_twin_link_api_twins_links__link_id__review_post">>>,
  Expect<Equals<{ verdict: Parameters<typeof api.reviewTwinLink>[1] }, Sends<"review_twin_link_api_twins_links__link_id__review_post">>>,
  Expect<Equals<Returns<typeof api.twins>, Ok<"job_twins_api_jobs__job_id__twins_get">>>,
  Expect<Equals<Returns<typeof api.placeSet>, Ok<"job_place_set_api_jobs__job_id__place_set_get">>>,
  Expect<Equals<Returns<typeof api.reviewPlaceSet>, Ok<"review_job_place_set_api_jobs__job_id__place_set_review_post">>>,
  Expect<Equals<{ decision: Parameters<typeof api.reviewPlaceSet>[1] }, Sends<"review_job_place_set_api_jobs__job_id__place_set_review_post">>>,
  Expect<Equals<Returns<typeof api.analyzeLineageLink>, Ok<"analyze_lineage_link_api_lineage_links__link_id__analyze_post">>>,
  Expect<Equals<Returns<typeof api.analyzeTwinLink>, Ok<"analyze_twin_link_api_twins_links__link_id__analyze_post">>>,
];

declare const decidedPosting: Returns<typeof api.lineageReviewHistory>["items"][number]["job"];
// @ts-expect-error: a Decided posting is a list row; an expanded row reads its description.
export const decidedDescription = decidedPosting.description_sections;
declare const decidedTwin: Returns<typeof api.twinReviewHistory>["items"][number];
// @ts-expect-error: nor does a Decided twin carry the description diff.
export const decidedTwinDiff = decidedTwin.description_diff;

export type RecipeRouteContract = [
  Expect<Equals<Returns<typeof api.recipes>, Ok<"recipes_index_api_connector_recipes_get">>>,
  Expect<Equals<Returns<typeof api.recipe>, Ok<"recipe_detail_api_connector_recipes__slug__get">>>,
  Expect<Equals<Returns<typeof api.saveRecipeDraft>, Created<"save_recipe_draft_api_connector_recipes_post">>>,
  Expect<Equals<Returns<typeof api.previewRecipe>, Ok<"preview_recipe_api_connectors_preview_post">>>,
  Expect<Equals<
    Returns<typeof api.checkRecipeVersion>,
    Ok<"validate_recipe_revision_api_connector_recipes__slug__revisions__revision_id__validate_post">
  >>,
  Expect<Equals<Returns<typeof api.useRecipeVersion>, Ok<"activate_recipe_api_connector_recipes__slug__activate_post">>>,
  Expect<Equals<
    Returns<typeof api.scanCompanyWithRecipe>,
    Created<"bind_company_recipe_api_companies__company__recipe_post">
  >>,
];

export type PluginRouteContract = [
  Expect<Equals<Returns<typeof api.plugins>, Ok<"plugins_api_plugins_get">>>,
  Expect<Equals<Returns<typeof api.plugin>, Ok<"plugin_api_plugins__plugin_id__get">>>,
  Expect<Equals<Returns<typeof api.approvePlugin>, Ok<"approve_api_plugins__plugin_id__approve_post">>>,
  Expect<Equals<Returns<typeof api.enablePlugin>, Ok<"enable_api_plugins__plugin_id__enable_post">>>,
  Expect<Equals<Returns<typeof api.disablePlugin>, Ok<"disable_api_plugins__plugin_id__disable_post">>>,
  Expect<Equals<Returns<typeof api.refreshPlugin>, Ok<"refresh_api_plugins__plugin_id__refresh_post">>>,
  Expect<Equals<Returns<typeof api.removePluginData>, Ok<"remove_data_api_plugins__plugin_id__remove_data_post">>>,
  Expect<Equals<Returns<typeof api.pausePlugin>, Ok<"pause_api_plugins__plugin_id__pause_post">>>,
  Expect<Equals<Returns<typeof api.resumePlugin>, Ok<"resume_api_plugins__plugin_id__resume_post">>>,
  Expect<Equals<Returns<typeof api.setPluginSchedule>, Ok<"set_schedule_api_plugins__plugin_id__schedule_put">>>,
  Expect<Equals<Returns<typeof api.uninstallPlugin>, Ok<"uninstall_api_plugins__plugin_id__delete">>>,
];

export type IntelligenceRouteContract = [
  Expect<Equals<Returns<typeof api.intelligence>, Ok<"get_intelligence_ep_api_intelligence_get">>>,
  Expect<Equals<Returns<typeof api.setIntelligenceEnabled>, Ok<"put_intelligence_ep_api_intelligence_put">>>,
  Expect<Equals<Returns<typeof api.setAiEgressEnabled>, Ok<"put_ai_egress_ep_api_intelligence_egress_put">>>,
  Expect<Equals<Returns<typeof api.setMatchingTier>, Ok<"put_matching_tier_ep_api_intelligence_matching_tier_put">>>,
  Expect<Equals<Returns<typeof api.stopMatchingSwitch>, Ok<"stop_matching_switch_api_intelligence_matching_stop_post">>>,
  Expect<Equals<
    Returns<typeof api.resumeMatchingSwitch>,
    Ok<"resume_matching_switch_api_intelligence_matching_resume_post">
  >>,
  Expect<Equals<Returns<typeof api.testIntelligence>, Ok<"test_intelligence_ep_api_intelligence_test_post">>>,
  Expect<Equals<Returns<typeof api.intelligenceFit>, Ok<"intelligence_fit_api_intelligence_fit_get">>>,
  Expect<Equals<Returns<typeof api.intelligenceFitBand>, Ok<"intelligence_fit_band_api_intelligence_fit_band__band__get">>>,
  Expect<Equals<Returns<typeof api.agentAccess>, Ok<"get_agent_access_ep_api_intelligence_agents_get">>>,
  Expect<Equals<Returns<typeof api.setAgentAccess>, Ok<"put_agent_access_ep_api_intelligence_agents_put">>>,
  Expect<MatchingStopResult extends IntelligenceStatus ? true : false>,
];

declare const answered: Extract<IntelligenceTestResult, { grounded: boolean }>;
// @ts-expect-error — an answer always carries its grounding verdict.
export const answerWithoutVerdict: IntelligenceTestResult = { ...answered, grounded: undefined };

declare const stopWithoutOutcome: Omit<MatchingStopResult, "outcome">;
// @ts-expect-error — a stop always says what it ended.
export const missingOutcome: MatchingStopResult = stopWithoutOutcome;

// @ts-expect-error — the bundled model offers two tiers, never a third.
export const unknownTier: IntelligenceStatus["matching"]["tier"] = "fp16";

declare const agents: AgentAccessState;
// @ts-expect-error — a tool is read, write or status access, never another.
export const unknownAccess: AgentAccessState = { ...agents, tools: [{ name: "drop_table", access: "admin" }] };

export type ModelConnectionRouteContract = [
  Expect<Equals<Returns<typeof api.localLLMProfiles>, Ok<"list_local_llm_profiles_api_intelligence_local_models_get">>>,
  Expect<Equals<
    Returns<typeof api.setLocalLLMEnabled>,
    Ok<"put_local_llm_enabled_api_intelligence_local_models_enabled_put">
  >>,
  Expect<Equals<
    Returns<typeof api.localServerStatus>,
    Ok<"get_local_llm_server_api_intelligence_local_models_server_get">
  >>,
  Expect<Equals<
    Returns<typeof api.controlLocalServer>,
    Ok<"post_local_llm_server_api_intelligence_local_models_server_post">
  >>,
  Expect<Equals<Returns<typeof api.addLocalLLMProfile>, Created<"add_local_llm_profile_api_intelligence_local_models_post">>>,
  Expect<Equals<
    Returns<typeof api.updateLocalLLMProfile>,
    Ok<"put_local_llm_profile_api_intelligence_local_models__profile_id__put">
  >>,
  Expect<Equals<
    Returns<typeof api.deleteLocalLLMProfile>,
    Ok<"remove_local_llm_profile_api_intelligence_local_models__profile_id__delete">
  >>,
  Expect<Equals<
    Returns<typeof api.selectLocalLLMProfile>,
    Ok<"put_active_local_llm_profile_api_intelligence_local_models_active_select_put">
  >>,
  Expect<Equals<
    Returns<typeof api.testLocalLLMProfile>,
    Ok<"test_local_llm_profile_api_intelligence_local_models__profile_id__test_post">
  >>,
  Expect<Equals<Returns<typeof api.cloudLLMProfiles>, Ok<"list_cloud_llm_profiles_api_intelligence_cloud_models_get">>>,
  Expect<Equals<Returns<typeof api.addCloudLLMProfile>, Created<"add_cloud_llm_profile_api_intelligence_cloud_models_post">>>,
  Expect<Equals<
    Returns<typeof api.updateCloudLLMProfile>,
    Ok<"put_cloud_llm_profile_api_intelligence_cloud_models__profile_id__put">
  >>,
  Expect<Equals<
    Returns<typeof api.deleteCloudLLMProfile>,
    Ok<"remove_cloud_llm_profile_api_intelligence_cloud_models__profile_id__delete">
  >>,
  Expect<Equals<
    Returns<typeof api.testCloudLLMProfile>,
    Ok<"test_cloud_llm_profile_api_intelligence_cloud_models__profile_id__test_post">
  >>,
  Expect<Equals<
    Parameters<typeof api.controlLocalServer>[0],
    Sends<"post_local_llm_server_api_intelligence_local_models_server_post">["action"]
  >>,
  Expect<Equals<Parameters<typeof api.addCloudLLMProfile>[0], Sends<"add_cloud_llm_profile_api_intelligence_cloud_models_post">>>,
  Expect<Equals<
    Parameters<typeof api.updateCloudLLMProfile>[1],
    Sends<"put_cloud_llm_profile_api_intelligence_cloud_models__profile_id__put">
  >>,
  // The local dialog's draft is a save the route accepts, with every parameter the route would default.
  Expect<
    Parameters<typeof api.addLocalLLMProfile>[0] extends Sends<"add_local_llm_profile_api_intelligence_local_models_post">
      ? true
      : false
  >,
  Expect<
    Parameters<typeof api.updateLocalLLMProfile>[1] extends Sends<"put_local_llm_profile_api_intelligence_local_models__profile_id__put">
      ? true
      : false
  >,
  Expect<LocalServerControlResult extends LocalServerStatus ? true : false>,
];

declare const savedLocalConnection: LocalLLMProfile;
// @ts-expect-error — a saved connection says whether a key is saved, never what the key is.
export const servedKey: LocalLLMProfile = { ...savedLocalConnection, api_key: "sk-live" };

declare const localServer: LocalServerStatus;
// @ts-expect-error — the server row's state is an availability the probe names, never a free word.
export const runningState: LocalServerStatus = { ...localServer, state: "running" };

declare const localTestWithoutMetrics: Omit<LocalLLMTestResult, "metrics">;
// @ts-expect-error — a local test always reports the completion's metrics.
export const missingMetrics: LocalLLMTestResult = localTestWithoutMetrics;

declare const cloudConnectionTest: CloudLLMTestResult;
// @ts-expect-error — a failed cloud test is an HTTP error, never an answer with `ok: false`.
export const failedCloudTest: CloudLLMTestResult = { ...cloudConnectionTest, ok: false };

export type CompanyProfileRouteContract = [
  Expect<Equals<Returns<typeof api.companyProfiles>, Ok<"company_profiles_list_api_company_profiles_get">>>,
  Expect<Equals<Returns<typeof api.companyProfile>, Ok<"company_profile_api_company_profiles__slug__get">>>,
  Expect<Equals<Returns<typeof api.companyPrices>, Ok<"company_prices_api_company_profiles__slug__prices_get">>>,
  Expect<Equals<Returns<typeof api.companyCard>, Ok<"company_card_api_companies__slug__card_get">>>,
  Expect<Equals<
    Returns<typeof api.setCompanyField>,
    Ok<"company_profile_set_manual_api_company_profiles__slug__patch">
  >>,
  Expect<Equals<
    Returns<typeof api.clearCompanyField>,
    Ok<"company_profile_clear_manual_api_company_profiles__slug__manual__field__delete">
  >>,
];

declare const profileDetail: CompanyProfileDetail;
declare const fieldsWithoutWebsite: Omit<CompanyProfileDetail["fields"], "website">;
// @ts-expect-error — a profile always carries all eight shown fields.
export const missingShownField: CompanyProfileDetail = { ...profileDetail, fields: fieldsWithoutWebsite };

// @ts-expect-error — a review item names a field the profile shows, never another column.
export const reviewOfHiddenColumn: CompanyProfileDetail["needs_review"][number]["field"] = "comp_notes";

declare const priceWindow: CompanyPrices;
// @ts-expect-error — the price window is one of four ranges; an unknown one is answered as `3m`.
export const unknownRange: CompanyPrices = { ...priceWindow, range: "5y" };

declare const hoverCard: CompanyCard;
// @ts-expect-error — a card always says whether the company has a profile.
export const cardWithoutProfileFlag: CompanyCard = { ...hoverCard, has_profile: undefined };

export type StatisticsRouteContract = [
  Expect<Equals<Returns<typeof api.stats>, Ok<"stats_api_stats_get">>>,
  Expect<Equals<Returns<typeof api.statisticsOverview>, Ok<"statistics_overview_api_statistics_overview_get">>>,
  Expect<Equals<
    Returns<typeof api.compensation>,
    Ok<"statistics_compensation_api_statistics_compensation_get">
  >>,
  Expect<Equals<
    Returns<typeof api.compTrajectory>,
    Ok<"statistics_comp_trajectory_api_statistics_comp_trajectory_get">
  >>,
  Expect<Equals<Returns<typeof api.compTrends>, Ok<"statistics_comp_trends_api_statistics_comp_trends_get">>>,
  Expect<Equals<
    Returns<typeof api.disclosureTrends>,
    Ok<"statistics_disclosure_trends_api_statistics_disclosure_trends_get">
  >>,
  Expect<Equals<Returns<typeof api.velocity>, Ok<"statistics_velocity_api_statistics_velocity_get">>>,
  Expect<Equals<Returns<typeof api.levelGuide>, Ok<"statistics_levels_api_statistics_levels_get">>>,
  Expect<Equals<Returns<typeof api.demand>, Ok<"demand_api_demand_get">>>,
];

declare const marketSummary: NonNullable<CompensationStats["overall"]>;
// @ts-expect-error — a comp group is never empty, so its median is always a number.
export const summaryWithoutMedian: CompensationStats["overall"] = { ...marketSummary, p50: null };

// @ts-expect-error — the comp trend groups by overall, company, level or family, never another axis.
export const unknownTrendDim: CompTrends["dim"] = "region";

declare const tracked: Demand["most_updated_open"][number];
// @ts-expect-error — a changed posting always says how many times it changed.
export const updatedWithoutCount: Demand["most_updated_open"][number] = { ...tracked, update_count: undefined };

declare const packaged: NonNullable<CompTrajectory["overall"]>;
// @ts-expect-error — a split is measured, estimated or mixed; never another source.
export const unknownSplit: CompTrajectory["overall"] = { ...packaged, split_source: "guessed" };

export type SkillsRouteContract = [
  Expect<Equals<Returns<typeof api.skillsTop>, Ok<"skills_top_api_skills_top_get">>>,
  Expect<Equals<Returns<typeof api.skillTrends>, Ok<"skills_trends_api_skills_trends_get">>>,
  Expect<Equals<Returns<typeof api.skillsOverlap>, Ok<"skills_overlap_api_skills_overlap_get">>>,
  Expect<Equals<Returns<typeof api.clusters>, Ok<"clusters_api_clusters_get">>>,
  Expect<Equals<Returns<typeof api.cluster>, Ok<"cluster_detail_api_clusters__cluster_id__get">>>,
];

declare const clusterMember: ClusterDetail["items"][number];
// A cluster lists its members as the rows every list shows.
export const memberAsRow: Job = clusterMember;

declare const leader: TopSkill;
// @ts-expect-error — every concept is filed under a category, so a leaderboard skill always names one.
export const uncategorizedSkill: TopSkill = { ...leader, category: null };

// @ts-expect-error — a trend point counts roles; a day without a slice is zero, never null.
export const gapAsNull: SkillTrends["series"][number]["points"][number] = { date: "2026-07-20", job_count: null };

declare const pairWithoutSimilarity: Omit<OverlapPair, "similarity">;
// @ts-expect-error: a shared pair always carries its similarity.
export const missingSimilarity: OverlapPair = pairWithoutSimilarity;

declare const clusterWithoutMix: Omit<ClusterSummary, "companies">;
// @ts-expect-error — a cluster in the list always carries its visible company mix.
export const missingMix: ClusterSummary = clusterWithoutMix;

export type ProfileRouteContract = [
  Expect<Equals<Returns<typeof api.pursuits>, Ok<"list_pursuits_ep_api_pursuits_get">>>,
  Expect<Equals<Returns<typeof api.setPursuit>, Ok<"set_pursuit_ep_api_jobs__job_id__pursuit_put">>>,
  Expect<Equals<Parameters<typeof api.setPursuit>[1], Sends<"set_pursuit_ep_api_jobs__job_id__pursuit_put">>>,
];

declare const listedWithoutOpportunity: Omit<PursuitListItem, "opportunity">;
// @ts-expect-error — a listed pursuit always names the opportunity it tracks.
export const missingOpportunity: PursuitListItem = listedWithoutOpportunity;

declare const writtenPursuit: PursuitInfo;
export const detailWithOpportunity: PursuitInfo = {
  ...writtenPursuit,
  // @ts-expect-error — a written or detail pursuit carries no opportunity.
  opportunity: { title: "Staff PM", company: "google", status: "open", url: "https://example.test" },
};

export type BoardFacetsRouteContract = [
  Expect<Equals<Returns<typeof api.facets>, Ok<"facets_api_facets_get">>>,
  Expect<Equals<Returns<typeof api.similar>, Ok<"similar_jobs_api_jobs__job_id__similar_get">>>,
];

declare const neighbour: SimilarJob;
// A neighbour is usable wherever a list row is.
export const neighbourAsRow: Job = neighbour;

declare const offeredLocation: Facets["location_groups"][string];
// @ts-expect-error — a location option always names its parent, even as null.
export const optionWithoutParent: Facets["location_groups"][string] = { display: offeredLocation.display };

declare const neighbours: SimilarJobs;
// @ts-expect-error — a similar list answers one of three scopes, never another.
export const unknownScope: SimilarJobs = { ...neighbours, scope: "nearby" };

// @ts-expect-error — a status without the scheduler's projection does not compile.
export const statusWithoutScheduler: SystemStatus = { ...statusFixture, scheduler: undefined };

// @ts-expect-error — a sync that attached to a live run names that run.
export const attachedWithoutRun: SyncResult = { status: "already_running", companies: [] };

// @ts-expect-error — a row carrying the wrong wire type for a key does not compile.
export const wrongWireType: Job = { ...jobFixture, id: "101" };

declare const rowMissingTwinCount: Omit<Job, "twin_count">;
// @ts-expect-error — nor does one missing a key the server always sends.
export const missingKey: Job = rowMissingTwinCount;

declare const location: ScopeLocation;
// @ts-expect-error — a location kind the taxonomy does not have does not compile.
export const unknownKind: ScopeLocation = { ...location, kind: "planet" };

declare const discovered: CompanyDiscoveryCompany;
// @ts-expect-error — a connector state the discovery catalog does not define does not compile.
export const unknownConnector: CompanyDiscoveryCompany = { ...discovered, connector_state: "beta" };

declare const suggestion: ProfileSuggestion;
// @ts-expect-error — a suggestion kind the table does not admit does not compile.
export const unknownSuggestionKind: ProfileSuggestion = { ...suggestion, kind: "world_sideways" };

declare const notificationWithoutSource: Omit<Notification, "source_type">;
// @ts-expect-error — a notification missing the source type every row carries does not compile.
export const missingSourceType: Notification = notificationWithoutSource;

declare const axesWithoutWorlds: Omit<ScopeAxes, "enabled_domain_groups">;
// @ts-expect-error — nor do axes missing the worlds axis every scope read sends.
export const missingWorlds: ScopeAxes = axesWithoutWorlds;

declare const stackWithoutRoot: Omit<Extract<LineageDetail, { lineage_id: number }>, "root_job_id">;
// @ts-expect-error — a stack missing its root is neither a stack nor a standalone posting.
export const missingRoot: LineageDetail = stackWithoutRoot;

declare const twinWithoutEvidence: Omit<TwinProposal, "description_diff">;
// @ts-expect-error — a twin proposal always carries its stored description evidence, even as null.
export const missingEvidence: TwinProposal = twinWithoutEvidence;

declare const verdict: DuplicateVerdictResult;
// @ts-expect-error — a verdict leaves a status the routes name, never another.
export const unknownVerdictStatus: DuplicateVerdictResult = { ...verdict, status: "withdrawn" };

declare const flowWithoutReposts: Omit<VelocityCompany, "reposted">;
// @ts-expect-error — a company's flow always counts its reposts.
export const missingReposts: VelocityCompany = flowWithoutReposts;
