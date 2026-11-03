import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import type { ScopeCatalog } from "../../api";
import { Button } from "../../ui/Button";
import { ScopeDraftProvider, useScopeDraft } from "./useScopeDraft";
import { ScopeRulesList } from "./ScopeSection";
import { StageDimmer } from "./StageDimmer";
import { calculateScopeImpact } from "./scopeDraftModel";
import { ToastProvider } from "../../ui/Toast";
import { profileStateFixture, scopeCatalogFixture, settingsSaveFixture } from "../../test/fixtures";

vi.mock("../../api", () => ({
  api: {
    scopeCatalog: vi.fn(),
    refreshScopeCatalog: vi.fn(),
    saveSettings: vi.fn(),
    companies: vi.fn(),
    profile: vi.fn(),
    scopeRules: vi.fn(),
    deleteScopeRule: vi.fn(),
    createScopeRule: vi.fn(),
    profileSuggestions: vi.fn(),
    acceptProfileSuggestion: vi.fn(),
    dismissProfileSuggestion: vi.fn(),
  },
}));

vi.mock("../../context/MissionState", () => ({
  useMissionActions: () => ({ refreshStats: vi.fn() }),
}));

const load = vi.mocked(api.scopeCatalog);
const refresh = vi.mocked(api.refreshScopeCatalog);
const save = vi.mocked(api.saveSettings);
const companies = vi.mocked(api.companies);
const suggestions = vi.mocked(api.profileSuggestions);

/* The scope pieces that share one draft: the level dimmer (walk step 2) and
   company exclusions (walk Summary). The page chrome they rely on (Save,
   the role-count refresh and its message) is this harness, driven by the real
   draft hook. */
function LiveScope() {
  const { catalog, dirty, save, refreshInventory, refreshMessage } = useScopeDraft();
  if (!catalog) return null;
  return (
    <section aria-label="What your radar looks for">
      <StageDimmer />
      <ScopeRulesList />
      {dirty && <Button onClick={() => void save()}>Save</Button>}
      <Button onClick={() => void refreshInventory()}>Refresh role counts</Button>
      {refreshMessage && <p role="status">{refreshMessage}</p>}
    </section>
  );
}

const renderScope = () => render(
  <ToastProvider>
    <MemoryRouter>
      <ScopeDraftProvider>
        <LiveScope />
      </ScopeDraftProvider>
    </MemoryRouter>
  </ToastProvider>,
);

const catalog = scopeCatalogFixture({
  settings: {
    enabled_role_groups: ["software_engineering"],
    enabled_seniority_bands: ["staff"],
    enabled_role_tracks: ["management", "product_program", "technical"],
    enabled_location_groups: ["silicon_valley", "uk"],
    enabled_domain_groups: ["ai_ml", "logistics_fulfillment"],
    excluded_domain_groups: [],
    excluded_location_groups: [],
    include_unstated_level: false,
    role_answers: [
      { track: "management", roles: ["software_engineering"] },
      { track: "product_program", roles: ["software_engineering"] },
      { track: "technical", roles: ["software_engineering"] },
    ],
  },
  domains: [
    { slug: "ai_ml", selected: true, count: 8, examples: ["Applied AI"], kind: "technology" },
    { slug: "logistics_fulfillment", selected: true, count: 3, examples: ["Fulfillment & Operations Management"], kind: "function" },
  ],
  unclassified_domain_count: 2,
  levels: [
    { slug: "entry", order: 0, default_enabled: false, selected: false, new: false, count: 2, decoder: { acme: { company_wide: "L3" } } },
    { slug: "staff", order: 2, default_enabled: true, selected: true, new: false, count: 7, decoder: { acme: { company_wide: "L6" } } },
  ],
  locations: [
    { slug: "silicon_valley", display: "Silicon Valley", default_enabled: true, selected: true, new: false, count: 6, kind: "metro", parent: "united_states", uncovered_by: [], prominent: true },
    { slug: "united_states", display: "United States", default_enabled: true, selected: false, new: false, count: 9, kind: "country", parent: null, uncovered_by: [], prominent: true },
    { slug: "europe", display: "Europe", default_enabled: false, selected: false, new: false, count: 5, kind: "region", parent: null, uncovered_by: ["acme"], prominent: true },
    // Tracked, and one source cannot be asked about it — the case the coverage
    // warning exists for.
    { slug: "uk", display: "United Kingdom", default_enabled: true, selected: true, new: false, count: 4, kind: "country", parent: "europe", uncovered_by: ["acme"], prominent: true },
    { slug: "germany", display: "Germany", default_enabled: false, selected: false, new: false, count: 1, kind: "country", parent: "europe", uncovered_by: ["acme"], prominent: true },
    { slug: "singapore", display: "Singapore", default_enabled: true, selected: false, new: false, count: 2, kind: "country", parent: null, uncovered_by: [], prominent: true },
    { slug: "canada", display: "Canada", default_enabled: false, selected: false, new: false, count: 2, kind: "country", parent: null, uncovered_by: ["acme"], prominent: true },
  ],
  tracks: [
    { slug: "management", order: 0, default_enabled: true, selected: true, new: false, count: 5, allowed_bands: ["senior", "staff", "principal", "director_plus"] },
    { slug: "product_program", order: 1, default_enabled: true, selected: true, new: false, count: 4, allowed_bands: ["intern", "entry", "mid", "senior", "staff", "principal", "director_plus"] },
    { slug: "technical", order: 2, default_enabled: true, selected: true, new: false, count: 9, allowed_bands: ["intern", "entry", "mid", "senior", "staff", "principal", "director_plus"] },
    { slug: "business_customer", order: 3, default_enabled: true, selected: false, new: false, count: 7, allowed_bands: ["intern", "entry", "mid", "senior", "staff", "principal"] },
  ],
  joint_counts_ready: true,
  categories: [
    {
      slug: "technology",
      
      groups: [
        {
          slug: "software_engineering",
          
          default_enabled: false,
          selected: true, new: false,
          enabled: true,
          total: 3,
          band_counts: { entry: 2, staff: 1 },
          band_track_counts: { entry: { technical: 2 }, staff: { technical: 1 } },
          joint_complete: true,
        },
        {
          slug: "security_engineering",
          
          default_enabled: false,
          selected: false, new: false,
          enabled: false,
          total: 4,
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
          slug: "technical_program_management",
          
          default_enabled: true,
          selected: false, new: false,
          enabled: false,
          total: 2,
          band_counts: { staff: 2 },
          band_track_counts: { staff: { product_program: 2 } },
          joint_complete: true,
        },
      ],
    },
  ],
  companies: [
    { slug: "acme", display: "Acme", enabled: true, role_catalog_status: "ready", role_catalog_scanned_at: null, role_catalog_error: null },
  ],
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.scopeRules).mockResolvedValue({ rules: [] });
  load.mockResolvedValue(catalog);
  refresh.mockResolvedValue({ status: "started", max_list: 600 });
  save.mockImplementation(async (payload) => settingsSaveFixture(payload));
  companies.mockResolvedValue({ companies: [] });
  suggestions.mockResolvedValue({ suggestions: [] });
  vi.mocked(api.profile).mockResolvedValue(profileStateFixture());
});

it("computes joint role and seniority impact without double counting", () => {
  const impact = calculateScopeImpact(
    catalog,
    new Set(["software_engineering"]),
    new Set(["staff"]),
    new Set(["management", "product_program", "technical"]),
    new Set(["software_engineering", "security_engineering"]),
    new Set(["staff", "entry"]),
    new Set(["management", "product_program", "technical"]),
  );
  expect(impact).toEqual({ total: 6, complete: true });
});

it("leaves the impact unpriced while a family it names has roles with no track split", () => {
  const unsplit = (group: ScopeCatalog["categories"][number]["groups"][number]) =>
    group.slug === "security_engineering" ? { ...group, joint_complete: false } : group;
  const partial: ScopeCatalog = {
    ...catalog,
    categories: catalog.categories.map((category) => ({ ...category, groups: category.groups.map(unsplit) })),
  };
  const roles = new Set(["software_engineering"]);
  const bands = new Set(["staff"]);
  const tracks = new Set(["management", "product_program", "technical"]);

  expect(calculateScopeImpact(partial, roles, bands, tracks, roles, new Set(["staff", "entry"]), tracks))
    .toEqual({ total: 2, complete: true });
  expect(
    calculateScopeImpact(partial, roles, bands, tracks, new Set([...roles, "security_engineering"]), bands, tracks)
      .complete,
  ).toBe(false);
});

// --------------------------------------------------------------------------- //
// Locations. A dominant search field over two DISJOINT blocks:
// "Tracking" (what you have) and "Add locations" (what you don't). A place is in
// exactly one of them. What a selection includes is spelled out in words — "All
// countries", or the actual names — because a ratio ("0/45 countries") does not
// answer the only question a user asks. No counts and no coverage badge live on
// this surface at all.
// --------------------------------------------------------------------------- //

it("starts a scope-only inventory refresh from settings", async () => {
  load.mockResolvedValue({
    ...catalog,
    joint_counts_ready: false,
    unstated_level_count: 0,
    companies: [{ ...catalog.companies[0], role_catalog_status: "partial" }],
  });
  renderScope();
  await screen.findByRole("region", { name: "What your radar looks for" });

  await userEvent.click(screen.getByRole("button", { name: "Refresh role counts" }));

  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  expect(await screen.findByText(/reads careers pages only/i)).toBeInTheDocument();
});

it("reports when scope refresh is deferred behind another sync", async () => {
  refresh.mockResolvedValue({ status: "deferred" });
  load.mockResolvedValue({
    ...catalog,
    joint_counts_ready: false,
    unstated_level_count: 0,
    companies: [{ ...catalog.companies[0], role_catalog_status: "partial" }],
  });
  renderScope();
  await screen.findByRole("region", { name: "What your radar looks for" });

  await userEvent.click(screen.getByRole("button", { name: "Refresh role counts" }));

  expect(await screen.findByText(/waits until the current scan or count ends/i)).toBeInTheDocument();
});

/* The level dimmer is the ONLY seniority control (`toggleBand` has no
   caller), and it writes stages, not bands. With no saved persona profile (a
   fresh install, or an app_settings loss) changing seniority must still make
   the draft dirty and offer a Save. `profile: null` is the beforeEach default
   here, matching that state. */
it("changing seniority with no saved persona profile offers a save", async () => {
  renderScope();
  await screen.findByRole("region", { name: "What your radar looks for" });

  // Place the "you are here" dot on a stage outside the saved bands (["staff"]).
  // Query the rail cell by role: once placed, the persona summary echoes the
  // stage name too, so a bare text match is ambiguous.
  await userEvent.click(screen.getByRole("button", { name: /^Entry \/ Junior/ }));

  expect(await screen.findByRole("button", { name: "Save" })).toBeInTheDocument();
});

it("saves the seniority span picked in step 2", async () => {
  save.mockResolvedValue(settingsSaveFixture({ ...catalog.settings, enabled_seniority_bands: ["entry"] }));
  renderScope();
  await screen.findByRole("region", { name: "What your radar looks for" });

  // Click places the anchor and arms the aim; the second click locks the pair.
  await userEvent.click(screen.getByRole("button", { name: /^Entry \/ Junior/ }));
  await userEvent.click(screen.getByRole("button", { name: /^Entry \/ Junior/ }));
  await userEvent.click(await screen.findByRole("button", { name: "Save" }));

  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.calls[0][0]).toMatchObject({
    enabled_seniority_bands: ["entry"],
    experience_stage: "entry",
    target_stage: "entry",
  });
});

/* Regression: the level control on an install with a saved persona.
   Skipping the stage->band sync in a "custom" mode would leave the only
   seniority control changing no draft set and offering no Save, while every
   save of another axis re-sent stale bands. There is no such mode; the markers
   ride every save. */
const fineTuned = (stages: { experience: string; target: string }) =>
  vi.mocked(api.profile).mockResolvedValue(profileStateFixture({
    profile: { experience_stage: stages.experience, target_stage: stages.target },
  }));

it("a fine-tuned install can still change its level, and the raw save carries it", async () => {
  // Stored bands already agree with the persona, so the screen loads clean and
  // the Save this asserts can only have come from the level edit.
  fineTuned({ experience: "staff", target: "staff" });
  renderScope();
  await screen.findByRole("region", { name: "What your radar looks for" });
  expect(screen.queryByRole("button", { name: "Save" })).toBeNull();

  // Re-aim from Staff down to Junior: click places the anchor and arms the aim,
  // the second click locks the pair.
  await userEvent.click(screen.getByRole("button", { name: /^Staff/ }));
  await userEvent.click(screen.getByRole("button", { name: /^Entry \/ Junior/ }));
  await userEvent.click(await screen.findByRole("button", { name: "Save" }));

  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  // The raw axis path, carrying the span AND the two markers — the markers
  // live only on the persona, so without them the level edit would be lost.
  expect(save.mock.calls[0][0]).toMatchObject({
    enabled_seniority_bands: ["entry", "staff"],
    experience_stage: "staff",
    target_stage: "entry",
  });
});

it("offers to repair a stored seniority axis that contradicts the level", async () => {
  // Persona says Junior, the axis says Staff.
  // With no band-level control anywhere, that is corruption, not a choice — so
  // the screen must not load clean over it.
  fineTuned({ experience: "entry", target: "entry" });
  renderScope();
  await screen.findByRole("region", { name: "What your radar looks for" });

  await userEvent.click(await screen.findByRole("button", { name: "Save" }));

  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.calls[0][0]).toMatchObject({
    enabled_seniority_bands: ["entry"],
    experience_stage: "entry",
    target_stage: "entry",
  });
});

it("keeps fifty exclusions collapsed, pages five at a time, and reconciles a shrinking last page", async () => {
  vi.mocked(api.scopeRules).mockResolvedValue({
    rules: Array.from({ length: 50 }, (_, i) => ({ id: i + 1, company: "acme", kind: "team", value: `Platform team ${i + 1}`, created_at: "2026-08-06T00:00:00Z" })),
  });
  vi.mocked(api.deleteScopeRule).mockResolvedValue({ deleted: true, in_scope_changed: 1, promoted: 0, promotion_pending: false });
  renderScope();
  const region = await screen.findByRole("region", { name: "Company exclusions" });
  const toggle = within(region).getByRole("button", { name: /Company exclusions 50/ });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(within(region).queryByRole("button", { name: /Remove exclusion/ })).toBeNull();
  await userEvent.click(toggle);
  expect(within(region).getAllByRole("button", { name: /Remove exclusion/ })).toHaveLength(5);
  expect(within(region).getByText(/Platform team 1”/)).toBeVisible();
  expect(within(region).queryByText(/Platform team 6”/)).toBeNull();
  for (let page = 1; page < 10; page++) await userEvent.click(within(region).getByRole("button", { name: "Next" }));
  expect(region).toHaveTextContent("Page 10 of 10");
  expect(within(region).getByRole("button", { name: "Next" })).toBeDisabled();
  for (let id = 46; id <= 50; id++) {
    await userEvent.click(within(region).getByRole("button", { name: `Remove exclusion Platform team ${id} at acme` }));
    await waitFor(() => expect(within(region).queryByRole("button", { name: `Remove exclusion Platform team ${id} at acme` })).toBeNull());
  }
  expect(region).toHaveTextContent("Page 9 of 9");
  expect(within(region).getAllByRole("button", { name: /Remove exclusion/ })).toHaveLength(5);
  await userEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(within(region).queryByRole("button", { name: /Remove exclusion/ })).toBeNull();
});

it("a failed read of the exclusions is said with Try again, never taken for none", async () => {
  vi.mocked(api.scopeRules)
    .mockRejectedValueOnce(new Error("unavailable"))
    .mockResolvedValue({ rules: [{ id: 3, company: "acme", kind: "team", value: "Fulfillment", created_at: "2026-08-06T00:00:00Z" }] });
  renderScope();
  const region = await screen.findByRole("region", { name: "Company exclusions" });
  expect(within(region).getByText("Couldn't load your company exclusions")).toBeInTheDocument();
  await userEvent.click(within(region).getByRole("button", { name: /Try again/ }));
  expect(await screen.findByRole("button", { name: /Company exclusions 1/ })).toBeInTheDocument();
});

it("lists learned company exclusions and revoking one reports the rows returned", async () => {
  vi.mocked(api.scopeRules).mockResolvedValue({
    rules: [
      { id: 3, company: "acme", kind: "team", value: "Fulfillment", created_at: "2026-08-06T00:00:00Z" },
    ],
  });
  vi.mocked(api.deleteScopeRule).mockResolvedValue({
    deleted: true,
    in_scope_changed: 6,
    promoted: 0,
    promotion_pending: false,
  });
  renderScope();
  await screen.findByRole("region", { name: "What your radar looks for" });

  const rules = await screen.findByRole("region", { name: "Company exclusions" });
  await userEvent.click(within(rules).getByRole("button", { name: /Company exclusions/ }));
  // The employer's verbatim vocabulary, attributed to its company and field.
  expect(rules).toHaveTextContent(/acme · team “Fulfillment”/);

  await userEvent.click(
    screen.getByRole("button", { name: "Remove exclusion Fulfillment at acme" })
  );
  await waitFor(() =>
    expect(api.deleteScopeRule).toHaveBeenCalledWith(3)
  );
  // Revoking is reversible in effect: the freed rows are counted back in.
  expect(await screen.findByText(/6 roles back on your radar/)).toBeInTheDocument();
  expect(screen.queryByText(/team “Fulfillment”/)).not.toBeInTheDocument();
});

it("puts a revoked exclusion back, by value, when Undo is taken", async () => {
  /* Revoking is undoable without dismissing a matching role again. The deleted
     row's id is gone with it, so the way back writes the same
     company/kind/value through the create endpoint the dismiss flow uses. */
  const rule = { id: 3, company: "acme", kind: "team" as const, value: "Fulfillment", created_at: "2026-08-06T00:00:00Z" };
  vi.mocked(api.scopeRules).mockResolvedValue({ rules: [rule] });
  vi.mocked(api.deleteScopeRule).mockResolvedValue({
    deleted: true,
    in_scope_changed: 6,
    promoted: 0,
    promotion_pending: false,
  });
  vi.mocked(api.createScopeRule).mockResolvedValue({
    rule: { ...rule, id: 9 },
    created: true,
    in_scope_changed: 6,
    promoted: 0,
    promotion_pending: false,
  });
  renderScope();
  await screen.findByRole("region", { name: "Company exclusions" });
  await userEvent.click(screen.getByRole("button", { name: /Company exclusions/ }));

  await userEvent.click(
    screen.getByRole("button", { name: "Remove exclusion Fulfillment at acme" })
  );
  await screen.findByText(/Exclusion removed/);
  // The list is empty now, so the way back has to live outside it — the toast.
  expect(screen.queryByRole("region", { name: "Company exclusions" })).not.toBeInTheDocument();

  vi.mocked(api.scopeRules).mockResolvedValue({
    rules: [{ ...rule, id: 9 }],
  });
  await userEvent.click(screen.getByRole("button", { name: "Undo" }));
  await waitFor(() =>
    expect(api.createScopeRule).toHaveBeenCalledWith({
      company: "acme",
      kind: "team",
      value: "Fulfillment",
    })
  );
  expect(await screen.findByText(/6 roles left your radar again/)).toBeInTheDocument();
  const restored = await screen.findByRole("region", { name: "Company exclusions" });
  expect(restored).toHaveTextContent(/acme · team “Fulfillment”/);
});

it("keeps a failed revoke visible and says it did not land", async () => {
  /* A rejected request leaves the row on screen, still excluding: saying
     nothing would let the click read as done. */
  vi.mocked(api.scopeRules).mockResolvedValue({
    rules: [
      { id: 3, company: "acme", kind: "team", value: "Fulfillment", created_at: "2026-08-06T00:00:00Z" },
    ],
  });
  vi.mocked(api.deleteScopeRule).mockRejectedValue(new Error("offline"));
  renderScope();
  await screen.findByRole("region", { name: "Company exclusions" });
  await userEvent.click(screen.getByRole("button", { name: /Company exclusions/ }));

  await userEvent.click(
    screen.getByRole("button", { name: "Remove exclusion Fulfillment at acme" })
  );

  expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't remove that exclusion. Try again.");
  expect(screen.getByText(/team “Fulfillment”/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
});
