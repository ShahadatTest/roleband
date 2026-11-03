import { expect, test } from "./fixtures";
import { showAdvancedInsights } from "./insightsView";
import {
  facetsFixture,
  jobFixture,
  jobListFixture,
  notificationsFixture,
  overviewFixture,
  statsFixture,
  statusFixture,
} from "../../src/test/fixtures";

// Compensation sub-tab. Two different quantities live here and must stay apart:
// the imputed total-comp estimate (a lookup, few distinct values) and the bands
// employers actually printed (base salary). The snapshot is the roles open now;
// the window moves the trend charts only.

const summary = (p50: number, count: number) => ({
  count,
  min: 298_053,
  max: 1_500_000,
  p25: p50 - 40_000,
  p50,
  p75: p50 + 80_000,
  p90: p50 + 200_000,
});

const compFixture = (over: Record<string, unknown> = {}) => ({
  currency: "USD",
  min_roles: 5,
  coverage: { with_comp: 732, total_open: 749, pct: 0.977 },
  overall: summary(479_251, 732),
  histogram: [
    { lo: 200_000, hi: 400_000, count: 309 },
    { lo: 400_000, hi: 600_000, count: 148 },
  ],
  by_level: [
    { level_band: "senior", ...summary(306_217, 406) },
    { level_band: "staff", ...summary(644_468, 265) },
  ],
  by_company: [{ company: "openai", ...summary(900_000, 58) }],
  by_family: [{ family: "software_engineering", ...summary(479_251, 400) }],
  by_skill: [
    { term: "rust", p50: 900_000, premium: 120_749, count: 17 },
    { term: "cpp", p50: 420_000, premium: -60_000, count: 26 },
  ],
  disclosed: {
    bands: [
      { company: "google", level_band: "staff", low: 262_000, high: 365_000, reqs: 18 },
      { company: "google", level_band: "principal", low: 240_000, high: 334_000, reqs: 12 },
      { company: "google-deepmind", level_band: "staff", low: 207_000, high: 301_000, reqs: 1 },
    ],
    reqs: 31,
    companies: 2,
    excluded: { unclear: 90, total: 0, not_usd: 0, not_yearly: 0, implausible: 1 },
    truncated: false,
  },
  // 749 open, 600 read by the disclosure pass, 150 of those stating a band. The
  // gap between 749 and 600 is our extraction backlog, not employer silence, and
  // the panel has to say which is which.
  base_estimates: { min_roles: 5, coverage: { with_base: 0, total_open: 749 }, overall: null, by_level: [], by_company: [], by_family: [] },
  disclosure: {
    overall: { open: 749, checked: 600, disclosed: 150, rate: 0.25 },
    by_company: [
      { company: "google", open: 200, checked: 200, disclosed: 160, rate: 0.8 },
      { company: "openai", open: 60, checked: 50, disclosed: 5, rate: 0.1 },
      { company: "netflix", open: 40, checked: 0, disclosed: 0, rate: null },
    ],
    by_level: [
      { level_band: "senior", open: 406, checked: 400, disclosed: 100, rate: 0.25 },
      { level_band: "staff", open: 265, checked: 200, disclosed: 50, rate: 0.25 },
    ],
  },
  ...over,
});

const disclosureTrendFixture = (dim: string) => ({
  dim,
  days: 30,
  basis: "base",
  cohort: null,
  dates: ["2026-07-20", "2026-07-21"],
  series:
    dim === "company"
      ? [
          {
            key: "google", checked: 200, disclosed: 160,
            points: [
              { date: "2026-07-20", open: 190, checked: 180, disclosed: 120, rate: 0.667, bands: 3, reqs: 20, low_p50: 250_000, high_p50: 350_000 },
              { date: "2026-07-21", open: 200, checked: 200, disclosed: 160, rate: 0.8, bands: 4, reqs: 24, low_p50: 262_000, high_p50: 365_000 },
            ],
          },
        ]
      : [
          {
            key: "", checked: 600, disclosed: 150,
            points: [
              { date: "2026-07-20", open: 700, checked: 560, disclosed: 118, rate: 0.211, bands: 3, reqs: 25, low_p50: 240_000, high_p50: 334_000 },
              { date: "2026-07-21", open: 749, checked: 600, disclosed: 150, rate: 0.25, bands: 4, reqs: 31, low_p50: 262_000, high_p50: 365_000 },
            ],
          },
        ],
});

test.beforeEach(async ({ page }) => {
  await showAdvancedInsights(page);
  await page.route("/api/statistics/overview**", (route) =>
    route.fulfill({ json: overviewFixture }));
  await page.route("/api/stats", (route) => route.fulfill({ json: statsFixture }));
  await page.route("/api/status", (route) => route.fulfill({ json: statusFixture }));
  await page.route("/api/facets", (route) => route.fulfill({ json: facetsFixture }));
  await page.route("/api/notifications**", (route) => route.fulfill({ json: notificationsFixture }));
  await page.route("/api/jobs/*/similar**", (route) => route.fulfill({ json: { scope: "cross", items: [] } }));
  await page.route("/api/jobs/101", (route) => route.fulfill({ json: jobFixture }));
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: jobListFixture }));
  await page.route("/api/statistics/comp-trends**", (route) =>
    route.fulfill({ json: { dim: "overall", days: 30, dates: [], series: [] } }),
  );
  await page.route("/api/statistics/disclosure-trends**", (route) => {
    const dim = new URL(route.request().url()).searchParams.get("dim") ?? "overall";
    return route.fulfill({ json: disclosureTrendFixture(dim) });
  });
  await page.route("/api/statistics/compensation**", (route) => route.fulfill({ json: compFixture() }));
});

test("shows employer-published bands, keeps them apart from the imputed estimate", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

  await page.goto("/statistics");
  await page.getByRole("tab", { name: "Compensation" }).click();

  // The hero stays compact. Its methodology remains available on demand.
  await expect(page.getByRole("heading", { level: 2, name: /median/ })).toHaveText(/\$479K median/);
  await expect(page.getByText(/732 \/ 749 open roles now · 98% coverage/)).toBeVisible();
  // The answer leads the tab, as on every Insights tab.
  await expect(page.locator(".insight-hero .eyebrow")).toHaveText("Compensation");
  const estimateTip = page.getByRole("button", { name: "How compensation is estimated" });
  await estimateTip.hover();
  await expect(page.getByRole("tooltip").filter({ hasText: /imputed from a company \+ level \+ family lookup/i })).toBeVisible();

  // Published bands: a row per level, never a bar per band.
  const rows = page.getByRole("list", { name: "Posted base salary ranges by level" });
  await expect(rows.getByRole("listitem")).toHaveCount(2);
  await expect(page.getByText(/3 ranges · 2 employers/)).toBeVisible();
  const staff = rows.getByRole("img", { name: /^Staff: 2 ranges from 2 employers/ });
  await expect(staff.locator(".pay-band[data-chosen]")).toHaveCount(0);
  // The exclusion detail is available from the compact heading.
  const publishedTip = page.getByRole("button", { name: "About posted ranges" });
  await publishedTip.focus();
  await expect(page.getByRole("tooltip").filter({ hasText: /90 more roles post a range/i })).toBeVisible();

  // Picking an employer is the only colour on the chart, and it is drawn where its band is.
  await page.locator(".pay-bands-pick").getByRole("button", { name: /^Filter by/ }).click();
  await page.getByRole("option", { name: /Google DeepMind/ }).click();
  await expect(staff).toHaveAttribute("aria-label", /Google DeepMind: \$207K to \$301K/);
  const picked = staff.locator(".pay-band[data-chosen]");
  await expect(picked).toHaveCount(1);
  const track = await staff.boundingBox();
  const bar = await picked.boundingBox();
  expect(track && bar && bar.x >= track.x && bar.x + bar.width <= track.x + track.width + 1).toBe(true);
  await expect(rows.getByRole("img", { name: /^Principal/ })).toHaveAttribute("aria-label", /posts no range/);

  // Every pay row says how many roles it rests on.
  await expect(page.locator(".comp-row", { hasText: "OpenAI" })).toContainText("58 roles");
  // A skill that pays less at the same level is shown as less.
  await expect(page.locator(".comp-row", { hasText: "C++" })).toContainText("−$60K");
  expect(errors).toEqual([]);
});

test("roles whose level we cannot place get their own row on Pay, never a rung's", async ({ page }) => {
  // The server counts them under `unstated`, listed after the rungs: a bare
  // title is stored at Mid for sorting only, and counted as Mid it would make
  // a "Mid-level" row of published pay above Senior.
  const base = compFixture();
  await page.route("/api/statistics/compensation**", (route) =>
    route.fulfill({
      json: compFixture({
        disclosed: {
          ...(base.disclosed as Record<string, unknown>),
          bands: [
            { company: "google", level_band: "staff", low: 262_000, high: 365_000, reqs: 18 },
            { company: "google", level_band: "principal", low: 240_000, high: 334_000, reqs: 12 },
            { company: "apple", level_band: "unstated", low: 251_000, high: 350_000, reqs: 4 },
          ],
          reqs: 34,
          companies: 2,
        },
        disclosure: {
          ...(base.disclosure as Record<string, unknown>),
          by_level: [
            { level_band: "staff", open: 265, checked: 200, disclosed: 50, rate: 0.25 },
            { level_band: "unstated", open: 300, checked: 250, disclosed: 90, rate: 0.36 },
          ],
        },
      }),
    }),
  );
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

  await page.goto("/statistics");
  await page.getByRole("tab", { name: "Compensation" }).click();

  const rows = page.getByRole("list", { name: "Posted base salary ranges by level" });
  await expect(rows.getByRole("listitem")).toHaveCount(3);
  await expect(rows.getByRole("listitem").last()).toContainText("Level not placed");
  await expect(rows.getByRole("img", { name: /^Level not placed: 1 range from 1 employer/ })).toBeVisible();
  await expect(rows.getByText(/^unstated$/)).toHaveCount(0);
  await expect(rows.getByText("Mid-level")).toHaveCount(0);

  await page.getByRole("group", { name: "Disclosure breakdown" }).getByRole("button", { name: "By level" }).click();
  const byLevel = page.getByRole("img", { name: /post a range, by level/i });
  await expect(byLevel.getByText("Level not placed")).toBeVisible();
  await expect(byLevel.getByText(/^unstated$/)).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("reports the disclosure rate against checked roles and names the backlog", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

  await page.goto("/statistics");
  await page.getByRole("tab", { name: "Compensation" }).click();

  // 150 of 600 CHECKED roles, not 150 of 749 open ones. The 20% that the wrong
  // denominator would produce is our own extraction queue showing up as employer
  // behaviour, so the headline and the note must both be present.
  await expect(page.locator(".chart-insight", { hasText: /25% of 600 checked roles post a range/ })).toBeVisible();
  await expect(page.getByText(/149 of 749 open roles have not been checked/i)).toBeVisible();

  const rateChart = page.getByRole("img", { name: /post a range, by employer/i });
  await expect(rateChart).toBeVisible();
  await expect(rateChart.getByText("80% · 160/200")).toBeVisible();
  // Netflix has nothing checked; it must not be drawn as a 0% employer.
  await expect(rateChart.getByText("Netflix")).toHaveCount(0);

  await page.getByRole("group", { name: "Disclosure breakdown" }).getByRole("button", { name: "By level" }).click();
  await expect(page.getByRole("img", { name: /post a range, by level/i })).toBeVisible();

  expect(errors).toEqual([]);
});

test("charts disclosure and published bands over time", async ({ page }) => {
  await page.goto("/statistics");
  await page.getByRole("tab", { name: "Compensation" }).click();

  const rateTrend = page.getByRole("img", { name: /post a range over time/i });
  await expect(rateTrend).toBeVisible();
  const bandTrend = page.getByRole("img", { name: /median posted base salary range over time/i });
  await expect(bandTrend).toBeVisible();
  // The chart's accessible description carries the actual figures, including the
  // unit: distinct bands, not roles.
  await expect(
    page.getByText(/across 4 distinct ranges covering 31 open roles: \$262K to \$365K/),
  ).toBeAttached();

  // Switching the rate breakdown must re-drive its own fetch...
  const request = page.waitForRequest(
    (r) => r.url().includes("/api/statistics/disclosure-trends") && r.url().includes("dim=company"),
  );
  await page.getByRole("group", { name: "Trend breakdown" }).getByRole("button", { name: "By employer" }).click();
  await request;
  await expect(rateTrend).toBeVisible();

  // ...while the band trend stays market-wide: a median of per-company medians is
  // not a median, so it must not follow the breakdown toggle.
  await expect(bandTrend).toBeVisible();
  await expect(page.getByText(/^Median posted base salary range\s*·/)).toBeVisible();
});

test("the window moves the trend charts, never the snapshot of open roles", async ({ page }) => {
  // A snapshot of roles FIRST SEEN in the window would let 7d/30d change WHICH
  // roles it summarises. The window re-drives the trend routes and never
  // refetches the snapshot.
  const snapshots: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/statistics/compensation")) snapshots.push(r.url());
  });
  await page.goto("/statistics/compensation");
  await expect(page.getByRole("heading", { level: 2, name: /median/ })).toHaveText(/\$479K median/);
  // A dev build mounts twice (StrictMode), so count what the mount sent and
  // hold the window click to adding nothing.
  const mounted = snapshots.length;
  expect(mounted).toBeGreaterThan(0);

  const trend = page.waitForRequest((r) => r.url().includes("/api/statistics/comp-trends") && r.url().includes("days=7"));
  await page.getByRole("group", { name: "Time range" }).getByRole("button", { name: "7d" }).click();
  await trend;
  await expect(page.getByRole("heading", { level: 2, name: /median/ })).toHaveText(/\$479K median/);
  expect(snapshots).toHaveLength(mounted);
  expect(snapshots.every((url) => !url.includes("days="))).toBe(true);
});


test("a fresh install's base-only roles have their own panel, apart from the totals", async ({ page }) => {
  // RoleBand's data prices these by their base
  // alone. They are counted, labelled and charted apart: never on the totals' axis.
  await page.route("/api/statistics/compensation**", (route) => route.fulfill({ json: compFixture({
    base_estimates: {
      min_roles: 5, coverage: { with_base: 40, total_open: 789 }, overall: summary(210_000, 40),
      by_level: [{ level_band: "senior", ...summary(196_000, 25) }, { level_band: "staff", ...summary(247_000, 15) }],
      by_company: [], by_family: [],
    },
  }) }));
  await page.goto("/statistics");
  await page.getByRole("tab", { name: "Compensation" }).click();

  const panel = page.getByRole("region", { name: "Estimated base salary by level" });
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("40 more roles have only an estimated base salary.");
  await expect(panel).toContainText("$196K");
  // The totals' hero is the totals' alone.
  await expect(page.getByRole("heading", { level: 2, name: /median/ })).toHaveText(/\$479K median/);
});
