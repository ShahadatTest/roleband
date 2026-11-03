import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DisclosureRates, DisclosureTrends } from "../../api";
import { api } from "../../api";
import { DisclosureRatePanel, DisclosureTrendPanel } from "./DisclosurePanel";

vi.mock("../../api", () => ({ api: { disclosureTrends: vi.fn() } }));

// The chart itself is an echarts canvas; these specs assert the copy and the
// wiring around it. The option builders are unit-tested in charts/disclosure.test.ts.
vi.mock("./charts/EChart", () => ({
  EChart: ({ ariaLabel, summary }: { ariaLabel: string; summary: string }) => (
    <figure>
      <div role="img" aria-label={ariaLabel} />
      <figcaption>{summary}</figcaption>
    </figure>
  ),
}));

const rates = (over: Partial<DisclosureRates> = {}): DisclosureRates => ({
  overall: { open: 732, checked: 600, disclosed: 150, rate: 0.25 },
  by_company: [
    { company: "google", open: 200, checked: 200, disclosed: 160, rate: 0.8 },
    { company: "openai", open: 60, checked: 50, disclosed: 5, rate: 0.1 },
  ],
  by_level: [
    { level_band: "senior", open: 406, checked: 400, disclosed: 100, rate: 0.25 },
    { level_band: "staff", open: 265, checked: 200, disclosed: 50, rate: 0.25 },
  ],
  ...over,
});

const trends = (over: Partial<DisclosureTrends> = {}): DisclosureTrends => ({
  dim: "overall",
  days: 90,
  basis: "base",
  dates: ["2026-07-20", "2026-07-21"],
  series: [
    {
      key: "",
      
      checked: 600,
      disclosed: 150,
      points: [
        {
          date: "2026-07-20", open: 700, checked: 560, disclosed: 120, rate: 0.214,
          bands: 4, reqs: 30, low_p50: 200_000, high_p50: 300_000,
        },
        {
          date: "2026-07-21", open: 732, checked: 600, disclosed: 150, rate: 0.25,
          bands: 5, reqs: 34, low_p50: 210_000, high_p50: 310_000,
        },
      ],
    },
  ],
  cohort: null,
  ...over,
});

const mockTrends = (data: DisclosureTrends = trends()) =>
  vi.mocked(api.disclosureTrends).mockResolvedValue(data);

describe("DisclosureRatePanel", () => {
  it("headlines the rate against the checked roles, not every open role", async () => {
    render(<DisclosureRatePanel rates={rates()} />);

    expect(screen.getByText("25% of 600 checked roles post a range")).toBeInTheDocument();
  });

  it("says the unread roles are backlog rather than employer silence", async () => {
    // 732 open, 600 checked. Reporting 150/732 = 20% would blame employers for our
    // own extraction queue, so the panel must name the gap explicitly.
    render(<DisclosureRatePanel rates={rates()} />);

    expect(
      screen.getByText(/132 of 732 open roles have not been checked/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/rather than counted as employers posting nothing/i))
      .toBeInTheDocument();
  });

  it("omits the backlog note when every open role has been checked", () => {
    render(
      <DisclosureRatePanel
        rates={rates({ overall: { open: 600, checked: 600, disclosed: 150, rate: 0.25 } })}
      />,
    );
    expect(screen.queryByText(/have not been checked/i)).not.toBeInTheDocument();
  });

  it("re-renders the chart when the grouping toggles", async () => {
    render(<DisclosureRatePanel rates={rates()} />);

    expect(
      screen.getByRole("img", { name: /post a range, by employer/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Google: 80%, 160 of 200 roles/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "By level" }));

    expect(screen.getByRole("img", { name: /post a range, by level/i })).toBeInTheDocument();
    expect(screen.getByText(/Senior: 25%, 100 of 400 roles/)).toBeInTheDocument();
  });

  it("shows an empty state instead of a chart when nothing has been checked", () => {
    render(
      <DisclosureRatePanel
        rates={{
          overall: { open: 40, checked: 0, disclosed: 0, rate: null },
          by_company: [{ company: "google", open: 40, checked: 0, disclosed: 0, rate: null }],
          by_level: [],
        }}
      />,
    );

    expect(screen.getByText(/no open roles have been checked/i)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

describe("DisclosureTrendPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders both the rate trend and the published-band trend", async () => {
    mockTrends();
    render(<DisclosureTrendPanel days={90} minRoles={5} />);

    expect(
      await screen.findByRole("img", { name: /post a range over time/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /median posted base salary range over time/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Market: 25% of 600 checked roles post a range \(from 21%\)/))
      .toBeInTheDocument();
  });

  it("draws both market charts from one market-wide request", async () => {
    mockTrends();
    render(<DisclosureTrendPanel days={90} minRoles={5} />);
    await screen.findByRole("img", { name: /post a range over time/i });
    await screen.findByRole("img", { name: /median posted base salary range over time/i });

    expect(api.disclosureTrends).toHaveBeenCalledTimes(1);
    expect(api.disclosureTrends).toHaveBeenCalledWith("overall", 90, undefined);
  });

  it("returns to the market grouping without asking again", async () => {
    mockTrends();
    render(<DisclosureTrendPanel days={90} minRoles={5} />);
    await screen.findByRole("img", { name: /post a range over time/i });
    await userEvent.click(screen.getByRole("button", { name: "By employer" }));
    await waitFor(() =>
      expect(api.disclosureTrends).toHaveBeenCalledWith("company", 90, undefined),
    );

    vi.mocked(api.disclosureTrends).mockClear();
    await userEvent.click(screen.getByRole("button", { name: "Market" }));

    expect(
      await screen.findByText(/Market: 25% of 600 checked roles post a range \(from 21%\)/),
    ).toBeInTheDocument();
    expect(api.disclosureTrends).not.toHaveBeenCalled();
  });

  it("re-fetches the rate trend when the breakdown changes, keeping the band trend market-wide", async () => {
    mockTrends();
    render(<DisclosureTrendPanel days={90} minRoles={5} />);
    await screen.findByRole("img", { name: /post a range over time/i });

    vi.mocked(api.disclosureTrends).mockClear();
    await userEvent.click(screen.getByRole("button", { name: "By employer" }));

    // A median of per-company medians is not a median, so the band chart stays
    // pinned to the market grain no matter what the rate breakdown is set to.
    await waitFor(() =>
      expect(api.disclosureTrends).toHaveBeenCalledWith("company", 90, undefined),
    );
    expect(api.disclosureTrends).toHaveBeenCalledTimes(1);
  });

  it("names the fixed cohort beside a market line that moved with the company set", async () => {
    const market = trends().series[0];
    const fixed = {
      ...market, key: "cohort", display: "Same companies",
      points: market.points.map((p) => ({ ...p, rate: 0.4 })),
    };
    mockTrends(trends({ series: [market, fixed], cohort: { since: "2026-07-20", companies: 11 } }));
    render(<DisclosureTrendPanel days={90} minRoles={5} />);

    expect(await screen.findByText(/follows only the 11 read on 2026-07-20/)).toBeInTheDocument();
    expect(screen.getByText(/Same companies: 40% of 600 checked roles post a range/)).toBeInTheDocument();
  });

  it("leaves out a same-companies line resting on fewer roles than every pay figure needs", async () => {
    const market = trends().series[0];
    const fixed = {
      ...market, key: "cohort", display: "Same companies", checked: 4, disclosed: 4,
      points: market.points.map((p) => ({ ...p, checked: 4, disclosed: 4, rate: 1 })),
    };
    mockTrends(trends({ series: [market, fixed], cohort: { since: "2026-10-12", companies: 1 } }));
    render(<DisclosureTrendPanel days={90} minRoles={5} />);

    expect(await screen.findByText(/Market: 25% of 600 checked roles post a range/)).toBeInTheDocument();
    expect(screen.queryByText(/Same companies/)).not.toBeInTheDocument();
    expect(screen.queryByText(/follows only the 1 read/)).not.toBeInTheDocument();
  });

  it("says nothing of a cohort when the company set never changed", async () => {
    mockTrends();
    render(<DisclosureTrendPanel days={90} minRoles={5} />);
    await screen.findByRole("img", { name: /post a range over time/i });
    expect(screen.queryByText(/Same companies/)).not.toBeInTheDocument();
  });

  it("warns that a single-day history is not yet a trend", async () => {
    mockTrends(trends({ dates: ["2026-07-21"] }));
    render(<DisclosureTrendPanel days={90} minRoles={5} />);

    expect(await screen.findAllByText(/history is still accruing/i)).not.toHaveLength(0);
  });

  it("shows an empty state for the band chart when no base band was ever posted", async () => {
    mockTrends(
      trends({
        series: [
          {
            key: "", checked: 600, disclosed: 150,
            points: [
              {
                date: "2026-07-21", open: 732, checked: 600, disclosed: 150, rate: 0.25,
                bands: 0, reqs: 0, low_p50: null, high_p50: null,
              },
            ],
          },
        ],
      }),
    );
    render(<DisclosureTrendPanel days={90} minRoles={5} />);

    // The rate still charts — employers disclosed, just never on a base-pay basis.
    expect(
      await screen.findByRole("img", { name: /post a range over time/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/no posted base salary range recorded yet/i)).toBeInTheDocument();
  });

  it("surfaces a failed fetch with a retry instead of an empty chart", async () => {
    vi.mocked(api.disclosureTrends).mockRejectedValue(
      new Error("boom"),
    );
    render(<DisclosureTrendPanel days={90} minRoles={5} />);

    expect(await screen.findAllByRole("button", { name: /try again/i })).not.toHaveLength(0);
    expect(screen.getAllByText(/couldn't load/i)).not.toHaveLength(0);
  });
});
