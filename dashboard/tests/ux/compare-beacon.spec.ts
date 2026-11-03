/* The ledger margin: from a selection to the comparison. Selecting a second
   role raises a
   beacon in the page margin to the RIGHT of the list, level with the row
   selected last. The list itself does not change: no row grows, nothing
   covers the next row. Click goes to Compare; hover reveals the roster where
   a role can be taken out. Geometry is the claim, so geometry is asserted. */

import { expect, mockApi, test } from "./fixtures";
import { comparison, installBoardRoutes } from "./boardHarness";
import { msg } from "../../src/test/msg";

test.beforeEach(async ({ page }) => {
  await installBoardRoutes(page);
  await page.route("/api/profile", (route) =>
    route.fulfill({ json: { profile: null, scope_configured: true } }));
});

test("a second selection raises the beacon beside the row selected last, outside the list, and it leads to the comparison", async ({ page, isMobile }) => {
  test.skip(isMobile, "the margin exists from 1100px; the phone form docks (covered below)");
  await page.goto("/");
  const first = page.getByRole("article").filter({ hasText: "Staff Product Manager, API" });
  const second = page.getByRole("article").filter({ hasText: "Principal Engineer, Platform" });
  await expect(second).toBeVisible();

  await first.getByRole("button", { name: msg("jobs-compare") }).click();
  await expect(page.getByRole("button", { name: /in compare/ })).toHaveCount(0);

  await second.getByRole("button", { name: msg("jobs-compare") }).click();
  const pill = page.getByRole("button", { name: "2 in compare. Compare 2 roles" });
  await expect(pill).toBeVisible();

  // Outside the list, level with the row: the pill's left edge is past the
  // list's right edge, and its vertical centre falls inside the row's box.
  const list = (await page.locator(".job-list").first().boundingBox())!;
  const rowBox = (await second.boundingBox())!;
  const pillBox = (await pill.boundingBox())!;
  expect(pillBox.x).toBeGreaterThanOrEqual(list.x + list.width);
  const centre = pillBox.y + pillBox.height / 2;
  expect(centre).toBeGreaterThan(rowBox.y);
  expect(centre).toBeLessThan(rowBox.y + rowBox.height);
  // Nothing in the list changed shape for it.
  expect((await second.boundingBox())!.height).toBe(rowBox.height);

  // Hover reveals the roster; one role can be taken out from there.
  await pill.hover();
  const reveal = page.getByRole("dialog", { name: "In compare" });
  await expect(reveal).toBeVisible();
  await expect(reveal).toContainText("Staff Product Manager, API");
  await expect(reveal).toContainText("Principal Engineer, Platform");
  await reveal.getByRole("button", { name: "Remove Staff Product Manager, API from compare" }).click();
  await expect(pill).toHaveCount(0);
  await expect(first.getByRole("button", { name: msg("jobs-compare") })).toHaveAttribute("aria-pressed", "false");

  // Back to two, and the pill itself is the way on.
  await first.getByRole("button", { name: msg("jobs-compare") }).click();
  const again = page.getByRole("button", { name: "2 in compare. Compare 2 roles" });
  // The newest selection is now the FIRST row: the beacon moved to it.
  const firstBox = (await first.boundingBox())!;
  const againBox = (await again.boundingBox())!;
  expect(againBox.y + againBox.height / 2).toBeGreaterThan(firstBox.y);
  expect(againBox.y + againBox.height / 2).toBeLessThan(firstBox.y + firstBox.height);
  await again.click();
  await expect(page).toHaveURL(/\/compare$/);
  await expect(comparison(page)).toContainText("Comparing 2 roles");
});

test("on a phone the beacon docks to the edge and still carries the count and the roster", async ({ page, isMobile }) => {
  test.skip(!isMobile, "the docked form is the phone form");
  await page.goto("/");
  const first = page.getByRole("article").filter({ hasText: "Staff Product Manager, API" });
  const second = page.getByRole("article").filter({ hasText: "Principal Engineer, Platform" });
  await first.getByRole("button", { name: msg("jobs-compare") }).click();
  await second.getByRole("button", { name: msg("jobs-compare") }).click();
  const pill = page.getByRole("button", { name: "2 in compare. Compare 2 roles" });
  await expect(pill).toBeVisible();
  await expect(pill.locator("xpath=..")).toHaveAttribute("data-docked", "true");
  // No hover here: the tap opens the reveal, whose primary is the way on.
  await pill.click();
  const reveal = page.getByRole("dialog", { name: "In compare" });
  await expect(reveal).toBeVisible();
  await reveal.getByRole("button", { name: "Compare 2 roles" }).click();
  await expect(page).toHaveURL(/\/compare$/);
});

/* Persistence. Held only in a `useState`, the selection would drop its roles
   and the count on a reload, or on opening a role in a new tab, with no
   explanation, while the star beside the same row survived. */

test("the selection and its count survive a reload", async ({ page, isMobile }) => {
  test.skip(isMobile, "the margin beacon's desktop form; the docked form is covered above");
  await page.goto("/");
  const first = page.getByRole("article").filter({ hasText: "Staff Product Manager, API" });
  const second = page.getByRole("article").filter({ hasText: "Principal Engineer, Platform" });
  await first.getByRole("button", { name: msg("jobs-compare") }).click();
  await second.getByRole("button", { name: msg("jobs-compare") }).click();
  await expect(page.getByRole("button", { name: "2 in compare. Compare 2 roles" })).toBeVisible();

  await page.reload();

  // The count comes back, and so does the state of the rows that produced it:
  // a selected row's toggle offers the way OUT, which is how the row says it is
  // in the comparison.
  await expect(page.getByRole("button", { name: "2 in compare. Compare 2 roles" })).toBeVisible();
  await expect(first.getByRole("button", { name: msg("jobs-compare") })).toHaveAttribute("aria-pressed", "true");
  await expect(second.getByRole("button", { name: msg("jobs-compare") })).toHaveAttribute("aria-pressed", "true");
});

test("a reload lands on the comparison itself, not on its empty state", async ({ page, isMobile }) => {
  test.skip(isMobile, "desktop form");
  await page.goto("/");
  const first = page.getByRole("article").filter({ hasText: "Staff Product Manager, API" });
  const second = page.getByRole("article").filter({ hasText: "Principal Engineer, Platform" });
  await first.getByRole("button", { name: msg("jobs-compare") }).click();
  await second.getByRole("button", { name: msg("jobs-compare") }).click();
  await page.getByRole("button", { name: "2 in compare. Compare 2 roles" }).click();
  await expect(page).toHaveURL(/\/compare$/);

  await page.reload();

  // Arriving with a selection must never read as having none, not even briefly.
  await expect(comparison(page)).toContainText("Comparing 2 roles");
  await expect(page.getByText("Pick at least two")).toHaveCount(0);
});

test("clearing is durable too: the selection does not come back on reload", async ({ page, isMobile }) => {
  test.skip(isMobile, "desktop form");
  await page.goto("/");
  const first = page.getByRole("article").filter({ hasText: "Staff Product Manager, API" });
  const second = page.getByRole("article").filter({ hasText: "Principal Engineer, Platform" });
  await first.getByRole("button", { name: msg("jobs-compare") }).click();
  await second.getByRole("button", { name: msg("jobs-compare") }).click();
  const pill = page.getByRole("button", { name: "2 in compare. Compare 2 roles" });
  await pill.hover();
  await page.getByRole("dialog", { name: "In compare" }).getByRole("button", { name: "Clear" }).click();
  await expect(pill).toHaveCount(0);

  await page.reload();

  await expect(page.getByRole("button", { name: /in compare/ })).toHaveCount(0);
  await expect(first.getByRole("button", { name: msg("jobs-compare") })).toHaveAttribute("aria-pressed", "false");
});

test("a selection that did not save says so with one role picked, and Try again saves it", async ({ page }) => {
  // The beacon stands only from two roles, so a warning in its reveal alone
  // would say nothing about a failed first pick.
  const sent: number[][] = [];
  let failNext = true;
  let stored: number[] = [];
  await mockApi(page, ["GET", "PUT"], "/api/compare-selection", async (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as { job_ids: number[] };
      sent.push(body.job_ids);
      if (failNext) {
        failNext = false;
        await route.fulfill({ status: 500, json: { detail: "unavailable" } });
        return;
      }
      stored = body.job_ids;
    }
    await route.fulfill({ json: { job_ids: stored } });
  });
  await page.goto("/");
  const first = page.getByRole("article").filter({ hasText: "Staff Product Manager, API" });

  await first.getByRole("button", { name: msg("jobs-compare") }).click();

  const alert = page.getByText("Couldn't save what you're comparing. It may be gone after a reload.");
  await expect(alert).toBeVisible();
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(alert).toHaveCount(0);
  expect(sent).toEqual([[101], [101]]);
});
