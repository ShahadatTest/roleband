/* Keyboard shortcuts are advertised.
 *
 * Four keys work on the radar: `j`/`k` move between roles (JobList), `s` saves
 * and `c` adds to compare (JobCard). `?` opens a sheet that lists every one,
 * and the palette offers the same sheet by name.
 */

import { expect, test } from "./fixtures";
import { installBoardRoutes } from "./boardHarness";
import { msg } from "../../src/test/msg";

test.beforeEach(async ({ page }) => {
  await installBoardRoutes(page);
});

test("? opens the shortcuts, which name the role list's keys; Escape closes them and focus comes back", async ({ page }) => {
  await page.goto("/");
  const firstRole = page.getByRole("article").first();
  await firstRole.focus();

  await page.keyboard.press("?");
  const sheet = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(sheet).toBeVisible();
  for (const key of ["j", "k", "s", "c", "/", "?"]) {
    await expect(sheet.getByText(key, { exact: true }), `the sheet lists ${key}`).toBeVisible();
  }
  await expect(sheet.getByText("Next role")).toBeVisible();
  await expect(sheet.getByText("Add to compare or take it out")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
  await expect(firstRole).toBeFocused();
});

test("a ? typed into the search field is text, and opens nothing", async ({ page }) => {
  await page.goto("/");
  const search = page.getByPlaceholder(msg("radar-search-placeholder"));
  await search.click();
  await page.keyboard.type("c++?");
  await expect(search).toHaveValue("c++?");
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toHaveCount(0);
});

test("the palette opens the same shortcuts by name", async ({ page }) => {
  await page.goto("/");
  // The shell listens for the shortcut once it has rendered, which
  // waits on the company names: a key pressed at page load can land
  // before the listener exists (the palette.spec readiness rule).
  await expect(page.getByRole("article").first()).toBeVisible({ timeout: 15_000 });
  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  await page.keyboard.type("keyboard");
  await palette.getByRole("option", { name: /Keyboard shortcuts/ }).click();

  await expect(palette).toBeHidden();
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
});
