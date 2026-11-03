import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CompanyDiscoveryState, InsightsScope } from "../../api";
import { api } from "../../api";
import { levelGuideFixture, profileStateFixture } from "../../test/fixtures";
import { LevelsPanel } from "./LevelsPanel";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return {
    ...actual,
    api: {
      ...actual.api,
      levelGuide: vi.fn(),
      companyDiscovery: vi.fn(),
      profile: vi.fn(),
      scopeSettings: vi.fn(),
      companies: vi.fn(),
    },
  };
});

function discoveryRow(slug: string, display: string, extra: Partial<CompanyDiscoveryState["companies"][number]> = {}) {
  return {
    slug, display, careers_url: null, sectors: ["faang"], aliases: [], connector_state: "live" as const,
    parked_reason: null, selectable: true, tracked: false, enabled: false, visible: true, builtin: true,
    curated: false, directory: false, wall: null, consented: false, status: null, ...extra,
  };
}

const discovery: CompanyDiscoveryState = {
  sectors: [],
  companies: [
    discoveryRow("google", "Google", { tracked: true, enabled: true, status: "active" }),
    discoveryRow("apple", "Apple"),
    discoveryRow("amazon", "Amazon", { aliases: ["AWS"] }),
    discoveryRow("openai", "OpenAI", { sectors: ["ai"] }),
    discoveryRow("stripe", "Stripe", { sectors: ["fintech"] }),
  ],
};

function settings(tracks: string[]) {
  return {
    enabled_role_groups: [], enabled_seniority_bands: [], enabled_role_tracks: tracks,
    enabled_location_groups: [], enabled_domain_groups: [], excluded_domain_groups: [], role_answers: [],
    excluded_location_groups: [], include_unstated_level: true,
  } as unknown as Awaited<ReturnType<typeof api.scopeSettings>>;
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

function renderLevels(route = "/statistics/levels", scope: InsightsScope = { side: "all", families: [] }) {
  const onResetSide = vi.fn();
  render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/statistics/levels" element={<LevelsPanel scope={scope} onResetSide={onResetSide} />} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
  return { onResetSide };
}

const table = () => screen.getByRole("table");
const rowOf = (name: string) => within(table()).getByRole("rowheader", { name: new RegExp(`^${name}`, "i") }).closest("tr")!;
const rowNames = () => within(table()).getAllByRole("rowheader").map((cell) => cell.textContent);

beforeEach(() => {
  vi.mocked(api.levelGuide).mockResolvedValue(levelGuideFixture);
  vi.mocked(api.companyDiscovery).mockResolvedValue(discovery);
  vi.mocked(api.profile).mockResolvedValue(profileStateFixture({
    profile: { experience_stage: "senior", target_stage: "staff" },
  }));
  // A fresh install: all four career tracks.
  vi.mocked(api.scopeSettings).mockResolvedValue(settings(["management", "product_program", "technical", "business_customer"]));
  vi.mocked(api.companies).mockResolvedValue({ companies: [] } as unknown as Awaited<ReturnType<typeof api.companies>>);
});

describe("LevelsPanel", () => {
  it("lists every reviewed ladder and lights the person's level and aim", async () => {
    renderLevels();
    await screen.findByRole("table");
    await waitFor(() => expect(screen.getByRole("columnheader", { name: "Senior, your level" })).toBeInTheDocument());
    expect(screen.getByRole("columnheader", { name: "Staff, your aim" })).toBeInTheDocument();
    // A fresh install opens on hands-on and drops nobody.
    expect(rowNames()).toHaveLength(levelGuideFixture.companies.length);
    // Most ladders name no intern: the column folds away.
    expect(screen.queryByRole("columnheader", { name: /Intern/ })).not.toBeInTheDocument();
  });

  it("counts the ladders in view, the flat ones, and those that skip the person's aim", async () => {
    renderLevels();
    await waitFor(() => expect(screen.getByText("No Staff level")).toBeInTheDocument());
    const tile = (label: string) => screen.getByText(label).closest(".kpi")!;
    expect(tile("Companies")).toHaveTextContent(String(levelGuideFixture.companies.length));
    expect(tile("Titles without levels")).toHaveTextContent("1");
    // Amazon and Microsoft name no Staff rung; flat Meta states no level, so it skips none.
    expect(tile("No Staff level")).toHaveTextContent("2");
  });

  it("translates a picked level across every company and clears back", async () => {
    const user = userEvent.setup();
    renderLevels();
    await user.click(await screen.findByRole("button", { name: "Translate from Apple ICT4" }));

    expect(screen.getByTestId("location")).toHaveTextContent("/statistics/levels?from=apple%3Asenior");
    expect(screen.getByRole("status")).toHaveTextContent("Translating Apple ICT4 (Senior) across every company");
    expect(screen.getByRole("heading", { name: "Apple ICT4 is Senior" })).toBeInTheDocument();
    // The row pins on top; its column is lit, and the Profile lighting steps aside.
    expect(rowNames()[0]).toBe("Apple");
    expect(screen.getByRole("columnheader", { name: "Senior, translating" })).toHaveClass("lit");
    expect(screen.getByRole("columnheader", { name: "Staff" })).not.toHaveClass("lit");
    expect(within(rowOf("Google")).getByRole("button", { name: "Translate from Google L5" }).closest("td")).toHaveClass("lit");

    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/statistics\/levels$/);
    expect(screen.getByRole("columnheader", { name: "Senior, your level" })).toBeInTheDocument();
  });

  it("says where a company skips the translated level, and what it reads as", async () => {
    renderLevels("/statistics/levels?from=google:staff");
    await screen.findByRole("table");
    const amazonStaff = within(rowOf("Amazon")).getByText("Amazon has no Staff level").closest("td")!;
    expect(amazonStaff).toHaveTextContent("No Staff level. Closest: L6");
  });

  it("asks which one when a code names a different level at several companies", async () => {
    const user = userEvent.setup();
    renderLevels();
    await user.type(await screen.findByRole("searchbox", { name: "Company or level" }), "L5");

    expect(screen.getByRole("status")).toHaveTextContent("L5 is a different level at 4 companies. Pick one to translate from.");
    expect(rowNames()).toEqual(["Amazon", "Google", "Netflix", "OpenAI"]);
    expect(within(rowOf("OpenAI")).getByRole("button", { name: "Translate from OpenAI L5" }).closest("td")).toHaveClass("hit");
    expect(screen.queryByText(/Translating/)).not.toBeInTheDocument();
  });

  it("translates straight away when a code names one level, showing the spelling a label hides", async () => {
    const user = userEvent.setup();
    renderLevels();
    await user.type(await screen.findByRole("searchbox", { name: "Company or level" }), "ICT4");
    expect(screen.getByRole("status")).toHaveTextContent("Translating Apple ICT4 (Senior)");
    expect(rowNames()).toHaveLength(levelGuideFixture.companies.length);

    await user.clear(screen.getByRole("searchbox", { name: "Company or level" }));
    await user.type(screen.getByRole("searchbox", { name: "Company or level" }), "Distinguished Engineer");
    expect(within(rowOf("NVIDIA")).getByText(", Distinguished Engineer")).toBeInTheDocument();
  });

  it("keeps engineering-only companies under another career track, marked", async () => {
    renderLevels("/statistics/levels?track=management");
    await screen.findByRole("table");
    expect(rowNames()).toHaveLength(levelGuideFixture.companies.length);
    expect(within(rowOf("Apple")).getByText("Engineering levels")).toBeInTheDocument();
    expect(within(rowOf("Google")).queryByText("Engineering levels")).not.toBeInTheDocument();
    // Google's L8 is Director+ for a manager.
    expect(within(rowOf("Google")).getByRole("button", { name: "Translate from Google L7" })).toBeInTheDocument();
    // A manager is never entry level: the column is gated, as on the Profile rail.
    expect(screen.getByRole("columnheader", { name: "Entry / Junior" })).toHaveClass("gated");
  });

  it("says a flat ladder's titles state no level instead of leaving blanks", async () => {
    renderLevels();
    await screen.findByRole("table");
    expect(within(rowOf("Meta")).getByText("Titles state no level here")).toBeInTheDocument();
    expect(within(rowOf("Amazon")).queryByText("Titles state no level here")).not.toBeInTheDocument();
  });

  it("answers a company without a level guide, and one that shares another's", async () => {
    const user = userEvent.setup();
    renderLevels();
    const search = await screen.findByRole("searchbox", { name: "Company or level" });
    await user.type(search, "stripe");
    expect(screen.getByText("No level guide for Stripe yet.")).toBeInTheDocument();

    await user.clear(search);
    await user.type(search, "deepmind");
    expect(screen.getByText("Shares the levels of Google.")).toBeInTheDocument();
    expect(rowNames()).toContain("Google");
  });

  it("finds a company by an alias", async () => {
    const user = userEvent.setup();
    renderLevels();
    await user.type(await screen.findByRole("searchbox", { name: "Company or level" }), "aws");
    expect(rowNames()).toEqual(["Amazon"]);
  });

  it("names the filters that emptied the table and resets them all", async () => {
    const user = userEvent.setup();
    const { onResetSide } = renderLevels("/statistics/levels?q=zzz&track=management");
    expect(await screen.findByText("No company or level matches")).toBeInTheDocument();
    expect(screen.getByText(/“zzz”/)).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Reset all" })[0]);
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/statistics\/levels$/);
    expect(onResetSide).toHaveBeenCalled();
  });

  it("under Your companies, shows followed ladders and counts those without one", async () => {
    vi.mocked(api.companyDiscovery).mockResolvedValue({
      ...discovery,
      companies: [...discovery.companies, discoveryRow("ramp-like", "Rampish", { tracked: true, enabled: true, status: "active" })],
    });
    renderLevels("/statistics/levels", { side: "yours", families: [] });
    await waitFor(() => expect(rowNames()).toEqual(["Google"]));
    expect(screen.getByText("1 company you follow has no level guide yet.")).toBeInTheDocument();
    // A followed company links to its page; one never followed is plain text.
    expect(within(rowOf("Google")).getByRole("link", { name: "Google" })).toHaveAttribute("href", "/company/google");
  });
});
