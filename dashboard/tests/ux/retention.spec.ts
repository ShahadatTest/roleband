/* Settings › Data retention: the deep link, the tab's place in the
   bar, a longer window that saves on the spot and a shorter one that waits for
   a confirm. Every request is mocked; the catch-all guard in
   `fixtures.ts` fails any that is not. */

import { expect, test } from "./fixtures";
import { installSettingsRoutes } from "./settingsHarness";
import { retentionStateFixture } from "../../src/test/fixtures";
import { mockApi } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await installSettingsRoutes(page);
});

test("the Data retention tab opens by its link, just before Privacy at the end of the bar", async ({ page }) => {
  await page.goto("/settings/retention");
  const tab = page.getByRole("tab", { name: "Data retention" });
  await expect(tab).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab").nth(-2)).toHaveText("Data retention");
  await expect(page.getByRole("tab").last()).toHaveText("Privacy");

  const region = page.getByRole("region", { name: "Data retention" });
  await expect(region.getByRole("combobox", { name: "Remove postings after" })).toHaveValue("60");
  await expect(region.getByText("1,240 kept · 210 no longer listed · 330 from companies you stopped following"))
    .toBeVisible();
  await expect(region.getByTestId("retention-due")).toHaveText("94 postings");
});

test("choosing a shorter time asks first, then saves it and says what is now due", async ({ page }) => {
  const sent: unknown[] = [];
  await mockApi(page, "PUT", "/api/settings/retention", async (route) => {
    sent.push(route.request().postDataJSON());
    await route.fulfill({ json: retentionStateFixture({ days: 14, due: 310 }) });
  });
  await page.goto("/settings/retention");
  const region = page.getByRole("region", { name: "Data retention" });

  await region.getByRole("combobox", { name: "Remove postings after" }).selectOption("14");
  await expect(region.getByText("With 14 days, 310 postings are due for removal. They're removed during the next scans."))
    .toBeVisible();
  expect(sent).toEqual([]);
  await region.getByRole("button", { name: "Remove after 14 days" }).click();

  await expect(region.getByText("Saved.")).toBeVisible();
  await expect(region.getByTestId("retention-due")).toHaveText("310 postings");
  expect(sent).toEqual([{ days: 14 }]);
});

test("Never is saved as no window at all", async ({ page }) => {
  const sent: unknown[] = [];
  await mockApi(page, "PUT", "/api/settings/retention", async (route) => {
    sent.push(route.request().postDataJSON());
    await route.fulfill({ json: retentionStateFixture({ days: null, due: 0 }) });
  });
  await page.goto("/settings/retention");
  const region = page.getByRole("region", { name: "Data retention" });

  await region.getByRole("combobox", { name: "Remove postings after" }).selectOption({ label: "Never" });

  await expect(region.getByText("Saved.")).toBeVisible();
  await expect(region.getByTestId("retention-due")).toHaveText("0 postings");
  await expect(region.getByText("Nothing is removed while this is set to Never.")).toBeVisible();
  expect(sent).toEqual([{ days: null }]);
});

test("what is due is a row of its own: a count in the data voice, its prose in the body voice, one hairline between rows", async ({ page }) => {
  // The status is its own row, count as fact, prose as description. A banner
  // between rows breaks the list in two; glued to the counts with a bare <br>
  // it reads "...stopped followingNothing is due for removal." as one run of
  // mono prose.
  await page.goto("/settings/retention");
  const region = page.getByRole("region", { name: "Data retention" });
  const due = region.getByTestId("retention-due");
  await expect(due).toHaveText("94 postings");
  await expect(due).toHaveCSS("font-family", /Mono/);
  const detail = region.getByText("Due postings are removed during scans, never by saving.");
  await expect(detail).toBeVisible();
  await expect(detail).not.toHaveCSS("font-family", /Mono/);
  await expect(region.locator(".settings-row-facts").first())
    .toHaveText("1,240 kept · 210 no longer listed · 330 from companies you stopped following");
  const borders = () => region.locator(".settings-row").evaluateAll((rows) =>
    rows.map((row) => getComputedStyle(row).borderTopWidth));
  expect(await borders()).toEqual(["0px", "1px", "1px"]);

  // A confirm between the rows is an aside in the list: the next row keeps its hairline.
  await region.getByRole("combobox", { name: "Remove postings after" }).selectOption("14");
  await expect(region.getByRole("button", { name: "Remove after 14 days" })).toBeVisible();
  expect(await borders()).toEqual(["0px", "1px", "1px"]);
});
