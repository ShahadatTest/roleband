/* Scope-surface fixtures shared by profile.spec.ts (Profile › Direction owns
   the scope editor) and the harnesses and specs of other screens that mock
   the same endpoints their shell touches. Each is held to its generated wire
   type, so a fixture that drifts from the API fails `npm run typecheck:ux`. */

import type { CompanyList, ScopeCatalog, ScopePreview } from "../../src/api";
import { emptyScopeCellsFixture } from "../../src/test/fixtures";

export const scopeCatalog = {
  settings: {
    enabled_role_groups: ["software_engineering"],
    enabled_seniority_bands: ["staff"],
    enabled_role_tracks: ["management", "product_program", "technical"],
    enabled_location_groups: ["silicon_valley", "uk", "singapore"],
    enabled_domain_groups: ["ai_ml", "logistics_fulfillment"],
    excluded_domain_groups: [],
    excluded_location_groups: [],
    include_unstated_level: true,
    // The server's reading of the two flat lists above: every saved kind,
    // holding the one saved family of the three this catalog lists.
    role_answers: [
      { track: "management", roles: ["software_engineering"] },
      { track: "product_program", roles: ["software_engineering"] },
      { track: "technical", roles: ["software_engineering"] },
    ],
  },
  domains: [
    { slug: "ai_ml", selected: true, count: 12, examples: ["Applied AI"], kind: "technology" },
    { slug: "logistics_fulfillment", selected: true, count: 7, examples: ["Fulfillment & Operations Management"], kind: "function" },
  ],
  unclassified_domain_count: 3,
  locations: [
    { slug: "silicon_valley", display: "Silicon Valley", default_enabled: true, selected: true, new: false, count: 6, kind: "metro", parent: "united_states", uncovered_by: [], prominent: true },
    { slug: "united_states", display: "United States", default_enabled: true, selected: false, new: false, count: 9, kind: "country", parent: null, uncovered_by: [], prominent: true },
    { slug: "europe", display: "Europe", default_enabled: false, selected: false, new: false, count: 0, kind: "region", parent: null, uncovered_by: [], prominent: true },
    { slug: "uk", display: "United Kingdom", default_enabled: true, selected: true, new: false, count: 4, kind: "country", parent: "europe", uncovered_by: [], prominent: true },
    { slug: "singapore", display: "Singapore", default_enabled: true, selected: true, new: false, count: 2, kind: "country", parent: null, uncovered_by: [], prominent: true },
  ],
  levels: [
    { slug: "entry", order: 0, default_enabled: false, selected: false, new: false, count: 2, decoder: { google: { company_wide: "L3" } } },
    { slug: "staff", order: 2, default_enabled: true, selected: true, new: false, count: 7, decoder: { google: { company_wide: "L6" }, openai: { company_wide: "L5" } } },
  ],
  unstated_level_count: 0,
  // No track declares its own level range (`allowed_bands` empty), so no
  // track gates a level.
  tracks: [
    { slug: "management", order: 0, default_enabled: true, selected: true, new: false, count: 5, allowed_bands: [] },
    { slug: "product_program", order: 1, default_enabled: true, selected: true, new: false, count: 4, allowed_bands: [] },
    { slug: "technical", order: 2, default_enabled: true, selected: true, new: false, count: 9, allowed_bands: [] },
    { slug: "business_customer", order: 3, default_enabled: true, selected: true, new: false, count: 7, allowed_bands: [] },
  ],
  joint_counts_ready: true,
  scope_cells: emptyScopeCellsFixture,
  categories: [
    {
      slug: "technology",
      groups: [
        {
          slug: "software_engineering", total: 3,
          default_enabled: false, selected: true, enabled: true, new: false,
          band_counts: { entry: 2, staff: 1 },
          band_track_counts: { entry: { technical: 2 }, staff: { technical: 1 } },
          joint_complete: true,
        },
        {
          slug: "security_engineering", total: 4,
          default_enabled: false, selected: false, enabled: false, new: false,
          band_counts: { staff: 4 },
          band_track_counts: { staff: { management: 4 } },
          joint_complete: true,
        },
      ],
    },
    {
      slug: "product",
      groups: [
        {
          slug: "technical_program_management", total: 2,
          default_enabled: true, selected: false, enabled: false, new: false,
          band_counts: { staff: 2 },
          band_track_counts: { staff: { product_program: 2 } },
          joint_complete: true,
        },
      ],
    },
  ],
  companies: [{ slug: "google", display: "Google", enabled: true, role_catalog_status: "ready", role_catalog_scanned_at: null, role_catalog_error: null }],
} satisfies ScopeCatalog;

/** `POST /api/scope/preview`: a save that changes nothing. */
export const scopePreview = {
  on_board_now: 0, on_board_after: 0, adds_now: 0, adds_on_board: 0, adds_later: 0, scan_running: false, examples: [],
} satisfies ScopePreview;

export const companyList = {
  companies: [
    {
      slug: "google", display: "Google", adapter: "greenhouse", board_token: "google",
      careers_url: null, status: "active", enabled: true, visible: true, source: "builtin",
      builtin: true, job_count: 12, role_catalog_status: "ready",
      role_catalog_scanned_at: null, role_catalog_error: null,
      detected_family: null, pending_reason: null,
    },
  ],
} satisfies CompanyList;
