import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import type { ScopeCatalog, ScopeRoleGroup } from "../../../api";
import { api } from "../../../api";
import { ScopeDraftProvider, useScopeDraft } from "../useScopeDraft";
import { Walk } from "./Walk";
import type { SetupCompaniesProps } from "../../../routing/setupMode";
import { ScopeGuideButton } from "../ScopeGuide";
import { Button } from "../../../ui/Button";
import { ToastProvider } from "../../../ui/Toast";
import { emptyScopeCellsFixture, profileStateFixture, settingsSaveFixture } from "../../../test/fixtures";
import { ROLE_QUESTIONS } from "./walkModel";
import { ProgressRail, previewSentences } from "./ProgressRail";
import { SummaryStep } from "./SummaryStep";
import { SubjectsStep } from "./SubjectsStep";
import { progressOf } from "./walkProgress";
import { countByOption, countUnderScope } from "../scopeCells";
import { msg } from "../../../test/msg";
import { companyName } from "../../../format";

/* The funnel and the card counts are spied on, never replaced: each spy runs
   the real count, so every screen below reads the numbers it always did, and
   a test can ask how often the joint was scanned. */
vi.mock("./walkProgress", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./walkProgress")>();
  return { ...actual, progressOf: vi.fn(actual.progressOf) };
});
vi.mock("../scopeCells", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../scopeCells")>();
  return {
    ...actual,
    countUnderScope: vi.fn(actual.countUnderScope),
    countByOption: vi.fn(actual.countByOption),
  };
});

vi.mock("../../../api", () => ({
  api: {
    scopeCatalog: vi.fn(),
    searchPlaces: vi.fn(),
    refreshScopeCatalog: vi.fn(),
    saveSettings: vi.fn(),
    previewScope: vi.fn(),
    companies: vi.fn(),
    profile: vi.fn(),
    scopeRules: vi.fn(),
    deleteScopeRule: vi.fn(),
    createScopeRule: vi.fn(),
    profileSuggestions: vi.fn(),
    acceptProfileSuggestion: vi.fn(),
    dismissProfileSuggestion: vi.fn(),
    payFloor: vi.fn(() => Promise.resolve({ pay_floor: null })),
    savePayFloor: vi.fn((floor: unknown) => Promise.resolve({ pay_floor: floor })),
    clearPayFloor: vi.fn(() => Promise.resolve({ pay_floor: null })),
  },
}));

vi.mock("../../../context/MissionState", () => ({
  useMissionActions: () => ({ refreshStats: vi.fn() }),
  useMissionState: () => ({ stats: { open_total: 904 }, newSignalsOnly: false, repostsOnly: false }),
}));

const load = vi.mocked(api.scopeCatalog);
const save = vi.mocked(api.saveSettings);
const companies = vi.mocked(api.companies);
const suggestions = vi.mocked(api.profileSuggestions);
const profile = vi.mocked(api.profile);
const rules = vi.mocked(api.scopeRules);
const searchPlaces = vi.mocked(api.searchPlaces);
const previewScope = vi.mocked(api.previewScope);

/** A Summary row's value, read by its label. */
const fact = (label: string) => label === "Minimum base" ? screen.getByRole("region", { name: "Minimum base" }) :
  screen.getByText(label, { selector: ".persona-fact-label" }).closest(".persona-fact")!.querySelector<HTMLElement>(".persona-fact-value")!;

const renderWalk = () => render(
  <ToastProvider>
    <MemoryRouter>
      <ScopeDraftProvider>
        <Walk />
      </ScopeDraftProvider>
    </MemoryRouter>
  </ToastProvider>,
);

const group = (slug: string): ScopeRoleGroup => ({
  slug, default_enabled: false, selected: false, new: false, enabled: false, total: 1,
  band_counts: { staff: 1 }, band_track_counts: { staff: { technical: 1 } }, joint_complete: true,
});

const ALL_BANDS = ["intern", "entry", "mid", "senior", "staff", "principal", "director_plus"];

/* Joint cells, so the progress rail and the Summary's funnel have something to
   count: 20 roles at "acme", spread so each answer narrows. A cell is
   [role, band, track, location set, domain set, count] over the dictionaries. */
const CELLS: ScopeCatalog["scope_cells"] = {
  ...emptyScopeCellsFixture,
  ready: true,
  roles: ["software_engineering", "engineering_management", "product_management"],
  bands: ["entry", "staff"],
  tracks: ["management", "technical", "product_program"],
  cities: [],
  location_sets: [["silicon_valley", "united_states"], ["uk", "europe"]],
  domain_sets: [[], ["ai_ml"], ["logistics_fulfillment"]],
  cells: [
    [1, 1, 0, 0, 1, 4], // EM · staff · management · SV · AI
    [1, 1, 0, 1, 2, 2], // EM · staff · management · UK · logistics
    [0, 1, 1, 0, 1, 5], // SWE · staff · technical · SV · AI
    [0, 0, 1, 0, 0, 3], // SWE · junior · technical · SV · unclassified
    [2, 1, 2, 1, 2, 6], // PM · staff · product · UK · logistics
  ],
  companies: ["acme"],
};

/* Settings without an excluded list read as a profile where nobody said
   "not interested in" anything. */
type Settings = Omit<ScopeCatalog["settings"], "excluded_domain_groups" | "excluded_location_groups" | "role_answers" | "include_unstated_level">
  & {
    excluded_domain_groups?: string[]; excluded_location_groups?: string[];
    role_answers?: ScopeCatalog["settings"]["role_answers"]; include_unstated_level?: boolean;
  };
/* The answers the server reads off two flat lists when none are saved
   (`taxonomy/role_answers.answers_from_axes`): every saved kind, holding the
   saved families, "any" when they are the whole taxonomy. */
const ALL_FAMILIES = Object.values(ROLE_QUESTIONS).flatMap((question) => question.rows.flatMap((row) => [...row.families]));
const answersOfAxes = (tracks: string[], roles: string[]): ScopeCatalog["settings"]["role_answers"] => {
  const any = [...new Set(ALL_FAMILIES)].every((family) => roles.includes(family));
  return roles.length === 0 ? [] : tracks.map((track) => ({ track, roles: any ? "any" as const : roles }));
};
const catalog = (settings: Settings, cells: ScopeCatalog["scope_cells"] = CELLS): ScopeCatalog => ({
  scope_cells: cells,
  settings: {
    excluded_domain_groups: [],
    excluded_location_groups: [],
    role_answers: answersOfAxes(settings.enabled_role_tracks, settings.enabled_role_groups),
    include_unstated_level: false,
    ...settings,
  },
  domains: [
    { slug: "ai_ml", selected: true, count: 8, examples: [], kind: "technology" },
    { slug: "logistics_fulfillment", selected: true, count: 3, examples: [], kind: "function" },
    { slug: "health_bio", selected: true, count: 2, examples: [], kind: "industry" },
  ],
  unclassified_domain_count: 2,
  levels: [
    { slug: "entry", order: 0, default_enabled: false, selected: false, new: false, count: 2, decoder: {} },
    { slug: "staff", order: 2, default_enabled: true, selected: true, new: false, count: 7, decoder: {} },
  ],
  locations: [
    { slug: "silicon_valley", display: "Silicon Valley", default_enabled: true, selected: true, new: false, count: 6, kind: "metro", parent: "united_states", uncovered_by: [], prominent: true },
    { slug: "united_states", display: "United States", default_enabled: true, selected: false, new: false, count: 9, kind: "country", parent: null, uncovered_by: [], prominent: true },
    { slug: "europe", display: "Europe", default_enabled: false, selected: false, new: false, count: 5, kind: "region", parent: null, uncovered_by: [], prominent: true },
    { slug: "uk", display: "United Kingdom", default_enabled: true, selected: true, new: false, count: 4, kind: "country", parent: "europe", uncovered_by: [], prominent: true },
    { slug: "sweden", display: "Sweden", default_enabled: false, selected: false, new: false, count: 0, kind: "country", parent: "europe", uncovered_by: ["acme"], prominent: true },
  ],
  tracks: [
    { slug: "management", order: 0, default_enabled: true, selected: true, new: false, count: 5, allowed_bands: ["senior", "staff", "principal", "director_plus"] },
    { slug: "product_program", order: 1, default_enabled: true, selected: true, new: false, count: 4, allowed_bands: ALL_BANDS },
    { slug: "technical", order: 2, default_enabled: true, selected: true, new: false, count: 9, allowed_bands: ALL_BANDS },
    { slug: "business_customer", order: 3, default_enabled: true, selected: false, new: false, count: 7, allowed_bands: ALL_BANDS },
  ],
  joint_counts_ready: true,
  unstated_level_count: 0,
  categories: [
    { slug: "technology", groups: [group("software_engineering"), group("engineering_management")] },
    { slug: "product", groups: [group("product_management")] },
  ],
  companies: [{ slug: "acme", display: "Acme", enabled: true, role_catalog_status: "ready", role_catalog_scanned_at: null, role_catalog_error: null }],
});

const RETURNING = {
  enabled_role_groups: ["software_engineering"],
  enabled_seniority_bands: ["staff"],
  enabled_role_tracks: ["management", "technical"],
  enabled_location_groups: ["silicon_valley", "uk"],
  enabled_domain_groups: ["ai_ml", "logistics_fulfillment", "health_bio"],
};

const FRESH = {
  enabled_role_groups: [],
  enabled_seniority_bands: ["staff"],
  enabled_role_tracks: [],
  enabled_location_groups: [],
  enabled_domain_groups: ["ai_ml", "logistics_fulfillment", "health_bio"],
};

const rail = () => screen.getByRole("complementary", { name: "Your progress" });
// A pyramid layer: its name is the step, what it keeps is its description.
const bar = (name: string) => within(rail()).getByRole("button", { name });
const strip = () => screen.getByRole("tablist", { name: "Steps" });
// A tab's name is its label, then its badge when it has one ("World 2").
const stripButton = (name: string) => within(strip()).getByRole("tab", { name: new RegExp(`^${name}( .*)?$`) });

beforeEach(() => {
  vi.clearAllMocks();
  companies.mockResolvedValue({ companies: [] });
  suggestions.mockResolvedValue({ suggestions: [] });
  rules.mockResolvedValue({ rules: [] });
  profile.mockResolvedValue(profileStateFixture());
  save.mockImplementation(async (body) => settingsSaveFixture(body, { in_scope_changed: 3, on_board: 3 }));
  searchPlaces.mockResolvedValue({ places: [], unions: [] });
  // No preview unless a test asks for one: an implementation left by one test
  // would put Board sentences in every later review card. A failed preview is
  // what the review already handles by keeping its radar delta.
  previewScope.mockReset();
  previewScope.mockRejectedValue(new Error("no preview in this test"));
});

it("walks a fresh user through the three answers, closes the funnel on the rail, and lands on the Summary", async () => {
  load.mockResolvedValue(catalog(FRESH));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });

  // The optional steps and the Summary are locked; the rail knows the whole before any answer.
  expect(stripButton("Discipline")).toBeDisabled();
  expect(stripButton("World")).toBeDisabled();
  expect(stripButton("Summary")).toBeDisabled();
  // Five layers, one per step, and no sixth for "all roles".
  expect(within(rail()).getAllByRole("button", { name: /^(Career track|Level|Location|Discipline|World)$/ })).toHaveLength(5);
  expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  // The first step has nowhere to go back to, so it offers no Back.
  expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();

  // Step 1: the answer narrows the funnel on the rail, and Continue opens.
  await user.click(screen.getByLabelText("Leading a team"));
  expect(bar("Career track")).toHaveAccessibleDescription("Keeps 30%, 6 roles"); // 6 of 20 are management
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("heading", { name: "Your level" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Back" })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: "Continue" }));

  // Step 3: a base and a reach; the region list never appears.
  expect(screen.getByRole("heading", { name: "Where do you want to work?" })).toBeVisible();
  expect(screen.queryByText("Europe")).toBeNull();
  expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  await user.type(screen.getByLabelText("Where are you based?"), "silicon");
  await user.click(screen.getByRole("button", { name: "Add Silicon Valley" }));
  const reach = screen.getByRole("group", { name: "How far from Silicon Valley" });
  expect(within(reach).getByRole("button", { name: "Silicon Valley" })).toHaveAttribute("aria-pressed", "true");
  expect(bar("Location")).toHaveAccessibleDescription("Keeps 20%, 4 roles"); // 4 of 20: EM · staff · SV
  await user.click(within(reach).getByRole("button", { name: "United States" }));
  // The headline carries the share alone; the number is the bar's tooltip.
  expect(bar("Location")).toHaveAccessibleDescription("Keeps 20%, 4 roles");

  // The Summary: the sentence, the choices with their way back, the funnel,
  // and leaving as the one primary — the rail's Save steps back.
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("heading", { name: "Summary" })).toBeVisible();
  expect(screen.queryByText("Change any answer and this page shows what it costs or gains.")).toBeNull();
  expect(fact("Career track")).toHaveTextContent(/^Leading a team/);
  expect(fact("Level")).toHaveTextContent(/^At Staff/);
  expect(fact("Location")).toHaveTextContent(/^Anywhere in the US/);
  expect(stripButton("Discipline")).toBeEnabled();
  expect(screen.getAllByRole("button").filter((b) => b.classList.contains("ui-btn-primary")).map((b) => b.textContent))
    .toEqual(["Save and see your radar"]);
  expect(screen.getByRole("region", { name: "What it keeps" }).querySelector(".walk-funnel-row:last-child")).toHaveTextContent(/4\s*20%/);

  // Step 4 from the Summary's own way back: narrow to engineers.
  await user.click(screen.getByRole("button", { name: "Adjust discipline" }));
  expect(screen.getByRole("heading", { name: "Any particular roles?" })).toBeVisible();
  // Each answer starts with nothing ticked: every role of the kind is kept,
  // and the layer stays open until a card is ticked.
  expect(screen.getByLabelText("Engineers (Leading a team)")).not.toBeChecked();
  expect(screen.getByLabelText("Engineers (Leading a team)")).toBeEnabled();
  expect(bar("Discipline")).toHaveAccessibleDescription("Any, nothing narrowed");
  // The filter narrows the cards by name or example; a card is the same object as step 1.
  await user.type(screen.getByLabelText("Filter roles"), "design");
  expect(screen.queryByLabelText("Engineers (Leading a team)")).toBeNull();
  expect(screen.getByLabelText("Designers (Leading a team)")).toBeVisible();
  await user.clear(screen.getByLabelText("Filter roles"));
  // Ticking engineers narrows to them, and the layer is drawn.
  await user.click(screen.getByLabelText("Engineers (Leading a team)"));
  expect(bar("Discipline")).toHaveAccessibleDescription(/^Keeps 20%/);
  // Unticking the last card gives every role back, and the layer opens again.
  await user.click(screen.getByLabelText("Engineers (Leading a team)"));
  expect(bar("Discipline")).toHaveAccessibleDescription("Any, nothing narrowed");
  await user.click(screen.getByLabelText("Engineers (Leading a team)"));

  // Save lives on the rail, under the impact of what is unsaved.
  const review = screen.getByRole("region", { name: "Review changes" });
  await user.click(within(review).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  const body = save.mock.calls[0][0];
  expect(body.enabled_role_tracks).toEqual(["management"]);
  expect(body.enabled_location_groups).toEqual(["united_states"]);
  expect(body.enabled_role_groups).toEqual(expect.arrayContaining(["engineering_management", "software_engineering"]));
  expect(body.enabled_role_groups).not.toContain("product_management");
  // The answer itself travels: leading a team of engineers, nothing else.
  expect(body.role_answers).toEqual([{
    track: "management",
    roles: ["data_engineering", "engineering_management", "hardware_engineering", "infrastructure_sre", "security_engineering", "software_engineering"],
  }]);
  expect(await within(rail()).findByText(
    "Saved. 3 roles are on your radar now. Up to 1 more arrive as each company is next scanned.",
  )).toBeVisible();
});

it("the rail and the Summary count what the save keeps, even when step 4 still reads as any", async () => {
  /* Leading a team reads "any" (no row fully off: the research row is partly
     on), but the saved families leave data science out. That leftover is what
     a dropped answer can leave behind, invisibly: a rail count above what the
     save keeps. */
  const cells: ScopeCatalog["scope_cells"] = {
    ...CELLS,
    roles: ["engineering_management", "data_science"],
    bands: ["staff"],
    tracks: ["management"],
    location_sets: [["silicon_valley", "united_states"]],
    domain_sets: [[]],
    cells: [
      [0, 0, 0, 0, 0, 4], // EM · staff · management · SV
      [1, 0, 0, 0, 0, 3], // DS · staff · management · SV: not in the saved families
    ],
  };
  const base = catalog({
    ...RETURNING,
    enabled_role_tracks: ["management"],
    enabled_role_groups: [...new Set(ALL_FAMILIES)].filter((family) => family !== "data_science"),
    enabled_location_groups: ["silicon_valley"],
  }, cells);
  load.mockResolvedValue({
    ...base,
    categories: [...base.categories, { slug: "ai_data", groups: [group("data_science")] }],
  });
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });

  expect(bar("Location")).toHaveAccessibleDescription("Keeps 100%, 7 roles");
  // The layer says it narrows, because the save does.
  expect(bar("Discipline")).toHaveAccessibleDescription("Keeps 57%, 4 roles");
  expect(rail().querySelectorAll(".walk-pyramid-caption")[3]).toHaveTextContent("Discipline57%");

  await user.click(stripButton("Summary"));
  expect(screen.getByRole("region", { name: "What it keeps" }).querySelector(".walk-funnel-row:last-child")).toHaveTextContent(/4\s*57%/);
});

it("lands a returning user on the same walk with every step live and the Summary already written", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });

  for (const name of ["Career track", "Level", "Location", "Discipline", "World", "Summary"]) {
    expect(stripButton(name)).toBeEnabled();
  }
  expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  expect(bar("Career track")).toHaveAccessibleDescription("Keeps 70%, 14 roles"); // 14 of 20: management + technical

  await user.click(stripButton("Summary"));
  // The kinds on one row, the narrowing on its own.
  expect(within(fact("Career track")).getByText("Leading a team or hands-on")).toBeVisible();
  expect(fact("Discipline")).toHaveTextContent(/^Software/);
  expect(fact("Location")).toHaveTextContent(/^In Silicon Valley or anywhere in the UK/);
  // No world picked keeps every world: said as such, never as "None yet".
  expect(fact("World")).toHaveTextContent("Any world");

  // Any step is one tap away, and the screen is the one they answered on.
  await user.click(stripButton("Location"));
  expect(within(screen.getByRole("group", { name: "How far from Silicon Valley" })).getByRole("button", { name: "Silicon Valley" })).toHaveAttribute("aria-pressed", "true");
  await user.click(screen.getByRole("button", { name: "Remove United Kingdom" }));
  const review = screen.getByRole("region", { name: "Review changes" });
  expect(within(review).getByRole("button", { name: "Save" })).toBeVisible();
  // The preview counts from the same joint as the rail: every role this
  // profile keeps is in Silicon Valley, so dropping the UK changes nothing,
  // and it says so instead of "Updates when you save".
  expect(review).toHaveTextContent("No change when you save");
});

it("names a not-interested pick that takes out most of a row picked on Which roles, and only that one", async () => {
  /* Engineering managers, only: 4 in AI (Silicon Valley), 2 in logistics
     (UK). "Not interested in AI" takes 4 of those 6, a contradiction the
     step names; logistics takes 2 of 6, an ordinary narrowing it does not. */
  const engineers = ["engineering_management", "software_engineering", "infrastructure_sre",
    "security_engineering", "hardware_engineering", "data_engineering"];
  load.mockResolvedValue(catalog({
    ...RETURNING,
    enabled_role_tracks: ["management"],
    enabled_role_groups: engineers,
    enabled_domain_groups: ["health_bio"],
    excluded_domain_groups: ["ai_ml", "logistics_fulfillment"],
    role_answers: [{ track: "management", roles: engineers }],
  }));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("World"));

  const notes = screen.getAllByRole("note").map((note) => note.textContent);
  expect(notes).toContain(
    "Not interested in AI & Machine Learning removes 4 of the 6 roles you picked under Engineers. Untick one if that isn't what you meant.",
  );
  expect(notes.join(" ")).not.toMatch(/Logistics/);
});

it("counts the roles with no subject under the draft, not across the market", async () => {
  /* Three unsorted roles exist, all Junior. At Staff the draft keeps none of
     them, so no line; at Junior and Staff it keeps them, out of 8. */
  load.mockResolvedValue(catalog(RETURNING));
  const user = userEvent.setup();
  const { unmount } = renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("World"));
  expect(screen.queryByText(/aren't sorted into a world yet/)).toBeNull();
  unmount();

  load.mockResolvedValue(catalog({ ...RETURNING, enabled_seniority_bands: ["entry", "staff"] }));
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("World"));
  expect(screen.getByText("3 of your 8 roles aren't sorted into a world yet. They stay on your radar whatever you pick.")).toBeVisible();
});

it("writes an interest with the verb first, reads it back on the Summary, and saves the worlds set it means", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });

  await user.click(stripButton("World"));
  expect(screen.getByRole("heading", { name: "Anything you care about, or want to avoid?" })).toBeVisible();
  // The list is chosen first, and both lists stay on screen: each says what
  // it does and how many it holds, the chosen one says "Picking now" and the
  // other offers the switch. The picker is named by the list it fills.
  const lists = screen.getByRole("group", { name: "Choose a list, then tick what goes in it" });
  const interestedList = within(lists).getByRole("radio", { name: "Interested in" });
  const avoidList = within(lists).getByRole("radio", { name: "Not interested in" });
  expect(interestedList).toBeChecked();
  expect(interestedList).toHaveAccessibleDescription(/plus roles not yet sorted into one/);
  expect(avoidList).toHaveAccessibleDescription(/Roles about these drop off/);
  const option = (radio: HTMLElement) => radio.closest("label")!;
  expect(option(interestedList)).toHaveTextContent(/Picking now/);
  expect(option(avoidList)).toHaveTextContent(/Switch to this/);
  expect(option(avoidList)).toHaveTextContent(/None yet/);
  expect(screen.queryByRole("group", { name: "Not interested in" })).toBeNull();
  await user.click(avoidList);
  expect(avoidList).toBeChecked();
  expect(option(avoidList)).toHaveTextContent(/Picking now/);
  expect(option(interestedList)).toHaveTextContent(/Switch to this/);
  const picker = screen.getByRole("group", { name: "Not interested in" });
  expect(within(picker).getByText("Not interested in · Business functions")).toBeVisible();
  // Each card says in one line what its world covers, and the filter reads
  // that line as well as the name ("warehouse" finds Logistics).
  expect(within(picker).getByText("Supply chain, warehouses")).toBeVisible();
  await user.type(within(picker).getByLabelText("Filter worlds"), "warehouse");
  expect(within(picker).getByLabelText("Logistics & Fulfillment")).toBeInTheDocument();
  expect(within(picker).queryByLabelText("AI & Machine Learning")).toBeNull();
  await user.clear(within(picker).getByLabelText("Filter worlds"));
  // The filter narrows the cards to the name typed; a tap on the card writes the pick.
  await user.type(within(picker).getByLabelText("Filter worlds"), "logist");
  expect(within(picker).queryByLabelText("AI & Machine Learning")).toBeNull();
  await user.click(within(picker).getByLabelText("Logistics & Fulfillment"));
  expect(within(picker).getByLabelText("Logistics & Fulfillment")).toBeChecked();
  await user.clear(within(picker).getByLabelText("Filter worlds"));
  // The list's count moves with the tick, so the chooser says where it landed.
  expect(option(avoidList)).toHaveTextContent(/1 picked/);
  expect(option(interestedList)).toHaveTextContent(/None yet/);

  // Seen from the other verb, the pick wears its verb as a tag instead of vanishing.
  await user.click(interestedList);
  const interested = screen.getByRole("group", { name: "Interested in" });
  expect(within(interested).getByLabelText("Logistics & Fulfillment")).not.toBeChecked();
  expect(within(interested).getByText("Not interested in", { selector: ".walk-card-tag" })).toBeVisible();

  expect(screen.queryByRole("region", { name: "Your picks" })).toBeNull();
  // Picks stay on their cards; the tab's name is stable while the funnel updates.
  expect(stripButton("World")).toHaveAccessibleName("World");
  expect(bar("World")).toHaveAccessibleDescription("Keeps 25%, 5 roles"); // 5 of 20: SWE · staff · SV · AI

  const review = screen.getByRole("region", { name: "Review changes" });
  await user.click(within(review).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][0].enabled_domain_groups).toEqual(["ai_ml", "health_bio"]);
  expect(save.mock.calls[0][0].excluded_domain_groups).toEqual(["logistics_fulfillment"]);

  // Removing the pick frees the subject again.
  await user.click(avoidList);
  await user.click(within(screen.getByRole("group", { name: "Not interested in" })).getByLabelText("Logistics & Fulfillment"));
  expect(within(screen.getByRole("group", { name: "Not interested in" })).getByLabelText("Logistics & Fulfillment")).not.toBeChecked();
  expect(bar("World")).toHaveAccessibleDescription("Any, nothing narrowed");
});

it("\"Not interested in\" drops a role about that subject even when it is also about something else", async () => {
  // SWE · staff · SV, tagged AI AND Logistics; without the veto, the AI tag would keep it.
  const cells: ScopeCatalog["scope_cells"] = {
    ...CELLS,
    domain_sets: [[], ["ai_ml"], ["ai_ml", "logistics_fulfillment"]],
    cells: [
      [0, 1, 1, 0, 1, 5], // SWE · staff · technical · SV · AI
      [0, 1, 1, 0, 2, 4], // SWE · staff · technical · SV · AI + Logistics
      [0, 1, 1, 0, 0, 3], // SWE · staff · technical · SV · untagged
    ],
  };
  load.mockResolvedValue(catalog({ ...RETURNING, enabled_role_tracks: ["technical"] }, cells));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });

  await user.click(stripButton("World"));
  const lists = screen.getByRole("group", { name: "Choose a list, then tick what goes in it" });
  const avoidList = within(lists).getByRole("radio", { name: "Not interested in" });
  expect(avoidList).toHaveAccessibleDescription("Roles about these drop off, even if they also match an interest.");
  await user.click(avoidList);
  await user.click(within(screen.getByRole("group", { name: "Not interested in" })).getByLabelText("Logistics & Fulfillment"));
  // 12 roles; the one tagged Logistics leaves, AI or not. Untagged stays.
  expect(bar("World")).toHaveAccessibleDescription("Keeps 67%, 8 roles");

  const review = screen.getByRole("region", { name: "Review changes" });
  await user.click(within(review).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][0].excluded_domain_groups).toEqual(["logistics_fulfillment"]);
});

it("a tab carries no done mark, and a locked one no count, whatever it held before", async () => {
  // Places emptied: the first three are not all answered, so the optional
  // steps lock, though World still holds a pick and Discipline a family.
  load.mockResolvedValue(catalog({ ...RETURNING, enabled_location_groups: [], enabled_domain_groups: ["ai_ml"] }));
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  const interests = stripButton("World");
  expect(interests).toBeDisabled();
  expect(interests).toHaveAccessibleName("World");
  expect(interests).toHaveAccessibleDescription("The other steps open once you answer the first three.");
  expect(rail().querySelector(".walk-progress-outcome")).toBeNull();
  // No done marks on any tab, answered or not: the selected tab is the one
  // mark the bar carries.
  expect(strip().querySelector("svg")).toBeNull();
  expect(stripButton("Career track")).toHaveAccessibleName("Career track");
});

it("a pyramid layer opens its step, and the current step's layer is marked", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  expect(bar("Career track")).toHaveAttribute("aria-current", "step");
  await user.click(bar("Location"));
  expect(screen.getByRole("heading", { name: "Where do you want to work?" })).toBeVisible();
  expect(stripButton("Location")).toHaveAttribute("aria-selected", "true");
  expect(bar("Location")).toHaveAttribute("aria-current", "step");
});

it("reads a narrowed worlds set back as the picks that produce it", async () => {
  load.mockResolvedValue(catalog({ ...RETURNING, enabled_domain_groups: ["ai_ml"] }));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  expect(stripButton("World")).toHaveAccessibleName("World");
  await user.click(stripButton("Summary"));
  expect(fact("World")).toHaveTextContent(/^AI & Machine Learning/);
});

it("says when nothing has been counted instead of showing a zero, and offers the count there", async () => {
  load.mockResolvedValue({ ...catalog(RETURNING, emptyScopeCellsFixture), joint_counts_ready: false });
  vi.mocked(api.refreshScopeCatalog).mockResolvedValue({ status: "started", max_list: 600 });
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  expect(rail()).toHaveTextContent("No count yet");
  expect(rail()).not.toHaveTextContent(/\b0%/);
  // Said once, as the headline; no bar shows a share it cannot know, and
  // each says so in its own tooltip.
  expect(within(rail()).getAllByText(/^No count yet/)).toHaveLength(1);
  expect(rail()).not.toHaveTextContent(/%/);
  expect(strip()).not.toHaveTextContent(/%/);
  expect(bar("Career track")).toHaveAccessibleDescription("Answered, no count yet");
  await user.click(within(rail()).getByRole("button", { name: "Count now" }));
  expect(await within(rail()).findByText(/Counting roles again/)).toBeVisible();
});

it("Count now asks for the places being answered, before they are saved", async () => {
  /* Anywhere picked on Where and not saved: the count must ask the sources
     for those places, or it recounts the saved ones and the draft stays
     "not scanned". */
  load.mockResolvedValue({ ...catalog(RETURNING, emptyScopeCellsFixture), joint_counts_ready: false });
  const refresh = vi.mocked(api.refreshScopeCatalog);
  refresh.mockResolvedValue({ status: "started", max_list: 600 });
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Location"));
  await user.click(screen.getByRole("button", { name: "Go worldwide" }));
  await user.click(within(rail()).getByRole("button", { name: "Count now" }));
  expect(refresh).toHaveBeenCalledTimes(1);
  expect(new Set(refresh.mock.calls[0][0])).toEqual(new Set(["united_states", "europe"]));
});

it("level rungs count the roles your other answers keep, and a rung the answer rules out shows none", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Level"));
  const rung = (name: string) => screen.getAllByRole("button").find((button) => button.classList.contains("stage-cell") && button.textContent?.startsWith(name))!;
  // Software engineers in Silicon Valley or the UK: 5 at Staff, 3 at Junior.
  // (The catalog's market-wide counts are 7 and 2.)
  expect(rung("Staff")).toHaveTextContent("5 roles");
  expect(rung("Entry / Junior")).toHaveTextContent("3 roles");

  // Leading a team alone starts at Senior: the Junior rung is ruled out and shows no count.
  await user.click(stripButton("Career track"));
  await user.click(screen.getByLabelText("Hands-on, as the expert"));
  await user.click(stripButton("Level"));
  expect(rung("Entry / Junior")).toBeDisabled();
  expect(rung("Entry / Junior")).not.toHaveTextContent(/roles/);
});

it("a followed company not counted yet leaves the counts standing, and the rail stays the funnel", async () => {
  const base = catalog(RETURNING, { ...CELLS, stale_companies: ["stripe"] });
  load.mockResolvedValue({
    ...base,
    joint_counts_ready: false,
    unstated_level_count: 0,
    companies: [...base.companies, { slug: "stripe", display: "Stripe", enabled: true, role_catalog_status: "ready", role_catalog_scanned_at: null, role_catalog_error: null }],
  });
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  expect(bar("Career track")).toHaveAccessibleDescription("Keeps 70%, 14 roles");
  // Which companies are not counted belongs to the company register, not the funnel card.
  expect(rail()).not.toHaveTextContent("Stripe");
});

it("a company scanned only for other places is named on the Where step, never on the funnel card", async () => {
  // Acme lists only the places it is asked for, and was asked for the US:
  // Silicon Valley is inside it, the UK is not.
  load.mockResolvedValue(catalog(RETURNING, { ...CELLS, scanned_places: { acme: ["united_states"] }, unplaced: 1234 }));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  expect(rail()).not.toHaveTextContent("scanned");
  expect(rail()).not.toHaveTextContent("1,234");
  await user.click(stripButton("Location"));
  const note = screen.getAllByRole("note").find((element) => /been scanned for/.test(element.textContent ?? ""))!;
  expect(note).toHaveTextContent("Acme hasn't been scanned for the UK yet. Count now");
  // The note offers the count, which asks for the places being answered.
  const refresh = vi.mocked(api.refreshScopeCatalog);
  refresh.mockResolvedValue({ status: "started", max_list: 600 });
  await user.click(within(note).getByRole("button", { name: "Count now" }));
  expect(new Set(refresh.mock.calls[refresh.mock.calls.length - 1][0])).toEqual(new Set(["silicon_valley", "uk"]));
  expect(await within(rail()).findByText(/Counting roles again/)).toBeVisible();
});

it("a scan that asked about a wider place covers the places inside it", async () => {
  load.mockResolvedValue(catalog(RETURNING, { ...CELLS, scanned_places: { acme: ["united_states", "europe"] } }));
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  const user = userEvent.setup();
  await user.click(stripButton("Location"));
  expect(screen.queryByText(/been scanned for/)).toBeNull();
});

it("a save says what the Board holds now, and how many more roles arrive with the next scans", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  save.mockImplementation(async (body) => settingsSaveFixture(body, { in_scope_changed: 9, on_board: 3 }));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Location"));
  await user.click(screen.getByRole("button", { name: "Remove United Kingdom" }));
  await user.click(within(screen.getByRole("region", { name: "Review changes" })).getByRole("button", { name: "Save" }));
  // The radar keeps 5 roles here; the Board holds 3, so 2 are still to
  // arrive. Never "9 roles changed", which counts closed rows and every company.
  const confirmation = await within(rail()).findByRole("status");
  expect(confirmation).toHaveTextContent("Saved. 3 roles are on your radar now. Up to 2 more arrive as each company is next scanned.");
});

const PREVIEW = {
  on_board_now: 12, on_board_after: 15, adds_now: 3, adds_on_board: 3, adds_later: 0, scan_running: false, examples: [],
};

it("before Save, the review says how the Board changes, from the server, for exactly what the save sends", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  previewScope.mockResolvedValue({
    ...PREVIEW,
    examples: [
      { title: "Staff Product Manager", company: "acme", company_display: "Acme" },
      { title: "Staff Engineer, Ads", company: "acme", company_display: "Acme" },
    ],
  });
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Location"));
  await user.click(screen.getByRole("button", { name: "Remove United Kingdom" }));

  const review = screen.getByRole("region", { name: "Review changes" });
  await waitFor(() => expect(review).toHaveTextContent(
    "Your radar goes from 12 to 15 roles. 3 of them from earlier scans, like Staff Product Manager at Acme and Staff Engineer, Ads at Acme.",
  ));
  await user.click(within(review).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  // The preview priced the very body the save sent: one normalisation, server side.
  expect(previewScope).toHaveBeenLastCalledWith(save.mock.calls[0][0]);
});

it("a narrowing says the Board shrinks, and a failed preview leaves the review as it was", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  previewScope.mockResolvedValueOnce({ ...PREVIEW, on_board_after: 9, adds_now: 0, adds_on_board: 0 });
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Location"));
  await user.click(screen.getByRole("button", { name: "Remove United Kingdom" }));
  const review = screen.getByRole("region", { name: "Review changes" });
  await waitFor(() => expect(review).toHaveTextContent("Your radar goes from 12 to 9 roles."));
  expect(review).not.toHaveTextContent("earlier scans");

  // An answer for an older draft is never shown against a newer one.
  previewScope.mockRejectedValueOnce(new Error("offline"));
  await user.click(screen.getByRole("button", { name: "Remove Silicon Valley" }));
  await waitFor(() => expect(previewScope).toHaveBeenCalledTimes(2));
  expect(review).not.toHaveTextContent("Your radar goes from");
});

it("the preview's sentences: unchanged, a running scan, and more than one promotion admits", () => {
  expect(previewSentences({ ...PREVIEW, on_board_after: 12, adds_now: 0, adds_on_board: 0 })).toEqual(["Your radar keeps its 12 roles."]);
  expect(previewSentences({
    ...PREVIEW, on_board_after: 12, adds_now: 0, adds_on_board: 0, adds_later: 4, scan_running: true,
    examples: [{ title: "Staff PM", company: "acme", company_display: "Acme" }],
  })).toEqual([
    "Your radar keeps its 12 roles.",
    "A scan is running: 4 roles from earlier scans join when it ends, like Staff PM at Acme.",
  ]);
  expect(previewSentences({ ...PREVIEW, on_board_after: 2012, adds_now: 2000, adds_on_board: 2000, adds_later: 7 })).toEqual([
    "Your radar goes from 12 to 2,012 roles.",
    "2,000 of them from earlier scans.",
    "More join as each company is next scanned.",
  ]);
  expect(previewSentences({ ...PREVIEW, on_board_now: 0, on_board_after: 1, adds_now: 1, adds_on_board: 1 })[0]).toBe("Your radar goes from 0 to 1 role.");
  // A hidden company's postings are added but never shown: the sentence
  // counts only what the Board gains.
  expect(previewSentences({ ...PREVIEW, on_board_after: 13, adds_now: 6, adds_on_board: 1 })).toEqual([
    "Your radar goes from 12 to 13 roles.", "1 of them from earlier scans.",
  ]);
});

async function saveWithout(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Location"));
  await user.click(screen.getByRole("button", { name: "Remove United Kingdom" }));
  await user.click(within(screen.getByRole("region", { name: "Review changes" })).getByRole("button", { name: "Save" }));
  return within(rail()).findByRole("status");
}

it("a save says how many of the Board's roles it added from earlier scans", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  save.mockImplementation(async (body) => settingsSaveFixture(body, {
    in_scope_changed: 9, on_board: 5, promoted: 2, promotion_pending: false,
  }));
  const user = userEvent.setup();
  renderWalk();
  const confirmation = await saveWithout(user);
  // All five roles the radar keeps are on the Board: nothing is left to arrive.
  expect(confirmation).toHaveTextContent(/^Saved\. 5 roles are on your radar now, 2 of them from earlier scans\.$/);
});

it("a save made while a scan runs says the rest arrive when it ends, counted once", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  save.mockImplementation(async (body) => settingsSaveFixture(body, {
    in_scope_changed: 9, on_board: 3, promoted: 0, promotion_pending: true,
  }));
  const user = userEvent.setup();
  renderWalk();
  const confirmation = await saveWithout(user);
  expect(confirmation).toHaveTextContent(
    /^Saved\. 3 roles are on your radar now\. Up to 2 more arrive when the current scan ends, or as each company is next scanned\.$/,
  );
});

it("counting again re-reads the counts while it runs, without touching the answers", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    load.mockResolvedValue({ ...catalog(RETURNING, emptyScopeCellsFixture), joint_counts_ready: false });
    vi.mocked(api.refreshScopeCatalog).mockResolvedValue({ status: "started", max_list: 600 });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWalk();
    await screen.findByRole("complementary", { name: "Your progress" });
    expect(load).toHaveBeenCalledTimes(1);
    load.mockResolvedValue(catalog(RETURNING));
    await user.click(within(rail()).getByRole("button", { name: "Count now" }));
    await vi.advanceTimersByTimeAsync(20_000);
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    // The new counts arrive; the answers are the ones on screen, not reloaded.
    expect(bar("Career track")).toHaveAccessibleDescription("Keeps 70%, 14 roles");
    expect(screen.queryByRole("region", { name: "Review changes" })).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});

it("unticking the last card gives every role of the kind back", async () => {
  load.mockResolvedValue(catalog({ ...RETURNING, enabled_role_tracks: ["product_program"], enabled_role_groups: ["product_management"] }));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Discipline"));
  const pm = screen.getByLabelText("Product management (Owning a product)");
  expect(pm).toBeChecked();
  expect(bar("Discipline")).toHaveAccessibleDescription(/^Keeps/);
  await user.click(pm);
  // Nothing ticked is every role of the kind, as an empty World is every world.
  expect(pm).not.toBeChecked();
  expect(bar("Discipline")).toHaveAccessibleDescription("Any, nothing narrowed");
  await user.click(stripButton("Summary"));
  expect(fact("Discipline")).toHaveTextContent(/^Any role that fits/);
});

it("where: the whole world is its own control, and a covered place cannot be added twice", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Location"));

  // No "Anywhere" reach inside a base row; Europe is one.
  const reach = screen.getByRole("group", { name: "How far from United Kingdom" });
  expect(within(reach).queryByRole("button", { name: "Anywhere" })).toBeNull();
  expect(within(reach).getByRole("button", { name: "Europe" })).toBeVisible();

  // A place already implied by a base is named as covered, not offered.
  await user.type(screen.getByLabelText("Add another place"), "silicon");
  expect(screen.getByRole("button", { name: "Add Silicon Valley" })).toBeDisabled();
  expect(screen.getByText("already added")).toBeVisible();

  // A place inside a base is offered, and picking it narrows that base to it.
  await user.clear(screen.getByLabelText("Add another place"));
  await user.type(screen.getByLabelText("Add another place"), "united k");
  expect(screen.getByRole("button", { name: "Add United Kingdom" })).toBeDisabled();

  // The search leads the step; the bases read back under it.
  const bases = screen.getByRole("list", { name: "Your bases" });
  expect(screen.getByLabelText("Add another place").compareDocumentPosition(bases) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

  // The explicit control replaces every base with the whole world.
  await user.click(screen.getByRole("button", { name: "Go worldwide" }));
  expect(screen.getByRole("button", { name: "Remove Anywhere" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Go worldwide" })).toBeNull();
  await user.click(stripButton("Summary"));
  expect(fact("Location")).toHaveTextContent(/^Anywhere/);

  // Anywhere keeps the search, and a place named there replaces it: a click
  // on Go worldwide is undone by naming the place meant, not by a hunt.
  await user.click(stripButton("Location"));
  await user.type(screen.getByLabelText("Name a place instead"), "united k");
  await user.click(screen.getByRole("button", { name: "Add United Kingdom" }));
  expect(screen.queryByRole("button", { name: "Remove Anywhere" })).toBeNull();
  expect(within(screen.getByRole("list", { name: "Your bases" })).getAllByRole("listitem")).toHaveLength(1);
  expect(screen.getByRole("group", { name: "How far from United Kingdom" })).toBeVisible();
});

it("where: a city the place search finds is a base like any other, and a count that cannot price it waits for the save", async () => {
  // Fake time, so "the read is not repeated" is checked over time the test
  // moves, not a real 600 ms sleep.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    load.mockResolvedValue(catalog(RETURNING));
    searchPlaces.mockImplementation(async (query: string) => query.toLowerCase().startsWith("stock")
      ? { places: [{ slug: "city_2673730", display: "Stockholm", kind: "city", parent: "sweden", context: "Sweden", matched_by: null }], unions: [] }
      : { places: [], unions: [] });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWalk();
    await screen.findByRole("complementary", { name: "Your progress" });
    await user.click(stripButton("Location"));

    // The catalog does not list Stockholm; the search does.
    await user.type(screen.getByLabelText("Add another place"), "stock");
    await user.click(await screen.findByRole("button", { name: "Add Stockholm, Sweden" }));
    expect(searchPlaces).toHaveBeenLastCalledWith("stock", 10, expect.any(AbortSignal));

    // A city reads like a metro: "only" at its own reach, then its country and region.
    const bases = screen.getByRole("list", { name: "Your bases" });
    expect(within(bases).getByText("Stockholm only")).toBeVisible();
    const reach = screen.getByRole("group", { name: "How far from Stockholm" });
    expect(within(reach).getAllByRole("button").map((button) => button.textContent)).toEqual(["Stockholm", "Sweden", "Europe"]);
    // It inherits its country's coverage: acme cannot be asked about Sweden.
    expect(screen.getByRole("note")).toHaveTextContent(
      msg("profile-where-step-careers-sites-cant-be-searched", { count: 1, companies: String(companyName("acme")), places: "Stockholm" }),
    );

    // The joint has no Stockholm yet: it is counted by a read that names it,
    // and until that read answers the share is unknown, never 0%.
    expect(bar("Location")).toHaveAccessibleDescription("Counting");
    expect(rail()).toHaveTextContent("Counting the roles in Stockholm…");
    await waitFor(() => expect(load).toHaveBeenLastCalledWith(["city_2673730"]));
    // This read could not price it (the mock lists no Stockholm): the share
    // waits for the save, and the read is not repeated in a loop.
    await waitFor(() => expect(rail()).toHaveTextContent("Save to count the roles in Stockholm."));
    expect(bar("Location")).toHaveAccessibleDescription("Counted after you save");
    const reads = load.mock.calls.length;
    // Well past the read's own delay: a loop would have read again by now.
    await vi.advanceTimersByTimeAsync(2_000);
    expect(load).toHaveBeenCalledTimes(reads);

    load.mockClear();
    await user.click(within(screen.getByRole("region", { name: "Review changes" })).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].enabled_location_groups).toEqual(expect.arrayContaining(["city_2673730", "silicon_valley", "uk"]));
    // Saving a city the joint could not price re-reads the counts.
    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
  } finally {
    vi.useRealTimers();
  }
});

it("where: a city the draft names is counted before the save, from a read that names it", async () => {
  const STOCKHOLM = "city_2673730";
  const priced: ScopeCatalog["scope_cells"] = {
    ...CELLS,
    cities: [STOCKHOLM],
    location_sets: [...CELLS.location_sets, ["europe", "sweden", STOCKHOLM]],
    cells: [...CELLS.cells, [0, 1, 1, 2, 1, 7]], // SWE · staff · technical · Stockholm · AI
  };
  load.mockImplementation(async (cities = []) => catalog(RETURNING, cities.includes(STOCKHOLM) ? priced : CELLS));
  searchPlaces.mockImplementation(async (query: string) => query.toLowerCase().startsWith("stock")
    ? { places: [{ slug: STOCKHOLM, display: "Stockholm", kind: "city", parent: "sweden", context: "Sweden", matched_by: null }], unions: [] }
    : { places: [], unions: [] });
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Location"));
  // Silicon Valley and the UK keep 11 of the 27 roles.
  expect(bar("Location")).toHaveAccessibleDescription(/11 roles/);

  await user.type(screen.getByLabelText("Add another place"), "stock");
  await user.click(await screen.findByRole("button", { name: "Add Stockholm, Sweden" }));
  expect(rail()).toHaveTextContent("Counting the roles in Stockholm…");

  // Stockholm's seven roles join the count, and nothing was saved for it.
  await waitFor(() => expect(bar("Location")).toHaveAccessibleDescription(/18 roles/));
  expect(rail()).not.toHaveTextContent("Stockholm");
  expect(load).toHaveBeenLastCalledWith([STOCKHOLM]);
  expect(save).not.toHaveBeenCalled();
});

it("where: without the place search the catalog's own places still answer", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  searchPlaces.mockRejectedValue(new Error("offline"));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Location"));
  await user.type(screen.getByLabelText("Add another place"), "swe");
  expect(await screen.findByRole("button", { name: "Add Sweden" })).toBeVisible();
});

it("where: a place a wider base covers is still clickable, and narrows that base to it", async () => {
  load.mockResolvedValue(catalog({ ...RETURNING, enabled_location_groups: ["united_states", "uk"] }));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Location"));
  await user.type(screen.getByLabelText("Add another place"), "silicon");
  expect(screen.getByText("in the US, choose to narrow to it")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Narrow the US to Silicon Valley" }));
  const bases = screen.getByRole("list", { name: "Your bases" });
  expect(within(bases).getByText("Silicon Valley only")).toBeVisible();
  expect(within(bases).queryByText("Anywhere in the US")).toBeNull();
});

it("narrowing one answer never changes another's cards or count", async () => {
  /* Leading a team + owning a product. Narrowing "owning a product" to
     product management must not delete TPM and program roles from BOTH
     answers: each answer keeps its own. */
  load.mockResolvedValue(catalog({
    ...RETURNING, enabled_role_tracks: ["management", "product_program"],
    role_answers: [{ track: "management", roles: "any" }, { track: "product_program", roles: "any" }],
  }));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Discipline"));
  const leadCards = () => ["Engineers", "Designers"].map((label) => (screen.getByLabelText(`${label} (Leading a team)`) as HTMLInputElement).checked);
  expect(leadCards()).toEqual([false, false]);
  await user.click(screen.getByLabelText("Product management (Owning a product)"));
  // Leading a team is exactly as it was: nothing ticked, every role kept.
  expect(leadCards()).toEqual([false, false]);
  await user.click(stripButton("Summary"));
  expect(fact("Career track")).toHaveTextContent(/^Leading a team or owning a product/);
  expect(fact("Discipline")).toHaveTextContent(/^Product management/);
});

it("counts the funnel once per draft change, however many parts of the screen show it", async () => {
  /* The Summary, the World step and the rail all read the funnel. Mounted
     together, one change to the draft is one count, not one per reader. */
  load.mockResolvedValue(catalog(RETURNING));
  const user = userEvent.setup();
  function NarrowWorlds() {
    const { toggleDomain } = useScopeDraft();
    return <Button onClick={() => toggleDomain("ai_ml")}>Narrow the worlds</Button>;
  }
  const answered = { accountable: true, level: true, where: true, roles: true, subjects: true };
  render(
    <ToastProvider>
      <MemoryRouter>
        <ScopeDraftProvider>
          <SummaryStep headingRef={createRef()} lines={[]} onGo={() => {}} onLeave={() => {}} />
          <SubjectsStep lines={[]} onChange={() => {}} />
          <ProgressRail view="summary" answered={answered} lines={[]} onGo={() => {}} />
          <NarrowWorlds />
        </ScopeDraftProvider>
      </MemoryRouter>
    </ToastProvider>,
  );
  await screen.findByRole("complementary", { name: "Your progress" });
  await waitFor(() => expect(profile).toHaveBeenCalled());
  const funnel = vi.mocked(progressOf);
  const lastRow = () => screen.getByRole("region", { name: "What it keeps" }).querySelector(".walk-funnel-row:last-child");
  expect(lastRow()).toHaveTextContent(/5\s*25%/);
  funnel.mockClear();

  // Dropping AI from the worlds takes the five AI engineers out.
  await user.click(screen.getByRole("button", { name: "Narrow the worlds" }));
  expect(funnel).toHaveBeenCalledTimes(1);
  // Every reader shows that one count.
  expect(lastRow()).toHaveTextContent(/0\s*0%/);
  expect(bar("World")).toHaveAccessibleDescription("Keeps 0%, 0 roles");
});

it("typing in the roles filter counts nothing again, and every card keeps its count", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Discipline"));
  const card = (label: string) => screen.getByLabelText(label).closest("label");
  expect(card("Engineers (Leading a team)")).toHaveTextContent(/6 roles ·/);
  vi.mocked(countUnderScope).mockClear();
  vi.mocked(countByOption).mockClear();

  await user.type(screen.getByLabelText("Filter roles"), "engineer");
  expect(countUnderScope).not.toHaveBeenCalled();
  expect(countByOption).not.toHaveBeenCalled();
  // The cards still say what they hold: engineers at Staff in the two places.
  expect(card("Engineers (Leading a team)")).toHaveTextContent(/6 roles ·/);
  expect(card("Data engineering (Hands-on, as the expert)")).toHaveTextContent(/0 roles ·/);
});

it("keeps Back and Continue in one frame across the three answers that decide", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  // jsdom lays nothing out, so the assertion is structural: the three stage-1
  // cards wear the one frame class and the footer is the body's last child.
  for (const name of ["Career track", "Level", "Location"]) {
    await user.click(stripButton(name));
    const card = screen.getByRole("region", { name: /What kind of role|Your level|Where do you want to work/ });
    expect(card.className).toContain("walk-card--stage1");
    const body = card.querySelector(".walk-card-body")!;
    expect(body.lastElementChild?.className).toContain("walk-step-foot");
  }
  await user.click(stripButton("Discipline"));
  expect(screen.getByRole("region", { name: "Any particular roles?" }).className).not.toContain("walk-card--stage1");
});

/* The guide on Profile explains the walk, not the first-run wizard's model:
   the five answers in order, grouped as the three that decide and the two
   that sharpen, and no way back into a guided setup (Profile is it), nor the
   wizard's "career track" and "discipline" words. */
it("explains the five answers of the walk in its guide, by the names its steps use", async () => {
  // The trigger lives in the Profile header (ProfileView), not in the walk.
  const user = userEvent.setup();
  render(<ScopeGuideButton variant="walk" compact />);
  await user.click(screen.getByRole("button", { name: "How your radar works" }));
  const guide = screen.getByRole("dialog", { name: "How your radar works" });

  const names = [...guide.querySelectorAll(".scope-guide-gate strong")].map((node) => node.textContent);
  expect(names).toEqual(["Career track", "Level", "Location", "Discipline", "World"]);
  expect(within(guide).getByText("Decide")).toBeVisible();
  expect(within(guide).getByText("Sharpen, optional")).toBeVisible();
  expect(guide).toHaveTextContent(/A role shows up only when it fits all of them/);
  expect(guide).not.toHaveTextContent(/Which roles|Interests|kind of role/);
  expect(within(guide).queryByRole("link", { name: "Open guided setup" })).toBeNull();
});

it("the setup guide describes no control its screen does not have", async () => {
  // Welcome shows no estimate and its rail is read-only, so "the rail offers a
  // refresh" would point at nothing.
  const user = userEvent.setup();
  render(<MemoryRouter><ScopeGuideButton variant="setup" compact /></MemoryRouter>);
  await user.click(screen.getByRole("button", { name: "How your radar works" }));
  const guide = screen.getByRole("dialog", { name: "How your radar works" });
  expect(within(guide).getByRole("heading", { name: "When changes apply" })).toBeVisible();
  expect(within(guide).queryByRole("heading", { name: "About the estimate" })).toBeNull();
  expect(guide).not.toHaveTextContent(/offers a refresh/);
  // It renders inside Welcome, so a link to guided setup would be a link to itself.
  expect(within(guide).queryByRole("link", { name: "Open guided setup" })).toBeNull();
});

/* The pay floor is the Summary's one OPTIONAL answer, saved on its
   own; it narrows nothing, and the CV action opens its future page. */
it("adds an optional pay floor on the Summary without touching the Walk's answers", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  const save = vi.mocked(api.savePayFloor);
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Summary"));

  expect(fact("Minimum base")).toHaveTextContent("Set your minimum base");
  expect(screen.getByText("Compared with the posted base salary, where a posting has one.", { selector: "p" })).toBeVisible();
  expect(screen.getByText("No roles are hidden.", { selector: "p" })).toBeVisible();
  const funnelBefore = screen.getByRole("region", { name: "What it keeps" }).textContent;
  expect(screen.queryByText("The pay floor never narrows this.")).toBeNull();

  await user.click(screen.getByRole("button", { name: "Add a minimum base" }));
  // "250.000" is 250,000 in much of Europe: never read as 250.
  await user.type(screen.getByLabelText("Lowest yearly base salary"), "250.000");
  await user.click(screen.getByRole("button", { name: "Save minimum base" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a yearly amount, like 250,000 or 250k.");
  expect(save).not.toHaveBeenCalled();

  await user.clear(screen.getByLabelText("Lowest yearly base salary"));
  await user.type(screen.getByLabelText("Lowest yearly base salary"), "250k");
  await user.click(screen.getByRole("button", { name: "Save minimum base" }));
  expect(save).toHaveBeenCalledWith({ amount: 250000, currency: "USD" });
  expect(await screen.findByText("$250,000 a year")).toBeVisible();
  expect(screen.getByRole("region", { name: "What it keeps" }).textContent).toEqual(funnelBefore);
  // Saving the floor is not a Walk save: the scope was never written.
  expect(api.saveSettings).not.toHaveBeenCalled();
  // One primary on the Summary, still the way out.
  expect(screen.getAllByRole("button").filter((b) => b.classList.contains("ui-btn-primary")).map((b) => b.textContent))
    .toEqual(["See your radar"]);
});

it("adjusts and removes a saved pay floor, with focus following the editor", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  vi.mocked(api.payFloor).mockResolvedValueOnce({ pay_floor: { amount: 180000, currency: "GBP" } });
  const clear = vi.mocked(api.clearPayFloor);
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Summary"));

  expect(await screen.findByText("£180,000 a year")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Adjust minimum base" }));
  // The editor opens on what is stored, with the cursor in the amount.
  expect(screen.getByLabelText("Lowest yearly base salary")).toHaveValue("180000");
  expect(screen.getByLabelText("Lowest yearly base salary")).toHaveFocus();
  expect(screen.getByLabelText("Currency")).toHaveValue("GBP");

  // Cancel returns focus to the control that opened the editor.
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: "Adjust minimum base" })).toHaveFocus();

  await user.click(screen.getByRole("button", { name: "Adjust minimum base" }));
  await user.click(screen.getByRole("button", { name: "Remove" }));
  expect(clear).toHaveBeenCalledTimes(1);
  expect(await screen.findByRole("button", { name: "Add a minimum base" })).toHaveFocus();
  expect(fact("Minimum base")).toHaveTextContent("Set your minimum base");
});

it("keeps the pay floor editor open and says so when a save fails", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  const save = vi.mocked(api.savePayFloor);
  save.mockRejectedValueOnce(new Error("500"));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Summary"));
  await user.click(await screen.findByRole("button", { name: "Add a minimum base" }));
  await user.type(screen.getByLabelText("Lowest yearly base salary"), "200000");
  await user.click(screen.getByRole("button", { name: "Save minimum base" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't save the minimum base. Try again.");
  expect(screen.getByLabelText("Lowest yearly base salary")).toHaveValue("200000");
  // A second try clears the old message before it runs.
  await user.click(screen.getByRole("button", { name: "Save minimum base" }));
  expect(await screen.findByText("$200,000 a year")).toBeVisible();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("never says the pay floor is unset when it could not be read", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  const read = vi.mocked(api.payFloor);
  read.mockRejectedValueOnce(new Error("503"));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Summary"));
  expect(await screen.findByText("Couldn't read your minimum base.")).toBeVisible();
  // No "Not set" and no Add: a save from here would overwrite a floor.
  expect(fact("Minimum base")).not.toHaveTextContent(/Not set/);
  expect(screen.queryByRole("button", { name: "Add a minimum base" })).toBeNull();
  read.mockResolvedValueOnce({ pay_floor: { amount: 250000, currency: "USD" } });
  await user.click(screen.getByRole("button", { name: "Retry reading the minimum base" }));
  expect(await screen.findByText("$250,000 a year")).toBeVisible();
});

it("links the CV action to its separate experience page", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Summary"));
  const hint = screen.getByRole("region", { name: "Your experience" });
  expect(hint).toHaveTextContent(/Add your CV/);
  expect(hint).toHaveTextContent("Coming soon");
  expect(within(hint).getByRole("link", { name: "Add your CV" })).toHaveAttribute("href", "/profile/experience");
});


// A failed catalog read must not end at "Your radar is unavailable" with no
// way out but reloading the page.
it("offers Try again when the radar could not be read, and reads it again", async () => {
  load.mockRejectedValueOnce(new Error("503 Service Unavailable"));
  load.mockResolvedValueOnce(catalog(RETURNING));
  const user = userEvent.setup();
  renderWalk();

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("Couldn't load your radar");
  await user.click(within(alert).getByRole("button", { name: "Try again" }));

  expect(await screen.findByRole("complementary", { name: "Your progress" })).toBeVisible();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(load).toHaveBeenCalledTimes(2);
});

/* ---- First-run setup ---------------------------------------------------
   The same walk, cut to what a first radar needs: three answers, the
   Summary, and a companies step the route hands in. It starts blank, offers
   no second save path, and the companies step's Start is the one commit. */

/** Stands in for the Companies feature's step: the walk owns only what it
 *  hands over (the foot, Back, and Start). */
function CompaniesStepDouble({ footClassName, onBack, onStart }: SetupCompaniesProps) {
  return (
    <footer className={footClassName}>
      <p>Companies step body</p>
      <Button onClick={onBack}>Back</Button>
      <Button variant="primary" onClick={() => void onStart()}>Start the radar</Button>
    </footer>
  );
}

/** The browser's own Back, which setup's history entries answer. */
function BrowserBack() {
  const navigate = useNavigate();
  return <button type="button" onClick={() => void navigate(-1)}>Browser back</button>;
}

const SETUP_ENTRY = { pathname: "/profile/direction", search: "?setup=1" };

/** `step`: the step a history entry names, as a reload of that entry opens it. */
const renderSetup = (step?: string) => render(
  <ToastProvider>
    <MemoryRouter initialEntries={["/welcome", step ? { ...SETUP_ENTRY, state: { setupStep: step } } : SETUP_ENTRY]}>
      <BrowserBack />
      <Routes>
        <Route path="/welcome" element={<p>The welcome</p>} />
        <Route path="/" element={<p>The board</p>} />
        <Route
          path="/profile/direction"
          element={(
            <ScopeDraftProvider initialSelection="empty">
              <Walk setup={{ companies: (props) => <CompaniesStepDouble {...props} /> }} />
            </ScopeDraftProvider>
          )}
        />
      </Routes>
    </MemoryRouter>
  </ToastProvider>,
);

it("first-run setup starts blank, asks the three answers then the two optional ones, and commits once, from the companies step", async () => {
  // A saved scope exists on the server; setup must not inherit it.
  load.mockResolvedValue(catalog(RETURNING));
  const user = userEvent.setup();
  renderSetup();
  await screen.findByRole("complementary", { name: "Your progress" });

  // The three questions, the two optional ones, the Summary and Companies.
  expect(within(strip()).getAllByRole("tab").map((tab) => tab.textContent))
    .toEqual(["Career track", "Level", "Location", "Discipline", "World", "Summary", "Companies"]);
  expect(within(rail()).getAllByRole("button", { name: /^(Career track|Level|Location|Discipline|World)$/ })
    .map((layer) => layer.getAttribute("aria-label") ?? layer.textContent)).toHaveLength(5);
  expect(stripButton("Companies")).toBeDisabled();
  expect(screen.getByLabelText("Leading a team")).not.toBeChecked();
  expect(screen.getByLabelText("Hands-on, as the expert")).not.toBeChecked();

  await user.click(screen.getByLabelText("Leading a team"));
  // A dirty draft offers no Save on the rail: setup has one commit.
  expect(within(rail()).queryByRole("button", { name: /Save/ })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Continue" }));
  // Setup asks for the level alone; the choice about roles that state none
  // keeps its default and lives in Profile.
  expect(screen.getByRole("heading", { name: "Your level" })).toBeVisible();
  expect(screen.queryByRole("checkbox", { name: /Include roles with an unknown level/ })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /^Staff/ }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.type(screen.getByLabelText("Where are you based?"), "silicon");
  await user.click(screen.getByRole("button", { name: "Add Silicon Valley" }));
  // Still on Location: Discipline has not been reached, so its layer is as
  // open as World's.
  expect(bar("Discipline")).toHaveAccessibleDescription("Any, nothing narrowed");
  expect(bar("World")).toHaveAccessibleDescription("Any, nothing narrowed");
  await user.click(screen.getByRole("button", { name: "Continue" }));

  // The two that sharpen come next, each skipped untouched.
  expect(screen.getByRole("heading", { name: "Any particular roles?" })).toHaveFocus();
  await user.click(screen.getByRole("button", { name: "Skip" }));
  expect(screen.getByRole("heading", { name: "Anything you care about, or want to avoid?" })).toHaveFocus();
  await user.click(screen.getByRole("button", { name: "Skip" }));

  // The Summary is a waypoint: all five answers, nothing that leaves the walk.
  expect(screen.getByRole("heading", { name: "Summary" })).toBeVisible();
  expect(fact("Career track")).toHaveTextContent(/^Leading a team/);
  expect(fact("Discipline")).toHaveTextContent("Any role that fits");
  expect(fact("World")).toHaveTextContent("Any world");
  expect(screen.queryByRole("link", { name: /Add your CV/ })).toBeNull();
  // The pay floor is offered, and saves nothing on its own here.
  expect(fact("Minimum base")).toHaveTextContent("Set your minimum base");
  expect(screen.getAllByRole("button").filter((b) => b.classList.contains("ui-btn-primary"))).toHaveLength(0);
  expect(save).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("heading", { name: "Where should your radar look?" })).toHaveFocus();
  expect(screen.getByText("Companies step body")).toBeVisible();

  // Back returns to the Summary with the answers kept.
  await user.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByRole("heading", { name: "Summary" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Continue" }));

  await user.click(screen.getByRole("button", { name: "Start the radar" }));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.calls[0][0]).toMatchObject({
    enabled_role_tracks: ["management"],
    enabled_location_groups: ["silicon_valley"],
    experience_stage: "staff",
    target_stage: "staff",
    // Skipped, the two that sharpen keep everything: every world, none avoided.
    enabled_domain_groups: ["ai_ml", "logistics_fulfillment", "health_bio"],
    excluded_domain_groups: [],
  });
  expect(await screen.findByText("The board")).toBeVisible();
  // An untouched floor is not written, not even cleared.
  expect(api.savePayFloor).not.toHaveBeenCalled();
  expect(api.clearPayFloor).not.toHaveBeenCalled();
});

/** Setup's three answers, both optional steps skipped: lands on the Summary. */
async function setupToSummary(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(screen.getByLabelText("Leading a team"));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: /^Staff/ }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.type(screen.getByLabelText("Where are you based?"), "silicon");
  await user.click(screen.getByRole("button", { name: "Add Silicon Valley" }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: "Skip" }));
  await user.click(screen.getByRole("button", { name: "Skip" }));
  expect(screen.getByRole("heading", { name: "Summary" })).toBeVisible();
}

/* Start is setup's one save, so a floor set on its Summary is held, not
   written, until then; written after the scope, it can never land without
   one. */
/* The first scan starts as setup opens, so a count there is partial and mostly
   zero: setup names the answers and counts nothing, even once roles are read.
   Profile's walk over the same catalog counts (the rung and card tests above). */
it("setup counts nothing on the rungs, the cards, the rail or the Summary, even once roles are read", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  const user = userEvent.setup();
  renderSetup();
  await screen.findByRole("complementary", { name: "Your progress" });
  const counted = /\d[\d,]* roles?\b/;

  await user.click(screen.getByLabelText("Leading a team"));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("heading", { name: "Your level" })).toBeVisible();
  expect(document.querySelectorAll(".stage-count")).toHaveLength(0);
  expect(screen.getByRole("button", { name: /^Staff/ })).not.toHaveTextContent(counted);
  await user.click(screen.getByRole("button", { name: /^Staff/ }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.type(screen.getByLabelText("Where are you based?"), "silicon");
  await user.click(screen.getByRole("button", { name: "Add Silicon Valley" }));
  await user.click(screen.getByRole("button", { name: "Continue" }));

  expect(screen.getByRole("heading", { name: "Any particular roles?" })).toBeVisible();
  const card = screen.getByLabelText("Engineers (Leading a team)").closest("label")!;
  expect(card).not.toHaveTextContent(counted);
  expect(card.querySelector("small")?.textContent).toBeTruthy();
  // The rail names the answers, as before anything is read.
  expect(rail()).not.toHaveTextContent(counted);
  expect(rail()).toHaveTextContent("Leading a team");
  expect(rail()).toHaveTextContent(/Illustrative funnel/);

  await user.click(screen.getByRole("button", { name: "Skip" }));
  await user.click(screen.getByRole("button", { name: "Skip" }));
  expect(screen.getByRole("heading", { name: "Summary" })).toBeVisible();
  expect(document.querySelector(".walk-summary-funnel")).toBeNull();
  expect(rail()).not.toHaveTextContent(counted);
});

it("setup holds the pay floor until Start and writes it after the scope", async () => {
  load.mockResolvedValue(catalog(FRESH));
  const floorSave = vi.mocked(api.savePayFloor);
  const user = userEvent.setup();
  renderSetup();
  await setupToSummary(user);

  await user.click(screen.getByRole("button", { name: "Add a minimum base" }));
  await user.type(screen.getByLabelText("Lowest yearly base salary"), "180k");
  await user.selectOptions(screen.getByLabelText("Currency"), "GBP");
  // Its button says it sets, not saves: nothing is written here.
  expect(screen.queryByRole("button", { name: "Save minimum base" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Set minimum base" }));
  expect(await screen.findByText("£180,000 a year")).toBeVisible();
  expect(floorSave).not.toHaveBeenCalled();

  // The held floor outlives the Summary: on to Companies and back.
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByText("£180,000 a year")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(floorSave).not.toHaveBeenCalled();
  expect(save).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "Start the radar" }));
  expect(await screen.findByText("The board")).toBeVisible();
  expect(floorSave).toHaveBeenCalledTimes(1);
  expect(floorSave).toHaveBeenCalledWith({ amount: 180000, currency: "GBP" });
  expect(save).toHaveBeenCalledTimes(1);
  expect(save.mock.invocationCallOrder[0]).toBeLessThan(floorSave.mock.invocationCallOrder[0]);
});

it("setup writes no floor when the scope save fails, and stays to retry a floor that failed", async () => {
  load.mockResolvedValue(catalog(FRESH));
  const floorSave = vi.mocked(api.savePayFloor);
  const user = userEvent.setup();
  renderSetup();
  await setupToSummary(user);
  await user.click(screen.getByRole("button", { name: "Add a minimum base" }));
  await user.type(screen.getByLabelText("Lowest yearly base salary"), "250000");
  await user.click(screen.getByRole("button", { name: "Set minimum base" }));
  await user.click(screen.getByRole("button", { name: "Continue" }));

  // The scope fails: the floor is not written without it.
  save.mockRejectedValueOnce(new Error("disk full"));
  await user.click(screen.getByRole("button", { name: "Start the radar" }));
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(floorSave).not.toHaveBeenCalled();

  // The scope saves, the floor fails: still on Companies, saying so.
  floorSave.mockRejectedValueOnce(new Error("500"));
  await user.click(screen.getByRole("button", { name: "Start the radar" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't save the minimum base. Try again.");
  expect(screen.getByText("Companies step body")).toBeVisible();
  expect(screen.queryByText("The board")).toBeNull();

  // Start again finishes it.
  await user.click(screen.getByRole("button", { name: "Start the radar" }));
  expect(await screen.findByText("The board")).toBeVisible();
  expect(floorSave).toHaveBeenLastCalledWith({ amount: 250000, currency: "USD" });
});

it("setup keeps an amount typed but not set when the person moves on, and Cancel keeps nothing", async () => {
  load.mockResolvedValue(catalog(FRESH));
  const floorSave = vi.mocked(api.savePayFloor);
  const user = userEvent.setup();
  renderSetup();
  await setupToSummary(user);
  // The first place is the United Kingdom: the editor opens in pounds.
  await user.click(screen.getByRole("button", { name: "Adjust location" }));
  await user.click(screen.getByRole("button", { name: "Remove Silicon Valley" }));
  await user.type(screen.getByLabelText("Where are you based?"), "united kingdom");
  await user.click(screen.getByRole("button", { name: "Add United Kingdom" }));
  await user.click(stripButton("Summary"));
  await user.click(screen.getByRole("button", { name: "Add a minimum base" }));
  expect(screen.getByLabelText("Currency")).toHaveValue("GBP");
  await user.type(screen.getByLabelText("Lowest yearly base salary"), "180k");
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByText("£180,000 a year")).toBeVisible();

  // Cancel closes the editor first, so leaving after it keeps the old floor.
  await user.click(screen.getByRole("button", { name: "Adjust minimum base" }));
  await user.clear(screen.getByLabelText("Lowest yearly base salary"));
  await user.type(screen.getByLabelText("Lowest yearly base salary"), "90k");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByText("£180,000 a year")).toBeVisible();
  // Text that is no amount is not kept either.
  await user.click(screen.getByRole("button", { name: "Adjust minimum base" }));
  await user.clear(screen.getByLabelText("Lowest yearly base salary"));
  await user.type(screen.getByLabelText("Lowest yearly base salary"), "lots");
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: "Start the radar" }));
  expect(await screen.findByText("The board")).toBeVisible();
  expect(floorSave).toHaveBeenCalledTimes(1);
  expect(floorSave).toHaveBeenCalledWith({ amount: 180000, currency: "GBP" });
});

/* Back, the browser's or a phone's gesture, steps back through setup one step
   at a time, and from the first step to the welcome: never out of RoleBand. */
it("setup's steps are history entries, so the browser's Back retraces them with the answers kept", async () => {
  load.mockResolvedValue(catalog(FRESH));
  const user = userEvent.setup();
  renderSetup();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(screen.getByLabelText("Leading a team"));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: /^Staff/ }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("heading", { name: "Where do you want to work?" })).toBeVisible();

  await user.click(screen.getByRole("button", { name: "Browser back" }));
  expect(screen.getByRole("heading", { name: "Your level" })).toHaveFocus();
  // The level is still answered: Continue opens only on an answered level.
  expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: "Browser back" }));
  expect(screen.getByRole("heading", { name: "What kind of role are you looking for?" })).toBeVisible();
  expect(screen.getByLabelText("Leading a team")).toBeChecked();
  await user.click(screen.getByRole("button", { name: "Browser back" }));
  expect(screen.getByText("The welcome")).toBeVisible();
});

/* Setup saves nothing before Start, so a reload would lose every answer: the
   tab keeps them, and the history entry keeps the step. */
it("a reload in setup opens the step it left, with every answer and the held floor", async () => {
  load.mockResolvedValue(catalog(FRESH));
  const user = userEvent.setup();
  const first = renderSetup();
  await setupToSummary(user);
  await user.click(screen.getByRole("button", { name: "Add a minimum base" }));
  await user.type(screen.getByLabelText("Lowest yearly base salary"), "180k");
  await user.click(screen.getByRole("button", { name: "Set minimum base" }));
  first.unmount();

  // The held floor is the tab's: it shows without waiting on the server's.
  vi.mocked(api.payFloor).mockReturnValueOnce(new Promise(() => {}));
  renderSetup("summary");
  expect(await screen.findByRole("heading", { name: "Summary" })).toBeVisible();
  expect(fact("Career track")).toHaveTextContent(/^Leading a team/);
  expect(fact("Location")).toHaveTextContent(/Silicon Valley/);
  expect(fact("Minimum base")).toHaveTextContent("$180,000");
  expect(save).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: "Start the radar" }));
  expect(await screen.findByText("The board")).toBeVisible();
  expect(save.mock.calls[0][0]).toMatchObject({
    enabled_role_tracks: ["management"],
    enabled_location_groups: ["silicon_valley"],
    experience_stage: "staff",
  });
  expect(api.savePayFloor).toHaveBeenCalledWith({ amount: 180000, currency: "USD" });
  // Start saved them: a later setup in this tab starts blank.
  expect(window.sessionStorage.getItem("roleband.setup.v1")).toBeNull();
});

it("a history entry for a step its answers no longer reach opens the first open question", async () => {
  load.mockResolvedValue(catalog(FRESH));
  renderSetup("summary");
  expect(await screen.findByRole("heading", { name: "What kind of role are you looking for?" })).toBeVisible();
  expect(screen.getByLabelText("Leading a team")).not.toBeChecked();
});

it("setup's Summary goes back to the step before it", async () => {
  load.mockResolvedValue(catalog(FRESH));
  const user = userEvent.setup();
  renderSetup();
  await setupToSummary(user);
  await user.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByRole("heading", { name: "Anything you care about, or want to avoid?" })).toHaveFocus();
});

it("setup's Remove takes back a held floor, so Start clears nothing it never set", async () => {
  load.mockResolvedValue(catalog(FRESH));
  const user = userEvent.setup();
  renderSetup();
  await setupToSummary(user);
  await user.click(screen.getByRole("button", { name: "Add a minimum base" }));
  await user.type(screen.getByLabelText("Lowest yearly base salary"), "250000");
  await user.click(screen.getByRole("button", { name: "Set minimum base" }));
  await user.click(screen.getByRole("button", { name: "Adjust minimum base" }));
  await user.click(screen.getByRole("button", { name: "Remove" }));
  expect(fact("Minimum base")).toHaveTextContent("Set your minimum base");
  expect(api.clearPayFloor).not.toHaveBeenCalled();
});

it("a failed setup save stays on the companies step instead of landing on an empty board", async () => {
  load.mockResolvedValue(catalog(FRESH));
  save.mockRejectedValue(new Error("disk full"));
  const user = userEvent.setup();
  renderSetup();
  await screen.findByRole("complementary", { name: "Your progress" });

  await user.click(screen.getByLabelText("Leading a team"));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: /^Staff/ }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.type(screen.getByLabelText("Where are you based?"), "silicon");
  await user.click(screen.getByRole("button", { name: "Add Silicon Valley" }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: "Skip" }));
  await user.click(screen.getByRole("button", { name: "Skip" }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: "Start the radar" }));

  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(screen.getByText("Companies step body")).toBeVisible();
  expect(screen.queryByText("The board")).toBeNull();
});

/* A disabled button cannot be focused or hovered on a touch screen, so the
   reason it is shut has to be text on the page, named as the button's
   description for a screen reader that reaches it. */
it("a shut Continue says beside it what opens it, on each answer that decides", async () => {
  load.mockResolvedValue(catalog(FRESH));
  const user = userEvent.setup();
  renderSetup();
  await screen.findByRole("complementary", { name: "Your progress" });
  const advance = () => screen.getByRole("button", { name: "Continue" });
  const shut = (reason: string) => {
    expect(advance()).toBeDisabled();
    expect(screen.getByText(reason)).toBeVisible();
    expect(screen.getByText(reason).closest("footer")).toBe(advance().closest("footer"));
    expect(advance()).toHaveAccessibleDescription(reason);
    expect(advance()).not.toHaveAttribute("title");
  };
  const open = (reason: string) => {
    expect(advance()).toBeEnabled();
    expect(screen.queryByText(reason)).toBeNull();
    expect(advance()).not.toHaveAttribute("aria-describedby");
  };

  const track = "Pick at least one career track to continue.";
  shut(track);
  await user.click(screen.getByLabelText("Leading a team"));
  open(track);
  await user.click(advance());

  const level = "Pick your level today and the one you're aiming for to continue.";
  shut(level);
  await user.click(screen.getByRole("button", { name: /^Staff/ }));
  open(level);
  await user.click(advance());

  const where = "Add at least one place to continue.";
  shut(where);
  await user.type(screen.getByLabelText("Where are you based?"), "silicon");
  await user.click(screen.getByRole("button", { name: "Add Silicon Valley" }));
  open(where);

  // Taking the last answer back shuts Continue again, with its reason.
  await user.click(stripButton("Career track"));
  await user.click(screen.getByLabelText("Leading a team"));
  shut(track);
});

it("an answered step and an optional one show no reason beside Continue", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  for (const name of ["Career track", "Level", "Location", "Discipline", "World"]) {
    await user.click(stripButton(name));
    const advance = screen.getByRole("button", { name: /^(Continue|Done)$/ });
    expect(advance).toBeEnabled();
    expect(advance).not.toHaveAttribute("aria-describedby");
    expect(advance.closest("footer")!.querySelector("p")).toBeNull();
  }
});

/* Discipline and World can be passed by, and say so: the label beside the
   question, and a quieter Skip beside Continue for as long as the step keeps
   everything. Continue stays, so a reader who presses it from habit moves on
   the same way; narrowing takes Skip away. */
it("an optional step says so, and offers Skip beside Continue until the step narrows something", async () => {
  load.mockResolvedValue(catalog(FRESH));
  const user = userEvent.setup();
  renderSetup();
  await screen.findByRole("complementary", { name: "Your progress" });
  const optional = () => screen.queryByText("Optional");
  expect(optional()).toBeNull();

  await user.click(screen.getByLabelText("Leading a team"));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(optional()).toBeNull();
  await user.click(screen.getByRole("button", { name: /^Staff/ }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.type(screen.getByLabelText("Where are you based?"), "silicon");
  await user.click(screen.getByRole("button", { name: "Add Silicon Valley" }));
  expect(optional()).toBeNull();
  await user.click(screen.getByRole("button", { name: "Continue" }));

  // Discipline: marked in its head, beside the question.
  const roles = screen.getByRole("region", { name: "Any particular roles?" });
  expect(within(roles).getByText("Optional").closest("header")).toContainElement(screen.getByRole("heading", { name: "Any particular roles?" }));
  expect(within(roles).getByText(/Skip it to keep them all\./)).toBeVisible();
  const skip = screen.getByRole("button", { name: "Skip" });
  const advance = screen.getByRole("button", { name: "Continue" });
  expect(skip).toBeEnabled();
  expect(advance).toBeEnabled();
  // Skip comes first, Continue last: Continue keeps the place it has on every step.
  expect(skip.closest("footer")!.lastElementChild).toBe(advance);
  expect(skip.nextElementSibling).toBe(advance);
  expect(skip).not.toHaveClass("ui-btn-strong");
  expect(advance).toHaveClass("ui-btn-strong");
  // A ticked card makes it Continue alone; unticking it brings Skip back.
  await user.click(screen.getByLabelText("Designers (Leading a team)"));
  expect(screen.queryByRole("button", { name: "Skip" })).toBeNull();
  expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  await user.click(screen.getByLabelText("Designers (Leading a team)"));
  expect(screen.getByRole("button", { name: "Skip" })).toBeVisible();
  // Continue on an untouched optional step moves on, as Skip would.
  await user.click(screen.getByRole("button", { name: "Continue" }));

  // World: the same, and a pick makes it Continue; setup's Summary follows.
  const subjects = screen.getByRole("region", { name: "Anything you care about, or want to avoid?" });
  expect(within(subjects).getByText("Optional")).toBeVisible();
  expect(within(subjects).getByText(/Skip it to rule nothing out\./)).toBeVisible();
  expect(screen.getByRole("button", { name: "Skip" })).toBeEnabled();
  await user.click(within(screen.getByRole("group", { name: "Interested in" })).getByLabelText("AI & Machine Learning"));
  expect(screen.queryByRole("button", { name: "Skip" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("heading", { name: "Summary" })).toBeVisible();
  expect(fact("World")).toHaveTextContent(/AI & Machine Learning/);
});

it("in Profile's walk, World untouched offers Skip beside Done, and narrowed only Done", async () => {
  load.mockResolvedValue(catalog(RETURNING));
  const user = userEvent.setup();
  renderWalk();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("World"));
  expect(screen.getByText("Optional")).toBeVisible();
  expect(screen.getByRole("button", { name: "Skip" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Done" })).toBeEnabled();
  await user.click(within(screen.getByRole("group", { name: "Interested in" })).getByLabelText("AI & Machine Learning"));
  expect(screen.queryByRole("button", { name: "Skip" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Done" }));
  expect(screen.getByRole("heading", { name: "Summary" })).toBeVisible();
});

/* A locked tab cannot be focused, and has no hover on a touch screen, so why
   it is locked is text beside the bar, named as each locked tab's
   description. */
it("the locked tabs say on screen why they are locked, until the first three are answered", async () => {
  load.mockResolvedValue(catalog(FRESH));
  const user = userEvent.setup();
  renderSetup();
  await screen.findByRole("complementary", { name: "Your progress" });
  const reason = "The other steps open once you answer the first three.";
  expect(screen.getByText(reason)).toBeVisible();
  expect(screen.getByText(reason).closest(".walk-tabs-row")).toContainElement(strip());
  for (const name of ["Discipline", "World", "Summary", "Companies"]) {
    expect(stripButton(name)).toBeDisabled();
    expect(stripButton(name)).toHaveAccessibleDescription(reason);
    expect(stripButton(name)).not.toHaveAttribute("title");
  }
  for (const name of ["Career track", "Level", "Location"]) {
    expect(stripButton(name)).not.toHaveAttribute("aria-describedby");
  }

  await user.click(screen.getByLabelText("Leading a team"));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: /^Staff/ }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.type(screen.getByLabelText("Where are you based?"), "silicon");
  await user.click(screen.getByRole("button", { name: "Add Silicon Valley" }));

  expect(screen.queryByText(reason)).toBeNull();
  for (const tab of within(strip()).getAllByRole("tab")) {
    expect(tab).toBeEnabled();
    expect(tab).not.toHaveAttribute("aria-describedby");
  }
});

it("Continue past the three that decide goes back to the first one still open", async () => {
  load.mockResolvedValue(catalog(FRESH));
  const user = userEvent.setup();
  renderSetup();
  await screen.findByRole("complementary", { name: "Your progress" });
  await user.click(stripButton("Location"));
  await user.type(screen.getByLabelText("Where are you based?"), "silicon");
  await user.click(screen.getByRole("button", { name: "Add Silicon Valley" }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("heading", { name: "What kind of role are you looking for?" })).toHaveFocus();
});

it("where: companies that cannot be asked about the same place share one sentence, and a covered place has none", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    const base = catalog(RETURNING);
    load.mockResolvedValue({
      ...base,
      locations: base.locations.map((place) => place.slug === "sweden" ? { ...place, uncovered_by: ["acme", "globex"] } : place),
      companies: [...base.companies, { ...base.companies[0], slug: "globex", display: "Globex" }],
    });
    searchPlaces.mockImplementation(async (query: string) => query.toLowerCase().startsWith("stock")
      ? { places: [{ slug: "city_2673730", display: "Stockholm", kind: "city", parent: "sweden", context: "Sweden", matched_by: null }], unions: [] }
      : { places: [], unions: [] });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWalk();
    await screen.findByRole("complementary", { name: "Your progress" });
    await user.click(stripButton("Location"));
    // The United Kingdom is the only base, and every company can be asked about it.
    expect(screen.queryByRole("note")).toBeNull();

    await user.type(screen.getByLabelText("Add another place"), "stock");
    await user.click(await screen.findByRole("button", { name: "Add Stockholm, Sweden" }));

    const notes = screen.getAllByRole("note");
    expect(notes).toHaveLength(1);
    expect(notes[0]).toHaveTextContent(msg("profile-where-step-careers-sites-cant-be-searched", {
      count: 2, companies: msg("profile-walk-model-and", { join: String(companyName("acme")), parts: String(companyName("globex")) }), places: "Stockholm",
    }));
  } finally {
    vi.useRealTimers();
  }
});
