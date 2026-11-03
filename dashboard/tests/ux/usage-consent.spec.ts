import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./fixtures";
import type { Page } from "./fixtures";
import type { Request } from "@playwright/test";
import {
  facetsFixture, jobListFixture, notificationsFixture, statsFixture, statusFixture, usageStateFixture,
} from "../../src/test/fixtures";
import type { UsageConsent, UsageState } from "../../src/api";
import { scopeCatalog, scopePreview } from "./scopeFixtures";

/* Usage sharing asks once, records the words it showed, and never asks over
   the welcome walk (docs/architecture.md):

   - a fresh install is asked between the radar intro and the walk;
   - a configured install from before sharing existed is asked once, in a
     dialog whose safe answer has focus and whose Escape is "No thanks";
   - an answered install is not asked; a group widened since is asked alone;
   - Settings > Privacy turns one kind on with the words beside its switch.

   Every request is mocked; the catch-all below fails any other. */

const SAID_USAGE = "Anonymous usage data: Which screens and features you use, and how scans go.";
const SAID_NEVER = "Never sent: company names, role titles, compensation, your CV or anything you type.";

test.beforeEach(async ({ page }) => {
  await page.route("/api/**", async (route) => {
    await route.abort("blockedbyclient");
    throw new Error(`Unmocked usage-consent API request: ${route.request().method()} ${route.request().url()}`);
  });
  // The page-level guard outranks the context fixtures: repeat the bootstrap reads.
  await page.route("/api/companies/names", (route) => route.fulfill({ json: { names: {} } }));
  await page.route("/api/compare-selection", (route) => route.fulfill({ json: { job_ids: [] } }));
  await page.route("/api/settings/locale", (route) => route.fulfill({ json: { language: "en", region: null } }));
  await page.route("/api/stats", (route) => route.fulfill({ json: statsFixture }));
  await page.route("/api/status", (route) => route.fulfill({ json: statusFixture }));
  await page.route("/api/facets", (route) => route.fulfill({ json: facetsFixture }));
  await page.route("/api/notifications**", (route) => route.fulfill({ json: notificationsFixture }));
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: jobListFixture }));
  await page.route("/api/scope/catalog", (route) => route.fulfill({ json: scopeCatalog }));
  await page.route("/api/scope/preview", (route) => route.fulfill({ json: scopePreview }));
  await page.route("/api/scope/rules", (route) => route.fulfill({ json: { rules: [] } }));
  await page.route("/api/companies", (route) => route.fulfill({ json: { companies: [] } }));
  // The radar intro says how many companies are within reach.
  await page.route("/api/companies/directory/status", (route) => route.fulfill({
    json: { size: 12_500, following: false, since: null, checked: 0, to_check: 12_500, with_roles: 0, waiting_for_power: false },
  }));
  // An install that already shares starts PostHog's library; answer it here
  // (what it sends is sharing-canary.spec.ts's subject, not this file's).
  await page.route(/^https:\/\/[^/]*posthog\.com\//, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
});

/** Serve `state` for GET /api/usage and record every consent PUT. */
async function usageServer(page: Page, state: UsageState) {
  const answers: UsageConsent[] = [];
  let reads = 0;
  let current = state;
  await page.route("/api/usage", (route) => {
    reads += 1;
    return route.fulfill({ json: current });
  });
  await page.route("/api/usage/consent", async (route) => {
    const body = route.request().postDataJSON() as UsageConsent;
    answers.push(body);
    current = {
      ...current,
      groups: current.groups.map((group) =>
        group.group in body.answers
          ? { ...group, status: body.answers[group.group] ? "shared" : "declined" }
          : group,
      ),
    };
    await route.fulfill({ json: current });
  });
  return { answers, reads: () => reads };
}

async function configured(page: Page) {
  await page.route("/api/profile", (route) => route.fulfill({
    json: { profile: null, scope_configured: true, intent_statement: "" },
  }));
}

const posthogRequests = (page: Page) => {
  const seen: Request[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).hostname.endsWith("posthog.com")) seen.push(request);
  });
  return seen;
};

test("a fresh install is asked before the walk, and the record is the words it showed", async ({ page }) => {
  await page.route("/api/profile", (route) => route.fulfill({
    json: { profile: null, scope_configured: false, intent_statement: "" },
  }));
  const usage = await usageServer(page, usageStateFixture("undecided"));
  const posthog = posthogRequests(page);

  await page.goto("/");
  await expect(page).toHaveURL(/\/welcome$/);
  await page.getByRole("button", { name: "Tune the radar" }).click();

  const question = page.getByRole("region", { name: "Help us improve" });
  await expect(question).toBeVisible();
  await expect(question).toContainText("free and open source");
  await expect(question.getByRole("checkbox")).toHaveCount(0);
  await question.getByRole("button", { name: "Happy to help" }).click();

  await expect(page).toHaveURL(/\/profile\/direction\?setup=1$/);
  await expect(page.getByRole("heading", { name: "What kind of role are you looking for?" })).toBeVisible();
  expect(usage.answers).toHaveLength(1);
  const [answer] = usage.answers;
  expect(answer.answers).toEqual({ usage: true, crashes: true, questions: true });
  expect(answer.fingerprints).toEqual({
    usage: "usage-fingerprint", crashes: "crashes-fingerprint", questions: "questions-fingerprint",
  });
  expect(answer.locale).toBe("en");
  expect(answer.text.split("\n\n")).toContain(SAID_USAGE);
  expect(answer.text.split("\n\n")).toContain(SAID_NEVER);
  expect(answer.text.startsWith("Help us improve\n\nWe're free and open source")).toBe(true);
  expect(answer.text).not.toContain("Session recordings");
  expect(posthog).toEqual([]);
});

test("declining on the welcome walk shares nothing and the walk goes on", async ({ page }) => {
  await page.route("/api/profile", (route) => route.fulfill({
    json: { profile: null, scope_configured: false, intent_statement: "" },
  }));
  const usage = await usageServer(page, usageStateFixture("undecided"));
  const posthog = posthogRequests(page);
  await page.goto("/welcome");
  await page.getByRole("button", { name: "Tune the radar" }).click();
  await page.getByRole("button", { name: "No thanks" }).click();
  await expect(page).toHaveURL(/\/profile\/direction\?setup=1$/);
  await expect(page.getByRole("heading", { name: "What kind of role are you looking for?" })).toBeVisible();
  expect(usage.answers.map((a) => a.answers)).toEqual([
    { usage: false, crashes: false, questions: false },
  ]);
  expect(posthog).toEqual([]);
});

test("an answered install goes straight from the intro to the walk", async ({ page }) => {
  await page.route("/api/profile", (route) => route.fulfill({
    json: { profile: null, scope_configured: false, intent_statement: "" },
  }));
  await usageServer(page, usageStateFixture("declined"));
  await page.goto("/welcome");
  await page.getByRole("button", { name: "Tune the radar" }).click();
  await expect(page).toHaveURL(/\/profile\/direction\?setup=1$/);
  await expect(page.getByRole("heading", { name: "What kind of role are you looking for?" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Help us improve" })).toHaveCount(0);
});

test("a configured install is asked once; the safe answer has focus and Escape declines", async ({ page }) => {
  await configured(page);
  const usage = await usageServer(page, usageStateFixture("undecided"));
  await page.goto("/");
  const dialog = page.getByRole("dialog", { name: "Help us improve" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "No thanks" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect.poll(() => usage.answers.length).toBe(1);
  expect(usage.answers[0].answers).toEqual({ usage: false, crashes: false, questions: false });
});

test("ticking kinds in the dialog shares exactly those, and the dialog fits a phone", async ({ page }) => {
  await configured(page);
  await page.setViewportSize({ width: 375, height: 740 });
  const usage = await usageServer(page, usageStateFixture("undecided"));
  await page.goto("/");
  const dialog = page.getByRole("dialog", { name: "Help us improve" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Session recordings")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Let me choose" }).click();
  // Clicking the row's sentence ticks its box: the row is the hit target.
  await dialog.getByText("An occasional one-question survey. Skip any you like.").click();
  await expect(dialog.getByRole("checkbox", { name: /Feedback surveys/ })).toBeChecked();
  await expect(dialog.getByRole("checkbox", { name: /Crash reports/ })).not.toBeChecked();
  // Nothing is cut off at phone width: no sideways scroll, both answers visible side by side.
  const overflow = await dialog.evaluate((node) => node.scrollWidth - node.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const decline = await dialog.getByRole("button", { name: "No thanks" }).boundingBox();
  const share = await dialog.getByRole("button", { name: "Happy to help" }).boundingBox();
  expect(decline && share && Math.abs(decline.width - share.width)).toBeLessThan(1);
  expect(decline && share && Math.abs(decline.y - share.y)).toBeLessThan(1);
  await dialog.getByRole("button", { name: "Happy to help" }).click();
  await expect(dialog).toHaveCount(0);
  expect(usage.answers.map((a) => a.answers)).toEqual([{ usage: false, crashes: false, questions: true }]);
});

test("an answered install is not asked", async ({ page }) => {
  await configured(page);
  await usageServer(page, usageStateFixture("shared"));
  // Count the reads that FINISH, not the requests: under the dev server
  // React's StrictMode mounts App twice and the first read is aborted on
  // cleanup, so a request count of 1 holds only against the build. An aborted
  // read fails; the read the app keeps finishes, once, in both modes.
  let finished = 0;
  page.on("requestfinished", (request) => {
    if (new URL(request.url()).pathname === "/api/usage") finished += 1;
  });
  await page.goto("/");
  await expect.poll(() => finished).toBeGreaterThan(0);
  await page.waitForTimeout(400);
  await expect(page.getByRole("dialog", { name: "Help us improve" })).toHaveCount(0);
  expect(finished, "the sharing state is read once").toBe(1);
});

test("a group widened since it was shared is asked alone", async ({ page }) => {
  await configured(page);
  const state = usageStateFixture("shared");
  state.groups = state.groups.map((group) => (group.group === "crashes" ? { ...group, status: "stale" } : group));
  const usage = await usageServer(page, state);
  await page.goto("/");
  const dialog = page.getByRole("dialog", { name: "Help us improve" });
  await expect(dialog.getByText("Crash reports")).toBeVisible();
  await expect(dialog.getByText("Anonymous usage data")).toHaveCount(0);
  // One kind: nothing to choose between.
  await expect(dialog.getByRole("button", { name: "Let me choose" })).toHaveCount(0);
  await dialog.getByRole("button", { name: "Happy to help" }).click();
  await expect(dialog).toHaveCount(0);
  expect(usage.answers.map((a) => a.answers)).toEqual([{ crashes: true }]);
});

test("Settings › Privacy turns one kind on with the words beside it", async ({ page }) => {
  await configured(page);
  const usage = await usageServer(page, usageStateFixture("declined", { pending_events: 1 }));
  await page.route("/api/usage/preview", (route) => route.fulfill({
    json: { body: { api_key: "phc_test", batch: [{ event: "daily_action", properties: { action: "save_job", count: 3 } }] }, left_out: 0 },
  }));
  await page.goto("/settings/privacy");
  const usageSwitch = page.getByRole("checkbox", { name: "Anonymous usage data" });
  await expect(usageSwitch).not.toBeChecked();
  await usageSwitch.click();
  await expect(usageSwitch).toBeChecked();
  expect(usage.answers).toHaveLength(1);
  expect(usage.answers[0].answers).toEqual({ usage: true });
  expect(usage.answers[0].text.split("\n\n")).toEqual(["Help us improve", SAID_USAGE, SAID_NEVER]);
  await page.getByRole("button", { name: "Show what's sent" }).click();
  await expect(page.getByLabel("Next send")).toContainText('"action": "save_job"');
});

test.describe("accessibility", () => {
  // As the a11y sweep does: a dialog caught mid fade-in has blended colours.
  test.use({ contextOptions: { reducedMotion: "reduce" } });

test("the question passes axe in both themes", async ({ page }) => {
  await configured(page);
  await usageServer(page, usageStateFixture("undecided"));
  for (const theme of ["light", "dark"] as const) {
    await page.addInitScript((value) => localStorage.setItem("theme", value), theme);
    await page.goto("/");
    await expect(page.getByRole("dialog", { name: "Help us improve" })).toBeVisible();
    await page.evaluate(async () => {
      await document.fonts.ready;
      await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    });
    const { violations } = await new AxeBuilder({ page }).include('[role="dialog"]').analyze();
    const serious = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious.map((v) => `${theme} ${v.id}: ${v.nodes.map((node) => `${node.target.join(" ")} ${node.failureSummary ?? ""}`).join(" | ")}`)).toEqual([]);
  }
});
});
