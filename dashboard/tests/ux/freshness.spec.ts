import { msg } from "../../src/test/msg";
import { jobListFixture, statsFixture, statusFixture } from "../../src/test/fixtures";
import { installBoardRoutes } from "./boardHarness";
import { expect, mockGet, test } from "./fixtures";

for (const hasHistory of [false, true]) {
  test(`the badge follows ${hasHistory ? "a repeat" : "the first"} scan without duplicating its progress`, async ({ page }, testInfo) => {
    await page.clock.install();
    await installBoardRoutes(page);
    let current = {
      ...statusFixture,
      last_success_at: hasHistory ? statusFixture.last_success_at : null,
      last_success_age_hours: hasHistory ? 2 : null,
      stale: !hasHistory,
    };
    await mockGet(page, "/api/status", (route) => route.fulfill({ json: current }));
    if (!hasHistory) {
      await mockGet(page, "/api/stats", (route) => route.fulfill({ json: {
        ...statsFixture, open_total: 0, new_today: 0, saved_total: 0, by_company: {},
      } }));
      await mockGet(page, "/api/jobs?**", (route) => route.fulfill({ json: {
        ...jobListFixture, total: 0, items: [],
      } }));
    }
    await page.goto("/");
    const badge = page.getByRole("status", { name: /Last scan/ });
    const text = badge.locator("strong");
    const idleText = hasHistory
      ? msg("shell-freshness-checked", { age: msg("format-age-hours", { count: 2 }) })
      : msg("shell-freshness-never");
    await expect(text).toHaveText(idleText);
    await expect(badge).toBeVisible();
    await expect(badge).toHaveAttribute("aria-label", msg("shell-freshness-aria", { state: idleText }));
    if (testInfo.project.name === "chromium") await expect(text).toBeVisible();
    const previousTitle = await badge.getAttribute("title");

    current = { ...current, running: true, stale: true, last_run_seen: 73 };
    await page.reload();
    await expect(text).toHaveText(msg("shell-scan-scanning"));
    await expect(badge).toHaveAttribute("aria-label", msg("shell-freshness-aria", { state: msg("shell-scan-scanning") }));
    if (testInfo.project.name === "chromium") await expect(text).toBeVisible();
    await expect(badge).not.toHaveClass(/stale/);
    await expect(badge).toHaveAttribute("title", previousTitle!);
    const scan = page.getByRole("button", { name: msg("shell-scan-in-progress-aria") });
    await expect(scan).toContainText(msg("shell-scan-found", { count: 73 }));
    await expect(text).not.toContainText("73");

    current = {
      ...current, running: false, stale: false,
      last_success_at: "2026-10-13T00:00:00Z", last_success_age_hours: 0.25,
      last_scan_at: "2026-10-13T00:00:00Z", last_scan_age_hours: 0.25,
    };
    await page.clock.runFor(3_100);
    await expect(text).toHaveText(msg("shell-freshness-checked", {
      age: msg("format-age-minutes", { count: 15 }),
    }));
    await expect(badge).toHaveAttribute("aria-label", msg("shell-freshness-aria", {
      state: msg("shell-freshness-checked", { age: msg("format-age-minutes", { count: 15 }) }),
    }));
    expect(await badge.getAttribute("title")).toContain(msg("shell-freshness-oldest", { when: "" }));
    expect(await badge.getAttribute("title")).not.toBe(previousTitle);
  });
}
