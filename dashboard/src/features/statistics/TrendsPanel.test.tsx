import { msg } from "../../test/msg";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SkillTrends } from "../../api";
import { api } from "../../api";
import { TrendsPanel } from "./TrendsPanel";

vi.mock("../../api", () => ({
  api: { skillTrends: vi.fn() },
}));

const mockTrends = (data: SkillTrends) =>
  vi.mocked(api.skillTrends).mockResolvedValue(data);

describe("TrendsPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders one sparkline row per skill with current value and signed delta", async () => {
    mockTrends({
      days: 90,
      dates: ["2026-07-11", "2026-07-12"],
      series: [
        {
          term: "python",
          
          current: 12,
          delta: 4,
          current_share: 0.12,
          share_delta: 0.04,
          points: [
            { date: "2026-07-11", job_count: 8, share: 0.08 },
            { date: "2026-07-12", job_count: 12, share: 0.12 },
          ],
        },
        {
          term: "rust",
          
          current: 3,
          delta: -2,
          current_share: 0.03,
          share_delta: -0.02,
          points: [
            { date: "2026-07-11", job_count: 5, share: 0.05 },
            { date: "2026-07-12", job_count: 3, share: 0.03 },
          ],
        },
      ],
      set_changes: [],
    });

    render(<TrendsPanel days={90} />);

    expect(await screen.findByRole("img", { name: "Skill demand trends" })).toBeInTheDocument();
    const pyRow = (await screen.findByText("Python")).closest(".trend-row")!;
    // The ledger reads shares of the day's skill mentions, not counts.
    expect(within(pyRow as HTMLElement).getByText("12.0%")).toBeInTheDocument();
    const pyDelta = pyRow.querySelector(".trend-delta")!;
    expect(pyDelta).toHaveTextContent("+4.0");
    expect(pyDelta.className).toContain("up");
    // A two-point series must draw a real polyline (a move + a line command).
    const pyPath = pyRow.querySelector(".trend-line")!.getAttribute("d")!;
    expect(pyPath).toMatch(/^M/);
    expect(pyPath).toContain("L");

    const rustRow = screen.getByText("Rust").closest(".trend-row")!;
    const rustDelta = rustRow.querySelector(".trend-delta")!;
    expect(rustDelta).toHaveTextContent("-2.0");
    expect(rustDelta.className).toContain("down");
  });

  it("shows the accruing-history note when only one snapshot exists", async () => {
    mockTrends({
      days: 30,
      dates: ["2026-07-13"],
      series: [
        {
          term: "python",
          
          current: 9,
          delta: 0,
          current_share: 0.09,
          share_delta: 0,
          points: [{ date: "2026-07-13", job_count: 9, share: 0.09 }],
        },
      ],
      set_changes: [],
    });

    render(<TrendsPanel days={30} />);

    expect(await screen.findByText(/History is still accruing/i)).toBeInTheDocument();
    // A single sample renders a flat baseline: a move-to then one horizontal line
    // segment whose start and end share the same y (backreference \1), no bend.
    const path = screen.getByText("Python").closest(".trend-row")!
      .querySelector(".trend-line")!
      .getAttribute("d")!;
    expect(path).toMatch(/^M0,([\d.]+) L100,\1$/);
  });

  it("renders an empty state when there is no skill history", async () => {
    mockTrends({ days: 90, dates: [], series: [], set_changes: [] });
    render(<TrendsPanel days={90} />);
    expect(await screen.findByText(/No skill history yet/i)).toBeInTheDocument();
  });

  it("shows a visible request error and recovers when retried", async () => {
    const user = userEvent.setup();
    const request = vi.mocked(api.skillTrends);
    request
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ days: 30, dates: [], series: [], set_changes: [] });

    render(<TrendsPanel days={30} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(msg("insights-trends-panel-load-failed"));
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText(/No skill history yet/i)).toBeInTheDocument();
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("names the days the measured set changed, so a step is not read as demand", async () => {
    // When a set of companies joins, every skill's count jumps; its share of
    // the day's mentions does not.
    mockTrends({
      days: 30, dates: ["2026-10-01", "2026-10-03"], set_changes: ["2026-10-03"],
      series: [{
        term: "machine_learning", current: 634, delta: 580, current_share: 0.07, share_delta: 0.001,
        points: [{ date: "2026-10-01", job_count: 54, share: 0.069 }, { date: "2026-10-03", job_count: 634, share: 0.07 }],
      }],
    });
    render(<TrendsPanel days={30} />);
    expect(await screen.findByText(/What is measured changed on Oct 3/)).toBeInTheDocument();
    const row = screen.getByText("Machine Learning", { selector: ".trend-name" }).closest(".trend-row") as HTMLElement;
    expect(row).toHaveTextContent("7.0%");
    expect(row).not.toHaveTextContent("580");
    // The window's two ends measured different sets, so no change is
    // stated: not in the ledger, and not in the chart's spoken summary.
    expect(row.querySelector(".trend-delta")).toBeNull();
    expect(screen.queryByText("Δ")).toBeNull();
    expect(screen.queryByText(/points/)).toBeNull();
    expect(screen.getByText(/Machine Learning: 7% of mentions/)).toBeInTheDocument();
  });
});
