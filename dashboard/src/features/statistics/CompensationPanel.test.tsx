import { msg } from "../../test/msg";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CompensationStats, CompSkill } from "../../api";
import { api } from "../../api";
import { CompensationPanel } from "./CompensationPanel";

vi.mock("../../context/SyncState", () => ({
  useSyncEpoch: () => ({ notificationVersion: 0, referenceVersion: 0 }),
  useSourceSwitch: () => {},
}));
vi.mock("../../api", () => ({
  api: { compensation: vi.fn(), compTrends: vi.fn(), disclosureTrends: vi.fn() },
}));

const mock = (data: CompensationStats) => {
  vi.mocked(api.compensation).mockResolvedValue(data);
  // The embedded CompTrendChart fetches on mount; give it an empty payload.
  vi.mocked(api.compTrends).mockResolvedValue({
    dim: "overall",
    days: 30,
    reference_changes: [],
    dates: [],
    series: [],
  });
  // Same for the embedded DisclosureTrendPanel.
  vi.mocked(api.disclosureTrends).mockResolvedValue({
    dim: "overall",
    days: 30,
    basis: "base",
    dates: [],
    series: [],
    cohort: null,
  });
};

const sum = (p25: number, p50: number, p75: number, p90: number, count: number) => ({
  count,
  min: 298_053,
  max: 1_500_000,
  p25,
  p50,
  p75,
  p90,
});

const skill = (
  term: string,
  p50: number,
  premium: number,
  count: number,
): CompSkill => ({ term, p50, premium, count });

// No role priced by its base alone: the block is sent, empty.
const noBase: CompensationStats["base_estimates"] = {
  min_roles: 5, coverage: { with_base: 0, total_open: 732 }, overall: null, by_level: [], by_company: [], by_family: [],
};
// 40 roles priced by their base alone.
const someBase: CompensationStats["base_estimates"] = {
  min_roles: 5,
  coverage: { with_base: 40, total_open: 772 },
  overall: sum(180_000, 210_000, 240_000, 260_000, 40),
  by_level: [
    { level_band: "senior", ...sum(180_000, 196_000, 210_000, 220_000, 25) },
    { level_band: "staff", ...sum(230_000, 247_000, 260_000, 270_000, 15) },
  ],
  by_company: [],
  by_family: [],
};

// A full valid payload; individual tests override the slices they assert on.
const base = (over: Partial<CompensationStats> = {}): CompensationStats => ({
  currency: "USD",
  min_roles: 5,
  coverage: { with_comp: 732, total_open: 732, pct: 1.0 },
  overall: sum(306_217, 479_251, 644_468, 900_000, 732),
  histogram: [
    { lo: 200_000, hi: 400_000, count: 309 },
    { lo: 400_000, hi: 600_000, count: 148 },
  ],
  by_level: [
    { level_band: "senior", ...sum(250_000, 306_217, 340_000, 400_000, 406) },
    { level_band: "staff", ...sum(560_000, 644_468, 720_000, 820_000, 265) },
  ],
  by_company: [{ company: "openai", ...sum(700_000, 900_000, 1_000_000, 1_200_000, 58) }],
  by_family: [
    {
      family: "ml_ai_research",
      ...sum(400_000, 479_251, 600_000, 820_000, 170),
    },
  ],
  by_skill: [skill("data_pipeline", 900_000, 420_749, 17)],
  disclosed: {
    bands: [
      { company: "google", level_band: "staff", low: 262_000, high: 365_000, reqs: 18 },
      { company: "google-deepmind", level_band: "staff", low: 207_000, high: 301_000, reqs: 1 },
    ],
    reqs: 19,
    companies: 2,
    excluded: { unclear: 90, total: 0, not_usd: 0, not_yearly: 0, implausible: 1 },
    truncated: false,
  },
  disclosure: {
    overall: { open: 732, checked: 600, disclosed: 150, rate: 0.25 },
    by_company: [
      { company: "google", open: 200, checked: 200, disclosed: 160, rate: 0.8 },
      { company: "openai", open: 60, checked: 50, disclosed: 5, rate: 0.1 },
    ],
    by_level: [
      { level_band: "senior", open: 406, checked: 400, disclosed: 100, rate: 0.25 },
      { level_band: "staff", open: 265, checked: 200, disclosed: 50, rate: 0.25 },
    ],
  },
  base_estimates: noBase,
  ...over,
});

describe("CompensationPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the median hero, coverage caveat, and percentile KPIs", async () => {
    mock(base());
    render(<CompensationPanel days={30} />);

    const hero = await screen.findByRole("heading", { level: 2 });
    expect(hero).toHaveTextContent("$479K median");
    expect(screen.getByText(/732 \/ 732 open roles now · 100% coverage/)).toBeInTheDocument();
    expect(screen.getByText("Coverage")).toBeInTheDocument();
  });

  it("keeps the basic view to the median, its middle half, and pay by level, company and discipline", async () => {
    mock(base({ base_estimates: someBase }));
    render(<CompensationPanel days={30} />);

    expect(await screen.findByRole("heading", { level: 2 })).toHaveTextContent("$479K median");
    expect(screen.getByText("Coverage")).toBeInTheDocument();
    expect(screen.getByText(msg("insights-compensation-panel-middle-50"))).toBeInTheDocument();
    expect(screen.queryByText(msg("insights-compensation-panel-top-decile"))).toBeNull();
    expect(screen.getByText(msg("insights-compensation-panel-median-comp-by-level"))).toBeInTheDocument();
    expect(screen.getByText(msg("insights-compensation-panel-top-paying-companies"))).toBeInTheDocument();
    expect(screen.getByText(msg("insights-compensation-panel-median-pay-by-discipline"))).toBeInTheDocument();
    // Every other panel is the advanced view's, and asks the server nothing.
    expect(screen.queryByText(msg("insights-compensation-panel-estimated-comp-distribution"))).toBeNull();
    expect(screen.queryByRole("region", { name: msg("insights-compensation-panel-estimated-base-by-level") })).toBeNull();
    expect(screen.queryByText(msg("insights-compensation-panel-what-a-skill-adds-at"))).toBeNull();
    expect(api.compTrends).not.toHaveBeenCalled();
    expect(api.disclosureTrends).not.toHaveBeenCalled();
  });

  it("orders levels by seniority and shows each band's median and the roles it rests on", async () => {
    mock(base({ coverage: { with_comp: 671, total_open: 732, pct: 0.916 } }));
    render(<CompensationPanel days={30} />);

    const seniorRow = (await screen.findAllByText("Senior")).map((el) => el.closest(".comp-row")).find(Boolean)!;
    expect(within(seniorRow as HTMLElement).getByText("$306K")).toBeInTheDocument();
    // Every row says what it rests on: a median of one role must not pass for a level's pay.
    expect(within(seniorRow as HTMLElement).getByText("406 roles")).toBeInTheDocument();
    expect(seniorRow.getAttribute("title")).toMatch(/p25–p75 \$250K–\$340K · 406 roles/);
    expect(screen.getAllByText("Groups of 5 roles or more")).toHaveLength(3);
  });

  it("renders distribution bins and formats company + family rows", async () => {
    mock(base());
    render(<CompensationPanel days={30} advanced />);

    const bin = (await screen.findByText("$200K–$400K")).closest(".comp-hist-row")!;
    expect(within(bin as HTMLElement).getByText("309")).toBeInTheDocument();

    const coRow = screen.getByText("OpenAI").closest(".comp-row")!; // companyName() applied
    expect(within(coRow as HTMLElement).getByText("$900K")).toBeInTheDocument();
    expect(within(coRow as HTMLElement).getByText("58 roles")).toBeInTheDocument();

    const famRow = screen.getByText("ML / AI Research").closest(".comp-row")!;
    expect(within(famRow as HTMLElement).getByText("$479K")).toBeInTheDocument();
  });

  it("shows companies and disciplines as an equal pair, the same number of rows each", async () => {
    const co = (i: number) => ({ company: `co-${i}`, ...sum(1, 900_000 - i, 2, 3, 10) });
    const fam = (i: number) => ({ family: `f${i}`, family_display: `Family ${i}`, ...sum(1, 800_000 - i, 2, 3, 10) });
    mock(base({ by_company: Array.from({ length: 15 }, (_, i) => co(i)), by_family: Array.from({ length: 11 }, (_, i) => fam(i)) }));
    render(<CompensationPanel days={30} />);

    const companies = (await screen.findByRole("heading", { name: "Top paying companies" })).closest(".panel")!;
    const families = screen.getByRole("heading", { name: "Median estimated total compensation by discipline" }).closest(".panel")!;
    expect(companies.querySelectorAll(".comp-row")).toHaveLength(8);
    expect(families.querySelectorAll(".comp-row")).toHaveLength(8);
    expect(companies.parentElement).toBe(families.parentElement);
  });

  it("says what a skill adds at the same level, signed, with the roles behind it", async () => {
    mock(
      base({
        by_skill: [
          skill("gcp", 780_000, 131_597, 31),
          skill("cpp", 420_000, -149_585, 26),
        ],
      }),
    );
    render(<CompensationPanel days={30} advanced />);

    const up = (await screen.findByText("GCP")).closest(".comp-row")!;
    expect(within(up as HTMLElement).getByText("+$132K")).toHaveClass("pay-premium");
    expect(within(up as HTMLElement).getByText("31 roles")).toBeInTheDocument();
    // A skill that pays less is shown as less, never dropped and never as a gain.
    const down = screen.getByText("C++").closest(".comp-row")!;
    expect(within(down as HTMLElement).getByText("−$150K")).not.toHaveClass("pay-premium");
    expect(down.querySelector(".bar-fill")).toHaveClass("is-below");
    expect(screen.getByRole("button", { name: /How a skill's compensation difference is measured/ }))
      .toHaveAccessibleDescription(/which employers ask for the skill/i);
  });

  it("reports roles priced by their base alone apart from the totals, labelled as base", async () => {
    // A base is never drawn on the totals' axis, where it
    // would read as a lower-paying role.
    mock(base({ base_estimates: someBase }));
    render(<CompensationPanel days={30} advanced />);
    const panel = await screen.findByRole("region", { name: msg("insights-compensation-panel-estimated-base-by-level") });
    expect(panel).toHaveTextContent(msg("insights-compensation-panel-base-only-lead", { count: 40 }));
    expect(within(panel).getByText("Senior")).toBeInTheDocument();
    expect(within(panel).getByText("$196K")).toBeInTheDocument();
    // The totals' level chart is unchanged: no base row joined it.
    const totals = screen.getByText(msg("insights-compensation-panel-median-comp-by-level")).closest(".panel")!;
    expect(within(totals as HTMLElement).queryByText("$196K")).toBeNull();
  });

  it("shows no base panel when no role is priced by its base alone", async () => {
    mock(base());
    render(<CompensationPanel days={30} />);
    await screen.findByText(msg("insights-compensation-panel-median-comp-by-level"));
    expect(screen.queryByRole("region", { name: msg("insights-compensation-panel-estimated-base-by-level") })).toBeNull();
  });

  it("still reports base-only roles when no role has a total estimate, in the basic view too", async () => {
    mock(base({ coverage: { with_comp: 0, total_open: 40, pct: 0 }, overall: null, histogram: [], by_level: [],
      by_company: [], by_family: [], by_skill: [], base_estimates: someBase }));
    render(<CompensationPanel days={30} />);
    expect(await screen.findByText(/No open roles with a compensation estimate/i)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: msg("insights-compensation-panel-estimated-base-by-level") }))
      .toBeInTheDocument();
  });

  it("shows an empty state when no open role has a comp estimate", async () => {
    mock(
      base({
        coverage: { with_comp: 0, total_open: 0, pct: 0 },
        overall: null,
        histogram: [],
        by_level: [],
        by_company: [],
        by_family: [],
        by_skill: [],
      }),
    );
    render(<CompensationPanel days={30} />);
    expect(await screen.findByText(/No open roles with a compensation estimate/i)).toBeInTheDocument();
  });

  it("describes the roles open now: the window moves the trend charts, never this population", async () => {
    // Keeping roles FIRST SEEN in the window would make 7d/30d change WHICH
    // roles are summarised, not the period: with most open postings first
    // seen in the last 30 days, "30d" would be all-time. The window moves the
    // two trend charts on this tab.
    mock(base());
    const { rerender } = render(<CompensationPanel days={30} advanced />);
    await screen.findByRole("heading", { level: 2 });
    expect(screen.getByText(/732 \/ 732 open roles now · 100% coverage/)).toBeInTheDocument();
    await vi.waitFor(() => expect(api.compTrends).toHaveBeenLastCalledWith("overall", 30, undefined));

    rerender(<CompensationPanel days={7} advanced />);
    await vi.waitFor(() => expect(api.compTrends).toHaveBeenLastCalledWith("overall", 7, undefined));
    expect(api.compensation).toHaveBeenCalledTimes(1);
    expect(api.compensation).toHaveBeenCalledWith(undefined);
  });

  it("says the estimate is imputed rather than posted, and never claims otherwise", async () => {
    mock(base());
    render(<CompensationPanel days={30} />);
    await screen.findByRole("heading", { level: 2 });

    expect(screen.getByRole("button", { name: "How compensation is estimated" }))
      .toHaveAccessibleDescription(/imputed from a company \+ level \+ family lookup/i);
    // No posted range reaches comp_median, so the copy must never claim the
    // estimate blends posted ranges in.
    expect(screen.queryByText(/blend posted ranges/i)).not.toBeInTheDocument();
  });

  it("draws published bands a row per level and colours only the employer picked", async () => {
    mock(
      base({
        disclosed: {
          bands: [
            { company: "google", level_band: "senior", low: 200_000, high: 280_000, reqs: 9 },
            { company: "google", level_band: "staff", low: 262_000, high: 365_000, reqs: 18 },
            { company: "google-deepmind", level_band: "staff", low: 207_000, high: 301_000, reqs: 1 },
            { company: "apple", level_band: "staff", low: 240_000, high: 340_000, reqs: 4 },
            { company: "apple", level_band: "staff", low: 300_000, high: 420_000, reqs: 2 },
          ],
          reqs: 34, companies: 3,
          excluded: { unclear: 90, total: 0, not_usd: 0, not_yearly: 0, implausible: 1 },
          truncated: false,
        },
      }),
    );
    const user = userEvent.setup();
    render(<CompensationPanel days={30} advanced />);

    const rows = within(await screen.findByRole("list", { name: "Posted base salary ranges by level" }));
    // One row per level, never one per band: four bands, two rows.
    expect(rows.getAllByRole("listitem")).toHaveLength(2);
    const staff = rows.getByRole("img", { name: /^Staff: 4 ranges from 3 employers/ });
    // One vote per band: the median of [207K, 240K, 262K, 300K] floors, not Google's 18 reqs.
    expect(staff).toHaveAccessibleName(/median \$251K to/);
    expect(staff.querySelectorAll(".pay-band[data-chosen]")).toHaveLength(0);
    expect(screen.getByText(/5 ranges · 3 employers/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Filter by/ }));
    await user.click(await screen.findByRole("option", { name: /Google DeepMind/ }));
    expect(staff).toHaveAccessibleName(/Google DeepMind: \$207K to \$301K/);
    expect(staff.querySelectorAll(".pay-band[data-chosen]")).toHaveLength(1);
    // A level the employer publishes nothing at says so, rather than showing the market.
    expect(rows.getByRole("img", { name: /^Senior/ })).toHaveAccessibleName(/posts no range at this level/);
    expect(rows.getByText("No range")).toBeInTheDocument();

    // Several bands at one level read as their span and count; each band is still said.
    await user.click(screen.getByRole("button", { name: /^Filter by/ }));
    await user.click(await screen.findByRole("option", { name: /Apple/ }));
    expect(rows.getAllByRole("listitem")[1]).toHaveTextContent("$240K–$420K · 2 ranges");
    expect(staff).toHaveAccessibleName(/Apple: \$240K to \$340K, \$300K to \$420K/);

    // The roles left off the base-pay scale are still said.
    expect(screen.getByRole("button", { name: "About posted ranges" }))
      .toHaveAccessibleDescription(/90 more roles post a range/i);
  });
});
