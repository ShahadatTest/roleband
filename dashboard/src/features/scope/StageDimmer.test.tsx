import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import { Button } from "../../ui/Button";
import { ScopeDraftProvider, useScopeDraft } from "./useScopeDraft";
import { StageDimmer } from "./StageDimmer";
import { AccountableStep } from "./walk/AccountableStep";
import { LevelStep } from "./walk/LevelStep";
import { profileStateFixture, scopeCatalogFixture, settingsSaveFixture } from "../../test/fixtures";

vi.mock("../../api", () => ({
  api: {
    profileSuggestions: vi.fn(async () => ({ suggestions: [] })),
    scopeCatalog: vi.fn(),
    refreshScopeCatalog: vi.fn(),
    saveSettings: vi.fn(),
    companies: vi.fn(),
    profile: vi.fn(),
    scopeRules: vi.fn(),
    deleteScopeRule: vi.fn(),
  },
}));

vi.mock("../../context/MissionState", () => ({
  useMissionActions: () => ({ refreshStats: vi.fn() }),
}));

const load = vi.mocked(api.scopeCatalog);
const profile = vi.mocked(api.profile);
const saveSettings = vi.mocked(api.saveSettings);
const companies = vi.mocked(api.companies);

const catalog = scopeCatalogFixture({
  settings: {
    enabled_role_groups: ["software_engineering"],
    enabled_seniority_bands: ["entry", "mid", "senior"],
    enabled_role_tracks: ["technical"],
    enabled_location_groups: ["uk"],
    enabled_domain_groups: ["ai_ml"],
    excluded_domain_groups: [],
    excluded_location_groups: [],
    include_unstated_level: false,
    role_answers: [{ track: "technical", roles: "any" }],
  },
  domains: [
    { slug: "ai_ml", selected: true, count: 8, examples: [], kind: "technology" },
  ],
  unclassified_domain_count: 0,
  levels: [
    { slug: "entry", order: 1, default_enabled: false, selected: true, new: false, count: 120, decoder: { google: { company_wide: "L3–L4" } } },
    { slug: "mid", order: 2, default_enabled: false, selected: true, new: false, count: 340, decoder: { google: { company_wide: "L4" }, anthropic: { per_track: { technical: "Software Engineer" } } } },
    { slug: "senior", order: 3, default_enabled: true, selected: true, new: false, count: 510, decoder: { google: { company_wide: "L5" }, apple: { per_track: { technical: "ICT4" } }, anthropic: { per_track: { technical: "Senior Software Engineer" } } } },
    { slug: "staff", order: 4, default_enabled: true, selected: false, new: false, count: 200, decoder: { google: { company_wide: "L6" }, apple: { per_track: { technical: "ICT5" } }, anthropic: { per_track: { technical: "Senior Staff Software Engineer" } } } },
  ],
  locations: [
    { slug: "uk", display: "United Kingdom", default_enabled: true, selected: true, new: false, count: 4, kind: "country", parent: null, uncovered_by: [], prominent: true },
  ],
  tracks: [
    { slug: "management", order: 0, default_enabled: true, selected: false, new: false, count: 4, allowed_bands: ["senior", "staff", "principal", "director_plus"] },
    { slug: "technical", order: 2, default_enabled: true, selected: true, new: false, count: 9, allowed_bands: ["intern", "entry", "mid", "senior", "staff", "principal", "director_plus"] },
    { slug: "business_customer", order: 3, default_enabled: true, selected: false, new: false, count: 3, allowed_bands: ["intern", "entry", "mid", "senior", "staff", "principal"] },
  ],
  joint_counts_ready: false,
  categories: [
    {
      slug: "technology",
      
      groups: [
        {
          slug: "software_engineering", total: 3,
          default_enabled: false, selected: true, new: false, enabled: true,
          band_counts: { senior: 3 },
          band_track_counts: {},
          joint_complete: true,
        },
      ],
    },
  ],
  companies: [{ slug: "google", display: "Google", enabled: true, role_catalog_status: "ready", role_catalog_scanned_at: null, role_catalog_error: null }],
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.scopeRules).mockResolvedValue({ rules: [] });
  load.mockResolvedValue(catalog);
  companies.mockResolvedValue({ companies: [] });
  profile.mockResolvedValue(profileStateFixture({ profile: { experience_stage: "entry", target_stage: "senior" } }));
  // The one save path echoes the axes it saved.
  saveSettings.mockImplementation(async (payload) => settingsSaveFixture(payload, { in_scope_changed: 5 }));
});

/* The dimmer where the walk hosts it: step 1's answers beside it, the
   collapsible decoder of the Level step, and the draft's own save. */
function SaveDraft() {
  const { save, dirty } = useScopeDraft();
  return dirty ? <Button onClick={() => void save()}>Save</Button> : null;
}

/* First-run setup's Level step: a blank draft. */
const renderSetup = () => render(
  <MemoryRouter>
    <ScopeDraftProvider initialSelection="empty">
      <AccountableStep />
      <LevelStep setup />
    </ScopeDraftProvider>
  </MemoryRouter>,
);

const renderScope = () => render(
  <MemoryRouter>
    <ScopeDraftProvider>
      <AccountableStep />
      <StageDimmer />
      <SaveDraft />
    </ScopeDraftProvider>
  </MemoryRouter>,
);

/* The Level step collapses the decoder; open it to assert its contents. */
const openDecoder = async () =>
  userEvent.click(screen.getByRole("button", { name: /What this means at each company/ }));

it("renders the dimmer band with marker, glow edge, and the corporate decoder", async () => {
  renderScope();

  const marker = await screen.findByRole("slider", { name: "Your level today" });
  const edge = screen.getByRole("slider", { name: "Level you're aiming for" });
  expect(marker).toHaveAttribute("aria-valuetext", "Entry / Junior");
  expect(edge).toHaveAttribute("aria-valuetext", "Senior");
  // The legend teaches the two handles with their real glyphs.
  expect(screen.getByText("you are here")).toBeInTheDocument();
  expect(screen.getByText("aiming for")).toBeInTheDocument();
  // Every stage shows its market inventory.
  expect(screen.getByText(/340 roles/)).toBeInTheDocument();

  // Decoder teaches the corporate grading per stage, behind a disclosure on
  // the Level step, so it costs no height until asked for.
  await openDecoder();
  expect(screen.getByText("L3–L4")).toBeInTheDocument();
  expect(screen.getByText("L5")).toBeInTheDocument();
  // Technical is the selected function, so Apple's technical grade decodes.
  expect(screen.getByText("ICT4")).toBeInTheDocument();
  // A ladder that repeats its role on every rung shows the rung word, and
  // the full title on hover; a rung that is only the role stays whole.
  const table = within(document.getElementById("stage-decoder-table")!);
  expect(table.getByText("Senior Staff")).toHaveAttribute("title", "Senior Staff Software Engineer");
  expect(table.getByText("Senior")).toHaveAttribute("title", "Senior Software Engineer");
  expect(table.getByText("Software Engineer")).not.toHaveAttribute("title");
  expect(table.queryByText("Senior Software Engineer")).not.toBeInTheDocument();
});

/* The grading matrix names every reference company: open, it is the tallest
   object in the stage section and pushes the step's Continue out of sight.
   The Level step opens without it. */
it("the Level step collapses the decoder by default and opens it on demand", async () => {
  renderScope();
  await screen.findByRole("slider", { name: "Level you're aiming for" });

  const toggle = screen.getByRole("button", { name: /What this means at each company/ });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByText("ICT4")).not.toBeInTheDocument();
  // The rail itself is never hidden by the disclosure.
  expect(screen.getByRole("slider", { name: "Your level today" })).toBeInTheDocument();

  await userEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("ICT4")).toBeInTheDocument();

  await userEvent.click(toggle);
  expect(screen.queryByText("ICT4")).not.toBeInTheDocument();
});

it("first-run setup folds the decoder too, and opens it on demand", async () => {
  profile.mockResolvedValue(profileStateFixture({ scope_configured: false }));
  renderSetup();

  await userEvent.click(await screen.findByLabelText("Hands-on, as the expert"));
  await screen.findByText("Pick your level today");

  const toggle = screen.getByRole("button", { name: /What this means at each company/ });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByText("L3–L4")).not.toBeInTheDocument();
  await userEvent.click(toggle);
  expect(screen.getByText("L3–L4")).toBeInTheDocument();
});

it("decoder is track-aware: technical shows the company code, other functions fall back to the tier word", async () => {
  renderScope();
  await screen.findByRole("slider", { name: "Level you're aiming for" });
  await openDecoder();

  // Technical selected -> Apple's technical-ladder code shows, in its own row.
  const table = () => document.getElementById("stage-decoder-table")!;
  const toggle = screen.getByRole("button", { name: /What this means at each company/ });
  expect(screen.getByText("ICT4")).toBeInTheDocument();
  expect(within(table()).getByText("Apple")).toBeInTheDocument();
  expect(toggle).toHaveTextContent("3 companies");

  // Switch the function to Business & Customer (IC): Apple publishes no grade for
  // it, so its row goes altogether rather than repeating the seniority words
  // the band already shows.
  await userEvent.click(screen.getByLabelText("Hands-on, as the expert"));
  await userEvent.click(screen.getByLabelText("Working with customers"));
  await waitFor(() => expect(screen.queryByText("ICT4")).not.toBeInTheDocument());
  expect(within(table()).queryByText("Apple")).not.toBeInTheDocument();
  expect(toggle).toHaveTextContent("1 company");

  // Google's company-wide number is function-agnostic and stays put.
  expect(within(table()).getByText("Google")).toBeInTheDocument();
  expect(screen.getByText("L5")).toBeInTheDocument();
});

it("gates tiers below a function's floor and snaps a stray marker up to it", async () => {
  renderScope();
  await screen.findByRole("slider", { name: "Your level today" });
  expect(screen.getByRole("slider", { name: "Your level today" }))
    .toHaveAttribute("aria-valuetext", "Entry / Junior");
  // Hands-on work spans every rung, so nothing is crossed out or explained.
  expect(screen.queryByText(/^This kind of role/)).not.toBeInTheDocument();

  // Management has no new-grad/junior/mid rung: switch to it alone.
  await userEvent.click(screen.getByLabelText("Hands-on, as the expert"));
  await userEvent.click(screen.getByLabelText("Leading a team"));

  // Sub-floor tiers become disabled, and the reason is on screen, not only in
  // a title a touch or keyboard user never sees...
  await waitFor(() => expect(screen.getByRole("button", { name: /Junior/ })).toBeDisabled());
  expect(screen.getByRole("button", { name: /Mid-level/ })).toBeDisabled();
  expect(screen.getByText("This kind of role starts at Senior.")).toBeVisible();
  // ...and the current-stage marker is DRAWN at the floor (Senior).
  expect(screen.getByRole("slider", { name: "Your level today" }))
    .toHaveAttribute("aria-valuetext", "Senior");

  // Drawn, never rewritten: widening the range again puts the
  // marker back where the person left it, and a save keeps their real level.
  await userEvent.click(screen.getByLabelText("Hands-on, as the expert"));
  await waitFor(() => expect(screen.getByRole("slider", { name: "Your level today" }))
    .toHaveAttribute("aria-valuetext", "Entry / Junior"));
  expect(screen.queryByText(/^This kind of role/)).not.toBeInTheDocument();
});

it("says where a kind of role tops out when the rungs above it are crossed out", async () => {
  load.mockResolvedValue({
    ...catalog,
    tracks: catalog.tracks.map((track) => track.slug === "business_customer"
      ? { ...track, allowed_bands: ["intern", "entry", "mid", "senior"] }
      : track),
  });
  renderScope();
  await screen.findByRole("slider", { name: "Your level today" });
  await userEvent.click(screen.getByLabelText("Hands-on, as the expert"));
  await userEvent.click(screen.getByLabelText("Working with customers"));

  await waitFor(() => expect(screen.getByRole("button", { name: /^Staff/ })).toBeDisabled());
  expect(screen.getByText("This kind of role tops out at Senior.")).toBeVisible();
  expect(screen.queryByText(/starts at/)).not.toBeInTheDocument();
});

it("first-run setup asks only for the rail: roles that state no level keep their default", async () => {
  profile.mockResolvedValue(profileStateFixture({ scope_configured: false }));
  renderSetup();
  await userEvent.click(await screen.findByLabelText("Hands-on, as the expert"));
  await screen.findByText("Pick your level today");

  expect(screen.queryByRole("checkbox", { name: /Include roles with an unknown level/ })).not.toBeInTheDocument();
});

it("a narrower kind of role never rewrites the saved level", async () => {
  renderScope();
  await screen.findByRole("slider", { name: "Your level today" });
  await userEvent.click(screen.getByLabelText("Hands-on, as the expert"));
  await userEvent.click(screen.getByLabelText("Leading a team"));
  await waitFor(() => expect(screen.getByRole("button", { name: /Junior/ })).toBeDisabled());

  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveSettings).toHaveBeenCalledTimes(1));
  // The persona's levels are what the person said, not the clamp.
  expect(saveSettings.mock.calls[0][0]).toMatchObject({ experience_stage: "entry", target_stage: "senior" });
});

it("stretching the glow edge extends the tracked span and saves the profile", async () => {
  renderScope();
  const edge = await screen.findByRole("slider", { name: "Level you're aiming for" });

  fireEvent.keyDown(edge, { key: "ArrowRight" });

  await waitFor(() => expect(screen.getByRole("slider", { name: "Level you're aiming for" }))
    .toHaveAttribute("aria-valuetext", "Staff"));
  const saveButton = screen.getByRole("button", { name: "Save" });
  expect(saveButton).toBeEnabled();

  await userEvent.click(saveButton);
  await waitFor(() => expect(saveSettings).toHaveBeenCalledTimes(1));
  expect(saveSettings.mock.calls[0][0]).toEqual({
    experience_stage: "entry",
    target_stage: "staff",
    enabled_seniority_bands: ["entry", "mid", "senior", "staff"],
    enabled_role_tracks: ["technical"],
    enabled_role_groups: ["software_engineering"],
    enabled_location_groups: ["uk"],
    enabled_domain_groups: ["ai_ml"],
    excluded_domain_groups: [],
    excluded_location_groups: [],
    include_unstated_level: false,
    // The answers read off the saved lists travel with the save. This
    // catalog lists one family and it is saved, so the answer is "any".
    role_answers: [{ track: "technical", roles: "any" }],
  });
  // The save lands: the draft reads clean again (the confirmation wording is
  // the walk rail's, tested in walk/Walk.test.tsx).
  await waitFor(() => expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument());
});

it("moving the marker re-anchors the span from the new current stage", async () => {
  renderScope();
  const marker = await screen.findByRole("slider", { name: "Your level today" });

  fireEvent.keyDown(marker, { key: "ArrowRight" });

  await waitFor(() => expect(screen.getByRole("slider", { name: "Your level today" }))
    .toHaveAttribute("aria-valuetext", "Mid-level"));
  // The aim stays where it was, so the span is now mid..senior, and that is
  // the seniority axis a save sends.
  expect(screen.getByRole("slider", { name: "Level you're aiming for" }))
    .toHaveAttribute("aria-valuetext", "Senior");
  await userEvent.click(await screen.findByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveSettings).toHaveBeenCalledTimes(1));
  expect(saveSettings.mock.calls[0][0].enabled_seniority_bands).toEqual(["mid", "senior"]);
});

it("calendar range: a fresh click re-anchors both markers and arms the aim; the next click locks it", async () => {
  renderScope();
  await screen.findByRole("slider", { name: "Level you're aiming for" });
  // Starts committed at Junior (dot) .. Senior (aim).
  expect(screen.getByRole("slider", { name: "Your level today" }))
    .toHaveAttribute("aria-valuetext", "Entry / Junior");
  expect(screen.getByRole("slider", { name: "Level you're aiming for" }))
    .toHaveAttribute("aria-valuetext", "Senior");

  // A fresh click on a committed rail wipes the old pair and drops BOTH markers
  // on the clicked stage (the new anchor) — no need to touch the old markers.
  await userEvent.click(screen.getByText("Mid-level"));
  expect(screen.getByRole("slider", { name: "Your level today" }))
    .toHaveAttribute("aria-valuetext", "Mid-level");
  expect(screen.getByRole("slider", { name: "Level you're aiming for" }))
    .toHaveAttribute("aria-valuetext", "Mid-level");

  // Now armed: the next click locks the aim wherever it lands (here, higher).
  await userEvent.click(screen.getByText("Staff"));
  expect(screen.getByRole("slider", { name: "Your level today" }))
    .toHaveAttribute("aria-valuetext", "Mid-level");
  expect(screen.getByRole("slider", { name: "Level you're aiming for" }))
    .toHaveAttribute("aria-valuetext", "Staff");
});

it("unmounting clears the pulse a click leaves running, so it never fires into a torn-down page", async () => {
  const set = vi.spyOn(window, "setTimeout");
  const clear = vi.spyOn(window, "clearTimeout");
  try {
    const { unmount } = renderScope();
    await screen.findByRole("slider", { name: "Level you're aiming for" });
    const before = set.mock.calls.length;
    await userEvent.click(screen.getByText("Mid-level"));
    // The pulse is the longest timer the click starts; userEvent's own are 0 ms.
    const started = set.mock.calls.slice(before).map(([, ms], i) => ({ ms: ms ?? 0, id: set.mock.results[before + i].value }));
    const pulse = started.reduce((a, b) => (b.ms > a.ms ? b : a), { ms: 0, id: undefined });
    expect(pulse.ms).toBeGreaterThan(0);

    unmount();
    expect(clear).toHaveBeenCalledWith(pulse.id);
  } finally {
    set.mockRestore();
    clear.mockRestore();
  }
});

it("calendar range: the aim can lock below the anchor, and a stray click after commit starts over", async () => {
  renderScope();
  await screen.findByRole("slider", { name: "Level you're aiming for" });

  // Anchor high, then aim low: the diamond is allowed to sit below the dot.
  await userEvent.click(screen.getByText("Staff"));      // fresh anchor -> both on Staff
  await userEvent.click(screen.getByText("Mid-level"));   // second click -> aim below
  expect(screen.getByRole("slider", { name: "Your level today" }))
    .toHaveAttribute("aria-valuetext", "Staff");
  expect(screen.getByRole("slider", { name: "Level you're aiming for" }))
    .toHaveAttribute("aria-valuetext", "Mid-level");

  // Committed: the next click is not a move — it restarts the pair on that stage.
  await userEvent.click(screen.getByText("Senior"));
  expect(screen.getByRole("slider", { name: "Your level today" }))
    .toHaveAttribute("aria-valuetext", "Senior");
  expect(screen.getByRole("slider", { name: "Level you're aiming for" }))
    .toHaveAttribute("aria-valuetext", "Senior");
});

it("first-run setup starts unplaced: the first click places you and arms the aim", async () => {
  profile.mockResolvedValue(profileStateFixture({ scope_configured: false }));
  renderSetup();

  // Setup must not inherit the saved or default selections.
  const handsOn = await screen.findByLabelText("Hands-on, as the expert");
  expect(handsOn).not.toBeChecked();
  await userEvent.click(handsOn);

  expect(await screen.findByText("Pick your level today")).toBeInTheDocument();
  expect(screen.queryByRole("slider", { name: "Your level today" })).not.toBeInTheDocument();

  // First click drops the dot and the aim on the same stage.
  await userEvent.click(screen.getByText("Mid-level"));

  expect(screen.getByRole("slider", { name: "Your level today" }))
    .toHaveAttribute("aria-valuetext", "Mid-level");
  expect(screen.getByRole("slider", { name: "Level you're aiming for" }))
    .toHaveAttribute("aria-valuetext", "Mid-level");
});

/* jsdom has no layout, so the rail has no box and `indexFromPointer` bails out.
   Give it a horizontal box: 4 rungs across 280px, so clientX 10 is rung 0. */
const layOutRail = (rail: HTMLElement) => {
  vi.spyOn(rail, "getBoundingClientRect").mockReturnValue({
    x: 0, y: 0, left: 0, top: 0, right: 280, bottom: 40,
    width: 280, height: 40, toJSON: () => ({}),
  } as DOMRect);
};

/* A fresh click ARMS the aim, and while armed the aim follows the pointer
   across the rail. A pointer merely travelling across the rail on its way to
   another control, or a pointermove the browser synthesises with a STALE
   position when the rail lays out under a stationary pointer, must not
   re-aim the user.

   The invariant: what gets SAVED is what the user committed,
   never a value a hover produced. Aiming still previews live; only a click (or
   the keyboard) commits. */
it("a stray pointer crossing the armed rail never changes the saved aim", async () => {
  renderScope();
  await screen.findByRole("slider", { name: "Level you're aiming for" });
  const rail = screen.getByRole("group", { name: "Level range" });
  layOutRail(rail);

  // Fresh click: both markers land on Staff and the aim is now armed.
  await userEvent.click(screen.getByText("Staff"));
  expect(screen.getByRole("slider", { name: "Your level today" }))
    .toHaveAttribute("aria-valuetext", "Staff");

  // A pointermove on the RAIL, at the very position the click landed on. Box
  // arithmetic resolves this to rung 0, disagreeing with the cell actually
  // clicked; the aim must not follow it into the save.
  fireEvent.pointerMove(rail, { clientX: 10, clientY: 20 });

  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveSettings).toHaveBeenCalledTimes(1));
  expect(saveSettings.mock.calls[0][0]).toMatchObject({
    experience_stage: "staff",
    target_stage: "staff",
  });
});

it("aiming still previews the rung under the pointer, and the click commits it", async () => {
  renderScope();
  await screen.findByRole("slider", { name: "Level you're aiming for" });
  const rail = screen.getByRole("group", { name: "Level range" });
  layOutRail(rail);

  await userEvent.click(screen.getByText("Entry / Junior"));
  // Armed: the rung under the pointer is the CELL under the pointer.
  fireEvent.pointerEnter(screen.getByText("Staff"));
  expect(screen.getByRole("slider", { name: "Level you're aiming for" }))
    .toHaveAttribute("aria-valuetext", "Staff");

  // The click is what commits it, and the commit is what saves.
  await userEvent.click(screen.getByText("Staff"));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveSettings).toHaveBeenCalledTimes(1));
  expect(saveSettings.mock.calls[0][0]).toMatchObject({
    experience_stage: "entry",
    target_stage: "staff",
  });
});

it("leaving the rail without locking keeps the aim the user last committed", async () => {
  renderScope();
  await screen.findByRole("slider", { name: "Level you're aiming for" });
  const rail = screen.getByRole("group", { name: "Level range" });
  layOutRail(rail);

  await userEvent.click(screen.getByText("Entry / Junior"));
  fireEvent.pointerEnter(screen.getByText("Staff"));
  fireEvent.pointerLeave(rail);

  // The preview is abandoned, not adopted: the aim is still on the anchor.
  expect(screen.getByRole("slider", { name: "Level you're aiming for" }))
    .toHaveAttribute("aria-valuetext", "Entry / Junior");

  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveSettings).toHaveBeenCalledTimes(1));
  expect(saveSettings.mock.calls[0][0]).toMatchObject({
    experience_stage: "entry",
    target_stage: "entry",
  });
});


/* Roles whose posting states no level sit on no rung. The Level
   step counts them apart and lets the person include them; this fixture has
   them saved off. */
it("offers roles whose level isn't stated beside the rail, off, and saves the choice", async () => {
  load.mockResolvedValue({ ...catalog, unstated_level_count: 1234 });
  renderScope();
  const choice = await screen.findByRole("checkbox", { name: /Include roles with an unknown level/ });
  expect(choice).not.toBeChecked();
  // Its count is its own, never folded into Mid-level's.
  expect(choice.closest("label")).toHaveTextContent("1,234 roles");
  expect(screen.getByText(/340 roles/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();

  await userEvent.click(choice);
  expect(choice).toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveSettings).toHaveBeenCalledTimes(1));
  expect(saveSettings.mock.calls[0][0]).toMatchObject({ include_unstated_level: true });
  // The echo is adopted: the draft reads clean with the choice kept.
  await waitFor(() => expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument());
  expect(screen.getByRole("checkbox", { name: /Include roles with an unknown level/ })).toBeChecked();
});

it("reads the saved choice back on", async () => {
  load.mockResolvedValue({ ...catalog, settings: { ...catalog.settings, include_unstated_level: true } });
  renderScope();
  expect(await screen.findByRole("checkbox", { name: /Include roles with an unknown level/ })).toBeChecked();
});
