import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { ScopeDraftProvider, useScopeDraft } from "./useScopeDraft";
import { profileStateFixture, scopeCatalogFixture, settingsSaveFixture } from "../../test/fixtures";

/* The scope draft provider, driven directly: catalog load, persona load, the
 * derived stage<->band span, and the one save path (`PUT /api/settings`, the
 * level markers riding with the scope).
 *
 * Its consumer tests exercise it only through their own screens and assert on
 * rendered scope, so a save that sent the wrong body could still let each of
 * them pass.
 */

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return {
    ...actual,
    api: {
      ...actual.api,
      scopeCatalog: vi.fn(),
      profile: vi.fn(),
      saveProfile: vi.fn(),
      saveSettings: vi.fn(),
    },
  };
});

/* One STABLE actions object. Returning a fresh `vi.fn()` per call would make
   `refreshStats` change identity every render, and the stability test below
   would then be measuring this mock rather than the hook. */
const refreshStats = vi.fn();
const missionActions = { refreshStats };
vi.mock("../../context/MissionState", () => ({ useMissionActions: () => missionActions }));


const CATALOG = scopeCatalogFixture({
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
    { slug: "mid", order: 2, default_enabled: false, selected: true, new: false, count: 340, decoder: { google: { company_wide: "L4" } } },
    { slug: "senior", order: 3, default_enabled: true, selected: true, new: false, count: 510, decoder: { google: { company_wide: "L5" }, apple: { per_track: { technical: "ICT4" } } } },
    { slug: "staff", order: 4, default_enabled: true, selected: false, new: false, count: 200, decoder: { google: { company_wide: "L6" }, apple: { per_track: { technical: "ICT5" } } } },
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

const SAVED_SCOPE = settingsSaveFixture(CATALOG.settings, { in_scope_changed: 3 });

/** A probe that renders the draft's state and exposes its verbs as buttons. */
function Probe() {
  const d = useScopeDraft();
  return (
    <div>
      <span data-testid="catalog">{d.catalog ? "loaded" : "none"}</span>
      <span data-testid="error">{d.error ?? ""}</span>
      <button onClick={() => d.save()}>save</button>
      <button onClick={() => d.setExperienceStage("entry")}>set experience</button>
      <button onClick={() => d.setTargetStage("staff")}>set target</button>
      <button onClick={() => d.reloadCatalog()}>reload</button>
    </div>
  );
}

const renderDraft = () =>
  render(
    <ScopeDraftProvider>
      <Probe />
    </ScopeDraftProvider>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.scopeCatalog).mockResolvedValue(CATALOG);
  vi.mocked(api.profile).mockResolvedValue(profileStateFixture());
  vi.mocked(api.saveSettings).mockResolvedValue(SAVED_SCOPE);
});

describe("the scope draft's one save path", () => {
  it("saves through /api/settings when no levels are placed", async () => {
    const user = userEvent.setup();
    renderDraft();
    await screen.findByText("loaded");

    await user.click(screen.getByRole("button", { name: "save" }));

    await waitFor(() => expect(api.saveSettings).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.saveSettings).mock.calls[0][0]).toMatchObject({
      enabled_role_groups: ["software_engineering"],
      enabled_seniority_bands: ["entry", "mid", "senior"],
    });
    expect(vi.mocked(api.saveSettings).mock.calls[0][0]).not.toHaveProperty("experience_stage");
  });

  it("sends both level markers with the scope, and the span is the seniority axis", async () => {
    const user = userEvent.setup();
    renderDraft();
    await screen.findByText("loaded");

    await user.click(screen.getByRole("button", { name: "set experience" }));
    await user.click(screen.getByRole("button", { name: "set target" }));
    await user.click(screen.getByRole("button", { name: "save" }));

    await waitFor(() => expect(api.saveSettings).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.saveSettings).mock.calls[0][0]).toMatchObject({
      enabled_role_groups: ["software_engineering"],
      experience_stage: "entry",
      target_stage: "staff",
      enabled_seniority_bands: ["entry", "mid", "senior", "staff"],
    });
  });

  it("moves a loaded persona's levels through the same path", async () => {
    /* The markers live on the persona, and every save carries them with the
       scope, so the seniority axis is always the span they describe.
       */
    vi.mocked(api.profile).mockResolvedValue(profileStateFixture({
      profile: { experience_stage: "senior", target_stage: "senior" },
    }));
    const user = userEvent.setup();
    renderDraft();
    await screen.findByText("loaded");

    await user.click(screen.getByRole("button", { name: "set target" }));
    await user.click(screen.getByRole("button", { name: "save" }));

    await waitFor(() => expect(api.saveSettings).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.saveSettings).mock.calls[0][0]).toMatchObject({
      enabled_seniority_bands: ["senior", "staff"],
      experience_stage: "senior",
      target_stage: "staff",
    });
  });

  it("sends no half pair of stages", async () => {
    /* Half a position is not a position, and the backend rejects one: with
       one marker placed, neither travels. */
    const user = userEvent.setup();
    renderDraft();
    await screen.findByText("loaded");

    await user.click(screen.getByRole("button", { name: "set experience" }));
    await user.click(screen.getByRole("button", { name: "save" }));

    await waitFor(() => expect(api.saveSettings).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(api.saveSettings).mock.calls[0][0];
    expect(payload).not.toHaveProperty("experience_stage");
    expect(payload).not.toHaveProperty("target_stage");
  });

  it("reports a failed save instead of leaving the button spinning", async () => {
    vi.mocked(api.saveSettings).mockRejectedValue(new Error("scope save exploded"));
    const user = userEvent.setup();
    renderDraft();
    await screen.findByText("loaded");

    await user.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() =>
      expect(screen.getByTestId("error")).toHaveTextContent("Couldn't save your radar. Try again."),
    );
    expect(screen.getByTestId("error")).not.toHaveTextContent("exploded");
  });
});

describe("the scope draft's catalog load", () => {
  it("surfaces a failed catalog and can be asked again", async () => {
    vi.mocked(api.scopeCatalog).mockRejectedValueOnce(new Error("catalog exploded"));
    const user = userEvent.setup();
    renderDraft();

    await waitFor(() =>
      expect(screen.getByTestId("error")).toHaveTextContent("Couldn't load your radar. Try again."),
    );
    expect(screen.getByTestId("error")).not.toHaveTextContent("exploded");
    expect(screen.getByTestId("catalog")).toHaveTextContent("none");

    // The failure is not permanent: asking again works without reloading the
    // page.
    await user.click(screen.getByRole("button", { name: "reload" }));
    await screen.findByText("loaded");
    expect(screen.getByTestId("error")).toHaveTextContent("");
  });
});

describe("the scope draft's identity", () => {
  it("hands consumers a stable value when nothing it holds has changed", async () => {
    /* A value rebuilt each render would re-render every consumer on a
       keystroke anywhere in the provider, and some consumers render the whole
       role catalog. Re-rendering the provider with identical state must not
       produce a new context value. */
    const seen: unknown[] = [];
    function Watcher() {
      seen.push(useScopeDraft());
      return null;
    }
    const view = render(
      <ScopeDraftProvider>
        <Watcher />
      </ScopeDraftProvider>,
    );
    await waitFor(() => expect(seen.length).toBeGreaterThan(1));

    const before = seen.length;
    act(() => {
      view.rerender(
        <ScopeDraftProvider>
          <Watcher />
        </ScopeDraftProvider>,
      );
    });
    expect(seen.length).toBeGreaterThan(before);
    expect(seen[seen.length - 1]).toBe(seen[before - 1]);
  });
});

/* Profile's draft outlives a navigation. The provider sits inside the route,
   so leaving Profile unmounts it, and without the stash every unsaved pick
   would go with it: back on Profile the screen would show the saved scope
   again, with no word said and nothing saved. The draft is kept in memory for the next visit; `saved` still comes fresh from
   the server, and nothing is written until Save. */
describe("Profile's unsaved draft survives leaving the page", () => {
  function DirtyProbe() {
    const d = useScopeDraft();
    return (
      <div>
        <span data-testid="catalog">{d.catalog ? "loaded" : "none"}</span>
        <span data-testid="dirty">{d.dirty ? "dirty" : "clean"}</span>
        <span data-testid="has-mid">{d.selectedBands.has("mid") ? "yes" : "no"}</span>
        <button onClick={() => d.toggleBand("mid")}>toggle mid</button>
        <button onClick={() => d.save()}>save</button>
      </div>
    );
  }
  const mount = () => render(<ScopeDraftProvider><DirtyProbe /></ScopeDraftProvider>);

  it("brings back unsaved picks after the page unmounts, and saves nothing on the way", async () => {
    const user = userEvent.setup();
    const first = mount();
    await screen.findByText("loaded");
    expect(screen.getByTestId("has-mid")).toHaveTextContent("yes");
    await user.click(screen.getByRole("button", { name: "toggle mid" }));
    expect(screen.getByTestId("dirty")).toHaveTextContent("dirty");
    first.unmount();

    mount();
    await screen.findByText("loaded");
    expect(screen.getByTestId("has-mid")).toHaveTextContent("no");
    expect(screen.getByTestId("dirty")).toHaveTextContent("dirty");
    expect(api.saveSettings).not.toHaveBeenCalled();
  });

  it("forgets the draft once it is saved", async () => {
    const user = userEvent.setup();
    const first = mount();
    await screen.findByText("loaded");
    await user.click(screen.getByRole("button", { name: "toggle mid" }));
    await user.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() => expect(api.saveSettings).toHaveBeenCalled());
    first.unmount();

    mount();
    await screen.findByText("loaded");
    // The server's scope, as the catalog answers it: the saved draft is not replayed.
    expect(screen.getByTestId("dirty")).toHaveTextContent("clean");
  });
});
