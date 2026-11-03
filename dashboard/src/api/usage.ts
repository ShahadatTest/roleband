/* Usage sharing: the consent, the install ID, and what is (and was) sent
   (docs/architecture.md). One domain of the typed client;
   `index.ts` composes `api`. Wire types alias the generated schemas
   (`tracker/api/schemas/usage.py`). */

import type { Schemas } from "./schemas";
import { getJSON, postJSON, putJSON } from "./transport";

/** `GET /api/usage`, and every write that answers with the state. */
export type UsageState = Schemas["UsageState"];
/** One consent group: its status, its CURRENT fingerprint (echoed back when the
 *  user answers, so a screen built for an older scope is refused with 409), and
 *  what the browser may turn on while it is shared. */
export type UsageGroupState = Schemas["UsageGroupState"];
export type UsageGroup = UsageGroupState["group"];
export type UsageStatus = UsageGroupState["status"];
export type UsageConsent = Schemas["UsageConsentPayload"];
export type UsagePreview = Schemas["UsagePreview"];
export type UsageSent = Schemas["UsageSent"];

export const usageApi = {
  /** Record the user's answer per group with the exact words the screen showed. */
  saveUsageConsent: (consent: UsageConsent) => putJSON<UsageState>("/api/usage/consent", consent),
  resetUsageInstallId: () => postJSON<UsageState>("/api/usage/install-id/reset"),
  usagePreview: (signal?: AbortSignal) => getJSON<UsagePreview>("/api/usage/preview", signal),
  usageSent: (signal?: AbortSignal) => getJSON<UsageSent>("/api/usage/sent", signal),
};
