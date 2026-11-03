import { msg } from "../../test/msg";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Demand, HiringCompany } from "../../api";
import { api } from "../../api";
import { activate } from "../../copy/activate";
import { jobFixture } from "../../test/fixtures";
import { DemandView } from "./Demand";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, api: { ...actual.api, demand: vi.fn() } };
});

/* The chart is canvas; it renders the bars it is handed as text here, so a test
   can read exactly what the view chose to draw. */
vi.mock("./charts/StatisticsCharts", () => ({
  HiringCompaniesChart: ({ bars }: { bars: { label: string; open: number }[] }) => (
    <ol aria-label="Company chart">{bars.map((b) => <li key={b.label}>{`${b.label}: ${b.open}`}</li>)}</ol>
  ),
}));

const company = (slug: string, open: number, _other = false, extra: Partial<HiringCompany> = {}): HiringCompany => ({
  company: slug, open, new_today: 0, closed_today: 0, ...extra,
});

/* `/api/demand` as the route sends it: roles, each once, by company
   and by region. Twenty companies: five picked, fifteen from the Other
   companies set, the long tail the tab must not draw one bar each for. */
const demand = (over: Partial<Demand> = {}): Demand => ({
  open_total: 160,
  new_today: 3,
  closed_today: 2,
  companies: [
    company("anthropic", 40, false, { new_today: 2, closed_today: 1 }),
    company("google", 30),
    company("openai", 20, false, { new_today: 1 }),
    ...Array.from({ length: 15 }, (_, i) => company(`tail-${String(i).padStart(2, "0")}`, 4, true)),
    company("netflix", 6),
    company("stripe", 4, false, { closed_today: 1 }),
  ],
  regions: [
    {
      key: "north_america", open: 120, region_wide: 4,
      countries: [{ key: "united_states", open: 112 }, { key: "canada", open: 9 }],
    },
    {
      key: "europe", open: 41, region_wide: 7,
      countries: Array.from({ length: 10 }, (_, i) => ({ key: ["uk", "germany", "france", "spain", "italy", "poland", "sweden", "ireland", "netherlands", "portugal"][i], open: 10 - i })),
    },
  ],
  unplaced: 3,
  employer_dated_share: 466 / 640,
  // A posting its employer dated 170 days ago that we first saw 3 days ago.
  longest_open: Array.from({ length: 8 }, (_, i) => ({
    ...jobFixture, id: 7 + i, company: "anthropic", title: i === 0 ? "Staff Product Manager, Claude" : `Role ${i}`,
    days_open: 3, listed_days: 170 - i,
  })),
  listed_over_a_year: 0,
  most_reposted: [],
  most_updated_open: [],
  ...over,
});

beforeEach(() => vi.clearAllMocks());

function renderHiring({ advanced = false } = {}) {
  return render(
    <MemoryRouter>
      <DemandView onOpen={vi.fn()} advanced={advanced} />
    </MemoryRouter>,
  );
}

it("leads with the roles open now, each once, and the recent motion", async () => {
  vi.mocked(api.demand).mockResolvedValue(demand());
  renderHiring();
  expect(await screen.findByRole("heading", { name: "160 roles open" })).toBeInTheDocument();
  expect(screen.getByText("20 companies hiring now · 3 new in the last 2 days, 2 closed today")).toBeInTheDocument();
});

/* The load lines are whole catalog messages. Built from a noun ("Loading
   hiring…"), the Spanish line would read "Cargando hiring…": the frame
   translates, the English noun inside it does not. */
describe("while the numbers load, and when they fail", () => {
  afterEach(() => activate("en"));

  it("says each state as one message, in English", async () => {
    vi.mocked(api.demand).mockReturnValue(new Promise(() => {}));
    renderHiring();
    expect(await screen.findByRole("status")).toHaveTextContent(msg("insights-demand-loading"));
  });

  it("says each state as one message, in Spanish, with no English word inside", async () => {
    await activate("es");
    vi.mocked(api.demand).mockReturnValue(new Promise(() => {}));
    const pending = renderHiring();
    const loading = await screen.findByRole("status");
    expect(loading).toHaveTextContent(msg("insights-demand-loading"));
    expect(loading).not.toHaveTextContent(/hiring/i);
    pending.unmount();

    vi.mocked(api.demand).mockRejectedValue(new Error("offline"));
    renderHiring();
    const failed = await screen.findByRole("alert");
    expect(within(failed).getByRole("heading")).toHaveTextContent(msg("insights-demand-load-failed"));
    expect(failed).not.toHaveTextContent(/hiring/i);
  });

  it("names each tile's window in the reader's words once the numbers arrive", async () => {
    await activate("es");
    vi.mocked(api.demand).mockResolvedValue(demand());
    renderHiring();
    expect(await screen.findByText(msg("insights-demand-last-2-days"))).toBeInTheDocument();
    expect(screen.getAllByText(msg("insights-demand-today"))).toHaveLength(1);
    expect(screen.queryByText("today")).toBeNull();
    expect(screen.queryByText("last 2 days")).toBeNull();
  });
});

it("draws the fifteen leaders and folds the long tail into one line that still counts it", async () => {
  vi.mocked(api.demand).mockResolvedValue(demand());
  renderHiring();
  const chart = await screen.findByRole("list", { name: "Company chart" });
  const bars = within(chart).getAllByRole("listitem").map((li) => li.textContent);
  expect(bars).toHaveLength(15);
  expect(bars[0]).toBe("Anthropic: 40");
  // 20 companies: 15 drawn, the 5 smallest folded into a sentence that keeps
  // their 4+4+4+6+4 roles; never a bar that would flatten the leaders.
  expect(screen.getByText("5 companies more hold 22 roles (14% of these roles).")).toBeInTheDocument();
});

it("asks the route for the scope it is given and names the side it shows", async () => {
  // The companies side is the scope bar's, sent to the route, which
  // ranks only that side; the view folds nothing when its companies fit.
  const scope = { side: "yours" as const, families: ["product_management"] };
  vi.mocked(api.demand).mockResolvedValue(demand({
    companies: [company("anthropic", 40), company("google", 30), company("stripe", 4)],
  }));
  render(<MemoryRouter><DemandView scope={scope} onOpen={vi.fn()} /></MemoryRouter>);
  const bars = within(await screen.findByRole("list", { name: "Company chart" })).getAllByRole("listitem");
  expect(bars.map((li) => li.textContent)).toEqual(["Anthropic: 40", "Google: 30", "stripe: 4"]);
  expect(api.demand).toHaveBeenCalledWith(scope);
  expect(screen.getByText("Your companies")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Show all/ })).toBeNull();
});

it("opens every company in a searchable sheet", async () => {
  vi.mocked(api.demand).mockResolvedValue(demand());
  renderHiring();
  fireEvent.click(await screen.findByRole("button", { name: "Show all 20 companies" }));
  const sheet = await screen.findByRole("dialog", { name: "All companies hiring" });
  expect(within(sheet).getByText("20 of 20 companies")).toBeInTheDocument();
  fireEvent.change(within(sheet).getByRole("searchbox", { name: "Find a company" }), { target: { value: "strip" } });
  expect(within(sheet).getByText("1 of 20 companies")).toBeInTheDocument();
  expect(within(sheet).getByText("stripe")).toBeInTheDocument();
  expect(within(sheet).queryByText("Anthropic")).toBeNull();
});

it("opens a region into its countries, with roles that name only the region apart", async () => {
  vi.mocked(api.demand).mockResolvedValue(demand());
  renderHiring();
  const europe = await screen.findByRole("button", { name: "Europe" });
  expect(europe).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByText("Germany")).toBeNull();

  fireEvent.click(europe);
  expect(europe).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("Germany")).toBeInTheDocument();
  expect(screen.getByText("All of Europe")).toBeInTheDocument();
  // Eight countries shown, the other two named as a count, never dropped.
  expect(screen.queryByText("Portugal")).toBeNull();
  expect(screen.getByText("and 2 more countries")).toBeInTheDocument();
  expect(screen.getByText("3 roles name no specific place, such as Remote alone.")).toBeInTheDocument();
});

it("captions a longest-open role with its listed age, and lists five", async () => {
  vi.mocked(api.demand).mockResolvedValue(demand());
  renderHiring({ advanced: true });
  const row = await screen.findByRole("link", { name: /Staff Product Manager, Claude/ });
  expect(row).toHaveTextContent("Anthropic · Listed for 170 days");
  expect(row).not.toHaveTextContent(/\bopen\b/i);
  expect(screen.getByRole("link", { name: /Role 4/ })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Role 5/ })).toBeNull();
});

it("says how many roles with a stale listing date the longest-open list left out", async () => {
  vi.mocked(api.demand).mockResolvedValue(demand({ listed_over_a_year: 95 }));
  renderHiring({ advanced: true });
  expect(await screen.findByText("95 roles listed over a year are left out: their dates read as stale.")).toBeInTheDocument();
});

it("says so when nothing is open", async () => {
  vi.mocked(api.demand).mockResolvedValue(
    demand({ open_total: 0, new_today: 0, closed_today: 0, companies: [], regions: [], unplaced: 0, longest_open: [] }),
  );
  renderHiring();
  expect(await screen.findByText("No open roles at these companies.")).toBeInTheDocument();
  expect(screen.getByText("No open roles yet.")).toBeInTheDocument();
  expect(screen.queryByText(/listed over a year/)).toBeNull();
});

it("shows a posting with only a base estimate as a base estimate, never a dash", async () => {
  // Fail-first: the lists printed fmtComp(comp_median), a bare dash here.
  const baseOnly = { ...jobFixture, id: 90, title: "Staff Engineer, Billing", company: "anthropic", listed_days: 400,
    comp_low: null, comp_high: null, comp_median: null, comp_base_median: 210_000 };
  vi.mocked(api.demand).mockResolvedValue(demand({ longest_open: [baseOnly], most_reposted: [{ ...baseOnly, id: 91, repost_count: 2 }] }));
  renderHiring({ advanced: true });
  const rows = await screen.findAllByText(msg("shared-pay-est-base", { range: "$210K" }));
  expect(rows).toHaveLength(2);
});

it("keeps the basic view to who is hiring and where, without the role lists", async () => {
  vi.mocked(api.demand).mockResolvedValue(demand({ listed_over_a_year: 95 }));
  renderHiring();
  expect(await screen.findByRole("heading", { name: /^Open roles by company/ })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Staff Product Manager, Claude/ })).toBeNull();
  expect(screen.queryByText(/listed over a year/)).toBeNull();
  expect(screen.queryByRole("heading", { name: /Reposted roles/ })).toBeNull();
  expect(screen.queryByRole("heading", { name: /Updated but never closed/ })).toBeNull();
});
