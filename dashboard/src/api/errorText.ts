import { companyName } from "../format";
import { list } from "../copy/format";
import {
  errorGeneric,
  errorPluginNotFound,
  errorPluginNotRunnable,
  errorPluginRunning,
  errorPluginApprovalStale,
  errorPluginStillEnabled,
  errorPluginConfirmMismatch,
  errorPluginEstimatesMoving,
  errorFieldAnsweredByPlugin,
  errorOffline,
  errorServer,
  errorInvalidInput,
  errorJobNotFound,
  errorCompanyNotFound,
  errorCompanyProfileNotFound,
  errorLocalModelNotFound,
  errorCloudModelNotFound,
  errorNotificationNotFound,
  errorLinkNotFound,
  errorSuggestionNotFound,
  errorRecipeNotFound,
  errorRuleNotFound,
  errorClusterNotFound,
  errorFitBandNotFound,
  errorScheduleNotFound,
  errorPageNotFound,
  errorCareersPageRefused,
  errorCareersPageUnreachable,
  errorCompanyConflict,
  errorCompanyRefused,
  errorConsentRequired,
  errorScopeRefused,
  errorScheduleRefused,
  errorSchedulingUnavailable,
  errorDiscoveryUnsupported,
  errorManualScanQueued,
  errorSwitchRunning,
  errorSwitchNotStarted,
  errorNoSwitchRunning,
  errorSwitchNotStopped,
  errorPriceKeyRefused,
  errorSwitchNotManaged,
  errorServerNotManaged,
  errorModelUnreachable,
  errorAiEgressOff,
  errorLocalModelsOff,
  errorModelProfilesUnreadable,
  errorNoLocalModel,
  errorLinkToItself,
  errorAlreadyLinked,
  errorVerdictDecided,
  errorPairRefused,
  errorNotAMember,
  errorSuggestionDecided,
  errorLastWorld,
  errorRecipeInvalid,
  errorRecipeConflict,
  errorUsageCatalogueChanged,
} from "../copy/gen/errors";
import { ApiError, type ErrorCode, type ErrorParams } from "./transport";

/* What a person reads when a request fails (docs/copy.md).
 *
 * Every code the API or the transport can send has its catalog message; the
 * `Record` makes a backend code with no message a type error, since the codes
 * come from `openapi.json`. Parameters carry slugs, so a company is named here,
 * in the reader's language, never by the server. A failure that is not an
 * ApiError (a defect in our own code) says the generic line. Never print an
 * error's `message`: it is English for logs. */

const names = (value: ErrorParams[string] | undefined): string[] =>
  (Array.isArray(value) ? value : value === undefined ? [] : [String(value)]).map((slug) => companyName(slug));

const BY_CODE: Record<ErrorCode, (params: ErrorParams) => string> = {
  "offline": () => errorOffline(),
  "server": () => errorServer(),
  "invalid-input": () => errorInvalidInput(),
  "job-not-found": () => errorJobNotFound(),
  "company-not-found": () => errorCompanyNotFound(),
  "company-profile-not-found": () => errorCompanyProfileNotFound(),
  "local-model-not-found": () => errorLocalModelNotFound(),
  "cloud-model-not-found": () => errorCloudModelNotFound(),
  "notification-not-found": () => errorNotificationNotFound(),
  "link-not-found": () => errorLinkNotFound(),
  "suggestion-not-found": () => errorSuggestionNotFound(),
  "recipe-not-found": () => errorRecipeNotFound(),
  "rule-not-found": () => errorRuleNotFound(),
  "cluster-not-found": () => errorClusterNotFound(),
  "fit-band-not-found": () => errorFitBandNotFound(),
  "schedule-not-found": () => errorScheduleNotFound(),
  "page-not-found": () => errorPageNotFound(),
  "plugin-not-found": () => errorPluginNotFound(),
  "plugin-not-runnable": () => errorPluginNotRunnable(),
  "plugin-running": () => errorPluginRunning(),
  "plugin-approval-stale": () => errorPluginApprovalStale(),
  "plugin-still-enabled": () => errorPluginStillEnabled(),
  "plugin-confirm-mismatch": () => errorPluginConfirmMismatch(),
  "plugin-estimates-moving": () => errorPluginEstimatesMoving(),
  "field-answered-by-plugin": () => errorFieldAnsweredByPlugin(),
  "careers-page-refused": () => errorCareersPageRefused(),
  "careers-page-unreachable": () => errorCareersPageUnreachable(),
  "company-conflict": () => errorCompanyConflict(),
  "company-refused": () => errorCompanyRefused(),
  "consent-required": () => errorConsentRequired(),
  "scope-refused": () => errorScopeRefused(),
  "schedule-refused": () => errorScheduleRefused(),
  "scheduling-unavailable": (p) => errorSchedulingUnavailable({ companies: list(names(p.companies)) }),
  "discovery-unsupported": (p) => errorDiscoveryUnsupported({ company: names(p.company)[0] ?? "" }),
  "manual-scan-queued": () => errorManualScanQueued(),
  "switch-running": () => errorSwitchRunning(),
  "switch-not-started": () => errorSwitchNotStarted(),
  "no-switch-running": () => errorNoSwitchRunning(),
  "switch-not-stopped": () => errorSwitchNotStopped(),
  "price-key-refused": () => errorPriceKeyRefused(),
  "switch-not-managed": () => errorSwitchNotManaged(),
  "server-not-managed": () => errorServerNotManaged(),
  "model-unreachable": () => errorModelUnreachable(),
  "local-models-off": () => errorLocalModelsOff(),
  "ai-egress-off": () => errorAiEgressOff(),
  "no-local-model": () => errorNoLocalModel(),
  "model-profiles-unreadable": () => errorModelProfilesUnreadable(),
  "link-to-itself": () => errorLinkToItself(),
  "already-linked": () => errorAlreadyLinked(),
  "verdict-decided": () => errorVerdictDecided(),
  "pair-refused": () => errorPairRefused(),
  "not-a-member": () => errorNotAMember(),
  "suggestion-decided": () => errorSuggestionDecided(),
  "last-world": () => errorLastWorld(),
  "recipe-invalid": () => errorRecipeInvalid(),
  "recipe-conflict": () => errorRecipeConflict(),
  "usage-catalogue-changed": () => errorUsageCatalogueChanged(),
  aborted: () => errorGeneric(),
  unknown: () => errorGeneric(),
};

/** Codes that say nothing the screen's own sentence does not say better. */
const UNEXPLAINED: ReadonlySet<ErrorCode> = new Set<ErrorCode>(["server", "unknown", "invalid-input", "aborted"]);

/** The message for a failure. With `fallback`, a failure that explains
 *  nothing (a crash, bare English from before codes, a malformed request)
 *  says the screen's own sentence instead of the generic line. */
export function errorText(error: unknown, fallback?: string): string {
  if (error instanceof ApiError && !(fallback !== undefined && UNEXPLAINED.has(error.code))) {
    if (Object.prototype.hasOwnProperty.call(BY_CODE, error.code)) return BY_CODE[error.code](error.params);
  }
  return fallback ?? errorGeneric();
}
