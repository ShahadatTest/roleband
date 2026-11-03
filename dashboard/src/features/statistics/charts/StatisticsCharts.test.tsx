import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  ClusterLandscapeChart,
  HiringCompaniesChart,
  OverlapHeatmapChart,
  OverviewSignalChart,
  SkillTrendChart,
  SkillsConstellationChart,
  TrajectoryShockChart,
  VelocityFlowChart,
} from "./StatisticsCharts";

describe("StatisticsCharts", () => {
  it("exposes a named visualization and exact text summary for every statistics tab", () => {
    render(
      <>
        <OverviewSignalChart skills={[{ term: "python", category: "language", job_count: 12 }]} />
        <HiringCompaniesChart bars={[
          { label: "Google", open: 20, fresh: 3, closed: 2 },
          { label: "1,074 companies more", open: 2_412, fresh: 9, closed: 4 },
        ]} />
        <VelocityFlowChart companies={[{
          company: "google", open: 20, opened: 3, updated: 5, reposted: 2, closed: 2,
          median_days_open: 18, median_observed_listing_duration_days: 31,
        }]} />
        <TrajectoryShockChart companies={[{
          company: "google", ticker: "GOOGL", equity_vehicle: "rsu", count: 8, median_tc: 620_000,
          base: 230_000, bonus: 40_000, equity: 350_000, equity_pct: 0.56,
          split_source: "measured" as const,
        }]} priceChange={0.25} />
        <SkillsConstellationChart skills={[{
          term: "python", category: "language", job_count: 12,
          share: 0.4, market_share: 0.1, lift: 4, distinctiveness: 5.2,
        }]} />
        <SkillTrendChart
          dates={["2026-07-12", "2026-07-13"]}
          series={[{
            term: "python", current: 12, delta: 2, current_share: 0.12, share_delta: 0.02,
            points: [
              { date: "2026-07-12", job_count: 10, share: 0.1 },
              { date: "2026-07-13", job_count: 12, share: 0.12 },
            ],
          }]}
        />
        <OverlapHeatmapChart data={{
          min_jobs: 2,
          companies: [
            { company: "google", skill_count: 20, open: 30 },
            { company: "openai", skill_count: 18, open: 12 },
          ],
          pairs: [{ a: "google", b: "openai", shared: 8, union: 30, similarity: 0.27, top_shared: ["python"] }],
        }} />
        <ClusterLandscapeChart
          clusters={[{
            id: 1, family_hint: "engineering",
            size: 14,
            top_terms: [{ term: "python", weight: 0.9 }],
            companies: { google: 14 },
          }]}
          onSelect={vi.fn()}
        />
      </>,
    );

    const names = [
      "Market demand field",
      "Open roles by company",
      "Hiring flow by company",
      "Equity shockwave by company",
      "What sets these roles apart",
      "Skill demand trends",
      "Cross-company skill overlap heatmap",
      "Role cluster landscape",
    ];
    for (const name of names) {
      expect(screen.getByRole("img", { name })).toBeInTheDocument();
    }

    expect(screen.getAllByText(/Python: 12/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Python: 40% of these roles, ×4 the market/)).toBeInTheDocument();
    // The company chart draws the rows it is given, the folded rest among them.
    expect(screen.getByText(/Google: 20 open, 3 new, 2 closed; 1,074 companies more: 2,412 open/)).toBeInTheDocument();
    // A cluster is named by its strongest skills.
    expect(screen.getByText("Python: 14 roles")).toBeInTheDocument();
    expect(screen.getByText(/Google and OpenAI: 27%/)).toBeInTheDocument();
  });
});
