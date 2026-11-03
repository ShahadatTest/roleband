/* A fresh install, no plugin on: RoleBand's own data prices roles by their
   base alone, and many postings state their own base range. The Board's Base
   column shows one figure of one kind, base salary, and never a total. */

import { expect, test } from "./fixtures";
import { jobFixture, jobListFixture } from "../../src/test/fixtures";
import { installBoardRoutes } from "./boardHarness";
import { mockGet } from "./fixtures";

const noTotal = { comp_low: null, comp_high: null, comp_median: null };
const estimated = {
  ...jobFixture, ...noTotal,
  id: 511,
  title: "Senior Product Manager, Estimated Base",
  comp_base_low: 212_500, comp_base_median: 250_000, comp_base_high: 287_500,
};
const totalAndBase = { ...jobFixture, id: 512, title: "Staff Product Manager, Priced",
  comp_low: 500_000, comp_high: 700_000, comp_median: 600_000 };
const unpriced = { ...jobFixture, ...noTotal, id: 513, title: "Product Manager, Unpriced",
  comp_base_low: null, comp_base_median: null, comp_base_high: null };
// A figure wider than its column: a posted range in another currency, per month.
const posted = { ...jobFixture, ...noTotal, id: 514, title: "Product Manager, Posted",
  locations: ["San Jose, California, United States of America"],
  posted_base: { min: 987_654_321_000, max: 999_999_999_000, currency: "CHF", period: "month" } };

test.beforeEach(async ({ page }) => {
  await installBoardRoutes(page);
  await mockGet(page, "/api/jobs?**", (route) => route.fulfill({ json: {
    ...jobListFixture, total: 4, items: [estimated, totalAndBase, unpriced, posted],
  } }));
});

test("the Base column shows one base figure per row, its source on hover, and nothing when none is known", async ({ page }) => {
  await page.goto("/");
  const comp = (title: string) => page.locator(".job-row").filter({ hasText: title }).locator(".comp");

  await expect(comp(estimated.title)).toHaveText("$250K Our estimate for this level");
  await expect(comp(estimated.title)).toHaveAttribute("title", "Our estimate for this level");
  // A total is never what the column shows.
  await expect(comp(totalAndBase.title)).toHaveText(/^\$400K /);
  await expect(comp(unpriced.title)).toHaveText("Base salary not known");
  // Nothing a sighted reader sees: the only words are the screen reader's.
  await expect(comp(unpriced.title).locator(".sr-only")).toHaveCount(1);
  expect(await comp(unpriced.title).evaluate((el) => [...el.childNodes]
    .filter((n) => !(n instanceof HTMLElement && n.classList.contains("sr-only"))).map((n) => n.textContent).join(""))).toBe("");
  await expect(comp(posted.title)).toHaveAttribute("title", /^Posted range: /);
  await expect(page.locator(".list-head")).toContainText("Base");
  await expect(page.locator(".list-head")).not.toContainText("Est. TC");
});

test("a wide figure stays inside its column and never draws over the city", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "Rows are stacked cards on mobile: the figure has its own line.");
  await page.goto("/");
  const row = page.locator(".job-row").filter({ hasText: posted.title });
  await expect(row.locator(".comp")).toContainText("+");
  const boxes = await row.evaluate((el) => {
    const box = (sel: string) => el.querySelector(sel)!.getBoundingClientRect();
    const comp = el.querySelector(".comp") as HTMLElement;
    return { comp: box(".comp"), cell: box(".jr-comp"), loc: box(".jr-loc"),
             wider: comp.scrollWidth > box(".jr-comp").width };
  });
  expect(boxes.wider, "the fixture's figure is wider than the column, so the cut is what keeps it in").toBe(true);
  expect(boxes.comp.right).toBeLessThanOrEqual(boxes.cell.right + 1);
  expect(boxes.comp.left).toBeGreaterThanOrEqual(boxes.loc.right);
  expect(boxes.cell.left).toBeGreaterThanOrEqual(boxes.loc.right);
});
