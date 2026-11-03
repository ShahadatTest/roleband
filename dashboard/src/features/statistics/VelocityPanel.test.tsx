import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { VelocityStats } from "../../api";
import { api } from "../../api";
import { VelocityPanel } from "./VelocityPanel";

vi.mock("../../api", () => ({
  api: { velocity: vi.fn() },
}));

const mock = (data: VelocityStats) =>
  vi.mocked(api.velocity).mockResolvedValue(data);

const AGING = [
  { lo: 0, hi: 7, label: "< 1 week", count: 732 },
  { lo: 7, hi: 14, label: "1–2 weeks", count: 0 },
  { lo: 14, hi: 30, label: "2–4 weeks", count: 0 },
  { lo: 30, hi: 60, label: "1–2 months", count: 0 },
  { lo: 60, hi: 90, label: "2–3 months", count: 0 },
  { lo: 90, hi: null, label: "3 months+", count: 0 },
];

describe("VelocityPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows activity KPIs, the company table, and aging distribution", async () => {
    mock({
      days: 30,
      kpis: {
        open_total: 732, first_scan: 0,
        opened: 733,
        updated: 176,
        reposted: 12,
        closed: 1,
        net: 732,
        median_days_open: 0,
        median_observed_listing_duration_days: null,
        closed_sample: 1,
        employer_dated_share: 0.7,
        closed_employer_dated_share: 1,
      },
      aging: AGING,
      posted: AGING,
      by_company: [
        { company: "apple", open: 392, opened: 392, updated: 31, reposted: 2, closed: 0, median_days_open: 0, median_observed_listing_duration_days: null },
        { company: "google", open: 183, opened: 183, updated: 75, reposted: 2, closed: 1, median_days_open: 0, median_observed_listing_duration_days: null },
      ],
    });

    render(<VelocityPanel days={30} />);

    expect(await screen.findByRole("img", { name: "Hiring flow by company" })).toBeInTheDocument();

    const hero = await screen.findByRole("heading", { level: 2, name: /opened/ });
    expect(hero).toHaveTextContent("733 opened");

    // Net flow KPI reads as a signed value.
    const net = screen.getByText("Net flow").closest(".kpi")!;
    expect(within(net as HTMLElement).getByText("+732")).toBeInTheDocument();

    // Activity table: one row per company with its lifecycle counts.
    const appleRow = screen.getByRole("table") &&
      within(screen.getByRole("table")).getByText("Apple").closest("tr")!;
    // Company · Open · Opened · Closed · Updated · Time posted, one row per company.
    expect(within(appleRow as HTMLElement).getAllByRole("cell").map((c) => c.textContent)).toEqual([
      "Apple", "392", "392", "0", "31", "",
    ]);

    // Aging: the current single band holds all open roles.
    const ageRow = screen.getByText("< 1 week").closest(".bar-row")!;
    expect(within(ageRow as HTMLElement).getByText("732")).toBeInTheDocument();
  });

  it("flags the observed duration as accruing when few roles have closed", async () => {
    mock({
      days: 30,
      kpis: {
        open_total: 732, first_scan: 0,
        opened: 733,
        updated: 176,
        reposted: 12,
        closed: 1,
        net: 732,
        median_days_open: 0,
        median_observed_listing_duration_days: null,
        closed_sample: 1,
        employer_dated_share: 0.7,
        closed_employer_dated_share: 1,
      },
      aging: AGING,
      posted: AGING,
      by_company: [
        { company: "apple", open: 392, opened: 392, updated: 31, reposted: 2, closed: 0, median_days_open: 0, median_observed_listing_duration_days: null },
      ],
    });

    render(<VelocityPanel days={30} />);
    expect(await screen.findByText(/only 1 have so far/i)).toBeInTheDocument();
  });

  it("reads the measure, and never claims the role was filled", async () => {
    // A "time to fill" heading would assert a hire nobody observed.
    mock({
      days: 0,
      kpis: {
        open_total: 500, first_scan: 0,
        opened: 900,
        updated: 300,
        reposted: 12,
        closed: 40,
        net: 860,
        median_days_open: 12,
        median_observed_listing_duration_days: 14,
        closed_sample: 40,
        employer_dated_share: 0.7,
        closed_employer_dated_share: 0.75,
      },
      aging: AGING,
      posted: AGING,
      by_company: [
        { company: "google", open: 180, opened: 200, updated: 60, reposted: 2, closed: 22, median_days_open: 11, median_observed_listing_duration_days: 12 },
      ],
    });

    render(<VelocityPanel days={0} />);

    await screen.findByRole("heading", { level: 2, name: /opened/ });
    expect(document.querySelector(".cockpit-lead p")!.textContent).toContain(
      "14d median time posted",
    );
    expect(screen.queryByText(/have so far/i)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/to fill/i);
  });

  it("renders per-company time-posted bars once closures accrue", async () => {
    mock({
      days: 0,
      kpis: {
        open_total: 500, first_scan: 0,
        opened: 900,
        updated: 300,
        reposted: 12,
        closed: 40,
        net: 860,
        median_days_open: 12,
        median_observed_listing_duration_days: 14,
        closed_sample: 40,
        employer_dated_share: 0.7,
        closed_employer_dated_share: 0.75,
      },
      aging: AGING,
      posted: AGING,
      by_company: [
        { company: "google", open: 180, opened: 200, updated: 60, reposted: 2, closed: 22, median_days_open: 11, median_observed_listing_duration_days: 12 },
        { company: "openai", open: 60, opened: 90, updated: 20, reposted: 2, closed: 8, median_days_open: 9, median_observed_listing_duration_days: 20 },
      ],
    });

    render(<VelocityPanel days={0} />);

    // No accruing note this time.
    expect(await screen.findByRole("heading", { level: 2, name: /opened/ })).toHaveTextContent("900 opened");
    expect(screen.queryByText(/have so far/i)).not.toBeInTheDocument();

    // Each company's median time posted is a column of the one company table.
    const googleRow = within(screen.getByRole("table")).getByText("Google").closest("tr")!;
    expect(within(googleRow as HTMLElement).getByText("12d")).toBeInTheDocument();
    // The posted distribution draws the bands it was handed.
    const postedPanel = screen.getByRole("heading", { name: "How long postings stay up" }).closest(".panel")!;
    expect(within(postedPanel as HTMLElement).getByText("< 1 week")).toBeInTheDocument();
  });

  /* The ages keep our first-sighting clock; each age panel says how much of
     its own sample the employer dated, so a source that dates its postings is
     not read as no older than one that does not. */
  it("states each age sample's employer-dated share beside it", async () => {
    mock({
      days: 0,
      kpis: {
        open_total: 640, first_scan: 0, opened: 900, updated: 300, reposted: 12, closed: 40, net: 860,
        median_days_open: 12, employer_dated_share: 466 / 640,
        median_observed_listing_duration_days: 14, closed_sample: 40, closed_employer_dated_share: 0.75,
      },
      aging: AGING,
      posted: AGING,
      by_company: [
        { company: "google", open: 180, opened: 200, updated: 60, reposted: 2, closed: 22, median_days_open: 11, median_observed_listing_duration_days: 12 },
      ],
    });
    render(<VelocityPanel days={0} />);
    await screen.findByRole("heading", { level: 2, name: /opened/ });

    const agePanel = screen.getByRole("heading", { name: "Age of open roles" }).closest(".panel") as HTMLElement;
    expect(agePanel).toHaveTextContent("Counted from when each role was first listed · 73% dated by the employer");
    const postedPanel = screen.getByRole("heading", { name: /How long postings stay up/ }).closest(".panel") as HTMLElement;
    expect(within(postedPanel).getByText("75% dated by the employer")).toBeInTheDocument();
  });

  it("states no share for an empty sample, never 0%", async () => {
    mock({
      days: 7,
      kpis: {
        open_total: 0, first_scan: 0, opened: 0, updated: 0, reposted: 0, closed: 0, net: 0,
        median_days_open: null, employer_dated_share: null,
        median_observed_listing_duration_days: null, closed_sample: 0, closed_employer_dated_share: null,
      },
      aging: AGING.map((band) => ({ ...band, count: 0 })),
      posted: AGING,
      by_company: [],
    });
    render(<VelocityPanel days={7} />);
    await screen.findByRole("heading", { level: 2, name: /opened/ });
    expect(screen.queryByText(/dated by the employer/)).toBeNull();
  });

  it("draws each company's open-roles bar from its open roles, the number printed beside it", async () => {
    // Amazon has fewer open roles but more opened ones than Google: a width
    // read off `opened` (797 vs 295) beside a label printing `open` would draw
    // the smaller number as the longer bar. A bar and its number are one fact.
    const company = (name: string, open: number, opened: number) => ({
      company: name, open, opened, updated: 0, reposted: 0, closed: 0,
      median_days_open: 0, median_observed_listing_duration_days: null,
    });
    mock({
      days: 30,
      kpis: {
        open_total: 155, first_scan: 0, opened: 1092, updated: 0, reposted: 0, closed: 0, net: 1092, median_days_open: 0,
        median_observed_listing_duration_days: null, closed_sample: 0, employer_dated_share: null,
        closed_employer_dated_share: null,
      },
      aging: AGING,
      posted: AGING,
      by_company: [company("amazon", 50, 797), company("google", 105, 295)],
    });
    render(<VelocityPanel days={30} />);
    const table = await screen.findByRole("table");
    const width = (name: string) => {
      const row = within(table).getByText(name).closest("tr") as HTMLElement;
      return parseFloat((row.querySelector(".bar-fill") as HTMLElement).style.width);
    };
    expect(width("Google")).toBe(100);
    expect(width("Amazon")).toBeCloseTo((50 / 105) * 100, 5);
  });

  it("names the roles a first scan found apart from the openings it counts", async () => {
    // A first scan of a new set of companies finds boards already listing,
    // never new openings. They are said, not counted.
    mock({
      days: 30,
      kpis: {
        open_total: 3192, first_scan: 1867, opened: 494, updated: 0, reposted: 0, closed: 217, net: 277,
        median_days_open: 40, median_observed_listing_duration_days: null, closed_sample: 0,
        employer_dated_share: 0.94, closed_employer_dated_share: null,
      },
      aging: AGING,
      posted: AGING,
      by_company: [],
    });
    render(<VelocityPanel days={30} />);
    expect(await screen.findByRole("heading", { level: 2, name: "494 opened" })).toBeInTheDocument();
    expect(screen.getByText(/1,867 more already listed when their company was first scanned/)).toBeInTheDocument();
  });
});
