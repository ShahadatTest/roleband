import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { api } from "../../api";
import { overviewFixture } from "../../test/fixtures";
import { OverviewPanel } from "./OverviewPanel";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, api: { ...actual.api, statisticsOverview: vi.fn() } };
});

vi.mock("./charts/StatisticsCharts", () => ({ OverviewSignalChart: () => null }));

/* "Open the longest" names postings, so each reads its own listed age
   (`listed_days`), the age its Board row shows; never "N days open"
   from our first sighting. Three rows, beside the three largest groups,
   in the advanced view. */
it("captions each role open the longest with its listed age", async () => {
  vi.mocked(api.statisticsOverview).mockResolvedValue({
    ...overviewFixture,
    longest_open: [
      { id: 7, title: "Staff Product Manager, Claude", company: "anthropic", listed_days: 170 },
      { id: 8, title: "Engineering Manager, Search", company: "google", listed_days: 120 },
      { id: 9, title: "Director, Payments", company: "stripe", listed_days: 0 },
    ],
  });
  render(
    <MemoryRouter>
      <OverviewPanel days={30} onOpen={vi.fn()} advanced />
    </MemoryRouter>,
  );

  const row = await screen.findByRole("link", { name: /Staff Product Manager, Claude/ });
  expect(row).toHaveTextContent("Anthropic · Listed for 170 days");
  expect(row).not.toHaveTextContent(/\bopen\b/i);
  expect(screen.getByRole("link", { name: /Director, Payments/ })).toHaveTextContent("Listed today");
});

it("leads with the window's motion and never draws the top skills twice", async () => {
  vi.mocked(api.statisticsOverview).mockResolvedValue({
    ...overviewFixture,
    kpis: { ...overviewFixture.kpis, new_count: 494, closed_count: 217, first_scan_count: 1867, open_total: 3192 },
    top_skills: [{ term: "roadmap", category: "process", job_count: 1435 }],
  });
  render(
    <MemoryRouter>
      <OverviewPanel days={30} onOpen={vi.fn()} />
    </MemoryRouter>,
  );
  expect(await screen.findByRole("heading", { level: 2, name: "494 opened · 217 closed" })).toBeInTheDocument();
  expect(screen.getByText("Overview", { selector: ".eyebrow" })).toBeInTheDocument();
  // The roles already listed at a company's first scan say when the radar
  // first looked, not what the market did: no tile and no sentence.
  expect(screen.queryByText("1,867")).toBeNull();
  expect(screen.queryByText(/first scanned/)).toBeNull();
  // The chart is the one place the top skills are drawn; the brief names the
  // first of them in a sentence.
  expect(screen.queryByRole("heading", { name: "Most in-demand skills" })).toBeNull();
  const drawn = screen.getAllByText(/Roadmapping/).filter((el) => !el.closest(".insight-hero"));
  expect(drawn).toHaveLength(1);
  expect(screen.getByText(/Top skill: Roadmapping \(1,435 roles\)\./)).toBeInTheDocument();
});

it("keeps the basic view to the window's motion and the top skills", async () => {
  vi.mocked(api.statisticsOverview).mockResolvedValue({
    ...overviewFixture,
    longest_open: [{ id: 7, title: "Staff Product Manager, Claude", company: "anthropic", listed_days: 170 }],
    top_clusters: [{ id: 1, family_hint: "product_management", terms: ["llm"], size: 88 }],
  });
  const { unmount } = render(
    <MemoryRouter>
      <OverviewPanel days={30} onOpen={vi.fn()} />
    </MemoryRouter>,
  );
  expect(await screen.findByRole("heading", { level: 2 })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Largest groups" })).toBeNull();
  expect(screen.queryByRole("link", { name: /Staff Product Manager, Claude/ })).toBeNull();
  expect(screen.queryByText(/Largest group:/)).toBeNull();
  unmount();

  render(
    <MemoryRouter>
      <OverviewPanel days={30} onOpen={vi.fn()} advanced />
    </MemoryRouter>,
  );
  expect(await screen.findByRole("heading", { name: "Largest groups" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Staff Product Manager, Claude/ })).toBeInTheDocument();
  expect(screen.getByText(/Largest group: LLMs \(88\)/)).toBeInTheDocument();
});
