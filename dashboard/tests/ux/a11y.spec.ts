/* The automated half of the accessibility contract.

   The UI contract asks for "axe both themes"; this file is what runs it.

   Automated rules catch roughly a third of what matters. They cannot see focus
   order, whether a live region actually announces, or whether a keyboard user
   can reach the thing they came for — those are asserted directly in
   `app-shell.spec.ts` and `job-detail.spec.ts`. This file is the floor, not the
   ceiling. */

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "./fixtures";
import { installEveryRoute } from "./routesHarness";

/* Every route in the tab table, plus the two outside it. `/welcome` is the
   first thing a new user meets, so it is the last one that should be exempt. */
const ROUTES = [
  "/",
  "/favorites",
  "/profile",
  "/compare",
  "/statistics",
  "/company",
  "/review",
  "/notifications",
  "/settings",
  // Usage sharing's switches, install ID and next batch (docs/architecture.md).
  "/settings/privacy",
  "/welcome",
];

// Text contrast is independent of the separate border-contrast design decision.
// Both the sweep and its positive control use this exact scanner.
const scan = (page: Page) => new AxeBuilder({ page }).analyze();
type ScanResult = Awaited<ReturnType<typeof scan>>;
const seriousProblems = (result: ScanResult) => result.violations.filter((v) =>
  v.impact === "serious" || v.impact === "critical");
const outlineProblems = (result: ScanResult) => [...result.violations, ...result.incomplete].filter((v) =>
  v.id === "heading-order" || v.id === "aria-prohibited-attr");
test.use({ contextOptions: { reducedMotion: "reduce" } });

test.beforeEach(async ({ page }) => {
  await installEveryRoute(page);
});

for (const theme of ["light", "dark"] as const) {
  for (const path of ROUTES) {
    // First-run setup is always dark (shownTheme in src/shell/theme.ts), so
    // /welcome has no light page; welcome.spec.ts holds a light choice to it.
    if (path === "/welcome" && theme === "light") continue;
    test(`${path}: accessible contrast, heading order and names (${theme})`, async ({ page }) => {
      await page.addInitScript((value) => localStorage.setItem("theme", value), theme);
      await page.goto(path);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      const main = page.getByRole("main").first();
      await expect(main).toBeVisible();
      await expect(main.getByRole("heading").first()).toBeVisible();
      await page.evaluate(async () => {
        await document.fonts.ready;
        await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      });

      const result = await scan(page);
      expect(seriousProblems(result).map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join("; ")}`)).toEqual([]);
      // These moderate/incomplete rules are not covered by the severity filter.
      expect(outlineProblems(result).map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join("; ")}`)).toEqual([]);
      expect(result.passes.length, "axe reported no passing rules; it scanned nothing").toBeGreaterThan(5);
    });
  }
}

/* The wide filter register also has a concrete heading hierarchy and named
   landmarks. These assertions hold the actual outline beyond axe's rule set. */
for (const path of ["/", "/notifications"]) {
  test(`${path}: the outline steps one level at a time, and named chrome has a role`, async ({ page }) => {
    // Rail width: the register is in the page rather than behind the Filters
    // opener, so its headings are in the outline being read.
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(path);
    await expect(page.getByRole("main").first()).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toBeVisible();
    await expect(page.getByRole("group", { name: "Mission telemetry" })).toBeVisible();
    const { violations, incomplete } = await scan(page);
    const order = violations.find((v) => v.id === "heading-order");
    expect(order?.nodes.map((n) => n.html), "heading levels skip").toBeUndefined();
    const prohibited = [...violations, ...incomplete].find((v) => v.id === "aria-prohibited-attr");
    expect(prohibited?.nodes.map((n) => n.html), "aria-label on an element with no role").toBeUndefined();
    // The outline as a reader steps through it: the screen, then its register.
    const levels = await page.locator("main h1, main h2, main h3").evaluateAll((hs) =>
      hs.slice(0, 4).map((h) => `${h.tagName}:${h.textContent?.trim()}`),
    );
    expect(levels[0]).toMatch(/^H1:/);
    expect(levels[1]).toBe("H2:Filters");
    expect(levels[2]).toMatch(/^H3:/);
  });
}

/* Company profiles: the page, a roster section, then the company and its
   sections, one level at a time. Its section heads and the company name sat
   at h3 under the page's h1. */
test("/company: the outline steps one level at a time", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/company");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const { violations, incomplete } = await scan(page);
  const order = violations.find((v) => v.id === "heading-order");
  expect(order?.nodes.map((n) => n.html), "heading levels skip").toBeUndefined();
  const prohibited = [...violations, ...incomplete].find((v) => v.id === "aria-prohibited-attr");
  expect(prohibited?.nodes.map((n) => n.html), "aria-label on an element with no role").toBeUndefined();
  const levels = await page.locator("main h1, main h2, main h3").evaluateAll((hs) =>
    hs.map((h) => Number(h.tagName.slice(1))),
  );
  expect(levels[0]).toBe(1);
  expect(levels.every((level, i) => i === 0 || level <= levels[i - 1] + 1), levels.join(",")).toBe(true);
});

test("the accessibility scanner rejects unreadable text", async ({ page }) => {
  await page.setContent('<main><h1 style="color:#eee;background:#fff">Contrast control</h1></main>');
  const result = await scan(page);
  const contrast = seriousProblems(result).find((violation) => violation.id === "color-contrast");
  expect(contrast?.impact).toBe("serious");
  expect(contrast?.nodes.some((node) => node.html.includes("Contrast control"))).toBe(true);
});

test("the accessibility gate rejects skipped headings and names on elements without roles", async ({ page }) => {
  await page.setContent('<main><h1>Screen</h1><h3>Skipped section</h3><div aria-label="Wrong name">Content</div></main>');
  const result = await scan(page);
  expect(outlineProblems(result).map((violation) => violation.id).sort()).toEqual(["aria-prohibited-attr", "heading-order"]);
});
