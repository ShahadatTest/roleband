/* AI settings: the state, matching, the self-test, fit, local and cloud models, agents.
   One domain of the typed client; `index.ts` composes `api`. */

import type { Schemas } from "./schemas";
import { getJSON, putJSON, postJSON, deleteJSON } from "./transport";

// --- Settings > AI: the state, matching, the experimental self-test, fit -----
//
// Nothing the app does automatically uses the experimental on-device model:
// salary extraction is built-in code with no provider, and the routing ladder is
// local/cloud only. These wire types are aliases of the generated schemas
// (`tracker/api/schemas/intelligence.py`).

/** Why a provider can (or cannot) run. `state` is the machine-readable reason;
 *  `message` is the plain-language line shown to the user. */
export type IntelligenceAvailability = Schemas["ProviderAvailability"];

/** Where a response was produced. `cloud` is the only value that means job text
 *  left this computer, and it is what the privacy copy keys off. */
export type ProviderOrigin = Schemas["RoutingTier"]["origin"];

/** One rung of the routed-task ladder, as configured and never probed. */
export type IntelligenceTier = Schemas["RoutingTier"];
export type IntelligenceRouting = Schemas["IntelligenceRouting"];

/** One artifact of the bundled model the user may run, priced for this machine.
 *  `recommended` tracks detected RAM, independent of what the user picked;
 *  `switch_seconds` is null when nothing has been measured — show no duration. */
export type MatchingTierOption = Schemas["MatchingTierOption"];
export type MatchingTier = MatchingTierOption["tier"];

/** `GET /api/intelligence`, and every write that answers with the state. */
export type IntelligenceStatus = Schemas["IntelligenceStateResponse"];

/** Provisioning of the bundled matching model and the corpus measured against
 *  it. `detected_ram_bytes` null means detection FAILED, not a small Mac;
 *  `other_tier_count > 0` with `job_phase === "none"` is a switch that stopped
 *  partway; `stale_count` is all the work owed, including rows never ranked. A configured model with no pinned manifest answers a fixed branch
 *  with no `estimate_seconds`, so read that key through `in`. */
export type MatchingStatus = IntelligenceStatus["matching"];

/** `POST /api/intelligence/matching/stop`: what the stop ended, then the state
 *  after the choice went back. */
export type MatchingStopResult = Schemas["MatchingStopResponse"];

/** `GET /api/intelligence/fit` — the ranking card's instrument data. The base set
 *  is the board's default browse base, so `total` equals the board's own count;
 *  `bands` quantize fit for the settings visual, and the raw score itself stays
 *  unrendered (rule). */
export type IntelligenceFitBand = Schemas["IntelligenceFitBand"];
export type IntelligenceFit = Schemas["IntelligenceFitResponse"];
export type IntelligenceFitBandPreview = Schemas["IntelligenceFitBandResponse"];

/** What the model returned, after grounding and bounds validation. */
export type IntelligenceExtracted = Schemas["ExtractedDisclosedComp"];

/** `POST /api/intelligence/test`: one of four outcomes, each with its own keys —
 *  unavailable, prefiltered, model failed, answered. Narrow with `in`: only an
 *  answer carries `grounded`, and only a model that ran carries `origin_label`. */
export type IntelligenceTestResult = Schemas["IntelligenceTestResponse"];

// --- Local OpenAI-compatible models (oMLX) ----------------------------------

/** A saved connection's generation controls, every key present. */
export type LocalLLMParameters = Schemas["LocalModelParameters"];

/** A saved local connection. `has_api_key` says whether a key is saved; the key
 *  itself is write-only and never served. */
export type LocalLLMProfile = Schemas["LocalModelProfile"];

/** What the connection dialog saves and tests: the route's request body with
 *  every parameter present, since the form edits each one (the route would
 *  default them). A null key keeps the saved one. */
export type LocalLLMProfileInput = Schemas["LocalLLMProfileInput"] & { parameters: LocalLLMParameters };

/** The local tier's switch and every saved connection. Off keeps the connections
 *  but stops the app reaching for a server — what a user without oMLX wants. */
export type LocalLLMState = Schemas["LocalModelState"];

/** Three independent facts about the local server, deliberately not collapsed:
 *  `installed` (is the oMLX CLI on this Mac), `managed` (may the app start/stop
 *  THIS connection — false for a non-oMLX server we did not launch), and
 *  `reachable` (is it answering right now). `state` is the probe's availability. */
export type LocalServerStatus = Schemas["LocalServerStatus"];

/** `POST /api/intelligence/local-models/server`: the probe taken after the
 *  command, then what the command reported. */
export type LocalServerControlResult = Schemas["LocalServerControlResponse"];

/** One local-model completion's timings and token use, as the client reports
 *  them. Token counts and rates are what the server sent, integer or not. */
export type LocalLLMMetrics = Schemas["LocalModelMetrics"];

/** A connection test the model answered; a reply cut off at max_tokens is not `ok`. */
export type LocalLLMTestResult = Schemas["LocalModelTestResult"];

// --- External agents / MCP -------------------------------------------------

/** Both gates as saved, and what an MCP client needs to connect over STDIO. */
export type AgentAccessState = Schemas["AgentAccessResponse"];

/** A saved BYOK connection; the key is write-only. */
export type CloudLLMProfile = Schemas["CloudModelProfile"];

/** What the cloud dialog saves. A null key keeps the saved one. */
export type CloudLLMProfileInput = Schemas["CloudLLMProfileInput"];

export type CloudLLMState = Schemas["CloudModelState"];

/** An authenticated check that succeeded; every failure is an HTTP error. */
export type CloudLLMTestResult = Schemas["CloudModelTestResult"];

/** The aim sentence as saved: trimmed, "" when there is none. */
export type IntentStatementResult = Schemas["IntentStatementResponse"];

export const intelligenceApi = {
  intelligence: () => getJSON<IntelligenceStatus>("/api/intelligence"),
  intelligenceFit: () => getJSON<IntelligenceFit>("/api/intelligence/fit"),
  /** Save the aim sentence alone. It ranks (Best fit) and never changes scope. */
  saveIntentStatement: (intent_statement: string) =>
    putJSON<IntentStatementResult>("/api/settings/intent", { intent_statement }),
  /** A band's few strongest roles, for the ranking card's preview list. */
  intelligenceFitBand: (band: IntelligenceFitBand["key"], limit: number) =>
    getJSON<IntelligenceFitBandPreview>(`/api/intelligence/fit/band/${band}?limit=${limit}`),
  setIntelligenceEnabled: (enabled: boolean) =>
    putJSON<IntelligenceStatus>("/api/intelligence", { enabled }),
  setAiEgressEnabled: (enabled: boolean) =>
    putJSON<IntelligenceStatus>("/api/intelligence/egress", { enabled }),
  /** Choose which artifact of the bundled model this Mac runs; null = auto.
   *  A tier that actually moves re-embeds the whole corpus in the background. */
  resumeMatchingSwitch: () =>
    postJSON<IntelligenceStatus>("/api/intelligence/matching/resume", {}),
  stopMatchingSwitch: () =>
    postJSON<MatchingStopResult>("/api/intelligence/matching/stop", {}),
  setMatchingTier: (tier: MatchingTier | null) =>
    putJSON<IntelligenceStatus>("/api/intelligence/matching/tier", { tier }),
  testIntelligence: (text?: string) =>
    postJSON<IntelligenceTestResult>("/api/intelligence/test", { text: text ?? null }),
  localLLMProfiles: () => getJSON<LocalLLMState>("/api/intelligence/local-models"),
  addLocalLLMProfile: (profile: LocalLLMProfileInput) =>
    postJSON<LocalLLMProfile>("/api/intelligence/local-models", profile),
  updateLocalLLMProfile: (id: string, profile: LocalLLMProfileInput) =>
    putJSON<LocalLLMProfile>(`/api/intelligence/local-models/${encodeURIComponent(id)}`, profile),
  deleteLocalLLMProfile: (id: string) =>
    deleteJSON<LocalLLMState>(`/api/intelligence/local-models/${encodeURIComponent(id)}`),
  selectLocalLLMProfile: (profile_id: string) =>
    putJSON<LocalLLMState>("/api/intelligence/local-models/active/select", { profile_id }),
  setLocalLLMEnabled: (enabled: boolean) =>
    putJSON<LocalLLMState>("/api/intelligence/local-models/enabled", { enabled }),
  localServerStatus: () =>
    getJSON<LocalServerStatus>("/api/intelligence/local-models/server"),
  controlLocalServer: (action: Schemas["LocalServerActionPayload"]["action"]) =>
    postJSON<LocalServerControlResult>("/api/intelligence/local-models/server", { action }),
  testLocalLLMProfile: (id: string, profile: LocalLLMProfileInput, prompt?: string) =>
    postJSON<LocalLLMTestResult>(
      `/api/intelligence/local-models/${encodeURIComponent(id)}/test`,
      { prompt: prompt ?? null, profile },
    ),
  agentAccess: () => getJSON<AgentAccessState>("/api/intelligence/agents"),
  setAgentAccess: (enabled: boolean, allow_writes: boolean) =>
    putJSON<AgentAccessState>("/api/intelligence/agents", { enabled, allow_writes }),
  cloudLLMProfiles: () => getJSON<CloudLLMState>("/api/intelligence/cloud-models"),
  addCloudLLMProfile: (profile: CloudLLMProfileInput) =>
    postJSON<CloudLLMProfile>("/api/intelligence/cloud-models", profile),
  updateCloudLLMProfile: (id: string, profile: CloudLLMProfileInput) =>
    putJSON<CloudLLMProfile>(`/api/intelligence/cloud-models/${encodeURIComponent(id)}`, profile),
  deleteCloudLLMProfile: (id: string) =>
    deleteJSON<CloudLLMState>(`/api/intelligence/cloud-models/${encodeURIComponent(id)}`),
  testCloudLLMProfile: (id: string) =>
    postJSON<CloudLLMTestResult>(`/api/intelligence/cloud-models/${encodeURIComponent(id)}/test`),
};
