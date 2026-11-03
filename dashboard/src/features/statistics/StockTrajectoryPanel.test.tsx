import { render, screen, within, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CompTrajectory } from "../../api";
import { api } from "../../api";
import { msg } from "../../test/msg";
import { StockTrajectoryPanel } from "./StockTrajectoryPanel";

vi.mock("../../api", () => ({
  api: { compTrajectory: vi.fn() },
}));

const mock = (data: CompTrajectory) => vi.mocked(api.compTrajectory).mockResolvedValue(data);

// A package whose components sum to median_tc, as the backend guarantees.
const pkg = (
  median_tc: number,
  equity: number,
  bonus: number,
  split_source: "measured" | "heuristic" | "mixed" = "measured",
) => ({
  count: 10,
  median_tc,
  equity,
  bonus,
  base: median_tc - equity - bonus,
  equity_pct: equity / median_tc,
  split_source,
});

const base = (over: Partial<CompTrajectory> = {}): CompTrajectory => ({
  currency: "USD",
  assumptions: { bonus_pct: 0.12, equity_by_band: { senior: 0.35, staff: 0.45 } },
  overall: pkg(1_000_000, 450_000, 120_000), // base 430k
  public: [
    { company: "google", ticker: "GOOGL", equity_vehicle: "rsu", ...pkg(1_000_000, 500_000, 120_000) },
    { company: "netflix", ticker: "NFLX", equity_vehicle: "rsu", ...pkg(700_000, 140_000, 84_000) },
  ],
  private: [{ company: "openai", equity_vehicle: null, ...pkg(1_100_000, 550_000, 132_000) }],
  ...over,
});

const setSlider = (value: number) =>
  fireEvent.change(screen.getByLabelText("Stock price change percent"), {
    target: { value: String(value) },
  });

// KPI labels ("Today"/"Projected"/"Change") also appear as table column headers,
// so scope the lookup to the KPI label element.
const kpi = (label: string) =>
  screen.getByText(label, { selector: ".kpi-l" }).closest(".kpi")! as HTMLElement;

describe("StockTrajectoryPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("leads with the equity share at today's price, and the projection once the price moves", async () => {
    mock(base());
    render(<StockTrajectoryPanel />);

    // At 0% the projection is today's median again: the figure would say
    // nothing a tile does not, so it says what a move acts on.
    const hero = await screen.findByRole("heading", { level: 2 });
    expect(hero).toHaveTextContent("45% of total compensation is equity");
    expect(hero).not.toHaveTextContent(/projected/);
    expect(within(kpi("Today")).getByText("$1M")).toBeInTheDocument();
    expect(within(kpi("Change")).getByText("$0")).toBeInTheDocument();

    setSlider(-20);
    expect(await screen.findByRole("heading", { level: 2, name: /\$910K projected/ })).toBeInTheDocument();
    setSlider(0);
    expect(await screen.findByRole("heading", { level: 2, name: "45% of total compensation is equity" })).toBeInTheDocument();
  });

  it("keeps TC short on the figure and tiles and spells it out on hover", async () => {
    mock(base());
    render(<StockTrajectoryPanel />);
    await screen.findByRole("heading", { level: 2 });
    setSlider(100);
    const hero = await screen.findByRole("heading", { level: 2, name: /projected/ });
    expect(hero.querySelector("abbr")).toHaveAttribute("title", "$1.45M projected total compensation");
    expect(within(kpi("Today")).getByText("median TC").closest("abbr"))
      .toHaveAttribute("title", "median total compensation");
    expect(within(kpi("Equity share")).getByText("of TC (at risk)").closest("abbr"))
      .toHaveAttribute("title", "of total compensation (at risk)");
  });

  it("charts what a 10% move is worth at today's price, never a chart of zeros", async () => {
    mock(base());
    render(<StockTrajectoryPanel />);
    await screen.findByRole("heading", { level: 2 });

    // 10% of Netflix's $140K equity and of Google's $500K.
    expect(screen.getByText(/Netflix: \+\$14K, Google: \+\$50K/)).toBeInTheDocument();
    expect(screen.getByText("Per 10% stock move · adjust above for a scenario")).toBeInTheDocument();
    // A scenario replaces the sensitivity view with itself.
    setSlider(-50);
    // A fall reads as one, never as "$-250000".
    expect(await screen.findByText(/Google: −\$250K/)).toBeInTheDocument();
    expect(screen.queryByText(/Google: \+\$50K/)).not.toBeInTheDocument();
  });

  it("re-prices only the equity slice when the stock moves up", async () => {
    mock(base());
    render(<StockTrajectoryPanel />);
    await screen.findByRole("heading", { level: 2 });

    setSlider(100); // stock doubles

    // overall: base 430k + bonus 120k + equity 450k*(1+1.0)=900k => 1.45M
    expect(within(kpi("Projected")).getByText("$1.45M")).toBeInTheDocument();
    // Change = equity * d = 450k * 1.0 = +450k
    expect(within(kpi("Change")).getByText("+$450K")).toBeInTheDocument();
  });

  it("drops total comp when the stock falls", async () => {
    mock(base());
    render(<StockTrajectoryPanel />);
    await screen.findByRole("heading", { level: 2 });

    setSlider(-50);
    // overall change = 450k * -0.5 = -225k (rendered with a U+2212 minus)
    const change = within(kpi("Change")).getByText(/225K/);
    expect(change).toHaveTextContent(/^−\$225K$/);
    expect(change).toHaveClass("bad");
  });

  it("projects each public company independently by its own equity slice", async () => {
    mock(base());
    render(<StockTrajectoryPanel />);
    await screen.findByRole("heading", { level: 2 });

    setSlider(50); // +50%

    // Google row: equity 500k * 0.5 = +250k; projected 1.25M.
    const goog = (await screen.findByText("Google")).closest("tr")!;
    expect(within(goog).getByText("GOOGL")).toBeInTheDocument();
    expect(within(goog).getByText("$1.25M")).toBeInTheDocument();
    expect(within(goog).getByText("+$250K")).toBeInTheDocument();

    // Netflix has a thinner equity slice, so the same move adds less: 140k*0.5=+70k.
    const nflx = screen.getByRole("row", { name: /Netflix/ });
    expect(within(nflx).getByText("+$70K")).toBeInTheDocument();
  });

  it("lists private companies as illiquid and does not move them with the slider", async () => {
    mock(base());
    render(<StockTrajectoryPanel />);
    await screen.findByRole("heading", { level: 2 });
    setSlider(200);

    const openai = (await screen.findByText("OpenAI")).closest("tr")!;
    // Median TC is shown, unchanged by the scenario (no projected column here).
    expect(within(openai).getByText("$1.10M")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Why private companies do not move" }))
      .toHaveAccessibleDescription(/Pre-IPO equity is illiquid/i);
  });

  it("shows an empty state when no public roles have a comp estimate", async () => {
    mock(base({ overall: null, public: [], private: [] }));
    render(<StockTrajectoryPanel />);
    expect(
      await screen.findByText(/No open roles at public companies/i),
    ).toBeInTheDocument();
  });

  it("labels a measured split as measured, not estimated", async () => {
    mock(base());
    render(<StockTrajectoryPanel />);
    const goog = (await screen.findByText("Google")).closest("tr")!;
    expect(within(goog).getByText("Measured")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "How stock trajectory is projected" }))
      .toHaveAccessibleDescription(/measured per company and level/i);
  });

  it("labels an estimated split as estimated", async () => {
    mock(
      base({
        overall: pkg(1_000_000, 450_000, 120_000, "heuristic"),
        public: [{ company: "stripe", ticker: "STRP", equity_vehicle: "options", ...pkg(900_000, 400_000, 100_000, "heuristic") }],
        private: [],
      }),
    );
    render(<StockTrajectoryPanel />);
    const row = (await screen.findByText("stripe")).closest("tr")!;
    expect(within(row).getByText("Estimated")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "How stock trajectory is projected" }))
      .toHaveAccessibleDescription(/estimated using a 12% bonus assumption/i);
  });

  it("flags a partially-measured company as part measured", async () => {
    mock(
      base({
        overall: pkg(1_000_000, 450_000, 120_000, "mixed"),
        public: [{ company: "google", ticker: "GOOGL", equity_vehicle: "rsu", ...pkg(1_000_000, 500_000, 120_000, "mixed") }],
        private: [],
      }),
    );
    render(<StockTrajectoryPanel />);
    const goog = (await screen.findByText("Google")).closest("tr")!;
    expect(within(goog).getByText("Part measured")).toBeInTheDocument();
  });

  const SPLITS = ["measured", "mixed", "heuristic"] as const;

  it.each(SPLITS)("says a %s split the same way in the hero, its explanation and the row", async (split) => {
    mock(
      base({
        overall: pkg(1_000_000, 450_000, 120_000, split),
        public: [{ company: "google", ticker: "GOOGL", equity_vehicle: "rsu", ...pkg(1_000_000, 500_000, 120_000, split) }],
        private: [],
      }),
    );
    render(<StockTrajectoryPanel />);
    const goog = (await screen.findByText("Google")).closest("tr")!;

    const label = within(goog).getByText(msg("insights-stock-trajectory-panel-split-source", { split }));
    expect(label).toHaveAttribute("title", msg("insights-stock-trajectory-panel-split-source-explained", { split }));
    expect(document.body).toHaveTextContent(msg("insights-stock-trajectory-panel-typical-package", { split }));
    expect(screen.getByRole("button", { name: msg("insights-stock-trajectory-panel-how-stock-trajectory-is-projected") }))
      .toHaveAccessibleDescription(msg("insights-stock-trajectory-panel-stock-moves-re-price-equity", { split, bonus_pct: "12%" }));
    // The other sources' words appear nowhere: each place picks from the data, not a default.
    for (const other of SPLITS.filter((s) => s !== split)) {
      expect(document.body).not.toHaveTextContent(msg("insights-stock-trajectory-panel-typical-package", { split: other }));
      expect(within(goog).queryByText(msg("insights-stock-trajectory-panel-split-source", { split: other }))).not.toBeInTheDocument();
    }
  });

  it("shows a listed cash-election company as having no stock exposure at all", async () => {
    // Netflix: publicly traded, yet 0% equity. It must NOT move under any
    // scenario; a heuristic equity share would invent a slice and move it.
    mock(
      base({
        public: [
          {
            company: "netflix",
            ticker: "NFLX",
            equity_vehicle: "cash_election",
            ...pkg(756_250, 0, 0),
          },
        ],
        private: [],
      }),
    );
    render(<StockTrajectoryPanel />);

    const nflx = await screen.findByRole("row", { name: /Netflix/ });
    expect(within(nflx).getByText("Cash election")).toBeInTheDocument();
    expect(within(nflx).getByText("0%")).toBeInTheDocument();
    expect(within(nflx).getByText("no exposure")).toBeInTheDocument();

    // Drive the stock hard in both directions — projected TC must not budge.
    setSlider(200);
    expect(within(screen.getByRole("row", { name: /Netflix/ })).getAllByText("$756K")).toHaveLength(2);
    setSlider(-75);
    expect(within(screen.getByRole("row", { name: /Netflix/ })).getAllByText("$756K")).toHaveLength(2);
  });
});
