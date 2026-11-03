import { expect, mockApi, mockGet, test } from "./fixtures";
import { cloudModelProfileFixture } from "../../src/test/fixtures";
import { msg } from "../../src/test/msg";
import { expectOnTop, pointAndClick } from "./paint";
import { installSettingsRoutes, intelligence } from "./settingsHarness";

test.beforeEach(async ({ page }) => {
  await installSettingsRoutes(page);
});

for (const theme of ["light", "dark"] as const) {
  test(`posting text permission names destinations, cancels without a write, and confirms before enabling (${theme})`, async ({ page }) => {
    await page.addInitScript((value) => localStorage.setItem("theme", value), theme);
    await mockGet(page, "/api/intelligence/cloud-models", (route) => route.fulfill({ json: { profiles: [
      { ...cloudModelProfileFixture, enabled: true },
      { ...cloudModelProfileFixture, id: "c2", name: "Research service", base_url: "https://models.example.org/api" },
    ] } }));
    const writes: unknown[] = [];
    await mockApi(page, "PUT", "/api/intelligence/egress", (route) => {
      writes.push(route.request().postDataJSON());
      return route.fulfill({ json: { ...intelligence, routing: { egress_enabled: true, tiers: [] } } });
    });
    await page.goto("/settings/intelligence");
    await expect(page.getByLabel(msg("ai-capabilities-card-use", { name: cloudModelProfileFixture.name }))).toBeVisible();
    const gate = page.getByLabel(msg("ai-capabilities-card-send-postings-to-online-services"));
    await gate.click();
    const dialog = page.getByRole("dialog", { name: msg("ai-egress-title") });
    expect(await dialog.evaluate((el) => getComputedStyle(el).backgroundColor)).toMatch(/^rgb\(/);
    await expect(dialog.getByText(msg("ai-egress-detail"))).toBeVisible();
    await expect(dialog.getByText(cloudModelProfileFixture.name)).toBeVisible();
    await expect(dialog.getByText(cloudModelProfileFixture.base_url)).toBeVisible();
    await expect(dialog.getByText("Research service")).toBeVisible();
    await expect(dialog.getByText("https://models.example.org/api")).toBeVisible();
    expect(writes).toEqual([]);
    await expect(gate).not.toBeChecked();

    const cancel = dialog.getByRole("button", { name: msg("ai-aim-line-cancel") });
    await expectOnTop(cancel, "Cancel");
    await pointAndClick(page, cancel);
    await expect(dialog).toHaveCount(0);
    await expect(gate).toBeFocused();
    expect(writes).toEqual([]);
    await gate.click();
    const allow = dialog.getByRole("button", { name: msg("ai-egress-allow") });
    await expectOnTop(allow, "Allow");
    await pointAndClick(page, allow);
    await expect(gate).toBeChecked();
    await expect(dialog).toHaveCount(0);
    expect(writes).toEqual([{ enabled: true }]);
  });
}

test("Escape leaves the standing permission off before a service is connected", async ({ page }) => {
  await page.goto("/settings/intelligence");
  const gate = page.getByLabel(msg("ai-capabilities-card-send-postings-to-online-services"));
  await expect(gate).toBeEnabled();
  await gate.click();
  const dialog = page.getByRole("dialog", { name: msg("ai-egress-title") });
  await expect(dialog.getByText(msg("ai-egress-empty"))).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(gate).not.toBeChecked();
  await expect(gate).toBeFocused();
});

test("turning posting text permission off takes one click", async ({ page }) => {
  await mockGet(page, "/api/intelligence", (route) => route.fulfill({
    json: { ...intelligence, routing: { egress_enabled: true, tiers: [] } },
  }));
  const writes: unknown[] = [];
  await mockApi(page, "PUT", "/api/intelligence/egress", (route) => {
    writes.push(route.request().postDataJSON());
    return route.fulfill({ json: { ...intelligence, routing: { egress_enabled: false, tiers: [] } } });
  });
  await page.goto("/settings/intelligence");
  const gate = page.getByLabel(msg("ai-capabilities-card-send-postings-to-online-services"));
  await expect(gate).toBeChecked();
  await gate.click();
  await expect(gate).not.toBeChecked();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(writes).toEqual([{ enabled: false }]);
});
