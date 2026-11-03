import {
  AgentAccessState,
  CloudLLMProfile,
  CloudLLMTestResult,
  CompanyCard,
  CompanyProfileDetail,
  CompanyProfileFieldWrite,
  CompanyProfileSummary,
  Demand,
  DescriptionDiffEvidence,
  DuplicateLLMAssessment,
  DuplicateProposal,
  DuplicateVerdictResult,
  Facets,
  IntelligenceFit,
  IntelligenceStatus,
  Job,
  JobCompPackage,
  JobDetail,
  JobDetailRow,
  JobList,
  LevelGuide,
  LocalLLMProfile,
  LocalLLMState,
  LocalLLMTestResult,
  LocalServerStatus,
  NotificationList,
  ProfileField,
  ProfileSuggestion,
  RecipeCheck,
  RecipeDetail,
  RecipeRevision,
  RecipeSummary,
  PriceFeedState,
  RetentionState,
  ProfileState,
  ScopeCatalog,
  ScopeCells,
  ScopeSettingsPayload,
  ScopeSettingsSaveResult,
  StatisticsOverview,
  Stats,
  SyncResult,
  SystemStatus,
  PluginDetail,
  PluginRunView,
  PluginRobots,
  PluginView,
  PluginsResponse,
  ReferenceView,
  TwinProposal,
  TrackedCompany,
  TwinVerdictResult,
  SchedulePlan,
  UsageState,
  UsageStatus,
} from "../api";

/** `GET /api/usage` as the server sends it, every group in `status` (the UX
 *  guard's default is "declined": no spec is asked unless it says so). The
 *  fingerprints are stand-ins; the server echoes back whatever it sent. */
export function usageStateFixture(status: UsageStatus = "declined", overrides: Partial<UsageState> = {}): UsageState {
  const scope: Record<string, string[]> = {
    usage: ["autocapture", "dead_clicks", "early_access", "experiments", "feature_flags", "heatmaps",
      "pageleave", "pageviews", "person_profile", "rage_clicks", "web_vitals"],
    crashes: ["exceptions"],
    questions: ["surveys"],
  };
  return {
    groups: (["usage", "crashes", "questions"] as const).map((group) => ({
      group,
      status,
      fingerprint: `${group}-fingerprint`,
      browser_scope: scope[group],
      decided_at: status === "undecided" ? null : "2026-10-08T12:00:00Z",
    })),
    blocked_by: null,
    install_id: status === "shared" ? "8f14e45f-ceea-4e7a-9b3a-1f2d3c4b5a69" : null,
    host: "https://eu.i.posthog.com",
    project_key: "phc_test",
    last_sent_at: null,
    pending_events: 0,
    ...overrides,
  };
}

/** A complete comp package as `GET /api/jobs/{id}` sends it: every key present,
 *  the offer policy included. The defaults are an unchecked posting with our
 *  estimate beside it; override the keys a test is about. */
export function compPackageFixture(overrides: Partial<JobCompPackage> = {}): JobCompPackage {
  return {
    state: "unchecked",
    basis: null,
    currency: null,
    pay_period: null,
    stated: null,
    bonus_pct: null,
    components: [],
    total: null,
    estimate: { low: 650000, median: 735000, high: 820000, provenance: "Google L6 reported median (product_management)" },
    split_source: "heuristic",
    split_provider: null,
    split_as_of: null,
    equity_basis: null,
    market_gap: null,
    reconciliation: null,
    no_split_reason: null,
    snippet: null,
    confidence: null,
    policy: {
      verified: false,
      bonus_rule: null,
      equity_rule: null,
      vesting: null,
      sign_on_bridges_vesting: false,
      base_cap_usd: null,
      annual_refresh: null,
      estimated: [],
      unknown: [],
    },
    ...overrides,
  };
}

/** A complete detail response built on `jobFixture`. The detail route always
 *  sends every one of these keys, so a test standing in for it cannot hand a
 *  component a shape the server never produces — the type is generated from the
 *  route's response model. */
export function jobDetailFixture(overrides: Partial<JobDetail> = {}): JobDetail {
  return {
    ...jobFixture,
    description_text: "Lead API product strategy.",
    description_html: null,
    // What the server sends for a posting with no standing verdict to give.
    posting_reality: null,
    // Null until the posting's own page has been read.
    application_form: null,
    application_form_readable: false,
    // A posting with no earlier posting of its role that counts.
    role_since: null,
    role_days: null,
    role_postings: null,
    // Null without a pay floor, or a band it cannot compare.
    pay_floor_check: null,
    description_sections: [],
    disclosed_comp: null,
    feedback_reason: null,
    pursuit: null,
    relevance_review: null,
    comp_sources: [],
    comp_package: compPackageFixture(),
    pay_source: { plugin: null, plugin_name: null, covered: true },
    lifecycle: [],
    requirements: { state: "unavailable", extractor_version: null, skills: [], qualifications: [], required_years: null },
    ...overrides,
  };
}

/** A posting as the lineage and twin routes pair it: `jobFixture`'s row plus the
 *  posting's own text and stated pay, and none of what the detail route adds. */
export function jobDetailRowFixture(overrides: Partial<JobDetailRow> = {}): JobDetailRow {
  const row: Job = { ...jobFixture };
  delete row.comp_sources;
  delete row.lifecycle;
  return {
    ...row,
    description_text: "Lead API product strategy.",
    description_html: null,
    description_sections: [],
    disclosed_comp: null,
    ...overrides,
  };
}

/** A suspected duplicate as both lineage surfaces send it, awaiting review. */
export function duplicateProposalFixture(overrides: Partial<DuplicateProposal> = {}): DuplicateProposal {
  return {
    proposal_kind: "duplicate",
    id: 7,
    job_id: 2,
    prior_job_id: 1,
    relation: "repost",
    method: "embedding",
    confidence: "suspected",
    status: "pending",
    score: 0.9,
    gap_days: 20,
    reasons: [],
    said: [{ code: "descriptions_alike", params: { pct: 90 } }],
    decision: null,
    decision_changes: 0,
    reviewed_at: null,
    ...overrides,
  };
}

/** A suspected twin: `job_id` is the pair's higher id and there is no gap. */
export function twinProposalFixture(overrides: Partial<TwinProposal> = {}): TwinProposal {
  return {
    proposal_kind: "twin",
    id: 19,
    job_id: 2,
    prior_job_id: 1,
    relation: "twin",
    method: "section_diff",
    confidence: "suspected",
    status: "pending",
    score: 0.87,
    gap_days: null,
    title_similarity: 0.9,
    reasons: [],
    said: [{ code: "titles_alike", params: { pct: 90 } }],
    decision: null,
    decision_changes: 0,
    reviewed_at: null,
    description_diff: null,
    ...overrides,
  };
}

/** The description evidence a twin review item carries for its pair. */
export const descriptionDiffFixture: DescriptionDiffEvidence = {
  comparable: true,
  equivalent: false,
  shared_count: 1,
  left_only_count: 1,
  right_only_count: 1,
  difference_ratio: 0.5,
  token_similarity: 0.62,
  left_only: [{ section_key: "responsibilities", section_title: "Responsibilities", text: "Own the API roadmap." }],
  right_only: [{ section_key: "responsibilities", section_title: "Responsibilities", text: "Own enterprise adoption." }],
};

/** `POST /api/lineage/links/{id}/review` after a `confirmed` verdict. */
export function duplicateVerdictFixture(overrides: Partial<DuplicateVerdictResult> = {}): DuplicateVerdictResult {
  return {
    id: 7,
    status: "confirmed",
    reviewed_at: "2026-07-15T15:00:00Z",
    lineages: 1,
    decision: "duplicate",
    twin_link_id: null,
    kept: [],
    ...overrides,
  };
}

/** `POST /api/twins/links/{id}/review` after a `confirmed` verdict. */
export function twinVerdictFixture(overrides: Partial<TwinVerdictResult> = {}): TwinVerdictResult {
  return {
    id: 19,
    status: "confirmed",
    decision: "twin",
    reviewed_at: "2026-07-15T15:00:00Z",
    lineages: 1,
    kept: [],
    ...overrides,
  };
}

/** The local model's advice on a proposal, metrics complete. */
export function relationshipAssessmentFixture(overrides: Partial<DuplicateLLMAssessment> = {}): DuplicateLLMAssessment {
  return {
    profile_id: "profile12345",
    provider: "omlx",
    model: "Ornith-1.0-35B-5bit-mlx",
    prompt_version: "duplicate_review/v2",
    assessment: {
      recommendation: "confirmed",
      confidence: 0.91,
      summary: "Same title, location, and responsibilities; the newer record is a relist.",
      matching_evidence: [],
      differences: [],
    },
    metrics: {
      wall_time_ms: 2400,
      total_time_ms: 2380,
      time_to_first_token_ms: 310,
      prompt_eval_ms: 600,
      generation_ms: 1780,
      prompt_tokens: 640,
      completion_tokens: 172,
      total_tokens: 812,
      cached_prompt_tokens: 0,
      prompt_tokens_per_second: 1066.7,
      generation_tokens_per_second: 96.6,
      finish_reason: "stop",
      context_window: 32768,
    },
    ...overrides,
  };
}

// A list row: every `GET /api/jobs` row carries `posting_reality`.
export const jobFixture: Job & Pick<JobList["items"][number], "posting_reality"> = {
  posting_reality: null,
  id: 101,
  company: "openai",
  req_id: "req-101",
  title: "Staff Product Manager, API",
  url: "https://example.test/jobs/101",
  department: "Product",
  team: "API",
  locations: ["San Francisco, CA"],
  location_groups: ["silicon_valley"],
  workplace_type: "hybrid",
  level_band: "staff",
  level_confidence: "confirmed",
  level_basis: "generic",
  family: "product_management",
  track: "product_program",
  comp_low: 650000,
  comp_high: 820000,
  comp_median: 735000,
  comp_currency: "USD",
  comp_provenance: "Google L6 reported median (product_management)",
  comp_base_low: 340000,
  comp_base_median: 400000,
  comp_base_high: 460000,
  status: "open",
  in_scope: true,
  posted_at: "2026-07-10T00:00:00Z",
  first_seen: "2026-07-11T00:00:00Z",
  last_seen: "2026-07-12T00:00:00Z",
  viewed_at: null,
  closed_at: null,
  days_open: 1,
  repost_count: 0,
  lineage_id: null,
  lineage_seq: null,
  lineage_role: null,
  lineage_size: null,
  lineage_days_open: null,
  listed_since: "2026-07-10T00:00:00Z",
  listed_days: 1,
  // Where the age counts from; this posting names no employer date.
  listed_basis: "sighting",
  // Not lit as new: a test that wants the row new says so.
  new_listing: false,
  twin_count: 0,
  place_count: null,
  place_set_size: null,
  is_favorite: false,
  is_dismissed: false,
  company_unfollowed: false,
  domains: ["ai_ml"],
  discloses_pay: false,
  description_text: "Lead API product strategy.",
  comp_sources: [],
  lifecycle: [],
};

export const statsFixture: Stats = {
  open_total: 1,
  new_today: 1,
  reposted_today: 0,
  closed_today: 0,
  saved_total: 0,
  review_pending: 0,
  notif_unread: 0, notif_high_unread: 0,
  by_company: { openai: 1 },
};

export function launcherFixture(status: Partial<NonNullable<SystemStatus["launcher"]>["status"]> = {}): NonNullable<SystemStatus["launcher"]> {
  return {
    product: "roleband", instance: "0123456789abcdef01234567", api_origin: "http://127.0.0.1:58221",
    version: "0.1.0", format: 1,
    status: {
      observed_at: "2026-10-27T18:00:00Z", activity: "idle", activity_since: null, hold: null,
      attention: [], queued: null, coverage_at: null, last_scan_at: null, last_scan_outcome: null,
      model: "ready", ...status,
    },
  };
}

export const statusFixture: SystemStatus = {
  db: "ok",
  launcher: null,
  last_success_at: "2026-07-13T05:00:00Z",
  last_success_age_hours: 2,
  last_scan_at: "2026-07-13T05:00:00Z",
  last_scan_age_hours: 2,
  last_run_status: "ok",
  last_run_started_at: "2026-07-13T04:00:00Z",
  last_run_finished_at: "2026-07-13T04:10:00Z",
  last_run_new: 3,
  last_run_seen: 40,
  running: false,
  manual_sync_running: false,
  manual_queued: [],
  manual_blocked: [],
  stuck_running: 0,
  stale: false,
  freshness_max_hours: 26,
  // One pass of each kind the server sends: an enabled pass with its freshness,
  // and a disabled one, which carries none.
  derivations: [
    {
      name: "embeddings", enabled: true, last_ok_at: "2026-07-13T04:10:00Z",
      last_run_at: "2026-07-13T04:10:00Z", last_status: "ok", age_hours: 2.8, stale: false,
    },
    { name: "prices", enabled: false, stale: false },
  ],
  derivations_stale: [],
  scheduler: {
    enabled: true, seeded: true, required: 2, ever_read: 2, fresh: 2, overdue: [], unread: [], excluded: [],
    last_complete_at: "2026-07-13T05:00:00Z", oldest_scan_at: "2026-07-13T05:00:00Z",
    next_due_at: "2026-07-13T11:00:00Z",
    providers: [],
  },
  // Nothing flagged, the common case. No screen reads it yet.
  bindings_attention: {
    followed: 0, automatic: 0, flagged: 0, stale: 0, empty: 0, outage: false, held_open: 0, items: [],
  },
  // Nothing installed, the core answers what it can, nothing moving.
  capabilities: [
    { slot: "pay.levels", providers: [], builtin: true },
    { slot: "pay.observations", providers: [], builtin: false },
    { slot: "company.facts", providers: [], builtin: true },
    { slot: "company.benefits", providers: [], builtin: true },
  ],
  reference: referenceFixture(),
  plugins_running: 0,
  matching_switch: "none",
  jobs: [],
  supervisor: { state: "running", since: "2026-08-08T10:00:00Z", reason: null },
};

/** `POST /api/sync` for a full-roster request that queued nothing new. */
/** The schedule plan as `/api/schedule` sends it: learned office
    hours, a 6-hour repeat, nothing run yet. `enabled: false` is the per-company
    timers, where the dial is what it was before the plan. */
export function schedulePlanFixture(overrides: Partial<SchedulePlan> = {}): SchedulePlan {
  return {
    enabled: true,
    repeat_hours: 6,
    repeat_anchor_minute: null,
    repeat_choices: [2, 3, 6, 12],
    full_after_hours: 20,
    roster: 1112,
    quick_roster: 944,
    pinned: 0,
    ready_by_minute: null,
    ready_by_today: null,
    days: [0, 1, 2, 3, 4, 5, 6],
    paused_until: null,
    mains_only: false,
    waiting: null,
    last_run: null,
    last_full_at: null,
    upcoming: [],
    usual: {
      timezone: "UTC",
      observed_days: 14,
      needed_days: 5,
      learning: false,
      today: [{ start_minute: 9 * 60, end_minute: 18 * 60 }],
      weekdays: [{ start_minute: 9 * 60, end_minute: 18 * 60 }],
      weekends: [],
      on_now: true,
    },
    ...overrides,
  };
}

export const syncStartedFixture: SyncResult = { status: "started", companies: [], queued: [] };

export const facetsFixture: Facets = {
  // Two tracked+visible companies come from the API's company list. `counts.company`
  // additionally carries a slug NOT in `companies` (a hidden company's open jobs are
  // still grouped): the filter must render from `companies`, never from the counts,
  // or a user-added company gets no checkbox.
  companies: { openai: { display: "OpenAI" }, amazon: { display: "Amazon" } },
  // Families, tracks and worlds are slugs: the client names them.
  families: {
    engineering_management: {},
    product_management: {},
    program_management: {},
    sales_business_development: {},
  },
  tracks: {
    management: {},
    product_program: {},
    technical: {},
    business_customer: {},
  },
  /* A metro under its country, plus the country itself — the nesting the
     register renders, and the shape that lets a test prove an all-board value
     is dropped: `united_states` counts every role the board has. */
  location_groups: {
    silicon_valley: { display: "Silicon Valley", parent: "united_states" },
    new_york: { display: "New York", parent: "united_states" },
    united_states: { display: "United States", parent: null },
  },
  domains: {
    ai_ml: {},
    logistics_fulfillment: {},
    unclassified: {},
  },
  total: 4,
  counts: {
    company: { openai: 1, amazon: 2, hidden_co: 5 },
    level_band: { staff: 1 },
    level_confidence: { confirmed: 1 },
    family: { engineering_management: 2, product_management: 1, program_management: 3, sales_business_development: 0 },
    track: { management: 3, product_program: 2, technical: 1, business_customer: 0 },
    workplace_type: { hybrid: 1 },
    location_group: { silicon_valley: 1, new_york: 2, united_states: 4 },
    domain: { ai_ml: 2, logistics_fulfillment: 1, unclassified: 1 },
  },
};

export const jobListFixture: JobList = {
  total: 1,
  limit: 25,
  offset: 0,
  items: [jobFixture],
};

export const notificationsFixture: NotificationList = {
  total: 0,
  limit: 15,
  offset: 0,
  unread_count: 0,
  high_unread_count: 0, category_counts: {},
  items: [],
};

/* The Statistics overview payload. Every route that mounts the Statistics shell
   fetches it, including the sub-tabs that show none of it — so a spec for the
   Compensation tab still has to answer it or the request falls through to the
   dev-server proxy. Specs share this one definition. */
export const overviewFixture: StatisticsOverview = {
  days: 30,
  kpis: { open_total: 12, new_count: 4, first_scan_count: 0, closed_count: 1, companies: 3, saved_total: 2 },
  top_skills: [],
  top_clusters: [],
  longest_open: [],
  
};

/** `GET /api/demand`, the Hiring tab: roles each once, by company
 *  and region. Eighteen companies so the tab folds a tail (fifteen drawn). */
export const hiringFixture: Demand = {
  open_total: 236,
  new_today: 4,
  closed_today: 2,
  companies: [
    { company: "anthropic", open: 48, new_today: 2, closed_today: 1 },
    { company: "google", open: 41, new_today: 1, closed_today: 0 },
    { company: "openai", open: 33, new_today: 1, closed_today: 1 },
    ...Array.from({ length: 15 }, (_, i) => ({
      company: `market-${String(i + 1).padStart(2, "0")}`, open: 8 - Math.floor(i / 3),
      new_today: 0, closed_today: 0,
    })),
  ],
  regions: [
    { key: "north_america", open: 180, region_wide: 3, countries: [{ key: "united_states", open: 170 }, { key: "canada", open: 9 }] },
    { key: "europe", open: 61, region_wide: 7, countries: [{ key: "uk", open: 40 }, { key: "germany", open: 12 }] },
  ],
  unplaced: 2,
  employer_dated_share: 0.73,
  longest_open: [],
  listed_over_a_year: 0,
  most_reposted: [],
  most_updated_open: [],
};

/** A pending suggestion to turn a world off, as `GET /api/profile/suggestions`
 *  lists it: every key present, the whole basis included. Override the keys a
 *  test is about. */
export const profileSuggestionFixture: ProfileSuggestion = {
  id: 7,
  kind: "world_off",
  world: "advertising",
  
  basis: {
    score: -9, favorited: 0, pursued: 0,
    dismissed_wrong_domain: 2, dismissed_other: 1,
    sectors: [], intent_matched: false, background: 0,
  },
  status: "pending",
  created_at: "2026-08-08T10:00:00Z",
};

/** Settings > Data retention as `GET /api/settings/retention` sends it: the
 *  default 60 days, 1,240 postings kept, 94 due, and a removal last week that
 *  finished. Every key present; override the ones a test is about. */
/** Settings > Plugins > Stock prices: no key anywhere, nothing priced yet. */
export function priceFeedStateFixture(overrides: Partial<PriceFeedState> = {}): PriceFeedState {
  return {
    configured: false,
    origin: null,
    priced: 0,
    as_of: null,
    last_run_at: null,
    refused: null,
    waiting: 0,
    next_at: null,
    key_check: null,
    ...overrides,
  };
}

export function retentionStateFixture(overrides: Partial<RetentionState> = {}): RetentionState {
  return {
    days: 60,
    default_days: 60,
    choices: [
      { days: 7, due: 402 },
      { days: 14, due: 310 },
      { days: 30, due: 188 },
      { days: 60, due: 94 },
      { days: 90, due: 40 },
      { days: 180, due: 0 },
      { days: 365, due: 0 },
    ],
    stored: 1240,
    no_longer_listed: 210,
    stopped_following: 330,
    due: 94,
    last_removed: { at: "2026-09-21T06:10:00Z", removed: 57, more: false },
    ...overrides,
  };
}

/** The Settings > AI state as the UX harness serves it: matching settled on fp32
 *  with both tiers measured, the experimental integration off and the routing
 *  ladder empty. Every key present; override the ones a test is about. */
export const intelligenceStatusFixture: IntelligenceStatus = {
  matching: {
    status: "ready",
    tier: "fp32",
    model_id: "lightonai/DenseOn",
    downloaded_bytes: 600153516,
    total_bytes: 600153516,
    chosen_by: "auto",
    detected_ram_bytes: 32 * 1024 ** 3,
    ram_threshold_bytes: 16 * 1024 ** 3,
    tiers: [
      { tier: "fp32", total_bytes: 600153516, recommended: true, installed: true, switch_seconds: 745 },
      { tier: "int8", total_bytes: 153490318, recommended: false, installed: false, switch_seconds: 919 },
    ],
    reembedding: false,
    corpus_embedded: 4114,
    corpus_total: 4114,
    stale_count: 0,
    other_tier_count: 0,
    job_phase: "none",
    estimate_seconds: null,
  },
  enabled: false,
  provider: "apple",
  availability: { state: "sdk_absent", ok: false, detail: null },
  model_id: "afm",
  prompt_version: "v1",
  routing: { egress_enabled: false, tiers: [] },
};

/** `GET /api/intelligence/fit` for a ranked board of 1,410 roles, every band populated. */
export const intelligenceFitFixture: IntelligenceFit = {
  ranked: true,
  intent_statement: "leadership in AI/frontier tech",
  total: 1410,
  unranked: 0,
  embedded_today: 140,
  last_embedded_at: "2026-08-23T05:13:08Z",
  bin_width: 0.02,
  bins: [
    { fit: 0.38, count: 146 },
    { fit: 0.44, count: 150 },
    { fit: 0.52, count: 87 },
    { fit: 0.62, count: 14 },
    { fit: 0.74, count: 1 },
  ],
  bands: [
    { key: "strong", count: 62, lower_edge: 0.6 },
    { key: "good", count: 326, lower_edge: 0.5 },
    { key: "some", count: 530, lower_edge: 0.42 },
    { key: "weak", count: 492, lower_edge: null },
  ],
};

/** Agent access with both gates off, as `GET /api/intelligence/agents` sends it. */
export const agentAccessFixture: AgentAccessState = {
  enabled: false,
  allow_writes: false,
  transport: "stdio",
  command: "/repo/backend/.venv/bin/python",
  args: ["-m", "tracker.mcp.server"],
  cwd: "/repo/backend",
  tools: [
    { name: "search_opportunities", access: "read" },
    { name: "update_pursuit", access: "write" },
  ],
  codex_command: "codex mcp add roleband -- /repo/backend/.venv/bin/python -m tracker.mcp.server",
  claude_json: {
    mcpServers: {
      roleband: { command: "/repo/backend/.venv/bin/python", args: ["-m", "tracker.mcp.server"], cwd: "/repo/backend" },
    },
  },
  
};

/** A saved oMLX connection as the local-model routes serve it: the default
 *  generation controls, no key saved. */
export const localModelProfileFixture: LocalLLMProfile = {
  id: "profile12345",
  name: "Local Ornith",
  provider: "omlx",
  base_url: "http://127.0.0.1:8000/v1",
  model: "Ornith-1.0-35B-5bit-mlx",
  has_api_key: false,
  parameters: {
    max_tokens: 32768, temperature: 0.2, top_p: 0.95, top_k: 0, min_p: 0,
    repetition_penalty: 1, presence_penalty: 0, frequency_penalty: 0, seed: null,
    enable_thinking: true, thinking_budget: 2048, timeout_seconds: 180,
  },
};

/** A second saved connection to the same server. */
export const otherLocalModelProfileFixture: LocalLLMProfile = {
  ...localModelProfileFixture,
  id: "profile67890",
  name: "Local Qwen",
  model: "Qwen3-30B-A3B-4bit",
};

/** `GET /api/intelligence/local-models`: the tier on, both connections saved, the first active. */
export const localModelStateFixture: LocalLLMState = {
  enabled: true,
  active_profile_id: localModelProfileFixture.id,
  profiles: [localModelProfileFixture, otherLocalModelProfileFixture],
};

/** `GET /api/intelligence/local-models/server` for the active connection: oMLX
 *  installed, and the server answering with the model loaded. */
export const localServerStatusFixture: LocalServerStatus = {
  enabled: true,
  installed: true,
  binary: "/opt/homebrew/bin/omlx",
  managed: true,
  profile_id: localModelProfileFixture.id,
  provider: "omlx",
  model: localModelProfileFixture.model,
  base_url: localModelProfileFixture.base_url,
  state: "available",
  reachable: true,
  detail: "",
};

/** A connection test the active model answered in full, with the server's own metrics. */
export const localModelTestResultFixture: LocalLLMTestResult = {
  ok: true,
  profile_id: localModelProfileFixture.id,
  provider: "omlx",
  model: localModelProfileFixture.model,
  response: "RoleBand local model connection is ready.",
  finish_reason: "stop",
  truncated: false,
  metrics: {
    wall_time_ms: 1770, total_time_ms: 1740, time_to_first_token_ms: 420,
    prompt_eval_ms: 200, generation_ms: 1320, prompt_tokens: 63,
    completion_tokens: 17, total_tokens: 80, cached_prompt_tokens: 10,
    prompt_tokens_per_second: 315, generation_tokens_per_second: 12.9,
    finish_reason: "stop", context_window: 262144,
  },
  
};

/** A saved OpenAI connection, switched off, with a key saved. */
export const cloudModelProfileFixture: CloudLLMProfile = {
  id: "c1",
  name: "OpenAI API",
  provider: "openai",
  base_url: "https://api.openai.com/v1",
  model: "gpt-5.4",
  enabled: false,
  has_api_key: true,
};

/** A test of that connection that authenticated. */
export const cloudModelTestResultFixture: CloudLLMTestResult = {
  ok: true,
  profile_id: cloudModelProfileFixture.id,
  provider: "openai",
  model: cloudModelProfileFixture.model,
  latency_ms: 240,
  
};

/** A plugin answering a profile's ladder and benefits with its own rows:
 *  never mixed with RoleBand's data, named by the plugin. */
export const PLUGIN_SOURCE = "acme-pay";
export const PLUGIN_NAME = "Acme pay data";
export const PLUGIN_ATTRIBUTION = "Data source: Acme (https://pay.example)";

/** A resolved field as a profile serves it, won by one of RoleBand's own sources
 *  and fresh. Override the provenance a test is about. */
export function profileFieldFixture(value: ProfileField["value"], over: Partial<ProfileField> = {}): ProfileField {
  return {
    value,
    source: "reported",
    observed_at: "2026-07-14T00:00:00+00:00",
    freshness: "fresh",
    is_manual: false,
    conflicts: [],
    candidates: [],
    editable: true,
    answered_by: null,
    ...over,
  };
}

/** A field no source asserts: every provenance key null, nothing to choose from. */
const unassertedProfileField: ProfileField = {
  value: null,
  source: null,
  observed_at: null,
  freshness: null,
  is_manual: false,
  conflicts: [],
  candidates: [],
  editable: true,
  answered_by: null,
};

/** Who answers a section when RoleBand's own data does. */
export const OUR_SECTION = { plugin: null, plugin_name: null, covered: true } as const;
/** A section the plugin answers and has read this company for. */
export const PLUGIN_SECTION = { plugin: PLUGIN_SOURCE, plugin_name: PLUGIN_NAME, covered: true } as const;

/** All eight shown fields, unasserted unless given: a profile always sends every one. */
export function companyProfileFieldsFixture(
  given: Partial<CompanyProfileDetail["fields"]> = {},
): CompanyProfileDetail["fields"] {
  return {
    is_public: unassertedProfileField,
    ticker: unassertedProfileField,
    headcount: unassertedProfileField,
    hq_city: unassertedProfileField,
    website: unassertedProfileField,
    equity_vehicle: unassertedProfileField,
    vesting_schedule: unassertedProfileField,
    ...given,
  };
}

/** A profile list row for a current, public, priced company. */
export const companyProfileSummaryFixture: CompanyProfileSummary = {
  slug: "google",
  display_name: "Google",
  logo_url: null,
  brand_color: null,
  is_public: true,
  ticker: "GOOG",
  equity_vehicle: "rsu",
  headcount: 258750,
  data_health: "ok",
  conflict_fields: [],
  mapped_levels: 5,
  sectors: ["faang"],
  in_dataset: true,
  price: 213.95,
  change_pct: -0.48,
  currency: "USD",
  price_as_of: "2026-07-13",
};

/** `GET /api/company-profiles` `sectors`: `company_discovery.SECTORS` order. */
export const profileSectorOrderFixture: string[] = [
  "faang", "ai", "technology", "gaming", "consulting", "fintech", "quant", "cybersecurity",
  "cloud-data-devtools", "semiconductors", "robotics", "consumer",
];

/** `GET /api/companies/google/card`: a profiled, priced company with open roles in two cities. */
export const companyCardFixture: CompanyCard = {
  slug: "google",
  display_name: "Google",
  logo_url: null,
  brand_color: "#4285F4",
  ticker: "GOOG",
  is_public: true,
  has_profile: true,
  open_roles: 3,
  unfollowed: false,
  top_cities: ["Mountain View, CA", "New York, NY"],
  price: 213.95,
  change_pct: -0.48,
  currency: "USD",
  price_as_of: "2026-07-13",
};

/** A pin that settled the last open field: the company is current again. */
export const companyProfileFieldWriteFixture: CompanyProfileFieldWrite = {
  slug: "reddit",
  field: "ticker",
  health: { status: "ok", missing: [], conflicts: [], stale: [], needs_review: [] },
};

/** The scope joint before any company has been re-scanned.
 *
 * `ready: false` is the state every existing catalog row is in until a full
 * scrape rewrites it, and it is what keeps the scope screen on its pre-gate
 * marginals. Fixtures that are not testing the joint itself use this, so the
 * shape is stated once rather than in each of the five scope test files.
 */
export const emptyScopeCellsFixture: ScopeCells = {
  ready: false,
  companies: [],
  missing_companies: [],
  stale_companies: [],
  partial_companies: [],
  scanned_places: {},
  unplaced: 0,
  roles: [],
  bands: [],
  tracks: [],
  cities: [],
  location_sets: [],
  domain_sets: [],
  cells: [],
};

/** `GET /api/profile` on an install whose scope is saved and whose persona is
 *  not: no stages placed and no aim sentence ("" is none, as the server sends it). */
export function profileStateFixture(overrides: Partial<ProfileState> = {}): ProfileState {
  return { profile: null, scope_configured: true, intent_statement: "", ...overrides };
}

/** `GET /api/scope/catalog` with nothing in it: every axis and every list
 *  empty, and `scope_cells` not scanned yet. A scope test passes the rows it reads.
 *  A `settings` it passes replaces these whole, so it states `role_answers` as
 *  the server sends them: the saved answers, or with none saved the server's
 *  reading of the two flat lists (`answers_from_axes`). */
export function scopeCatalogFixture(overrides: Partial<ScopeCatalog> = {}): ScopeCatalog {
  return {
    settings: {
      enabled_role_groups: [],
      enabled_seniority_bands: [],
      enabled_role_tracks: [],
      enabled_location_groups: [],
      enabled_domain_groups: [],
      excluded_domain_groups: [],
      excluded_location_groups: [],
      include_unstated_level: true,
      role_answers: [],
    },
    domains: [],
    unclassified_domain_count: 0,
    levels: [],
    unstated_level_count: 0,
    locations: [],
    tracks: [],
    categories: [],
    companies: [],
    joint_counts_ready: true,
    scope_cells: emptyScopeCellsFixture,
    ...overrides,
  };
}

/** `PUT /api/settings` answering `payload`: each axis as it was sent (a list
 *  the payload leaves out, answers included, reads as empty), and no row moved
 *  unless `overrides` says so. The persona passengers are never echoed. */
export function settingsSaveFixture(
  payload: ScopeSettingsPayload,
  overrides: Partial<ScopeSettingsSaveResult> = {},
): ScopeSettingsSaveResult {
  return {
    enabled_role_groups: payload.enabled_role_groups,
    enabled_seniority_bands: payload.enabled_seniority_bands,
    enabled_role_tracks: payload.enabled_role_tracks ?? [],
    enabled_location_groups: payload.enabled_location_groups ?? [],
    enabled_domain_groups: payload.enabled_domain_groups ?? [],
    excluded_domain_groups: payload.excluded_domain_groups ?? [],
    excluded_location_groups: payload.excluded_location_groups ?? [],
    include_unstated_level: payload.include_unstated_level ?? true,
    role_answers: payload.role_answers ?? [],
    in_scope_changed: 0,
    on_board: 0,
    promoted: 0,
    promotion_pending: false,
    ...overrides,
  };
}

/* Recipes: a checked, in-use recipe scanning one company, as
   `GET /api/connector-recipes` and `GET /api/connector-recipes/{slug}` send it. */
export const recipeDocumentFixture = {
  format_version: 1,
  kind: "job_listing",
  id: "valve-jobs",
  match: { domains: ["www.valvesoftware.com"] },
  transport: { mode: "static_http" },
  listing: {
    start_url: "https://www.valvesoftware.com/en/jobs",
    response: "html",
    item: "div.job",
    fields: {
      req_id: { attr: "data-id", required: true },
      title: { css: "h3", text: true, required: true },
      url: { css: "a", attr: "href", absolute: true, required: true },
    },
  },
};

export function recipeRevisionFixture(overrides: Partial<RecipeRevision> = {}): RecipeRevision {
  return {
    id: 7,
    version: 1,
    checksum: "a".repeat(64),
    created_at: "2026-09-26T09:00:00Z",
    created_by: "settings",
    document: recipeDocumentFixture,
    validated_at: "2026-09-26T09:05:00+00:00",
    validation: { passed: true, found: 12, pages: 1 },
    ...overrides,
  };
}

export function recipeSummaryFixture(overrides: Partial<RecipeSummary> = {}): RecipeSummary {
  return {
    slug: "valve-jobs",
    status: "active",
    domains: ["www.valvesoftware.com"],
    versions: 1,
    active_revision_id: 7,
    active_version: 1,
    active_validated: true,
    companies: ["valve"],
    ...overrides,
  };
}

export function recipeDetailFixture(overrides: Partial<RecipeDetail> = {}): RecipeDetail {
  return {
    slug: "valve-jobs",
    status: "active",
    active_revision_id: 7,
    companies: ["valve"],
    revisions: [recipeRevisionFixture()],
    ...overrides,
  };
}

export function recipeCheckFixture(overrides: Partial<RecipeCheck> = {}): RecipeCheck {
  return {
    passed: false,
    problems: [],
    errors: [],
    found: 2,
    pages: 1,
    list_complete: false,
    robots: { allowed: true },
    jobs: [
      { req_id: "101", title: "Game Designer", url: "https://www.valvesoftware.com/en/jobs/101", locations: ["Bellevue, WA"], posted_at: null },
      { req_id: "102", title: "Software Engineer", url: "https://www.valvesoftware.com/en/jobs/102", locations: [], posted_at: null },
    ],
    ...overrides,
  };
}

export function trackedCompanyFixture(overrides: Partial<TrackedCompany> = {}): TrackedCompany {
  return {
    slug: "valve",
    display: "Valve",
    adapter: null,
    board_token: null,
    careers_url: "https://www.valvesoftware.com/en/jobs",
    status: "pending",
    enabled: true,
    visible: true,
    source: "directory",
    builtin: false,
    job_count: 0,
    role_catalog_status: "pending",
    role_catalog_scanned_at: null,
    role_catalog_error: null,
    detected_family: null,
    pending_reason: null,
    ...overrides,
  };
}


/** `reference` on `/api/status` and `/api/plugins`: one applied set, nothing moving. */
export function referenceFixture(overrides: Partial<ReferenceView> = {}): ReferenceView {
  return {
    applied_fp: "a1".repeat(32),
    target_fp: null,
    pending_jobs: 0,
    last_change_id: 4,
    last_change: { id: 4, at: "2026-07-13T04:12:00Z", jobs: 412, moved: 37, gained: 5, lost: 2, companies: 6 },
    ...overrides,
  };
}

/** One plugin update as `last_run` and `runs[]` carry it: `pluginFixture`'s
    clean weekly refresh, every company read (96 of 96). */
export function pluginRunFixture(overrides: Partial<PluginRunView> = {}): PluginRunView {
  return {
    id: 12, job: "refresh", trigger: "schedule", outcome: "clean", started_at: "2026-07-12T03:00:00Z",
    ended_at: "2026-07-12T03:14:00Z", progress_done: 96, progress_total: 96,
    published: { "pay.levels": 2804, "company.benefits": 1120 }, message: null, summary: null, continues: false,
    ...overrides,
  };
}

/** A pass over many companies split across updates: this one ended
    cleanly within its time after 300 of 1,180 companies, and the next update
    carries on from there. */
export function pluginRunContinuingFixture(overrides: Partial<PluginRunView> = {}): PluginRunView {
  return pluginRunFixture({
    id: 21, started_at: "2026-07-12T13:00:00Z", ended_at: "2026-07-12T13:30:00Z",
    progress_done: 300, progress_total: 1180, continues: true, published: { "pay.levels": 412 },
    ...overrides,
  });
}

/** An update the person stopped (Pause) after 4 of 1,180 companies; the host
    says so in its own words, which restate the outcome. */
export function pluginRunStoppedFixture(overrides: Partial<PluginRunView> = {}): PluginRunView {
  return pluginRunFixture({
    id: 23, trigger: "manual", outcome: "stopped", started_at: "2026-07-12T15:27:00Z",
    ended_at: "2026-07-12T15:37:00Z", progress_done: 4, progress_total: 1180,
    published: { "pay.levels": 32 }, message: "the run is stopped",
    ...overrides,
  });
}

/** An update that failed after 4 of 1,180 companies, with the host's
    diagnostic about why: shown as written, never translated. */
export function pluginRunErroredFixture(overrides: Partial<PluginRunView> = {}): PluginRunView {
  return pluginRunFixture({
    id: 22, trigger: "manual", outcome: "error", started_at: "2026-07-12T15:16:00Z",
    ended_at: "2026-07-12T15:18:00Z", progress_done: 4, progress_total: 1180, published: {},
    message: "ladder.example answered 503 three times in a row; the update gave up",
    ...overrides,
  });
}

/** A plugin partway through its first pass over 1,180 followed companies:
    its updates have read 4 companies whole for pay by level and none yet for
    benefits or company facts, at about a minute a company, so the rest takes
    about 21 hours of updates; a company it has not read shows none of it.
    Its credit begins with its own label, as real ones do. */
export function pluginAdoptingFixture(overrides: Partial<PluginView> = {}): PluginView {
  return pluginFixture({
    id: "example-ladder",
    name: "Example ladder data",
    slots: ["company.benefits", "company.facts", "pay.levels"],
    active_slots: ["pay.levels"],
    coverage: { "pay.levels": 4 },
    companies: 1180,
    reading_left: { units: 1176, seconds_per_unit: 62, seconds: 76_000 },
    hosts: ["ladder.example"],
    attribution: "Data source: Example ladder (https://ladder.example)",
    repository: "https://github.com/example/example-ladder",
    last_run: pluginRunStoppedFixture(),
    last_clean_at: null,
    paused: true,
    paused_at: "2026-07-12T15:37:00Z",
    next_update_at: null,
    ...overrides,
  });
}

/** One installed plugin as Settings > Plugins lists it: approved, enabled, a
    clean weekly refresh, answering pay by level and benefits, on the plugin's
    own schedule, next update a week after the last clean one. The switch
    (`enabled`) follows `state` unless an override sets it: only an update that
    lapsed the approval leaves it on beside `needs_approval`
    (`pluginLapsedFixture`). */
export function pluginFixture(overrides: Partial<PluginView> = {}): PluginView {
  return {
    id: "example-pay",
    name: "Example pay data",
    version: "0.3.1",
    state: "enabled",
    enabled: (overrides.state ?? "enabled") === "enabled",
    slots: ["company.benefits", "pay.levels"],
    active_slots: ["company.benefits", "pay.levels"],
    jobs: [{ name: "refresh", schedule: "weekly", manifest_schedule: "weekly", budget_seconds: 1800 }],
    hosts: ["data.example.com"],
    attribution: "Pay data courtesy of Example",
    description: null,
    licence: "MIT",
    repository: "https://github.com/example/example-pay",
    installed_at: "2026-07-01T09:00:00Z",
    approved_at: "2026-07-01T09:05:00Z",
    enabled_at: "2026-07-01T09:06:00Z",
    running: false,
    last_run: pluginRunFixture(),
    last_clean_at: "2026-07-12T03:00:00Z",
    coverage: { "pay.levels": 96, "company.benefits": 81 },
    companies: 120,
    reading_left: null,
    removable_slots: ["company.benefits", "pay.levels"],
    estimates_read: false,
    robots_consent_at: null,
    robots_lapsed: [],
    reports: [],
    schedule: null,
    schedules: ["manual", "daily", "weekly", "monthly"],
    paused: false,
    paused_at: null,
    next_update_at: "2026-07-19T03:00:00Z",
    ...overrides,
  };
}

/** `GET /api/plugins/{id}/robots`: data.example.com asks RoleBand to
    skip two patterns; nothing is allowed yet. */
export function pluginRobotsFixture(overrides: Partial<PluginRobots> = {}): PluginRobots {
  return {
    sites: [{ host: "data.example.com", state: "rules", sha256: "ab".repeat(32),
              disallow: ["/private/", "/*?page="] }],
    consent: null,
    consent_at: null,
    ...overrides,
  };
}

/** `GET /api/plugins` with plugins shown and one installed. Off
    (`available: false`), the API lists none. */
export function pluginsFixture(overrides: Partial<PluginsResponse> = {}): PluginsResponse {
  return {
    available: true,
    plugins: [pluginFixture()],
    reference: referenceFixture(),
    capabilities: [
      { slot: "pay.levels", providers: ["example-pay"], builtin: true },
      { slot: "pay.observations", providers: [], builtin: false },
      { slot: "company.facts", providers: [], builtin: true },
      { slot: "company.benefits", providers: ["example-pay"], builtin: true },
    ],
    ...overrides,
  };
}

/** `GET /api/plugins/{id}` for `pluginFixture`, waiting for approval: what the
    approve dialog shows. */
export function pluginDetailFixture(overrides: Partial<PluginDetail> = {}): PluginDetail {
  const base = pluginFixture({ state: "needs_approval", approved_at: null, enabled_at: null, active_slots: [],
                               last_run: null, last_clean_at: null, coverage: {}, next_update_at: null });
  return {
    ...base,
    runs: [],
    fingerprint: "f0".repeat(32),
    approval: {
      plugin: base.id, name: base.name, version: base.version, repository: base.repository ?? "",
      licence: "MIT", attribution: "Pay data courtesy of Example", slots: ["pay.levels", "company.benefits"],
      fact_fields: [], fact_rank: null,
      hosts: ["data.example.com"], identity: "identified",
      jobs: [{ name: "refresh", schedule: "weekly", budget_seconds: 1800, needs: ["followed_companies"] }],
    },
    ...overrides,
  };
}

/** `pluginFixture` after an update it installed lapsed its approval: the user
    left it on (`enabled`), so it waits for approval with the switch still on,
    reads nothing meanwhile, and can be turned off without approving. */
export function pluginLapsedFixture(overrides: Partial<PluginView> = {}): PluginView {
  return pluginFixture({ state: "needs_approval", enabled: true, version: "0.4.0", active_slots: [], ...overrides });
}


const wide = (label: string, ...spellings: string[]) => ({ company_wide: { label, spellings: spellings.length ? spellings : [label] } });
const tech = (label: string, ...spellings: string[]) => ({ per_track: { technical: { label, spellings: spellings.length ? spellings : [label] } } });

/** `GET /api/statistics/levels` over real ladders: Google splits L8 by track,
 *  Amazon skips Staff and its "L8–L10" holds no L9, NVIDIA's "IC7+" hides
 *  Distinguished Engineer, Apple and Meta grade engineers only, Meta is flat,
 *  and "L5" is a different level at four companies. */
export const levelGuideFixture: LevelGuide = {
  companies: [
    { slug: "amazon", flat: false, levels: {
      entry: wide("L4", "L4", "SDE I"), mid: wide("L5", "L5", "SDE II"), senior: wide("L6", "L6", "SDE III"),
      principal: wide("L7", "L7", "Principal SDE"),
      director_plus: wide("L8–L10", "L8", "Senior Principal SDE", "L10", "Distinguished Engineer"),
    } },
    { slug: "apple", flat: false, levels: {
      entry: tech("ICT2"), mid: tech("ICT3"), senior: tech("ICT4"), staff: tech("ICT5"), principal: tech("ICT6"),
      director_plus: tech("Distinguished Engineer"),
    } },
    { slug: "google", flat: false, levels: {
      entry: wide("L3"), mid: wide("L4"), senior: wide("L5"), staff: wide("L6"),
      principal: { per_track: {
        technical: { label: "L7–L8", spellings: ["L7", "L8"] },
        management: { label: "L7", spellings: ["L7"] },
        product_program: { label: "L7", spellings: ["L7"] },
        business_customer: { label: "L7", spellings: ["L7"] },
      } },
      director_plus: { per_track: {
        technical: { label: "L9–L10", spellings: ["L9", "L10"] },
        management: { label: "L8–L10", spellings: ["L8", "L9", "L10"] },
        product_program: { label: "L8–L10", spellings: ["L8", "L9", "L10"] },
        business_customer: { label: "L8–L10", spellings: ["L8", "L9", "L10"] },
      } },
    } },
    { slug: "meta", flat: true, levels: { entry: tech("University Grad"), mid: tech("Software Engineer") } },
    { slug: "microsoft", flat: false, levels: {
      entry: wide("59–60", "59", "60"), mid: wide("61–62", "61", "62"), senior: wide("63–64", "63", "64"),
      principal: wide("65–67", "65", "66", "67"), director_plus: wide("68–70", "68", "69", "70"),
    } },
    { slug: "netflix", flat: false, levels: {
      entry: wide("L3"), mid: wide("L4"), senior: wide("L5"), staff: wide("L6"), principal: wide("L7"),
    } },
    { slug: "nvidia", flat: false, levels: {
      entry: wide("IC1–IC2", "IC1", "IC2"), mid: wide("IC3"), senior: wide("IC4"), staff: wide("IC5"), principal: wide("IC6"),
      director_plus: wide("IC7+", "IC7", "Distinguished Engineer"),
    } },
    { slug: "openai", flat: false, levels: {
      entry: wide("L2"), mid: wide("L3"), senior: wide("L4"), staff: wide("L5"), principal: wide("L6"), director_plus: wide("L7"),
    } },
  ],
  unguided: [{ slug: "google-deepmind", same_as: "google" }, { slug: "stripe", same_as: null }],
  tracks: {
    technical: ["intern", "entry", "mid", "senior", "staff", "principal", "director_plus"],
    management: ["senior", "staff", "principal", "director_plus"],
    product_program: ["intern", "entry", "mid", "senior", "staff", "principal", "director_plus"],
    business_customer: ["intern", "entry", "mid", "senior", "staff", "principal"],
  },
};
