import { installJobDetailRoutes } from "./boardHarness";
import { expect, test } from "./fixtures";
import type { Locator, Page } from "@playwright/test";
import { detail } from "./boardHarness";
import {
  facetsFixture,
  jobFixture,
  jobListFixture,
  notificationsFixture,
  overviewFixture,
  statsFixture,
  statusFixture,
  syncStartedFixture,
} from "../../src/test/fixtures";
import { msg } from "../../src/test/msg";

const emptyDemand = {
  open_total: 0, new_today: 0, closed_today: 0, companies: [], regions: [], unplaced: 0, employer_dated_share: null,
  longest_open: [], listed_over_a_year: 0, most_reposted: [], most_updated_open: [],
};
const velocityFixture = {
  days: 30,
  kpis: {
    open_total: 12, opened: 5, updated: 3, closed: 1, net: 4,
    median_days_open: 20, median_observed_listing_duration_days: null, closed_sample: 1,
  },
  aging: [{ lo: 0, hi: 30, label: "0–30d", count: 8 }],
  by_company: [
    { company: "google", open: 6, opened: 3, updated: 2, closed: 1, median_days_open: 18, median_observed_listing_duration_days: null },
  ],
};

test.beforeEach(async ({ page }) => {
  await installJobDetailRoutes(page);
  await page.route("/api/profile", (route) => route.fulfill({ json: {
    profile: null, scope_configured: true,
  } }));
  await page.route("/api/stats", (route) => route.fulfill({ json: statsFixture }));
  await page.route("/api/status", (route) => route.fulfill({ json: statusFixture }));
  await page.route("/api/sync", (route) => route.fulfill({ json: syncStartedFixture }));
  await page.route("/api/facets", (route) => route.fulfill({ json: facetsFixture }));
  await page.route("/api/notifications**", (route) => route.fulfill({ json: notificationsFixture }));
  await page.route("/api/demand", (route) => route.fulfill({ json: emptyDemand }));
  await page.route("/api/statistics/overview**", (route) => route.fulfill({ json: overviewFixture }));
  await page.route("/api/statistics/velocity**", (route) => route.fulfill({ json: velocityFixture }));
  await page.route("/api/jobs/101", (route) => route.fulfill({ json: jobFixture }));
  await page.route("/api/jobs/*/similar**", (route) => route.fulfill({ json: { scope: "cross", items: [] } }));
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: jobListFixture }));
});

/* The ⌘K listener is attached by the app shell's effect, after React's first
   commit, which can land AFTER the page's load event: a key pressed the moment
   `goto` resolves can reach a page with nobody listening, and the palette never
   opens. Pressed right after the navigation commits, it is lost every time;
   under host load, sometimes. A rendered role row means the shell has mounted
   and its effects have run. */
async function openRadar(page: Page) {
  await page.goto("/");
  // A precondition, not a claim: it may take as long as the host needs.
  await expect(page.getByRole("article").first()).toBeVisible({ timeout: 15_000 });
}

/* ui/Overlay repairs a Tab that the browser sent out of a dialog AFTER the
   browser moved focus (a zero-delay timer queued on keydown), because WebKit
   skips buttons and walks out from a text field. Judging focus the instant the
   key press resolves races that repair. Timers of equal delay run in the order
   they were queued, so one more zero-delay timer, queued after the key, runs
   after the repair: this judges focus once the trap's own work is done and
   nothing later. One round trip per key, not two, so a loop of ~60 keys stays
   inside the test budget on a loaded host. */
const focusInsideAfterRepair = (dialog: Locator) =>
  dialog.evaluate((el) =>
    new Promise<boolean>((resolve) => setTimeout(() => resolve(el.contains(document.activeElement)), 0)));

test("cmd-k opens the palette and arrow+enter navigates to a route", async ({ page }) => {
  await openRadar(page);

  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  await expect(page.getByLabel("Command query")).toBeFocused();

  await page.keyboard.type("insights");
  // First result is the role search; arrow down to the Statistics destination.
  await page.keyboard.press("ArrowDown");
  await expect(palette.getByRole("option", { name: "Insights", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Enter");

  await expect(palette).toBeHidden();
  // Insights opens on its Overview sub-tab, whose hero names it.
  await expect(page.locator(".insight-hero .eyebrow")).toHaveText("Overview");
});

test("the palette deep-links to a section's sub-tab", async ({ page }) => {
  await openRadar(page);

  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();

  await page.keyboard.type("Pace");
  // First result is the role search; arrow down to the "Insights: Pace" jump.
  await page.keyboard.press("ArrowDown");
  await expect(
    palette.getByRole("option", { name: "Insights: Pace", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Enter");

  await expect(palette).toBeHidden();
  await expect(page).toHaveURL(/\/statistics\/velocity$/);
  await expect(page.getByRole("tab", { name: "Pace" })).toHaveAttribute("aria-selected", "true");
});

/* Arrowing scrolls the list under a pointer resting on it, and the browser
   reports each row that arrives as the pointer entering it. Enter runs the
   highlighted row, so the highlight must stay where the keys put it. */
test("arrowing past a resting pointer lands where the keys took it", async ({ page, isMobile }) => {
  test.skip(isMobile, "the palette is a keyboard surface");
  await page.setViewportSize({ width: 1440, height: 900 });
  await openRadar(page);
  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();

  // A moving pointer picks a row.
  const profile = palette.getByRole("option", { name: "Profile", exact: true });
  const box = (await profile.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 4 });
  await page.mouse.move(box.x + box.width / 2 + 3, box.y + box.height / 2);
  await expect(profile).toHaveAttribute("aria-selected", "true");

  const names = await palette.getByRole("option").allTextContents();
  const target = names[names.indexOf("Profile") + 12];
  for (let i = 0; i < 12; i++) await page.keyboard.press("ArrowDown");
  // The list has scrolled, so the row the keys reached is no longer under the pointer.
  const reached = palette.getByRole("option", { name: target, exact: true });
  await expect(reached).toHaveAttribute("aria-selected", "true");
  await expect(profile).not.toBeInViewport();
});

test("palette free text runs a role search on the board", async ({ page }) => {
  const jobRequests: string[] = [];
  await page.route("/api/jobs?**", (route) => {
    jobRequests.push(route.request().url());
    return route.fulfill({ json: jobListFixture });
  });

  await openRadar(page);
  await page.keyboard.press("ControlOrMeta+k");
  await page.keyboard.type("api product");
  await page.keyboard.press("Enter");

  await expect(page.getByRole("dialog", { name: "Command palette" })).toBeHidden();
  await expect(page.getByPlaceholder(msg("radar-search-placeholder"))).toHaveValue("api product");
  await expect
    .poll(() => jobRequests.some((url) => new URL(url).searchParams.get("q") === "api product"))
    .toBe(true);
});

test("escape closes the palette without acting", async ({ page }) => {
  await openRadar(page);
  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.getByRole("dialog", { name: "Command palette" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Command palette" })).toBeHidden();
  await expect(page.getByText("Staff Product Manager, API")).toBeVisible();
});

/* A role's detail opened over the list is a cover, and the palette over it
   takes the first Escape, and only the palette closes. Surfaces that each
   listen at the window for themselves would both close on one press. */
test("over a role's detail, Escape closes the palette and the detail stays open", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Staff Product Manager, API").click();
  const cover = page.getByRole("dialog", { name: /^Role:/ });
  await expect(cover).toHaveAttribute("aria-modal", "true");
  await expect(page).toHaveURL(/\/company\/openai\/job\/101$/);

  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();

  // Stepping back is `history.go(-1)`, which lands a task after the key press;
  // so the detail is asserted a beat later, not the instant the palette hides.
  await page.waitForTimeout(300);
  await expect(page).toHaveURL(/\/company\/openai\/job\/101$/);
  await expect(cover).toContainText("Lead API product strategy.");

  // The next Escape is the cover's: one step, back to the board.
  await page.keyboard.press("Escape");
  await expect(cover).toHaveCount(0);
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByText("Staff Product Manager, API")).toBeVisible();
});

test("signal rows support keyboard open and arrow movement", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "Keyboard row navigation is a desktop flow.");

  await page.goto("/");
  const row = page.locator(".job-row").first();
  await row.focus();
  await page.keyboard.press("Enter");

  // Enter opens the full-screen detail at its own company-scoped URL.
  await expect(page).toHaveURL(/\/company\/openai\/job\/101$/);
  const detailPanel = detail(page);
  await expect(detailPanel).toContainText("Lead API product strategy.");

  // Escape closes it and returns to the board.
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/\/$/);
  await expect(detailPanel).toHaveCount(0);
});

/* A palette that declares aria-modal must hold focus: one that holds nothing
   lets Tabs land on the page behind it (the board's search field, the sort
   select, a role row), and the page still scrolls underneath. A modal holds
   the keyboard and the page, all
   the way round its ring in both directions. */
test("the palette holds focus and the page: Tab never reaches what is behind it, and Escape hands focus back", async ({ page }) => {
  // ~60 key presses, each judged after the trap's own repair: a long walk by
  // design, and WebKit's is the slow one. More time, not fewer checks.
  test.slow();
  await page.goto("/");
  const row = page.getByRole("article").first();
  await row.focus();

  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.body).overflow)).toBe("hidden");

  // Every option plus the query field, and two more: past the end of the ring.
  const presses = (await palette.getByRole("option").count()) + 3;
  for (const key of ["Tab", "Shift+Tab"]) {
    for (let i = 1; i <= presses; i++) {
      await page.keyboard.press(key);
      const inside = await focusInsideAfterRepair(palette);
      expect(inside, `${key} #${i} left the palette`).toBe(true);
    }
  }

  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();
  await expect(row).toBeFocused();
});

/* The palette reads the compare selection, which the app hydrates from the
   server after load. When that answer lands while the palette is open, the
   palette re-renders — and that must not move the user's focus or forget where
   Escape hands it back. A focus callback ref that is a new function every
   render does both: React re-runs it, which focuses the input again and
   re-captures the "opener" as whatever holds focus at that moment. */
test("a re-render while the palette is open keeps focus where the user put it", async ({ page }) => {
  let answer: () => void = () => {};
  const held = new Promise<void>((resolve) => { answer = resolve; });
  await page.route("/api/compare-selection", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await held;
    await route.fulfill({ json: { job_ids: [] } });
  });

  await page.goto("/");
  const row = page.getByRole("article").first();
  await row.focus();
  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();

  // Focus the second option directly: how it gets there (Tab, pointer) is the
  // focus-trap test's concern, not this one's.
  const option = palette.getByRole("option").nth(1);
  await option.focus();
  await expect(option).toBeFocused();

  const hydrated = page.waitForResponse((r) => r.url().endsWith("/api/compare-selection"));
  answer();
  await hydrated;
  // Let the state update commit before judging it.
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0))));

  await expect(option).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();
  await expect(row).toBeFocused();
});

