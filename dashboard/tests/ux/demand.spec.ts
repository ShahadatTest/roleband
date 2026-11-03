import { installJobDetailRoutes } from "./boardHarness";
import { expect, test } from "./fixtures";
import { showAdvancedInsights } from "./insightsView";
import { detail } from "./boardHarness";
import {
  facetsFixture,
  hiringFixture,
  jobFixture,
  jobListFixture,
  notificationsFixture,
  overviewFixture,
  statsFixture,
  statusFixture,
  syncStartedFixture,
} from "../../src/test/fixtures";

// Hiring as the route sends it, with the three role lists this spec reads.
const demandFixture = {
  ...hiringFixture,
  // Dated by its employer 170 days ago, first seen by us 3 days ago.
  longest_open: [
    {
      ...jobFixture,
      id: 203,
      company: "openai",
      title: "Staff Product Manager, API Platform",
      days_open: 3,
      listed_days: 170,
    },
  ],
  most_updated_open: [
    {
      ...jobFixture,
      id: 202,
      company: "anthropic",
      title: "Engineering Manager, Agent Runtime Platform",
      update_count: 3,
      last_updated_at: "2026-07-12T16:00:00Z",
    },
  ],
};

test.beforeEach(async ({ page }) => {
  await showAdvancedInsights(page);
  await installJobDetailRoutes(page);
  await page.route("/api/profile", (route) => route.fulfill({ json: {
    profile: null, scope_configured: true,
  } }));
  await page.route("/api/stats", (route) => route.fulfill({ json: statsFixture }));
  await page.route("/api/status", (route) => route.fulfill({ json: statusFixture }));
  await page.route("/api/sync", (route) => route.fulfill({ json: syncStartedFixture }));
  await page.route("/api/facets", (route) => route.fulfill({ json: facetsFixture }));
  await page.route("/api/notifications**", (route) => route.fulfill({ json: notificationsFixture }));
  await page.route("/api/demand**", (route) => route.fulfill({ json: demandFixture }));
  await page.route("/api/statistics/overview**", (route) => route.fulfill({ json: overviewFixture }));
  await page.route("/api/jobs/202", (route) => route.fulfill({ json: demandFixture.most_updated_open[0] }));
  await page.route("/api/jobs/*/similar**", (route) => route.fulfill({ json: { scope: "cross", items: [] } }));
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: jobListFixture }));
});

test("demand shows roles updated but never closed", async ({ page }) => {
  // Demand is a sub-tab of the Statistics page.
  await page.goto("/statistics");
  await page.getByRole("tab", { name: "Hiring", exact: true }).click();
  await expect(page.getByRole("group", { name: "Time range" })).toHaveCount(0);

  await expect(page.getByRole("banner", { name: "Application navigation" })).toContainText("Insights/Hiring");
  await expect(page.getByRole("heading", { name: "Updated but never closed" })).toBeVisible();
  await expect(page.getByText("Engineering Manager, Agent Runtime Platform")).toBeVisible();
  const updated = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Updated but never closed" }) });
  await expect(updated.getByText("Anthropic")).toBeVisible();
  await expect(page.getByLabel("Updated 3 times")).toBeVisible();
  await expect(page.getByText("updated ×3")).toHaveCount(0);
});

/* One posting's age on Insights is its own listed age, the age its
 * Board row shows; our first-sighting clock stays inside the aggregates. */
test("a longest-open role reads its listed age", async ({ page }) => {
  await page.goto("/statistics");
  await page.getByRole("tab", { name: "Hiring", exact: true }).click();

  const row = page.getByRole("link", { name: /Staff Product Manager, API Platform/ });
  await expect(row).toContainText("OpenAI · Listed for 170 days");
  await expect(row).not.toContainText(/days? open/i);
});

/* Unbounded, the tab would draw one bar per company, every place group and a
 * row per role, many screens tall. Every view has a ceiling. */
test("Hiring draws bounded views: fifteen companies, a counted tail, regions that open", async ({ page }) => {
  await page.goto("/statistics/demand");
  await expect(page.locator(".insight-hero .eyebrow")).toHaveText("Hiring");
  await expect(page.getByRole("heading", { level: 2, name: "236 roles open" })).toBeVisible();

  await expect(page.getByText("3 companies more hold 12 roles (6% of these roles).")).toBeVisible();
  await expect(page.locator("table")).toHaveCount(0);
  // The whole tab fits in a few screens at a desktop width.
  const height = await page.locator(".stats-main").evaluate((el) => el.scrollHeight);
  expect(height).toBeLessThan(4000);

  // A side of the split is the scope bar's, sent to the route.
  const yours = page.waitForRequest((r) => r.url().includes("/api/demand?side=yours"));
  await page.getByRole("group", { name: "Companies" }).getByRole("button", { name: "Your companies" }).click();
  await yours;
  await expect(page).toHaveURL(/side=yours/);
  await page.getByRole("button", { name: "All companies" }).click();

  // Every company, searchable, in a sheet.
  await page.getByRole("button", { name: "Show all 18 companies" }).click();
  const sheet = page.getByRole("dialog", { name: "All companies hiring" });
  await sheet.getByRole("searchbox", { name: "Find a company" }).fill("market-1");
  await expect(sheet.getByText("6 of 18 companies")).toBeVisible();
  await page.keyboard.press("Escape");

  // A region opens into its countries; a role naming only the region stays apart.
  const europe = page.getByRole("button", { name: "Europe" });
  await expect(europe).toHaveAttribute("aria-expanded", "false");
  await europe.click();
  await expect(europe).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByText("All of Europe")).toBeVisible();
  await expect(page.getByText("Germany")).toBeVisible();
});

/* A compact job row is a real destination: a link with the canonical URL,
 * reachable by Tab and openable by Enter. A <div onClick> would be out of the
 * keyboard's reach entirely. */
test("a compact job row is a link the keyboard can reach and open", async ({ page }) => {
  await page.goto("/statistics");
  await page.getByRole("tab", { name: "Hiring", exact: true }).click();

  const row = page.getByRole("link", { name: /Engineering Manager, Agent Runtime Platform/ });
  // The canonical position URL, so the platform can offer "open in new tab".
  await expect(row).toHaveAttribute("href", "/company/anthropic/job/202");

  await row.focus();
  await expect(row).toBeFocused();
  await page.keyboard.press("Enter");

  // Enter opens the detail as an overlay over Demand — the app's navigation,
  // not the browser's: the Demand panel is still behind it.
  await expect(detail(page)).toBeVisible();
  await expect(page).toHaveURL(/\/company\/anthropic\/job\/202$/);
});
