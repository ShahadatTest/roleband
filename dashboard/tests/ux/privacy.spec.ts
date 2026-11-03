/* Settings › Privacy in a real browser: what jsdom cannot see. The switch in
   a kit row is a switch (the row's 15px checkbox box must not collapse its
   32x18 track into a dot, and nothing but a browser measures a track), the
   whole row turns it, the card is named by its tab with the consent
   question's title over its switches, what is never sent is the intro rather
   than a boxed note, so the rows keep one hairline rhythm. Every request is
   mocked; the catch-all guard in `fixtures.ts` fails any that is not. */

import type { UsageConsent, UsageState } from "../../src/api";
import { usageStateFixture } from "../../src/test/fixtures";
import { msg } from "../../src/test/msg";
import { expect, test, type Page } from "./fixtures";
import { installSettingsRoutes } from "./settingsHarness";
import { expectOnTop, pointAndClick } from "./paint";

/** GET and PUT of the usage state, the way the server answers them. */
async function usageServer(page: Page, state: UsageState) {
  const answers: UsageConsent[] = [];
  let current = state;
  await page.route("/api/usage", (route) => route.fulfill({ json: current }));
  await page.route("/api/usage/consent", async (route) => {
    const body = route.request().postDataJSON() as UsageConsent;
    answers.push(body);
    current = {
      ...current,
      groups: current.groups.map((group) =>
        group.group in body.answers ? { ...group, status: body.answers[group.group] ? "shared" : "declined" } : group),
    };
    await route.fulfill({ json: current });
  });
  return answers;
}

test.beforeEach(async ({ page }) => {
  await installSettingsRoutes(page);
  // Turning a kind on starts the library; its own hosts answer nothing here.
  await page.route(/^https:\/\/[^/]*posthog\.com\//, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
});

/** A Switch's track and knob as drawn: the input box and its `::after`. */
function switchGeometry(page: Page, name: string) {
  return page.getByRole("checkbox", { name }).evaluate((track) => {
    const box = track.getBoundingClientRect();
    const knob = getComputedStyle(track, "::after");
    const shift = new DOMMatrixReadOnly(knob.transform === "none" ? undefined : knob.transform).m41;
    return {
      width: box.width,
      height: box.height,
      knobWidth: parseFloat(knob.width),
      knobRight: parseFloat(knob.left) + shift + parseFloat(knob.width),
      knobFill: knob.backgroundColor,
    };
  });
}

for (const theme of ["dark", "light"] as const) {
  test(`a switch in a kit row is a 32x18 track whose knob travels inside it (${theme})`, async ({ page }) => {
    await page.addInitScript((value) => localStorage.setItem("theme", value), theme);
    await usageServer(page, usageStateFixture("declined", {
      groups: usageStateFixture("declined").groups.map((g) => (g.group === "usage" ? { ...g, status: "shared" } : g)),
    }));
    await page.goto("/settings/privacy");

    for (const [name, on] of [["Anonymous usage data", true], ["Crash reports", false]] as const) {
      const geometry = await switchGeometry(page, name);
      // The row's checkbox box (15px) must never reach a switch's track.
      expect(geometry.width, `${name} track width`).toBe(32);
      expect(geometry.height, `${name} track height`).toBe(18);
      expect(geometry.knobWidth).toBe(14);
      // On: the knob ends 2px inside the track's right edge; off: at the left.
      expect(geometry.knobRight, `${name} knob`).toBe(on ? 30 : 16);
      // The knob is paint, not a 2.8% wash: on a kit card a bare `surface`
      // knob draws no visible knob in dark.
      expect(geometry.knobFill, `${name} knob fill`).toMatch(/^rgb\(/);
    }
  });
}

test("the row's words turn its switch, and the record is the words on the card", async ({ page }) => {
  const answers = await usageServer(page, usageStateFixture("declined"));
  await page.goto("/settings/privacy");
  const crashes = page.getByRole("checkbox", { name: "Crash reports" });
  await expect(crashes).not.toBeChecked();
  await page.getByText(msg("privacy-group-crashes-detail")).click();
  await expect(crashes).toBeChecked();
  expect(answers.map((a) => a.answers)).toEqual([{ crashes: true }]);
  // The consent question's title is on this card, over the switch it records.
  const [title] = answers[0].text.split("\n\n");
  await expect(page.getByRole("heading", { level: 3, name: title })).toBeVisible();
});

test("the card is named by its tab; what is never sent is its intro, and the rows keep one hairline rhythm", async ({ page }) => {
  await usageServer(page, usageStateFixture("shared", { pending_events: 2 }));
  await page.goto("/settings/privacy");
  const card = page.getByRole("region", { name: "Privacy" });
  await expect(card.getByRole("heading", { level: 2 })).toHaveText("Privacy");
  await expect(page.getByRole("tab", { name: "Privacy" })).toHaveAttribute("aria-selected", "true");
  await expect(card.getByText(msg("privacy-never"), { exact: false })).toBeVisible();
  await expect(card.getByRole("note")).toHaveCount(0);

  // Seven rows, one list: no hairline missing, no boxed note between them.
  const borders = await card.locator(".settings-row").evaluateAll((rows) =>
    rows.map((row) => getComputedStyle(row).borderTopWidth));
  expect(borders).toEqual(["0px", "1px", "1px", "1px", "1px", "1px", "1px"]);
});

test("while it loads, the row it becomes stands in: the card's title is said once", async ({ page }) => {
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route("/api/usage", async (route) => {
    await held;
    await route.fulfill({ json: usageStateFixture("declined") });
  });
  await page.goto("/settings/privacy");
  const card = page.getByRole("region", { name: "Privacy" });
  await expect(card.getByText("Anonymous usage data")).toBeVisible();
  await expect(card.getByText("Privacy", { exact: true })).toHaveCount(1);
  await expect(card.getByText("Help us improve")).toHaveCount(0);
  release();
  await expect(card.getByRole("checkbox", { name: "Anonymous usage data" })).toBeVisible();
});

test("on a phone each row's control sits under its words and the page never scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await usageServer(page, usageStateFixture("shared", { pending_events: 1 }));
  await page.goto("/settings/privacy");
  const reset = page.getByRole("button", { name: "Reset ID" });
  await expect(reset).toBeVisible();
  // Under the row's last line (its ID), at the words' own left edge: beside
  // them, the copy was squeezed to a few words a line.
  const title = await page.getByText("Your install ID").boundingBox();
  const id = await page.getByText("8f14e45f-ceea-4e7a-9b3a-1f2d3c4b5a69").boundingBox();
  const button = await reset.boundingBox();
  expect(button!.y, "Reset ID wraps under its row's words").toBeGreaterThanOrEqual(id!.y + id!.height);
  expect(Math.round(button!.x)).toBe(Math.round(title!.x));
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
});

test("Sent recently lists what left this machine, with an empty state", async ({ page }) => {
  await usageServer(page, usageStateFixture("shared"));
  let events = [
    { name: "daily_heartbeat", group: "usage", day: "2026-10-18", count: 1, props: {}, sent_at: "2026-10-18T09:00:00Z" },
    { name: "daily_action", group: "usage", day: "2026-10-17", count: 4, props: { action: "save_job" }, sent_at: "2026-10-17T09:00:00Z" },
  ];
  await page.route("/api/usage/sent", (route) => route.fulfill({ json: { events } }));
  await page.goto("/settings/privacy");

  const show = page.getByRole("button", { name: "Show the list" });
  await show.click();
  const list = page.getByRole("list", { name: "Sent recently" });
  await expect(list.getByRole("listitem")).toHaveCount(2);
  // Newest first, each with its own name, how often and when.
  await expect(list.getByRole("listitem").first()).toContainText("daily_heartbeat");
  await expect(list.getByRole("listitem").nth(1)).toContainText(/daily_action.*4 times/);
  await expect(page.getByRole("button", { name: "Hide the list" })).toHaveAttribute("aria-expanded", "true");

  events = [];
  await page.getByRole("button", { name: "Hide the list" }).click();
  await page.getByRole("button", { name: "Show the list" }).click();
  await expect(page.getByText("Nothing was sent in the last 30 days.")).toBeVisible();
  await expect(page.getByRole("list", { name: "Sent recently" })).toHaveCount(0);
});

for (const pendingImport of [false, true]) {
  test(`Reset ID replaces browser persistence and device identity while keeping every choice (pending import: ${pendingImport})`, async ({ page }) => {
    const old = usageStateFixture("shared");
    const next = { ...old, install_id: "0b5c1f7e-2d4a-4c8e-9f10-6a7b8c9d0e1f" };
    await usageServer(page, old);
    await page.route("/api/usage/install-id/reset", (route) => route.fulfill({ json: next }));
    let release!: () => void;
    let requested!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    const importing = new Promise<void>((resolve) => { requested = resolve; });
    if (pendingImport) {
      await page.addInitScript((id) => {
        localStorage.setItem("ph_phc_test_posthog", JSON.stringify({
          distinct_id: id, $device_id: "old-browser-device", $user_state: "identified",
        }));
      }, old.install_id);
      /* The library is a hashed chunk in a build and a pre-bundled dependency
         on the Vite dev server; holding either holds the import. */
      await page.route(/\/(assets\/module\.full\.no-external-[^/]+|node_modules\/\.vite\/deps\/posthog-js_dist_module__full__no-external)\.js/, async (route) => {
        requested();
        await held;
        await route.continue();
      });
    }
    const identity = () => page.evaluate(() => {
      const stored = localStorage.getItem("ph_phc_test_posthog");
      return stored ? JSON.parse(stored) as { distinct_id: string; $device_id: string } : null;
    });
    /* WebKit counts an import started before `load` toward the load event, and
       this test holds that import until after the reset, so waiting for
       `load` here would wait for the test itself. */
    await page.goto("/settings/privacy", { waitUntil: pendingImport ? "commit" : "load" });
    await expect(page.getByText(old.install_id!)).toBeVisible();
    if (pendingImport) await importing;
    else await expect.poll(async () => (await identity())?.distinct_id).toBe(old.install_id);
    const before = await identity();
    const reset = page.getByRole("button", { name: msg("privacy-reset-id") });
    await reset.scrollIntoViewIfNeeded();
    await expectOnTop(reset, "Reset ID");
    await pointAndClick(page, reset);
    await expect(page.getByText(next.install_id)).toBeVisible();
    release();
    await expect.poll(async () => (await identity())?.distinct_id).toBe(next.install_id);
    const after = await identity();
    expect(after?.$device_id).toBeTruthy();
    expect(after?.$device_id).not.toBe(before?.$device_id);
    expect(JSON.stringify(after)).not.toContain(old.install_id);
    for (const name of ["Anonymous usage data", "Crash reports", "Feedback surveys"]) {
      await expect(page.getByRole("checkbox", { name })).toBeChecked();
    }
  });
}
