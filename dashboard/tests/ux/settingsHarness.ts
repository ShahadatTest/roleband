import { mockApi, mockGet } from "./fixtures";
/* Settings' route harness and the fixtures its beforeEach serves.

   Every Settings tab shares ONE harness because the shell is what they have
   in common: several tests assert a fact ACROSS tabs (the wash, the header
   height, the panel gutter), so a per-tab harness would have to be
   re-entered mid-test. installSettingsRoutes is a function for the same reason
   as the board's: routes are per-page side effects, not shared state. */

import { type Page } from "@playwright/test";
import {
  agentAccessFixture,
  facetsFixture,
  intelligenceFitFixture,
  intelligenceStatusFixture,
  jobFixture,
  jobListFixture,
  localModelProfileFixture,
  localModelStateFixture,
  localModelTestResultFixture,
  localServerStatusFixture,
  notificationsFixture,
  otherLocalModelProfileFixture,
  recipeSummaryFixture,
  priceFeedStateFixture,
  retentionStateFixture,
  schedulePlanFixture,
  statsFixture,
  statusFixture,
  pluginDetailFixture,
  pluginFixture,
  pluginsFixture,
} from "../../src/test/fixtures";
import { companyList, scopeCatalog, scopePreview } from "./scopeFixtures";
import type { CompanyDiscoveryState } from "../../src/api";

export const companyDiscovery = {
  // Sectors are slugs; the register names them from the catalog.
  sectors: [
    {
      slug: "faang",
      company_count: 2, ready_count: 2, selected_count: 1,
    },
    {
      slug: "ai",
      company_count: 1, ready_count: 0, selected_count: 0,
    },
    {
      slug: "robotics",
      company_count: 1, ready_count: 0, selected_count: 0,
    },
    {
      // This pair exists only to host the two-sector row below. Every other
      // sector in this fixture already carries assertions (AI is the sector
      // that must VANISH when planned rows are hidden, Robotics is the "no
      // connectors" case, Cloud anchors the scroll-order test), so the chip
      // squeeze lives here rather than move a contract unrelated to it.
      slug: "gaming",
      company_count: 1, ready_count: 1, selected_count: 0,
    },
    {
      slug: "semiconductors",
      company_count: 1, ready_count: 1, selected_count: 0,
    },
    {
      slug: "cloud-data-devtools",
      company_count: 10, ready_count: 10, selected_count: 0,
    },
  ],
  companies: [
    {
      slug: "google", display: "Google", careers_url: "https://google.com/careers",
      sectors: ["faang"], aliases: [], connector_state: "live",
      parked_reason: null, selectable: true, tracked: true,
      enabled: true, visible: true, builtin: true, curated: true, directory: false, wall: null, consented: false, status: "active",
    },
    {
      slug: "apple", display: "Apple", careers_url: "https://apple.com/careers",
      sectors: ["faang"], aliases: [], connector_state: "ready",
      parked_reason: null, selectable: true, tracked: false,
      enabled: false, visible: true, builtin: true, curated: true, directory: false, wall: null, consented: false, status: null,
    },
    {
      // Two sectors, and the OTHER one has a long display name: this row
      // renders an "also Semiconductors & compute" chip beside a short company
      // name, the shape that can collapse the name to 0px.
      slug: "nvidia", display: "NVIDIA", careers_url: "https://nvidia.example/careers",
      sectors: ["gaming", "semiconductors"], aliases: [], connector_state: "ready",
      parked_reason: null, selectable: true, tracked: false,
      enabled: false, visible: true, builtin: false, curated: false, directory: false, wall: null, consented: false, status: null,
    },
    {
      slug: "snowflake", display: "Snowflake", careers_url: "https://careers.snowflake.com",
      sectors: ["ai"], aliases: [], connector_state: "planned",
      parked_reason: null, selectable: true, tracked: false,
      enabled: false, visible: true, builtin: false, curated: false, directory: false, wall: null, consented: false, status: null,
    },
    {
      slug: "tesla", display: "Tesla", careers_url: "https://tesla.com/careers",
      sectors: ["robotics"], aliases: [], connector_state: "parked",
      parked_reason: "bot_protected", selectable: false,
      tracked: false, enabled: false, visible: true, builtin: false, curated: false, directory: false, wall: null, consented: false, status: null,
    },
    {
      slug: "datadog", display: "Datadog", careers_url: "https://datadog.example/careers",
      sectors: ["cloud-data-devtools"], aliases: [], connector_state: "ready",
      parked_reason: null, selectable: true, tracked: false,
      enabled: false, visible: true, builtin: false, curated: false, directory: false, wall: null, consented: false, status: null,
    },
    {
      slug: "github", display: "GitHub", careers_url: "https://github.example/careers",
      sectors: ["cloud-data-devtools"], aliases: [], connector_state: "ready",
      parked_reason: null, selectable: true, tracked: false,
      enabled: false, visible: true, builtin: false, curated: false, directory: false, wall: null, consented: false, status: null,
    },
    {
      slug: "gitlab", display: "GitLab", careers_url: "https://gitlab.example/careers",
      sectors: ["cloud-data-devtools"], aliases: [], connector_state: "ready",
      parked_reason: null, selectable: true, tracked: false,
      enabled: false, visible: true, builtin: false, curated: false, directory: false, wall: null, consented: false, status: null,
    },
    {
      slug: "hashicorp", display: "HashiCorp", careers_url: "https://hashicorp.example/careers",
      sectors: ["cloud-data-devtools"], aliases: [], connector_state: "ready",
      parked_reason: null, selectable: true, tracked: false,
      enabled: false, visible: true, builtin: false, curated: false, directory: false, wall: null, consented: false, status: null,
    },
    {
      slug: "mongodb", display: "MongoDB", careers_url: "https://mongodb.example/careers",
      sectors: ["cloud-data-devtools"], aliases: [], connector_state: "ready",
      parked_reason: null, selectable: true, tracked: false,
      enabled: false, visible: true, builtin: false, curated: false, directory: false, wall: null, consented: false, status: null,
    },
    {
      slug: "confluent", display: "Confluent", careers_url: "https://confluent.example/careers",
      sectors: ["cloud-data-devtools"], aliases: [], connector_state: "ready",
      parked_reason: null, selectable: true, tracked: false,
      enabled: false, visible: true, builtin: false, curated: false, directory: false, wall: null, consented: false, status: null,
    },
    {
      slug: "vercel", display: "Vercel", careers_url: "https://vercel.example/careers",
      sectors: ["cloud-data-devtools"], aliases: [], connector_state: "ready",
      parked_reason: null, selectable: true, tracked: false,
      enabled: false, visible: true, builtin: false, curated: false, directory: false, wall: null, consented: false, status: null,
    },
    {
      slug: "docker", display: "Docker", careers_url: "https://docker.example/careers",
      sectors: ["cloud-data-devtools"], aliases: [], connector_state: "ready",
      parked_reason: null, selectable: true, tracked: false,
      enabled: false, visible: true, builtin: false, curated: false, directory: false, wall: null, consented: false, status: null,
    },
    {
      slug: "elastic", display: "Elastic", careers_url: "https://elastic.example/careers",
      sectors: ["cloud-data-devtools"], aliases: [], connector_state: "ready",
      parked_reason: null, selectable: true, tracked: false,
      enabled: false, visible: true, builtin: false, curated: false, directory: false, wall: null, consented: false, status: null,
    },
    {
      slug: "grafana", display: "Grafana Labs", careers_url: "https://grafana.example/careers",
      sectors: ["cloud-data-devtools"], aliases: [], connector_state: "ready",
      parked_reason: null, selectable: true, tracked: false,
      enabled: false, visible: true, builtin: false, curated: false, directory: false, wall: null, consented: false, status: null,
    },
  ],
} satisfies CompanyDiscoveryState;

export // Open-role counts are a separate request from the roster on purpose, so the
// Company Explorer paints before this aggregate lands.
const companyOpenCounts = { counts: { google: 12 }, not_counted: {}, unplaced: {}, unsorted: {}, last_read: {} };

/* The schedule plan is on: the dial draws a quick scan this
   afternoon and tomorrow's full scan when the computer comes on. OpenAI and
   Anthropic keep a reconciliation time the user set, so they keep their marks
   and the dial's editing contract below still has companies to hold. */
export const syncSchedule = {
  generated_at: "2026-07-28T14:30:00Z",
  enabled: true,
  tick_seconds: 600,
  max_parallel_providers: 2,
  authoritative_stale_hours: 30,
  plan: schedulePlanFixture({
    pinned: 2,
    upcoming: [
      { at: "2026-07-28T15:00:00Z", kind: "quick", seconds: 600, estimated: false, on_wake: false, running: false, ready_by: false },
      { at: "2026-07-29T09:00:00Z", kind: "full", seconds: 2460, estimated: false, on_wake: true, running: false, ready_by: false },
    ],
  }),
  providers: [
    {
      provider: "greenhouse", state: "ready", cooldown_until: null,
      last_started_at: "2026-07-28T13:00:00Z", last_finished_at: "2026-07-28T13:02:00Z",
      last_outcome: "ok", binding_count: 2,
    },
    {
      provider: "meta", state: "policy_denied", cooldown_until: null,
      last_started_at: null, last_finished_at: null, last_outcome: null, binding_count: 1,
    },
  ],
  bindings: [
    {
      binding_id: 1, company: "openai", provider: "greenhouse",
      closure_capability: "authoritative", scheduled: true,
      discovery_enabled: true, discovery_cadence_seconds: 21600,
      reconcile_cadence_seconds: 86400, last_discovery_at: "2026-07-28T08:00:00Z",
      last_reconcile_at: "2026-07-27T20:00:00Z", next_discovery_at: "2026-07-28T16:00:00Z",
      next_reconcile_at: "2026-07-28T20:00:00Z", eligible_discovery_at: "2026-07-28T16:00:00Z",
      discovery_anchor_minute: null, reconcile_anchor_minute: 20 * 60, schedule_timezone: "UTC",
      eligible_reconcile_at: "2026-07-28T20:00:00Z", manual_requested_at: null,
      last_outcome: "ok", last_new_count: 1, consecutive_empty_discoveries: 0,
      provider_state: "ready", cooldown_until: null, status: "scheduled",
    },
    {
      binding_id: 2, company: "anthropic", provider: "greenhouse",
      closure_capability: "authoritative", scheduled: true,
      discovery_enabled: true, discovery_cadence_seconds: 28800,
      reconcile_cadence_seconds: 86400, last_discovery_at: null, last_reconcile_at: null,
      next_discovery_at: "2026-07-28T17:00:00Z", next_reconcile_at: "2026-07-28T21:00:00Z",
      discovery_anchor_minute: null, reconcile_anchor_minute: 21 * 60, schedule_timezone: "UTC",
      eligible_discovery_at: "2026-07-28T17:00:00Z", eligible_reconcile_at: "2026-07-28T21:00:00Z",
      manual_requested_at: null, last_outcome: null, last_new_count: 0,
      consecutive_empty_discoveries: 3, provider_state: "ready",
      cooldown_until: null, status: "scheduled",
    },
    {
      binding_id: 3, company: "meta", provider: "meta",
      closure_capability: "authoritative", scheduled: true,
      discovery_enabled: false, discovery_cadence_seconds: 21600,
      reconcile_cadence_seconds: 86400, last_discovery_at: null, last_reconcile_at: null,
      next_discovery_at: "2026-07-28T18:00:00Z", next_reconcile_at: "2026-07-28T22:00:00Z",
      discovery_anchor_minute: null, reconcile_anchor_minute: null, schedule_timezone: null,
      eligible_discovery_at: null, eligible_reconcile_at: null, manual_requested_at: null,
      last_outcome: null, last_new_count: 0, consecutive_empty_discoveries: 0,
      provider_state: "policy_denied", cooldown_until: null, status: "policy_denied",
    },
  ],
};

/* The same plan partway through its day: a quick scan is running, and
   tomorrow's full scan has no measured length yet, so the plan's list, the
   dial and that scan's inspector say a running time and a guessed length. */
export const syncScheduleUnderway = {
  ...syncSchedule,
  plan: schedulePlanFixture({
    ...syncSchedule.plan,
    upcoming: [
      { at: "2026-07-28T14:20:00Z", kind: "quick", seconds: 600, estimated: false, on_wake: false, running: true, ready_by: false },
      { at: "2026-07-29T09:00:00Z", kind: "full", seconds: 2460, estimated: true, on_wake: true, running: false, ready_by: false },
    ],
  }),
};

export const intelligence = intelligenceStatusFixture;

export const intelligenceFit = intelligenceFitFixture;

const agentAccess = agentAccessFixture;

const localModelProfile = localModelProfileFixture;

export const otherLocalModelProfile = otherLocalModelProfileFixture;

const syncTargets = { companies: [], freshness_max_hours: 24 };

/** The three reads the Companies register issues on arrival. A spec that only
    NAVIGATES there (a link from another screen) still owns them: the requests
    fire after the URL changes, so an unmocked one fails whichever test is still
    running when it lands, intermittently. */
export async function installCompanyRegisterRoutes(page: Page) {
  await mockGet(page, "/api/sync/targets", (route) => route.fulfill({ json: syncTargets }));
  await mockGet(page, "/api/companies/discovery", (route) =>
    route.fulfill({ json: companyDiscovery }));
  await mockGet(page, "/api/companies/open-counts", (route) =>
    route.fulfill({ json: companyOpenCounts }));
  // Every search of two or more characters also asks the directory of other
  // companies; by default it knows none.
  await mockGet(page, "/api/companies/directory?**", (route) =>
    route.fulfill({ json: { size: 0, match_count: 0, matches: [] } }));
  // ... and the whole set's status: no set by default, so a spec
  // that is not about it sees the register it was written for.
  await mockGet(page, "/api/companies/directory/status", (route) =>
    route.fulfill({ json: { size: 0, following: false, since: null, checked: 0, to_check: 0, with_roles: 0, waiting_for_power: false } }));
}

export async function installSettingsRoutes(page: Page) {
  await installCompanyRegisterRoutes(page);
  await mockGet(page, "/api/scope/rules", (route) => route.fulfill({ json: { rules: [] } }));
  await mockGet(page, "/api/profile/suggestions", (route) => route.fulfill({ json: { suggestions: [] } }));
  await mockGet(page, "/api/stats", (route) => route.fulfill({ json: statsFixture }));
  await mockGet(page, "/api/status", (route) => route.fulfill({ json: statusFixture }));
  await mockGet(page, "/api/plugins", (route) => route.fulfill({ json: pluginsFixture() }));
  await mockGet(page, "/api/plugins/example-pay", (route) =>
    route.fulfill({ json: pluginDetailFixture({ ...pluginFixture(), runs: [pluginFixture().last_run!] }) }));
  await mockGet(page, "/api/schedule?**", (route) => route.fulfill({ json: syncSchedule }));
  await mockGet(page, "/api/facets", (route) => route.fulfill({ json: facetsFixture }));
  await mockGet(page, "/api/notifications**", (route) => route.fulfill({ json: notificationsFixture }));
  await mockGet(page, "/api/jobs/101", (route) => route.fulfill({ json: jobFixture }));
  await mockGet(page, "/api/jobs/*/similar**", (route) => route.fulfill({ json: { scope: "cross", items: [] } }));
  await mockGet(page, "/api/jobs?**", (route) => route.fulfill({ json: jobListFixture }));
  await mockGet(page, "/api/scope/catalog", (route) => route.fulfill({ json: scopeCatalog }));
  await mockApi(page, ["POST"], "/api/scope/preview", (route) => route.fulfill({ json: scopePreview }));
  await mockGet(page, "/api/profile", (route) => route.fulfill({
    json: { profile: null, scope_configured: true },
  }));
  await mockGet(page, "/api/companies", (route) => route.fulfill({ json: companyList }));
  await mockGet(page, "/api/intelligence", (route) => route.fulfill({ json: intelligence }));
  await mockGet(page, "/api/intelligence/fit", (route) => route.fulfill({ json: intelligenceFit }));
  await mockApi(page, ["GET", "PUT"], "/api/intelligence/agents", async (route) => {
    const body = route.request().method() === "PUT" ? route.request().postDataJSON() : {};
    await route.fulfill({ json: { ...agentAccess, ...body } });
  });
  await mockGet(page, "/api/connector-recipes", (route) =>
    route.fulfill({ json: [recipeSummaryFixture()] }));
  await mockGet(page, "/api/settings/retention", (route) =>
    route.fulfill({ json: retentionStateFixture() }));
  await mockGet(page, "/api/settings/price-feed", (route) =>
    route.fulfill({ json: priceFeedStateFixture() }));
  await mockGet(page, "/api/intelligence/cloud-models", (route) => route.fulfill({ json: { profiles: [] } }));
  await mockGet(page, "/api/intelligence/local-models", (route) =>
    route.fulfill({ json: localModelStateFixture }));
  await mockGet(page, "/api/intelligence/local-models/server", (route) =>
    route.fulfill({ json: localServerStatusFixture }));
  await mockApi(page, "POST", `/api/intelligence/local-models/${localModelProfile.id}/test`, (route) =>
    route.fulfill({ json: localModelTestResultFixture }));
}
