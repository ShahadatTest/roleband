import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { msg } from "../../test/msg";
import { readInsightsView, writeInsightsView } from "./insightsView";
import { StatisticsView } from "./StatisticsView";

vi.mock("./OverviewPanel", () => ({
  OverviewPanel: ({ scope, advanced }: { scope?: { side: string; families: readonly string[] }; advanced?: boolean }) => (
    <div data-advanced={String(Boolean(advanced))}>Overview content{scope ? ` scope=${scope.side}:${scope.families.join("+")}` : ""}</div>
  ),
}));
vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  const { facetsFixture } = await import("../../test/fixtures");
  return { ...actual, api: { ...actual.api, facets: vi.fn().mockResolvedValue(facetsFixture) } };
});
vi.mock("./Demand", () => ({ DemandView: () => <div>Demand content</div> }));
vi.mock("./VelocityPanel", () => ({ VelocityPanel: () => <div>Velocity content</div> }));
vi.mock("./CompensationPanel", () => ({ CompensationPanel: () => <div>Compensation content</div> }));
vi.mock("./StockTrajectoryPanel", () => ({ StockTrajectoryPanel: () => <div>Trajectory content</div> }));
vi.mock("./SkillsView", () => ({ SkillsView: () => <div>Skills content</div> }));
vi.mock("./TrendsPanel", () => ({ TrendsPanel: () => <div>Trends content</div> }));
vi.mock("./OverlapPanel", () => ({ OverlapPanel: () => <div>Overlap content</div> }));
vi.mock("./ClustersView", () => ({ ClustersView: () => <div>Clusters content</div> }));
vi.mock("./LevelsPanel", async () => {
  const actual = await vi.importActual<typeof import("./LevelsPanel")>("./LevelsPanel");
  return { ...actual, LevelsPanel: ({ scope }: { scope: { side: string } }) => <div>Levels content scope={scope.side}</div> };
});

// The sub-tab lives in the path (`/statistics/:tab`), so every render mounts the
// view under a matching route. A probe echoes the URL for navigation assertions.
function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{`${loc.pathname}${loc.search}`}</div>;
}

function renderStats(route = "/statistics/overview", extra?: ReactElement) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/statistics/:tab" element={<StatisticsView onOpen={vi.fn()} />} />
      </Routes>
      <LocationProbe />
      {extra}
    </MemoryRouter>,
  );
}

describe("StatisticsView", () => {
  // These cases walk every tab, so they read the advanced view, which lists
  // them all; the basic view has its own cases below.
  beforeEach(() => writeInsightsView("advanced"));

  it("narrows every tab but Stock by one scope, kept in the address", async () => {
    // Your companies / Other companies and disciplines, one bar for all
    // tabs, in `?side=` and `?family=` like the window.
    const user = userEvent.setup();
    renderStats("/statistics/overview?side=other");
    expect(screen.getByRole("group", { name: "Companies" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Other companies" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Overview content scope=other:")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Your companies" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/statistics/overview?side=yours");
    expect(screen.getByText("Overview content scope=yours:")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "All companies" }));
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/statistics\/overview$/);

    await user.click(screen.getByRole("tab", { name: "Stock" }));
    expect(screen.queryByRole("group", { name: "Companies" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Skills" }));
    expect(screen.getByRole("group", { name: "Companies" })).toBeInTheDocument();
  });

  it("keeps the scope and the window when the reader switches tabs", async () => {
    const user = userEvent.setup();
    renderStats("/statistics/overview?window=90&side=other&family=design_ux");
    await user.click(screen.getByRole("tab", { name: "Pace" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/statistics/velocity?window=90&side=other&family=design_ux");
  });

  it("reads disciplines from the address into the scope", () => {
    renderStats("/statistics/overview?family=product_management&family=engineering_management");
    expect(screen.getByText("Overview content scope=all:product_management+engineering_management")).toBeInTheDocument();
  });

  it("shows the period lens only for tabs whose data honors it", async () => {
    const user = userEvent.setup();
    renderStats();

    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("group", { name: "Time range" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "30d" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("tab", { name: "Hiring" }));
    expect(screen.getByText("Demand content")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Time range" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Trends" }));
    expect(screen.getByRole("group", { name: "Time range" })).toBeInTheDocument();
  });

  it("supports arrow-key navigation across the statistics tabs", async () => {
    const user = userEvent.setup();
    renderStats();

    const overview = screen.getByRole("tab", { name: "Overview" });
    overview.focus();
    await user.keyboard("{ArrowRight}");

    expect(screen.getByRole("tab", { name: "Hiring" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Demand content")).toBeInTheDocument();
  });

  it("puts the active sub-tab in the URL path so the view is deep-linkable", async () => {
    const user = userEvent.setup();
    renderStats();

    await user.click(screen.getByRole("tab", { name: "Pace" }));

    expect(screen.getByTestId("location")).toHaveTextContent("/statistics/velocity");
    expect(screen.getByRole("tab", { name: "Pace" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Velocity content")).toBeInTheDocument();
  });

  it("deep-links straight to a sub-tab from the URL", () => {
    renderStats("/statistics/compensation");
    expect(screen.getByRole("tab", { name: "Compensation" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Compensation content")).toBeInTheDocument();
  });

  it("honors the ?window= lens from the URL", () => {
    renderStats("/statistics/overview?window=90");
    expect(screen.getByRole("button", { name: "90d" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "30d" })).toHaveAttribute("aria-pressed", "false");
  });

  it("redirects an unknown sub-tab to Overview", async () => {
    renderStats("/statistics/bogus");
    expect(await screen.findByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("location")).toHaveTextContent("/statistics/overview");
  });

  it("keeps the companies side on Levels, without disciplines or a window", async () => {
    // A ladder is reference data: the side picks whose ladders show, and
    // nothing counts postings, so no discipline or period narrows it.
    renderStats("/statistics/levels?side=yours");
    expect(screen.getByText("Levels content scope=yours")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Companies" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /discipline/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Time range" })).not.toBeInTheDocument();
  });

  it("leaves Levels' search and translation behind on a tab switch, keeping the side", async () => {
    const user = userEvent.setup();
    renderStats("/statistics/levels?side=yours&q=ICT4&from=apple%3Asenior&track=management&sector=ai");
    await user.click(screen.getByRole("tab", { name: "Overview" }));
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/statistics\/overview\?side=yours$/);
    // The discipline control the Levels tab hides is back.
    expect(screen.getByRole("button", { name: /discipline/i })).toBeInTheDocument();
  });
});

describe("the basic and advanced views", () => {
  const BASIC = ["Overview", "Hiring", "Compensation", "Skills"];
  const ADVANCED = ["Pace", "Levels", "Stock", "Trends", "Overlap", "Groups"];
  const listed = () => within(screen.getByRole("tablist")).getAllByRole("tab").map((tab) => tab.textContent);
  const advancedSwitch = () => screen.getByRole("checkbox", { name: msg("insights-statistics-view-advanced-view") });

  it("starts basic: four tabs, the switch off, and the panels told so", () => {
    renderStats();
    expect(listed()).toEqual(BASIC);
    expect(advancedSwitch()).not.toBeChecked();
    expect(screen.getByText(/Overview content/)).toHaveAttribute("data-advanced", "false");
  });

  it("asks once before the advanced view, and lists every tab after a yes", async () => {
    const user = userEvent.setup();
    renderStats();
    await user.click(advancedSwitch());

    const dialog = screen.getByRole("dialog", { name: msg("insights-statistics-view-advanced-warning-title") });
    expect(dialog).toHaveTextContent(msg("insights-statistics-view-advanced-warning-body"));
    // Nothing changes until the person answers.
    expect(listed()).toEqual(BASIC);
    expect(advancedSwitch()).not.toBeChecked();

    await user.click(within(dialog).getByRole("button", { name: msg("insights-statistics-view-show-me-everything") }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(advancedSwitch()).toBeChecked();
    expect(listed()).toEqual(["Overview", "Hiring", "Pace", "Compensation", "Levels", "Stock", "Skills", "Trends", "Overlap", "Groups"]);
    expect(screen.getByText(/Overview content/)).toHaveAttribute("data-advanced", "true");
    expect(readInsightsView()).toBe("advanced");
  });

  it("stays basic when the person keeps it simple, and asks again next time", async () => {
    const user = userEvent.setup();
    renderStats();
    await user.click(advancedSwitch());
    await user.click(screen.getByRole("button", { name: msg("insights-statistics-view-keep-it-simple") }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(advancedSwitch()).not.toBeChecked();
    expect(listed()).toEqual(BASIC);
    expect(readInsightsView()).toBeNull();

    await user.click(advancedSwitch());
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(listed()).toEqual(BASIC);
  });

  it("switches both ways without asking once the person has said yes", async () => {
    const user = userEvent.setup();
    writeInsightsView("advanced");
    renderStats();
    expect(listed()).toEqual(expect.arrayContaining(ADVANCED));

    await user.click(advancedSwitch());
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(listed()).toEqual(BASIC);
    expect(readInsightsView()).toBe("basic");

    await user.click(advancedSwitch());
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(listed()).toEqual(expect.arrayContaining(ADVANCED));
  });

  it("opens a link to an advanced tab in the basic view, says so, and offers the switch", async () => {
    const user = userEvent.setup();
    renderStats("/statistics/trends");
    expect(screen.getByText("Trends content")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Trends" })).toHaveAttribute("aria-selected", "true");
    expect(listed()).toEqual([...BASIC.slice(0, 3), "Skills", "Trends"]);
    expect(screen.getByText(msg("insights-statistics-view-part-of-advanced-view"))).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: msg("insights-statistics-view-show-advanced-view") }));
    expect(screen.getByRole("dialog", { name: msg("insights-statistics-view-advanced-warning-title") })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: msg("insights-statistics-view-keep-it-simple") }));

    // Once the reader leaves it, the basic view stops listing the tab.
    await user.click(screen.getByRole("tab", { name: "Overview" }));
    expect(listed()).toEqual(BASIC);
    expect(screen.queryByText(msg("insights-statistics-view-part-of-advanced-view"))).toBeNull();
  });
});
