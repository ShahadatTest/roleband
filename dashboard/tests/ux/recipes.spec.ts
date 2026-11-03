/* Settings › Recipes: preview a recipe without saving, open one,
   and scan a company with it. Every request is mocked; the catch-all guard in
   `fixtures.ts` fails any that is not. */

import { expect, test } from "./fixtures";
import { installSettingsRoutes } from "./settingsHarness";
import {
  recipeCheckFixture,
  recipeDetailFixture,
  recipeDocumentFixture,
  trackedCompanyFixture,
} from "../../src/test/fixtures";
import { mockApi, mockGet } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await installSettingsRoutes(page);
  await mockGet(page, "/api/connector-recipes/valve-jobs", (route) =>
    route.fulfill({ json: recipeDetailFixture() }));
  // After the harness, so this list wins for the screen's company picker.
  await mockGet(page, "/api/companies", (route) =>
    route.fulfill({ json: { companies: [trackedCompanyFixture()] } }));
});

test("the Recipes tab lists each recipe and what it scans", async ({ page }) => {
  await page.goto("/settings/recipes");
  await expect(page.getByRole("tab", { name: "Recipes" })).toHaveAttribute("aria-selected", "true");
  const region = page.getByRole("region", { name: "Recipes" });
  await expect(region.getByText("valve-jobs")).toBeVisible();
  await expect(region.getByText("version 1 in use · checked · scans valve")).toBeVisible();
});

test("a preview shows what the recipe reads and saves nothing", async ({ page }) => {
  let sent: unknown = null;
  let saved = false;
  await mockApi(page, "POST", "/api/connectors/preview", async (route) => {
    sent = route.request().postDataJSON();
    await route.fulfill({ json: recipeCheckFixture() });
  });
  await mockApi(page, "POST", "/api/connector-recipes", async (route) => {
    saved = true;
    await route.fulfill({ status: 201, json: { slug: "valve-jobs", revision_id: 8, version: 2 } });
  });
  await page.goto("/settings/recipes");
  await page.getByLabel("Recipe (JSON)").fill(JSON.stringify(recipeDocumentFixture));
  await page.getByRole("button", { name: "Preview" }).click();

  const result = page.getByLabel("Preview result");
  await expect(result.getByText("Game Designer")).toBeVisible();
  expect(sent).toEqual({ document: recipeDocumentFixture });
  expect(saved).toBe(false);
});

test("an opened recipe scans a company chosen from those RoleBand does not cover", async ({ page }) => {
  let bound: unknown = null;
  await mockApi(page, "POST", "/api/companies/valve/recipe", async (route) => {
    bound = route.request().postDataJSON();
    await route.fulfill({
      status: 201,
      json: { company: "valve", recipe: "valve-jobs", binding_id: 3, revision_id: 7, closure_capability: "none" },
    });
  });
  await page.goto("/settings/recipes");
  await page.getByRole("button", { name: "Open", exact: true }).click();
  await expect(page.getByLabel("Versions").getByText("Version 1")).toBeVisible();
  await page.getByRole("combobox", { name: "Company" }).selectOption("valve");
  await page.getByRole("button", { name: "Scan with it" }).click();

  await expect(page.getByText(/Valve is now scanned|valve is now scanned/)).toBeVisible();
  expect(bound).toEqual({ recipe: "valve-jobs" });
});

test("the editor fits a phone-width screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/settings/recipes");
  const editor = page.getByLabel("Recipe (JSON)");
  await expect(editor).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
