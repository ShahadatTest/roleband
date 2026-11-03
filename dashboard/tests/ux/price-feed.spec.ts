/* Settings › Plugins › Stock prices: one kit
   row under the plugin list. The price service's key is write-only: it is
   typed in a dialog's password field, sent once, trimmed, and no response or
   screen shows it again. Every request is mocked; the catch-all guard in
   `fixtures.ts` fails any that is not. */

import { msg } from "../../src/test/msg";
import { priceFeedStateFixture, statusFixture } from "../../src/test/fixtures";
import { expect, mockApi, test } from "./fixtures";
import type { Page } from "./fixtures";
import { installSettingsRoutes } from "./settingsHarness";

const KEY = "tk_0123456789abcdef";

test.beforeEach(async ({ page }) => {
  await installSettingsRoutes(page);
});

const card = (page: Page) =>
  page.locator(".settings-card").filter({ has: page.getByRole("heading", { name: msg("settings-price-feed-title") }) });

test("a key is added in a dialog, saved trimmed, and never shown again", async ({ page }) => {
  const sent: unknown[] = [];
  await mockApi(page, ["PUT"], "/api/settings/price-feed", async (route) => {
    sent.push(route.request().postDataJSON());
    await route.fulfill({ json: priceFeedStateFixture({ configured: true, origin: "settings", key_check: "ok" }) });
  });
  await page.goto("/settings/plugins");

  const row = card(page).getByTestId("price-feed-row");
  await expect(row.getByText(msg("settings-price-feed-source"), { exact: true })).toBeVisible();
  await expect(row.getByTestId("price-feed-facts")).toHaveText(msg("settings-price-feed-key-state", { origin: "none" }));
  await expect(row.locator("input")).toHaveCount(0);

  await row.getByRole("button", { name: msg("settings-price-feed-add") }).click();
  const dialog = page.getByRole("dialog", { name: msg("settings-price-feed-dialog-title") });
  const field = dialog.getByLabel(msg("settings-price-feed-dialog-field"));
  await expect(field).toBeFocused();
  await expect(field).toHaveAttribute("type", "password");
  await field.fill(`  ${KEY} `);
  await dialog.getByRole("button", { name: msg("settings-price-feed-dialog-save", { choice: "no" }) }).click();

  await expect(dialog).toHaveCount(0);
  await expect(card(page).getByText(msg("settings-price-feed-saved", { check: "ok" }))).toBeVisible();
  expect(sent).toEqual([{ api_key: KEY }]);
  await expect(row.getByTestId("price-feed-facts")).toHaveText(msg("settings-price-feed-key-state", { origin: "settings" }));
  await expect(row.getByRole("button", { name: msg("settings-price-feed-remove") })).toBeVisible();
  await expect(page.locator("body")).not.toContainText(KEY);
});

test("the card is on the Plugins tab only, below the plugin list", async ({ page }) => {
  await page.goto("/settings/plugins");
  const heading = page.getByRole("heading", { name: msg("settings-price-feed-title") });
  await expect(heading).toBeVisible();
  const list = page.getByRole("region", { name: "Plugins" });
  const [listBox, headingBox] = [(await list.boundingBox())!, (await heading.boundingBox())!];
  expect(headingBox.y).toBeGreaterThan(listBox.y);

  await page.goto("/settings/retention");
  await expect(page.getByRole("tab", { name: msg("shell-tab-settings-retention") })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: msg("settings-price-feed-title") })).toHaveCount(0);
});

test("the row's text and actions stay inside the card at every width", async ({ page }) => {
  // A phone's narrow card is where the actions would clip past its edge.
  await page.route("/api/settings/price-feed", (route) =>
    route.fulfill({ json: priceFeedStateFixture({ configured: true, origin: "settings", priced: 66, as_of: "2026-10-09" }) }));
  await page.goto("/settings/plugins");
  const box = (await card(page).boundingBox())!;
  for (const control of [
    card(page).getByRole("link", { name: msg("shared-price-feed-get-key") }),
    card(page).getByRole("button", { name: msg("settings-price-feed-replace") }),
    card(page).getByRole("button", { name: msg("settings-price-feed-remove") }),
  ]) {
    await expect(control).toBeVisible();
    const b = (await control.boundingBox())!;
    expect(b.x).toBeGreaterThanOrEqual(box.x);
    expect(b.x + b.width).toBeLessThanOrEqual(box.x + box.width + 0.5);
  }
});


test("an open card follows the prices job: updating while it runs, then what it stored and what waits", async ({ page }) => {
  const job = (state: "running" | "idle") => ({
    key: "prices", job: "prices", state, reason: null, since: "2026-10-19T09:00:00Z", next_at: null,
    run_id: state === "running" ? 9 : null, progress: null, waiting: null, queued: 0,
  });
  let running = true;
  await page.route("/api/status", (route) =>
    route.fulfill({ json: { ...statusFixture, jobs: [job(running ? "running" : "idle")] } }));
  const later = new Date(Date.now() + 40 * 60_000).toISOString();
  let reads = 0;
  await mockApi(page, ["GET"], "/api/settings/price-feed", async (route) => {
    reads += 1;
    await route.fulfill({
      json: running
        ? priceFeedStateFixture({ configured: true, origin: "settings", priced: 1, as_of: "2026-10-16" })
        : priceFeedStateFixture({ configured: true, origin: "settings", priced: 50, as_of: "2026-10-16",
                                  last_run_at: new Date().toISOString(), waiting: 8, next_at: later }),
    });
  });
  await page.goto("/settings/plugins");
  const facts = card(page).getByTestId("price-feed-facts");
  await expect(facts).toContainText(msg("settings-price-feed-updating"));
  await expect(card(page).getByRole("button", { name: msg("settings-price-feed-update-now") })).toBeDisabled();

  running = false;
  await expect(facts).toContainText("50 companies", { timeout: 10_000 });
  await expect(facts).toContainText(/8 more in 40 minutes$/);
  expect(reads).toBeGreaterThanOrEqual(2);
  await expect(card(page).getByRole("button", { name: msg("settings-price-feed-update-now") })).toBeEnabled();
});

test("a key the price service refuses keeps the dialog open and says why", async ({ page }) => {
  await mockApi(page, ["PUT"], "/api/settings/price-feed", (route) =>
    route.fulfill({ status: 409, json: { detail: { code: "price-key-refused", params: {}, message: "refused" } } }));
  await page.goto("/settings/plugins");
  await card(page).getByRole("button", { name: msg("settings-price-feed-add") }).click();
  const dialog = page.getByRole("dialog", { name: msg("settings-price-feed-dialog-title") });
  await dialog.getByLabel(msg("settings-price-feed-dialog-field")).fill(KEY);
  await dialog.getByRole("button", { name: msg("settings-price-feed-dialog-save", { choice: "no" }) }).click();
  await expect(dialog.getByRole("alert")).toHaveText(msg("error-price-key-refused"));
  await expect(dialog).toBeVisible();
});
