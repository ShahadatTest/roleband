import { expect, test } from "./fixtures";
import { msg } from "../../src/test/msg";
import { uxProfile } from "./runProfile";

// The deck is a dev-only endpoint; it is absent from the shipped artifact.
test("review deck finds a message and shows its translation beside the English", async ({ page }) => {
  test.skip(uxProfile().mode !== "dev", "development-only review endpoint");
  const catalog = page.waitForResponse((response) => new URL(response.url()).pathname === "/__copy-review/data");
  await page.goto("/__copy-review/");
  const response = await catalog;
  expect(response.ok()).toBe(true);
  await response.finished();
  await expect(page.getByRole("heading", { name: msg("review-title") })).toBeVisible();

  const search = page.getByRole("searchbox", { name: msg("review-search") });
  await expect(search).toBeEnabled();
  await search.fill("companies-data-curated-follow-failed");
  await expect(page.getByRole("heading", { name: "companies-data-curated-follow-failed", exact: true })).toBeVisible();

  // A current Spanish translation renders in Spanish beside its English. (A
  // quarantined one renders the English: contracts.test.ts.)
  await page.getByRole("combobox", { name: msg("review-status") }).selectOption("current");
  await expect(page.locator("article")).toHaveCount(1);
  const samples = page.locator("article .review-columns");
  await expect(samples).not.toHaveCount(0);
  const [english, spanish] = await samples.first().locator(".review-sample").allTextContents();
  expect(english).toMatch(/^Couldn't follow the/);
  expect(spanish).toMatch(/^Error al seguir/);

  await search.fill("there-is-no-such-message");
  await expect(page.locator("article")).toHaveCount(0);
});
