import samples from "../../src/api/notification-samples.json" with { type: "json" };
import {
  jobListFixture, notificationsFixture, pluginAdoptingFixture, pluginDetailFixture, pluginFixture, pluginLapsedFixture,
  pluginRunContinuingFixture, pluginRunErroredFixture, pluginRunStoppedFixture, pluginsFixture, statusFixture, usageStateFixture,
} from "../../src/test/fixtures";
import { expect, mockGet, test, type Page } from "./fixtures";
import { installBoardRoutes, installJobDetailRoutes, twoJobList } from "./boardHarness";
import { bootPseudo, unbracketed } from "./pseudoScan";
import { installEveryRoute } from "./routesHarness";
import { installSettingsRoutes, syncScheduleUnderway } from "./settingsHarness";

/* Every screen in its populated state says only the catalog's words.
 * `copy-locale.spec.ts` sweeps the rail after a live switch, over
 * the thin fixtures every route can share; this boots each screen straight into
 * the pseudo locale over the fixtures its own specs use: a Board of roles, a
 * role's detail, each Settings page, a feed of notifications. A plain word here
 * is copy the catalog does not hold, or third-party text not marked as such. */

/** The server's samples as a page of the feed. */
const sampleFeed = {
  ...notificationsFixture,
  total: samples.length,
  limit: samples.length,
  items: samples.map((sample, i) => ({
    id: i + 1, created_at: "2026-09-28T12:00:00Z", priority: "normal", category: "coverage",
    title: sample.title, body: sample.body, job_id: null, company: null, run_id: null,
    source_type: "sample", read_at: null, dismissed_at: null, meta: { say: sample.say },
  })),
};

const SCREENS: { path: string; install: (page: Page) => Promise<void> }[] = [
  // Ranked rows name their world as a slug the catalog names.
  { path: "/", install: async (page) => {
    await installBoardRoutes(page);
    const ranked = { ...twoJobList, ranked_by: "intent", items: twoJobList.items.map((job) => ({ ...job, why_world: "ai_ml" })) };
    await mockGet(page, "/api/jobs?**", (route) => route.fulfill({ json: ranked }));
  } },
  { path: "/job/101", install: async (page) => { await installSettingsRoutes(page); await installJobDetailRoutes(page); } },
  // A feed of every wording branch the server has, as it stores them.
  { path: "/notifications", install: async (page) => {
    await installSettingsRoutes(page);
    await mockGet(page, "/api/notifications**", (route) => route.fulfill({ json: sampleFeed }));
  } },
  ...["companies", "intelligence", "schedule", "language", "recipes", "retention", "scope", "roles", "privacy",
    "plugins"].map(
    (tab) => ({ path: `/settings/${tab}`, install: installSettingsRoutes }),
  ),
];

test("the pseudo scan cannot be bypassed by a bracket, an arbitrary exemption or non-Latin text", async ({page}) => {
  await page.setContent('<main><p>⟦ĥéļļö⟧ plain suffix</p><p data-copy="anything">Hidden literal</p><p>未提取文本</p><p title="Repeating literal">Repeating literal</p><p data-copy="content" translate="no">Stripe</p><p>⟦ĥéļļö⟧</p></main>');
  expect(await unbracketed(page)).toEqual(["⟦ĥéļļö⟧ plain suffix","Hidden literal","未提取文本","Repeating literal","title=Repeating literal"]);
});

for (const { path, install } of SCREENS) {
  test(`${path} says only the catalog's words, and marks what RoleBand did not write`, async ({ page }) => {
    await bootPseudo(page);
    await install(page);
    await page.goto(path);
    await expect(page.locator("h1").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    // Proof of life: the pseudo locale is active, so an empty list means something.
    await expect(page.locator("main").getByText(/⟦/).first()).toBeVisible();
    expect(await unbracketed(page, "main, [role='dialog']"), `${path}: plain text`).toEqual([]);
  });
}

// The Board through the first scan: an empty board a third of the way in
// (its link to Profile), a list with the scan's line and its end note, and an
// empty board once every company is read.
test("the Board during and after the first scan says only the catalog's words", async ({ page }) => {
  await bootPseudo(page);
  await installBoardRoutes(page);
  await mockGet(page, "/api/companies/directory/status", (route) => route.fulfill({ json: {
    size: 4_200, following: false, since: null, checked: 0, to_check: 4_123, with_roles: 0, waiting_for_power: false,
  } }));
  const scan = (ever_read: number, running: boolean) => ({
    ...statusFixture, running, last_run_started_at: new Date(Date.now() - 4 * 60_000).toISOString(),
    jobs: [], scheduler: { ...statusFixture.scheduler, required: 150, ever_read },
  });
  const empty = { ...jobListFixture, items: [], total: 0 };
  for (const [status, list, name] of [
    [scan(50, true), empty, "empty, a third read"],
    [scan(12, true), twoJobList, "a list mid-scan"],
    [scan(150, false), empty, "empty, every company read"],
  ] as const) {
    await page.unroute("/api/status");
    await page.unroute("/api/jobs?**");
    await mockGet(page, "/api/status", (route) => route.fulfill({ json: status }));
    await mockGet(page, "/api/jobs?**", (route) => route.fulfill({ json: list }));
    await page.goto("/");
    await expect(page.locator(".board-first-scan, .board-first-scan-line, .board-content .empty").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(await unbracketed(page, "main"), `/ ${name}`).toEqual([]);
  }
});

// Settings > Schedule partway through: a scan running, a full scan whose
// length is a guess, and that full scan's inspector.
test("a running scan, a guessed length and a scan's inspector say only the catalog's words", async ({ page }) => {
  await bootPseudo(page);
  await installSettingsRoutes(page);
  await mockGet(page, "/api/schedule?**", (route) => route.fulfill({ json: syncScheduleUnderway }));
  await page.goto("/settings/schedule");
  await expect(page.locator("h1").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  // The running scan's row says its time in the catalog's words.
  await expect(page.locator(".schedule-upcoming-row time").first()).toContainText("⟦");
  expect(await unbracketed(page, "main"), "/settings/schedule with a scan running").toEqual([]);

  await page.getByRole("main").locator("button.plan-handle.reconcile").press("Enter");
  const inspector = page.getByRole("dialog");
  await expect(inspector).toBeVisible();
  await expect(inspector.getByText(/⟦/).first()).toBeVisible();
  expect(await unbracketed(page, "[role='dialog']"), "a full scan's inspector").toEqual([]);
});

/* The states a populated fixture never shows: nothing to list, a surface laid
 * over the page, and the first run. */
test("an empty Board, an empty feed, the palette and the first run say only the catalog's words", async ({ page }) => {
  await bootPseudo(page);
  await installBoardRoutes(page);
  await mockGet(page, "/api/jobs?**", (route) => route.fulfill({ json: { ...jobListFixture, total: 0, items: [] } }));
  await page.goto("/");
  await expect(page.locator("h1").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(await unbracketed(page, "main"), "/ with no roles").toEqual([]);

  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(await unbracketed(page, "[role='dialog']"), "the command palette").toEqual([]);
  await page.keyboard.press("Escape");

  await mockGet(page, "/api/notifications**", (route) => route.fulfill({ json: { ...notificationsFixture, total: 0, items: [] } }));
  await page.goto("/notifications");
  await expect(page.locator("h1").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(await unbracketed(page, "main"), "/notifications with nothing").toEqual([]);
});

test("the first run says only the catalog's words", async ({ page }) => {
  await bootPseudo(page);
  await installEveryRoute(page);
  await page.route("/api/profile", (route) => route.fulfill({ json: { profile: null, scope_configured: false } }));
  await page.goto("/welcome");
  await expect(page.locator("h1, h2").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expect(page.getByText(/⟦/).first()).toBeVisible();
  expect(await unbracketed(page, "body"), "/welcome").toEqual([]);
});

// Usage sharing's question, as a configured install meets it (docs/architecture.md).
test("the usage-sharing question says only the catalog's words", async ({ page }) => {
  await bootPseudo(page);
  await installEveryRoute(page);
  await page.route("/api/usage", (route) => route.fulfill({ json: usageStateFixture("undecided") }));
  await page.goto("/");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(/⟦/).first()).toBeVisible();
  expect(await unbracketed(page, "[role='dialog']"), "usage-sharing question").toEqual([]);
});


// Settings > Plugins: nothing installed, and the approval dialog.
test("Plugins with nothing installed and its approval dialog say only the catalog's words", async ({ page }) => {
  await bootPseudo(page);
  await installSettingsRoutes(page);
  await mockGet(page, "/api/plugins", (route) => route.fulfill({ json: pluginsFixture({ plugins: [] }) }));
  await page.goto("/settings/plugins");
  await expect(page.locator("h1").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(await unbracketed(page, "main"), "/settings/plugins with nothing installed").toEqual([]);

  await mockGet(page, "/api/plugins", (route) => route.fulfill({ json: pluginsFixture({ available: false, plugins: [] }) }));
  await page.goto("/settings/plugins");
  await expect(page.getByTestId("plugins-coming-soon")).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(await unbracketed(page, "main"), "/settings/plugins coming soon").toEqual([]);

  await mockGet(page, "/api/plugins", (route) => route.fulfill({ json: pluginsFixture({
    plugins: [pluginFixture({ state: "needs_approval", active_slots: [], last_run: null, last_clean_at: null })],
  }) }));
  // Every part of what approval records: facts and their trust, older rows and
  // their family spellings (third-party, through Content), what it receives.
  const detail = pluginDetailFixture();
  await mockGet(page, "/api/plugins/example-pay", (route) => route.fulfill({ json: { ...detail, approval: {
    ...detail.approval, slots: ["pay.levels", "company.facts"], fact_fields: ["headcount"], fact_rank: 40,
  } } }));
  await page.goto("/settings/plugins");
  await page.getByRole("main").getByRole("checkbox").first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(await unbracketed(page, "[role='dialog']"), "the plugin approval dialog").toEqual([]);
});

// An update that lapsed the approval of a plugin left on: the row, and its
// approval through Review on its settings, which says approving uses it again.
test("a plugin waiting for approval while on says only the catalog's words", async ({ page }) => {
  await bootPseudo(page);
  await installSettingsRoutes(page);
  await mockGet(page, "/api/plugins", (route) => route.fulfill({ json: pluginsFixture({
    plugins: [pluginLapsedFixture()] }) }));
  await mockGet(page, "/api/plugins/example-pay", (route) => route.fulfill({ json: pluginDetailFixture({
    ...pluginLapsedFixture(), runs: [] }) }));
  await page.goto("/settings/plugins");
  await expect(page.getByTestId("plugin-row-example-pay")).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(await unbracketed(page, "main"), "/settings/plugins with an approval lapsed while on").toEqual([]);
  await page.goto("/settings/plugins/example-pay");
  await expect(page.locator("h1").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(await unbracketed(page, "main"), "/settings/plugins/example-pay, approval lapsed while on").toEqual([]);
  // Review sits in the plugin's own card, in the row that says it waits for approval.
  await page.getByRole("main").getByRole("region").first().getByRole("button").click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(await unbracketed(page, "[role='dialog']"), "the approval dialog of a plugin still on").toEqual([]);
});

// One plugin's settings, populated: schedule, history, remove.
test("a plugin's settings say only the catalog's words", async ({ page }) => {
  await bootPseudo(page);
  await installSettingsRoutes(page);
  await page.goto("/settings/plugins/example-pay");
  await expect(page.locator("h1").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(await unbracketed(page, "main"), "/settings/plugins/example-pay").toEqual([]);
  await page.getByRole("main").getByRole("button").last().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(await unbracketed(page, "[role='dialog']"), "the uninstall dialog").toEqual([]);
});

/* A fresh install's pay, no plugin on: a role priced by its base
 * alone on the Board, and the Pay tab's panel for such roles. */
test("an estimated base on the Board and the Pay tab's base panel say only the catalog's words", async ({ page }) => {
  await bootPseudo(page);
  await installBoardRoutes(page);
  const baseOnly = { ...twoJobList.items[0], comp_low: null, comp_high: null, comp_median: null,
    comp_base_low: 212_500, comp_base_median: 250_000, comp_base_high: 287_500 };
  await mockGet(page, "/api/jobs?**", (route) => route.fulfill({ json: { ...twoJobList, items: [baseOnly] } }));
  await page.goto("/");
  await expect(page.locator(".job-row .comp")).toContainText("⟦");
  expect(await unbracketed(page, "main"), "/ with an estimated base").toEqual([]);

  await installEveryRoute(page);
  const summary = (p50: number, count: number) => ({ count, min: p50 - 50_000, max: p50 + 90_000,
    p25: p50 - 20_000, p50, p75: p50 + 20_000, p90: p50 + 60_000 });
  await mockGet(page, "/api/statistics/compensation**", (route) => route.fulfill({ json: {
    currency: "USD", min_roles: 5, coverage: { with_comp: 0, total_open: 40, pct: 0 }, overall: null, histogram: [],
    by_level: [], by_company: [], by_family: [], by_skill: [],
    disclosed: { bands: [], reqs: 0, companies: 0,
      excluded: { unclear: 0, total: 0, not_usd: 0, not_yearly: 0, implausible: 0 }, truncated: false },
    disclosure: { overall: { open: 40, checked: 0, disclosed: 0, rate: null }, by_company: [], by_level: [] },
    base_estimates: { min_roles: 5, coverage: { with_base: 40, total_open: 40 }, overall: summary(210_000, 40),
      by_level: [{ level_band: "senior", ...summary(196_000, 25) }], by_company: [], by_family: [] },
  } }));
  await mockGet(page, "/api/statistics/comp-trends**", (route) => route.fulfill({ json: {
    dim: "overall", days: 30, dates: [], series: [] } }));
  await mockGet(page, "/api/statistics/disclosure-trends**", (route) => route.fulfill({ json: {
    dim: "overall", days: 30, basis: "base", dates: [], series: [], cohort: null } }));
  await page.goto("/statistics/compensation");
  // The panel itself: the rest of the Pay tab is scanned by its own specs.
  await expect(page.locator("main section.panel")).toContainText("⟦");
  await page.waitForLoadState("networkidle");
  expect(await unbracketed(page, "main section.panel"), "the Pay tab's base-only panel").toEqual([]);
});

// A plugin partway through a long pass that also answers from what RoleBand read
// before: the row (how far its update got, how many companies are fresh, Start
// named by its plugin) and its settings (fresh and adopted per kind, the last
// update's progress, each update's time and an error's own words).
test("a plugin partway through a long pass says only the catalog's words", async ({ page }) => {
  await bootPseudo(page);
  await installSettingsRoutes(page);
  const runs = [pluginRunStoppedFixture(), pluginRunErroredFixture(), pluginRunContinuingFixture()];
  await mockGet(page, "/api/plugins", (route) => route.fulfill({ json: pluginsFixture({
    plugins: [pluginFixture(), pluginAdoptingFixture({ paused: false, last_run: pluginRunContinuingFixture() })] }) }));
  await mockGet(page, "/api/plugins/example-ladder", (route) => route.fulfill({ json: pluginDetailFixture({
    ...pluginAdoptingFixture(), runs }) }));
  await page.goto("/settings/plugins");
  await expect(page.getByTestId("plugin-row-example-ladder")).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(await unbracketed(page, "main"), "/settings/plugins, a plugin partway through a pass").toEqual([]);
  await page.goto("/settings/plugins/example-ladder");
  await expect(page.locator("h1").first()).toBeVisible();
  await expect(page.locator("time").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(await unbracketed(page, "main"), "/settings/plugins/example-ladder").toEqual([]);
});
