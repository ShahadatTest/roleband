import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CompTrends } from "../../api";
import { api } from "../../api";
import { CompTrendChart } from "./CompTrendChart";
import { msg } from "../../test/msg";

vi.mock("../../api", () => ({
  api: { compTrends: vi.fn() },
}));
vi.mock("../../context/SyncState", () => ({ useSyncEpoch: () => ({ notificationVersion: 0, referenceVersion: 0 }) }));

const compTrends = vi.mocked(api.compTrends);
const mock = (data: CompTrends) => compTrends.mockResolvedValue(data);

const pt = (date: string, p50: number) => ({
  date,
  p25: p50 - 50_000,
  p50,
  p75: p50 + 50_000,
  p90: p50 + 100_000,
});

const overallMulti = (): CompTrends => ({
  dim: "overall",
  days: 90, reference_changes: [],
  dates: ["2026-07-10", "2026-07-11", "2026-07-12"],
  series: [
    {
      key: "",
      
      count: 700,
      points: [pt("2026-07-10", 460_000), pt("2026-07-11", 470_000), pt("2026-07-12", 480_000)],
    },
  ],
});

describe("CompTrendChart", () => {
  beforeEach(() => vi.clearAllMocks());

  it("fetches the selected dim and switches when the toggle is clicked", async () => {
    mock(overallMulti());
    render(<CompTrendChart days={90} />);

    // Initial fetch is the overall (market) breakdown at the given period.
    await screen.findByText("Total compensation over time");
    expect(compTrends).toHaveBeenCalledWith("overall", 90, undefined);

    await userEvent.click(screen.getByRole("button", { name: "By company" }));
    expect(compTrends).toHaveBeenCalledWith("company", 90, undefined);
  });

  it("draws a median line and a p25–p75 band for a single multi-point series", async () => {
    mock(overallMulti());
    const { container } = render(<CompTrendChart days={90} />);

    await screen.findByText("Total compensation over time");
    const line = container.querySelector(".comp-trend-line");
    expect(line?.getAttribute("d")).toMatch(/^M/);
    const band = container.querySelector(".comp-trend-band");
    expect(band?.getAttribute("d")).toBeTruthy();
    expect(band?.getAttribute("d")).toContain("Z"); // closed polygon
  });

  it("draws one line per series with a legend and no band for a breakdown", async () => {
    mock({
      dim: "company",
      days: 90, reference_changes: [],
      dates: ["2026-07-10", "2026-07-11"],
      series: [
        { key: "google", count: 180, points: [pt("2026-07-10", 640_000), pt("2026-07-11", 650_000)] },
        { key: "openai", count: 58, points: [pt("2026-07-10", 890_000), pt("2026-07-11", 900_000)] },
      ],
    });
    const { container } = render(<CompTrendChart days={90} />);

    await screen.findByText("Total compensation over time");
    expect(container.querySelectorAll(".comp-trend-line")).toHaveLength(2);
    // Band is only drawn for a single series.
    expect(container.querySelector(".comp-trend-band")).toBeNull();
    // Legend formats company slugs via companyName().
    expect(screen.getByText("Google")).toBeInTheDocument();
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
  });

  it("shows an accruing-history note when only one date exists", async () => {
    mock({
      dim: "overall",
      days: 90, reference_changes: [],
      dates: ["2026-07-13"],
      series: [{ key: "", count: 700, points: [pt("2026-07-13", 480_000)] }],
    });
    render(<CompTrendChart days={90} />);
    expect(await screen.findByText(/History is still accruing/i)).toBeInTheDocument();
  });

  it("shows an empty state when there is no comp history", async () => {
    mock({ dim: "overall", days: 90, reference_changes: [], dates: [], series: [] });
    render(<CompTrendChart days={90} />);
    expect(await screen.findByText(/No compensation history yet/i)).toBeInTheDocument();
  });
});


describe("CompTrendChart reference markers (plugin plan P12)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("marks a reference change at its day and says the step is a change of data", async () => {
    mock({
      ...overallMulti(),
      reference_changes: [{ id: 7, at: "2026-07-11T03:20:00Z", jobs: 412, moved: 37, gained: 5, lost: 2, companies: 6 }],
    });
    render(<CompTrendChart days={90} />);
    expect(await screen.findAllByTestId("comp-trend-marker")).toHaveLength(1);
    expect(screen.getByTestId("comp-trend-reference-note")).toHaveTextContent(
      msg("insights-comp-trend-chart-reference-changed", { count: 1 }),
    );
  });

  it("draws no marker and no note when nothing changed", async () => {
    mock(overallMulti());
    render(<CompTrendChart days={90} />);
    await screen.findByRole("img");
    expect(screen.queryByTestId("comp-trend-marker")).toBeNull();
    expect(screen.queryByTestId("comp-trend-reference-note")).toBeNull();
  });
});
