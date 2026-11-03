/* The browser side of usage sharing (docs/architecture.md, docs/usage-data.md).

   Nothing here runs, and PostHog's library is not even loaded, until the user
   has shared at least one kind of sharing: `applySharing` is called with the
   server's state at startup and after every answer, and it loads the library
   (a separate chunk) only then.

   Three rules hold whatever the PostHog project's settings say, because they
   are set here, in code:

   1. **No remote code.** The library is `module.full.no-external`: surveys
      and exception capture are bundled, and nothing is ever loaded from
      PostHog at runtime (`disable_external_dependency_loading` as well). A
      project setting can switch a capability off; it can never switch on one
      the user did not share, nor change what it records.
   2. **No session recordings.** RoleBand records no sessions:
      `disable_session_recording` is always true and nothing starts one.
      Autocapture records no element text or attributes at all
      (`mask_all_text`, `mask_all_element_attributes`).
   3. **Addresses are screens.** `before_send` rewrites every address to its
      screen (`/jobs/:id`) wherever the library puts it: values at any depth,
      and keys, which is how heatmaps record the page. It drops referrers,
      titles and the target of an outbound click, and cleans exception
      messages of addresses, emails, quoted text and long numbers.

   What left is kept in memory (`recentEvents`) for Settings › Privacy. */

import type { UsageGroup, UsageState } from "../api";

type PostHogModule = typeof import("posthog-js/dist/module.full.no-external");
type PostHog = PostHogModule["default"];
type Config = Parameters<PostHog["init"]>[1];
type BeforeSend = Extract<NonNullable<NonNullable<Config>["before_send"]>, (...args: never[]) => unknown>;
type CaptureResult = Parameters<BeforeSend>[0];

export type SharedGroups = Record<UsageGroup, boolean>;

/** The groups the browser may act on: shared, and allowed by the machine. */
export function sharedGroups(state: UsageState): SharedGroups {
  const allowed = state.blocked_by === null && state.project_key !== "" && state.install_id !== null;
  const shared = (group: UsageGroup) =>
    allowed && state.groups.some((item) => item.group === group && item.status === "shared");
  return { usage: shared("usage"), crashes: shared("crashes"), questions: shared("questions") };
}

/* Screen paths: the first segment names the screen; a later segment is kept
   only when it is one of the app's own sub-tabs, otherwise it is an id or a
   slug and becomes a placeholder. */
const SCREENS = new Set([
  "", "favorites", "profile", "statistics", "company", "review", "notifications", "settings",
  "welcome", "compare", "job", "jobs", "position",
]);
const SUB_TABS = new Set([
  "direction", "experience",
  "companies", "intelligence", "schedule", "recipes", "language", "privacy", "retention", "plugins",
  "overview", "demand", "velocity", "compensation", "levels", "trajectory", "skills", "trends", "overlap", "clusters",
]);

export function screenPath(pathname: string): string {
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length === 0) return "/";
  const [first, ...rest] = parts;
  if (!SCREENS.has(first)) return "/:screen";
  return "/" + [first, ...rest.map((part) => (SUB_TABS.has(part) ? part : ":id"))].join("/");
}

/** Any URL of this app reduced to its screen; any other site's to a marker,
 *  since its host alone can name an employer. The app's own script files
 *  name no record and stay whole, so a crash report can still be read. */
export function screenUrl(value: string): string {
  try {
    const url = new URL(value, window.location.origin);
    if (url.origin !== window.location.origin) return "<url>";
    if (url.pathname.startsWith("/assets/")) return `${url.origin}${url.pathname}`;
    return `${url.origin}${screenPath(url.pathname)}`;
  } catch {
    return "";
  }
}

/** Quoted text, each opening quote with its own closing one: a curly quote
 *  closes on its partner, never on itself. */
const QUOTED = /"[^"\n]{1,200}"|'[^'\n]{1,200}'|`[^`\n]{1,200}`|“[^”\n]{1,200}”|‘[^’\n]{1,200}’|«[^»\n]{1,200}»/g;

export function redactMessage(message: string): string {
  return message
    .replace(/[a-z][a-z0-9+.-]*:\/\/\S+/gi, "<url>")
    .replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, "<email>")
    .replace(QUOTED, "<text>")
    .replace(/\d{4,}/g, "<n>");
}

/* Dropped under any prefix the library gives them ($referrer, $initial_referrer,
   $session_entry_referrer, ...): what the referrer reveals, page titles, the
   target of an outbound click, and the stored first-visit record. */
const DROPPED = [
  "referrer", "referring_domain", "search_engine", "ph_keyword", "title", "external_click_url", "initial_person_info",
];
const ABSOLUTE_URL = /^[a-z][a-z0-9+.-]*:\/\//i;

function dropped(key: string): boolean {
  const bare = key.replace(/^\$+/, "");
  return DROPPED.some((name) => bare === name || bare.endsWith(`_${name}`));
}

function cleanString(key: string, value: string): string {
  if (/pathname$/i.test(key)) return screenPath(value);
  if (ABSOLUTE_URL.test(value)) return screenUrl(value);
  if (/url$/i.test(key) && value.startsWith("/")) return screenPath(value);
  return value;
}

/* Every value at any depth, and every key that is itself an address. Lists
   whose keys land on one screen are merged, as two jobs' heatmaps are. */
function clean(value: unknown, key: string, depth: number): unknown {
  if (typeof value === "string") return cleanString(key, value);
  if (depth > 8 || value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map((item) => clean(item, key, depth + 1));
  const out: Record<string, unknown> = {};
  for (const [name, item] of Object.entries(value)) {
    if (dropped(name)) continue;
    const at = ABSOLUTE_URL.test(name) ? screenUrl(name) : name;
    const cleaned = clean(item, name, depth + 1);
    const earlier = out[at];
    out[at] = Array.isArray(earlier) && Array.isArray(cleaned) ? [...earlier, ...cleaned] : earlier ?? cleaned;
  }
  return out;
}

function cleanProperties(raw: Record<string, unknown> | undefined): Record<string, unknown> | undefined {
  if (!raw) return raw;
  const properties = clean(raw, "", 0) as Record<string, unknown>;
  const exceptions = properties.$exception_list;
  if (Array.isArray(exceptions)) {
    for (const entry of exceptions as Array<Record<string, unknown>>) {
      if (typeof entry.value === "string") entry.value = redactMessage(entry.value);
    }
  }
  if (typeof properties.$exception_message === "string") {
    properties.$exception_message = redactMessage(properties.$exception_message);
  }
  return properties;
}

const RECENT_MAX = 100;
export const recentEvents: { event: string; at: string }[] = [];

/** The last line of defence before anything leaves: see the module comment. */
export function beforeSend(event: CaptureResult | null): CaptureResult | null {
  if (!event) return null;
  type Event = NonNullable<CaptureResult>;
  event.properties = cleanProperties(event.properties) as Event["properties"];
  if (event.$set) event.$set = cleanProperties(event.$set) as Event["$set"];
  if (event.$set_once) event.$set_once = cleanProperties(event.$set_once) as Event["$set_once"];
  recentEvents.unshift({ event: event.event, at: new Date().toISOString() });
  recentEvents.length = Math.min(recentEvents.length, RECENT_MAX);
  return event;
}

/** The whole configuration, from what is shared. Pure: held by a test. */
export function sharingConfig(state: UsageState, shared: SharedGroups): NonNullable<Config> {
  const usage = shared.usage;
  return {
    api_host: state.host,
    defaults: "2026-01-30",
    bootstrap: { distinctID: state.install_id ?? undefined, isIdentifiedID: true },
    person_profiles: "identified_only",
    persistence: "localStorage",
    opt_out_capturing_by_default: true,
    disable_external_dependency_loading: true,
    opt_in_site_apps: false,
    disable_web_experiments: true,
    disable_product_tours: true,
    disable_conversations: true,
    advanced_disable_flags: !usage,
    save_referrer: false,
    // Usage: screens, clicks (no text, no attributes), heatmaps, timings.
    capture_pageview: usage ? "history_change" : false,
    capture_pageleave: usage,
    autocapture: usage ? { capture_copied_text: false } : false,
    rageclick: usage,
    capture_dead_clicks: usage,
    capture_heatmaps: usage,
    capture_performance: usage ? { web_vitals: true, network_timing: false } : false,
    mask_all_text: true,
    mask_all_element_attributes: true,
    // Crash reports.
    capture_exceptions: shared.crashes,
    // No session recordings, whatever the project says (see the module comment).
    disable_session_recording: true,
    enable_recording_console_log: false,
    // Feedback surveys.
    disable_surveys: !shared.questions,
    before_send: beforeSend,
  } as NonNullable<Config>;
}

let client: PostHog | null = null;
let desiredState: UsageState | null = null;
let loading: Promise<void> | null = null;

function configureClient(state: UsageState): void {
  if (!client) return;
  const shared = sharedGroups(state);
  const config = sharingConfig(state, shared);
  const changedId = client.get_distinct_id() !== state.install_id;
  if (changedId) client.opt_out_capturing();
  client.set_config(config);
  if (changedId) {
    // Bootstrap the replacement directly so identify cannot link it to the old ID.
    client.reset({ resetDeviceID: true, bootstrap: config.bootstrap });
  }
  if (!Object.values(shared).some(Boolean)) {
    client.opt_out_capturing();
    return;
  }
  if (client.has_opted_out_capturing()) client.opt_in_capturing({ captureEventName: false });
  if (shared.usage && state.install_id) client.identify(state.install_id);
}

/** Make the browser do exactly what `state` shares: load and start on the
 *  first share, reconfigure on a change, stop everything when nothing is. */
export async function applySharing(state: UsageState): Promise<void> {
  desiredState = state;
  if (client) {
    configureClient(state);
    return;
  }
  if (!Object.values(sharedGroups(state)).some(Boolean)) return;
  if (!loading) {
    loading = import("posthog-js/dist/module.full.no-external").then((module: PostHogModule) => {
      const latest = desiredState!;
      const shared = sharedGroups(latest);
      if (!Object.values(shared).some(Boolean)) return;
      client = module.default;
      // Persisted SDK identities must not capture or merge before the server ID is applied.
      client.init(latest.project_key, {
        ...sharingConfig(latest, { usage: false, crashes: false, questions: false }), bootstrap: {},
      });
      client.opt_out_capturing();
      configureClient(latest);
    }).finally(() => { loading = null; });
  }
  await loading;
}
