import { expect, test, type Page } from "./fixtures";
import { jobListFixture, statusFixture } from "../../src/test/fixtures";
import type { SystemStatus } from "../../src/api";
import { msg } from "../../src/test/msg";
import { installBoardRoutes, twoJobList } from "./boardHarness";

/* The board through a new install's first scan: until every followed company
   has been read once, an empty or short board says the scan is still reading,
   never that the person's filters emptied it. */

const EMPTY = { ...jobListFixture, items: [], total: 0 };

/** 12 of 150 companies read. The first read already set `last_success_at`,
    which is what used to end the first-scan screen. */
function firstScan(over: Partial<SystemStatus> = {}, scheduler: Partial<SystemStatus["scheduler"]> = {}): SystemStatus {
  return {
    ...statusFixture,
    last_success_at: new Date(Date.now() - 60_000).toISOString(),
    running: true,
    last_run_started_at: new Date(Date.now() - 4 * 60_000).toISOString(),
    last_run_finished_at: null,
    jobs: [],
    ...over,
    scheduler: { ...statusFixture.scheduler, required: 150, ever_read: 12, unread: [], last_complete_at: null, ...scheduler },
  };
}

/** Whether the person follows every company, and how far the check of the
    others has got: 4,123 companies beyond the ones followed. */
type Directory = { following: boolean; checked?: number };
const directoryStatus = ({ following, checked = 0 }: Directory) => ({
  size: 4_200, following, since: following ? "2026-11-01T00:00:00Z" : null,
  checked, to_check: 4_123, with_roles: 0, waiting_for_power: false,
});

async function board(page: Page, status: SystemStatus, list: unknown = EMPTY, url = "/", directory: Directory = { following: false }) {
  await installBoardRoutes(page);
  await page.route("/api/companies/directory/status", (route) => route.fulfill({ json: directoryStatus(directory) }));
  await page.route("/api/status", (route) => route.fulfill({ json: status }));
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: list }));
  await page.goto(url);
}

const empty = (page: Page) => page.locator(".board-content .empty");

test("a first scan that has read one company says it is running, not that filters emptied the board", async ({ page }) => {
  await board(page, firstScan());

  await expect(empty(page).getByText(msg("radar-first-scan-running-title"))).toBeVisible();
  await expect(empty(page)).toContainText(msg("radar-first-scan-progress", { read: "12", total: "150" }));
  // 12 read in 4 minutes: 138 left at 3 a minute, 46 minutes, or 47 once
  // the seconds since the fixture was built count too.
  const text = await empty(page).innerText();
  expect([46, 47].some((minutes) => text.includes(msg("radar-first-scan-back-minutes", { minutes })))).toBe(true);
  await expect(page.getByText(msg("radar-empty-filtered-title"))).toHaveCount(0);
  await expect(page.getByText(msg("radar-empty-fit-title"))).toHaveCount(0);
  await expect(page.getByText(/No roles fit yet/)).toHaveCount(0);
  // The dots are decoration: the title reads once, without them.
  await expect(empty(page).locator(".scan-dots")).toHaveAttribute("aria-hidden", "true");
});

test("a third of the way through with nothing, the scan points at what the person is looking for", async ({ page }) => {
  await board(page, firstScan({}, { ever_read: 50 }));

  await expect(empty(page).getByText(msg("radar-first-scan-running-title"))).toBeVisible();
  const link = empty(page).getByRole("link", { name: msg("radar-first-scan-looking-for") });
  await expect(link).toHaveAttribute("href", "/profile/direction");
  await expect(empty(page)).toContainText(/50.*150/);
});

test("a scan the background service holds says why, without moving dots", async ({ page }) => {
  await board(page, firstScan({
    running: false,
    jobs: [{
      key: "scan", job: "scan", state: "waiting", reason: "waiting_for_mains", since: new Date().toISOString(),
      next_at: null, run_id: null, progress: null, waiting: null, queued: 1,
    }],
  }));

  await expect(empty(page).getByText(msg("radar-first-scan-held-title"))).toBeVisible();
  await expect(empty(page)).toContainText(msg("radar-first-scan-held", { reason: "waiting_for_mains" }));
  await expect(empty(page).locator(".scan-dots")).toHaveCount(0);
});

test("a stopped first scan offers Scan now, which asks for a scan", async ({ page }) => {
  await board(page, firstScan({ running: false, last_run_finished_at: new Date().toISOString() }));

  await expect(empty(page).getByText(msg("radar-first-scan-stopped-title"))).toBeVisible();
  await Promise.all([
    page.waitForRequest((req) => req.url().endsWith("/api/sync") && req.method() === "POST"),
    empty(page).getByRole("button", { name: msg("radar-first-scan-scan-now") }).click(),
  ]);
});

test("before the first scan starts the board says it is about to", async ({ page }) => {
  await board(page, firstScan({ running: false, last_success_at: null, last_run_started_at: null }, { ever_read: 0 }));

  await expect(empty(page).getByText(msg("radar-first-scan-starting-title"))).toBeVisible();
  await expect(empty(page)).toContainText(msg("radar-first-scan-starting"));
});

test("with every followed company read and nothing fitting, the board suggests more companies before Profile", async ({ page }) => {
  const status = firstScan({ running: false }, { ever_read: 150 });
  await board(page, { ...status, bindings_attention: { ...status.bindings_attention, followed: 150 } });

  await expect(empty(page).getByText(msg("radar-empty-few-title", { count: 150 }))).toBeVisible();
  await expect(empty(page)).toContainText(msg("radar-empty-few", { choice: "counted", more: "4,100" }));
  const links = empty(page).getByRole("link");
  // More companies first, then Profile: the person sees part of the market.
  await expect(links.nth(0)).toHaveText(msg("radar-empty-follow-more"));
  await expect(links.nth(0)).toHaveAttribute("href", "/settings/companies");
  await expect(links.nth(1)).toHaveText(msg("radar-empty-change-looking-for"));
  await expect(links.nth(1)).toHaveAttribute("href", "/profile/direction");
  await expect(page.getByText(msg("radar-empty-fit-title"))).toHaveCount(0);
  await expect(page.getByText(msg("radar-first-scan-running-title"))).toHaveCount(0);
});

test("following every company, nothing fitting points at Profile alone, and says while the others are still checked", async ({ page }) => {
  const read = firstScan({ running: false }, { ever_read: 150 });
  await board(page, read, EMPTY, "/", { following: true, checked: 4_123 });

  await expect(empty(page).getByText(msg("radar-empty-fit-title"))).toBeVisible();
  await expect(empty(page)).toContainText(msg("radar-empty-fit", { choice: "done", checked: "4,123", total: "4,123" }));
  await expect(empty(page).getByRole("link")).toHaveCount(1);
  await expect(empty(page).getByRole("link", { name: msg("radar-empty-change-looking-for") })).toHaveAttribute("href", "/profile/direction");

  await page.unroute("/api/companies/directory/status");
  await page.route("/api/companies/directory/status", (route) =>
    route.fulfill({ json: directoryStatus({ following: true, checked: 900 }) }));
  await page.goto("/");
  await expect(empty(page)).toContainText(msg("radar-empty-fit", { choice: "checking", checked: "900", total: "4,123" }));
});

test("when the board's own filters empty it, it says so and clears them", async ({ page }) => {
  await board(page, firstScan({ running: false }, { ever_read: 150 }), EMPTY, "/?company=amazon");

  await expect(empty(page).getByText(msg("radar-empty-filtered-title"))).toBeVisible();
  await empty(page).getByRole("button", { name: msg("radar-empty-filtered-clear") }).click();
  await expect(page).not.toHaveURL(/company=/);
});

test("during the first scan a filtered empty board says filters are on, and keeps the scan's words", async ({ page }) => {
  await board(page, firstScan({}, { ever_read: 50 }), EMPTY, "/?company=amazon");

  await expect(empty(page).getByText(msg("radar-first-scan-running-title"))).toBeVisible();
  await expect(empty(page)).toContainText(msg("radar-first-scan-filtered"));
  // The Profile pointer is about the person's choices, and filters are on.
  await expect(empty(page).getByRole("link", { name: msg("radar-first-scan-looking-for") })).toHaveCount(0);
});

test("a list during the first scan says how far it has got, and that more companies are left", async ({ page }) => {
  await board(page, firstScan(), twoJobList);

  await expect(page.locator(".board-first-scan-line"))
    .toHaveText(msg("radar-first-scan-line", { dots: "...", read: "12", total: "150" }));
  await expect(page.locator(".board-list-end")).toHaveText(msg("radar-end-scanning", { count: 138 }));
});

test("a list after the first pass ends on where to change what fits, or how to clear the filters", async ({ page }) => {
  await board(page, firstScan({ running: false }, { ever_read: 150 }), twoJobList);

  await expect(page.locator(".board-first-scan-line")).toHaveCount(0);
  const end = page.locator(".board-list-end");
  await expect(end.getByRole("link", { name: msg("radar-empty-follow-more") })).toHaveAttribute("href", "/settings/companies");
  await expect(end.getByRole("link", { name: msg("radar-end-change-looking-for") })).toHaveAttribute("href", "/profile/direction");

  await page.goto("/?company=amazon");
  await expect(end.getByRole("link")).toHaveCount(0);
  await end.getByRole("button", { name: msg("radar-empty-filtered-clear") }).click();
  await expect(page).not.toHaveURL(/company=/);
});

test("following every company, a list ends on Profile alone", async ({ page }) => {
  await board(page, firstScan({ running: false }, { ever_read: 150 }), twoJobList, "/", { following: true, checked: 4_123 });

  const end = page.locator(".board-list-end");
  await expect(end).toContainText(msg("radar-end-fit", { change: msg("radar-empty-change-looking-for") }));
  await expect(end.getByRole("link")).toHaveCount(1);
});

test("a list cut at its ranking ceiling keeps its own note and gets no end note", async ({ page }) => {
  await board(page, firstScan({ running: false }, { ever_read: 150 }), {
    ...twoJobList, ranking_truncated: true, matched: 900,
  });

  await expect(page.locator(".search-truncation-note")).toBeVisible();
  await expect(page.locator(".board-list-end")).toHaveCount(0);
});

test("roles found mid-scan reach an empty board without waiting for the scan to end", async ({ page }) => {
  let read = 12;
  let found = false;
  await installBoardRoutes(page);
  // Each status read finds a few more companies read; the scan never ends here.
  await page.route("/api/status", (route) => {
    read += 3;
    return route.fulfill({ json: firstScan({}, { ever_read: read }) });
  });
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: found ? twoJobList : EMPTY }));
  await page.clock.install();
  await page.goto("/");
  await expect(empty(page).getByText(msg("radar-first-scan-running-title"))).toBeVisible();

  // The scan has written roles. Under a minute the list is not read again,
  // however many companies land meanwhile.
  found = true;
  await page.clock.runFor(30_000);
  await expect(empty(page)).toBeVisible();

  await page.clock.runFor(35_000);
  await expect(page.getByText(twoJobList.items[0].title).first()).toBeVisible();
  await expect(empty(page)).toHaveCount(0);
});
