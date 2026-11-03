/* Settings › Plugins: the deep link and its place in the bar, one kit row
   per plugin (as Privacy's), search, the switch (a plugin that needs approval
   is reviewed first, AS SHOWN), Start (named by its plugin), what estimates
   did above the list, the install command, and the gear into one plugin's
   settings: its own card, how often, Pause / Resume on the Next update line
   and Start on the Last update line, fresh companies per kind, update
   history, Remove data behind the typed id, Uninstall. The ranks and the
   rhythm are measured here, where a browser draws them. Every request is
   mocked; the catch-all guard in `fixtures.ts` fails any that is not. */

import { msg } from "../../src/test/msg";
import type { Locator, Page } from "@playwright/test";
import { expect, mockApi, mockGet, test } from "./fixtures";
import { installSettingsRoutes } from "./settingsHarness";
import {
  pluginAdoptingFixture, pluginDetailFixture, pluginFixture, pluginLapsedFixture, pluginRunContinuingFixture,
  pluginRunErroredFixture, pluginRunStoppedFixture, pluginsFixture, pluginRobotsFixture
} from "../../src/test/fixtures";

const reports = pluginFixture({
  id: "acme-reports", name: "Acme pay reports", slots: ["pay.observations"], active_slots: ["pay.observations"],
  attribution: "Data source: Acme", hosts: ["reports.example.com"], coverage: { "pay.observations": 2 },
});
const done = (plugin = pluginFixture()) => ({ plugin, reestimate_started: false, stopped: [] });

/** One fact line of a plugin's settings (label | value), found by its label. */
const factLine = (page: Page, label: string) =>
  page.locator(".plugin-settings-facts > div").filter({ has: page.getByText(label, { exact: true }) });

/** `inner` is drawn inside `outer`'s box: on that line, not merely after it. */
async function expectInside(inner: Locator, outer: Locator) {
  const [a, b] = [(await inner.boundingBox())!, (await outer.boundingBox())!];
  expect(a.y).toBeGreaterThanOrEqual(b.y);
  expect(a.y + a.height).toBeLessThanOrEqual(b.y + b.height);
  expect(a.x).toBeGreaterThanOrEqual(b.x);
  expect(a.x + a.width).toBeLessThanOrEqual(b.x + b.width + 0.5);
}

test.beforeEach(async ({ page }) => {
  await installSettingsRoutes(page);
});

test("the Plugins tab opens by its link, right after Schedule, one row per plugin", async ({ page }) => {
  await mockGet(page, "/api/plugins", (route) => route.fulfill({ json: pluginsFixture({
    plugins: [pluginFixture(), reports] }) }));
  await page.goto("/settings/plugins");
  await expect(page.getByRole("tab", { name: "Plugins" })).toHaveAttribute("aria-selected", "true");
  const tabs = await page.getByRole("tab").allTextContents();
  expect(tabs.slice(2, 4)).toEqual(["Schedule", "Plugins"]);
  expect(tabs).not.toContain("Pay data");

  const region = page.getByRole("region", { name: "Plugins" });
  await expect(region.getByText("2 of 2 on")).toBeVisible();
  const row = region.getByTestId("plugin-row-acme-reports");
  await expect(row.getByText("Acme pay reports")).toBeVisible();
  await expect(row).toContainText("Answers compensation estimates");
  await expect(row.getByRole("checkbox", { name: "Use Acme pay reports" })).toBeChecked();
  // Every row has a Start: each is named by its plugin, and still reads Start.
  const start = row.getByRole("button", { name: "Start Acme pay reports", exact: true });
  await expect(start).toBeEnabled();
  await expect(start).toHaveText("Start");
  await expect(region.getByRole("button", { name: "Start Example pay data", exact: true })).toBeVisible();
  await expect(region.getByRole("button", { name: "Start", exact: true })).toHaveCount(0);
  await expect(row.getByRole("button", { name: "Settings for Acme pay reports" })).toBeVisible();
  await expect(region.getByText("More plugins")).toBeVisible();
  await expect(region.getByRole("note")).toContainText("Estimates changed for 44 roles at 6 companies");
});

test("search narrows the list to the plugins it names", async ({ page }) => {
  await mockGet(page, "/api/plugins", (route) => route.fulfill({ json: pluginsFixture({
    plugins: [pluginFixture(), reports] }) }));
  await page.goto("/settings/plugins");
  const search = page.getByRole("searchbox", { name: "Search plugins" });
  await search.fill("acme");
  await expect(page.getByTestId("plugin-row-acme-reports")).toBeVisible();
  await expect(page.getByTestId("plugin-row-example-pay")).toHaveCount(0);
  await search.fill("nothing like this");
  await expect(page.getByText("No installed plugin matches your search.")).toBeVisible();
});

test("turning on a plugin that needs approval shows what it may do, then approves what was shown and turns it on", async ({ page }) => {
  await mockGet(page, "/api/plugins", (route) => route.fulfill({ json: pluginsFixture({
    plugins: [pluginFixture({ state: "needs_approval", active_slots: [], last_run: null, last_clean_at: null })],
  }) }));
  await mockGet(page, "/api/plugins/example-pay", (route) => route.fulfill({ json: pluginDetailFixture() }));
  const sent: string[] = [];
  await mockApi(page, "POST", "/api/plugins/example-pay/approve", async (route) => {
    sent.push(`approve ${JSON.stringify(route.request().postDataJSON())}`);
    await route.fulfill({ json: done(pluginFixture({ state: "disabled" })) });
  });
  await mockApi(page, "POST", "/api/plugins/example-pay/enable", async (route) => {
    sent.push("enable");
    await route.fulfill({ json: done() });
  });
  await page.goto("/settings/plugins");
  await page.getByRole("checkbox", { name: "Use Example pay data" }).click();

  const dialog = page.getByRole("dialog", { name: "Approve this plugin?" });
  await expect(dialog.getByText("data.example.com")).toBeVisible();
  await expect(dialog).toContainText("Weekly, when plugged in");
  await expect(dialog).toContainText("It receives the list of companies you follow.");
  await expect(dialog).toContainText("It visits them openly, as RoleBand.");
  await expect(dialog.getByTestId("plugin-approval-version")).toContainText("0.3.1");
  expect(sent).toEqual([]);
  await dialog.getByRole("button", { name: "Approve, turn on" }).click();
  await expect(dialog).toBeHidden();
  await expect.poll(() => sent).toEqual([`approve {"fingerprint":"${"f0".repeat(32)}","robots":null}`, "enable"]);
});

test("the approval quotes each site's rules and, allowed, sends the files the person saw", async ({ page }) => {
  await mockGet(page, "/api/plugins", (route) => route.fulfill({ json: pluginsFixture({
    plugins: [pluginFixture({ state: "needs_approval", active_slots: [], last_run: null, last_clean_at: null })],
  }) }));
  await mockGet(page, "/api/plugins/example-pay", (route) => route.fulfill({ json: pluginDetailFixture() }));
  await mockGet(page, "/api/plugins/example-pay/robots", (route) => route.fulfill({ json: pluginRobotsFixture() }));
  const sent: string[] = [];
  await mockApi(page, "POST", "/api/plugins/example-pay/approve", async (route) => {
    sent.push(JSON.stringify(route.request().postDataJSON()));
    await route.fulfill({ json: done(pluginFixture({ state: "disabled" })) });
  });
  await mockApi(page, "POST", "/api/plugins/example-pay/enable", (route) => route.fulfill({ json: done() }));
  await page.goto("/settings/plugins");
  await page.getByRole("checkbox", { name: "Use Example pay data" }).click();

  const dialog = page.getByRole("dialog", { name: "Approve this plugin?" });
  const site = dialog.getByTestId("plugin-robots-site-data.example.com");
  await expect(site).toContainText("asks RoleBand to skip these pages");
  await expect(site).toContainText("/*?page=");
  const allow = dialog.getByRole("checkbox", { name: "Read past these rules" });
  await expect(allow).not.toBeChecked();
  await allow.click();
  await dialog.getByRole("button", { name: "Approve, turn on" }).click();
  await expect.poll(() => sent).toEqual([JSON.stringify({ fingerprint: "f0".repeat(32),
                                                          robots: { "data.example.com": "ab".repeat(32) } })]);
});

test("turning on an approved plugin that has not read every followed company asks first, then turns it on", async ({ page }) => {
  await mockGet(page, "/api/plugins", (route) => route.fulfill({ json: pluginsFixture({
    plugins: [pluginFixture({ state: "disabled", active_slots: [] })],
  }) }));
  const sent: string[] = [];
  await mockApi(page, "POST", "/api/plugins/example-pay/enable", async (route) => {
    sent.push("enable");
    await route.fulfill({ json: done() });
  });
  await page.goto("/settings/plugins");
  await page.getByRole("checkbox", { name: "Use Example pay data" }).click();

  const dialog = page.getByRole("dialog", { name: "Turn this plugin on?" });
  await expect(dialog).toContainText("replaces the built-in data for every company");
  await expect(dialog.getByTestId("plugin-approval-gap")).toContainText(
    "Until it reads a company, that company shows none of what it brings");
  await expect(dialog.getByTestId("plugin-approval-gap")).toContainText("96 of 120 companies");
  expect(sent).toEqual([]);
  await dialog.getByRole("button", { name: "Turn on", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect.poll(() => sent).toEqual(["enable"]);
});

test("Start updates now, says so at once although the run is not listed yet, and is not offered twice", async ({ page }) => {
  const sent: unknown[] = [];
  await mockApi(page, "POST", "/api/plugins/example-pay/refresh", async (route) => {
    sent.push(route.request().postDataJSON());
    await route.fulfill({ json: { started: true, job: "refresh", waiting: null } });
  });
  await page.goto("/settings/plugins");
  const row = page.getByTestId("plugin-row-example-pay");
  await row.getByRole("button", { name: "Start" }).click();
  await expect.poll(() => sent).toEqual([{}]);
  // `/api/plugins` still answers `running: false`: the row says it is updating anyway.
  await expect(row.getByText("Updating", { exact: true })).toBeVisible();
  await expect(row.getByRole("button", { name: "Start" })).toBeDisabled();
});

test("an update that lapsed the approval of a plugin left on: the switch stays on and turns it off without approving", async ({ page }) => {
  await mockGet(page, "/api/plugins", (route) => route.fulfill({ json: pluginsFixture({
    plugins: [pluginLapsedFixture()] }) }));
  const sent: string[] = [];
  await mockApi(page, "POST", "/api/plugins/example-pay/disable", async (route) => {
    sent.push("disable");
    await route.fulfill({ json: done(pluginLapsedFixture({ enabled: false })) });
  });
  await page.goto("/settings/plugins");
  const row = page.getByTestId("plugin-row-example-pay");
  await expect(row.getByText("Needs approval")).toBeVisible();
  const toggle = row.getByRole("checkbox", { name: "Use Example pay data" });
  await expect(toggle).toBeChecked();
  await expect(row.getByRole("button", { name: "Start" })).toBeDisabled();
  await toggle.click();
  await expect.poll(() => sent).toEqual(["disable"]);
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("the gear opens the plugin's settings: how often it updates, and Pause", async ({ page }) => {
  await mockGet(page, "/api/plugins/example-pay", (route) => route.fulfill({ json: pluginDetailFixture({
    ...pluginFixture(), runs: [pluginFixture().last_run!] }) }));
  const sent: unknown[] = [];
  await mockApi(page, "PUT", "/api/plugins/example-pay/schedule", async (route) => {
    sent.push(route.request().postDataJSON());
    await route.fulfill({ json: done(pluginFixture({ schedule: "daily" })) });
  });
  await mockApi(page, "POST", "/api/plugins/example-pay/pause", async (route) => {
    sent.push("pause");
    await route.fulfill({ json: done(pluginFixture({ paused: true })) });
  });
  await page.goto("/settings/plugins");
  await page.getByRole("button", { name: "Settings for Example pay data" }).click();
  await expect(page).toHaveURL(/\/settings\/plugins\/example-pay$/);
  await expect(page.getByRole("tab", { name: "Plugins" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "Example pay data" })).toBeVisible();

  const often = page.getByRole("group", { name: "How often" });
  await expect(often.getByRole("button", { name: "Weekly" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("The plugin suggests weekly.", { exact: false })).toBeVisible();
  await often.getByRole("button", { name: "Daily" }).click();
  await page.getByRole("button", { name: "Pause" }).click();
  await expect.poll(() => sent).toEqual([{ schedule: "daily" }, "pause"]);

  await page.getByRole("button", { name: "All plugins" }).click();
  await expect(page).toHaveURL(/\/settings\/plugins$/);
});

test("Remove data waits for the plugin to be off and for the typed id, then reports what it removed", async ({ page }) => {
  await mockGet(page, "/api/plugins/example-pay", (route) => route.fulfill({ json: pluginDetailFixture({
    ...pluginFixture({ state: "disabled", active_slots: [] }), runs: [] }) }));
  const sent: unknown[] = [];
  await mockApi(page, "POST", "/api/plugins/example-pay/remove-data", async (route) => {
    sent.push(route.request().postDataJSON());
    await route.fulfill({ json: { deleted: { company_comp_level: 3, company_benefit: 2, plugin_coverage: 1 },
                                  reestimate_started: true } });
  });
  await page.goto("/settings/plugins/example-pay");
  await page.getByRole("button", { name: "Remove data" }).click();
  const dialog = page.getByRole("dialog", { name: "Remove this plugin's data?" });
  const remove = dialog.getByRole("button", { name: "Remove data" });
  await expect(remove).toBeDisabled();
  // The id shows as it must be typed: the label is upper case, the id is not.
  await expect(dialog.locator(".plugin-remove-id")).toHaveCSS("text-transform", "none");
  await expect(dialog.locator("label")).toHaveCSS("text-transform", "uppercase");
  const field = dialog.getByLabel("Type example-pay to confirm");
  await field.fill("EXAMPLE-PAY");
  await expect(remove).toBeDisabled();
  await field.fill("example-pay");
  await remove.click();
  // The coverage bookkeeping cleared beside the rows is not counted as removed data.
  await expect(page.getByText("Removed 5 rows.")).toBeVisible();
  expect(sent).toEqual([{ confirm: "example-pay" }]);
});

test("Uninstall says its data stays, and sends one DELETE when confirmed", async ({ page }) => {
  await mockGet(page, "/api/plugins/example-pay", (route) => route.fulfill({ json: pluginDetailFixture({
    ...pluginFixture(), runs: [] }) }));
  let deleted = 0;
  await mockApi(page, "DELETE", "/api/plugins/example-pay", async (route) => {
    deleted += 1;
    await route.fulfill({ json: done(pluginFixture({ state: "removed", active_slots: [] })) });
  });
  await page.goto("/settings/plugins/example-pay");
  await page.getByRole("button", { name: "Uninstall" }).click();
  const dialog = page.getByRole("dialog", { name: "Uninstall this plugin?" });
  await expect(dialog).toContainText("The data it added stays, unread, until you remove it.");
  await dialog.getByRole("button", { name: "Uninstall" }).click();
  await expect.poll(() => deleted).toBe(1);
});

test("on a phone a plugin row stacks and the page never scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/settings/plugins");
  await expect(page.getByTestId("plugin-row-example-pay")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await page.goto("/settings/plugins/example-pay");
  await expect(page.getByRole("heading", { name: "Example pay data" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
});

test("the list loads in one whole sentence, then each plugin is a kit row with its controls at the kit's ranks", async ({ page }) => {
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route("/api/plugins", async (route) => {
    await held;
    await route.fulfill({ json: pluginsFixture() });
  });
  await page.goto("/settings/plugins");
  const region = page.getByRole("region", { name: "Plugins" });
  await expect(region.getByRole("status")).toHaveText(
    msg("settings-plugins-section-loading"));
  release();

  const row = region.getByTestId("plugin-row-example-pay");
  // The switch is the kit row's toggle: a 32x18 track, left of the name it governs.
  const toggle = row.getByRole("checkbox", { name: "Use Example pay data" });
  await expect(toggle).toHaveCSS("width", "32px");
  await expect(toggle).toHaveCSS("height", "18px");
  const name = row.getByText("Example pay data", { exact: true });
  await expect(name).toHaveCSS("font-size", "15px");
  expect((await toggle.boundingBox())!.x).toBeLessThan((await name.boundingBox())!.x);
  // The repeated row verb is the kit's small ghost, as Privacy's Reset ID.
  const start = row.getByRole("button", { name: "Start" });
  expect((await start.boundingBox())!.height).toBe(28);
  await expect(start).not.toHaveClass(/ui-btn-strong/);
  // "On" beside a switch that is on is the same fact twice.
  await expect(row.getByText("On", { exact: true })).toHaveCount(0);

  // Search is the toolbar rank, as the Companies roster's: same job, same rank.
  const searchHeight = async () =>
    (await page.getByRole("searchbox").first().locator("xpath=..").boundingBox())!.height;
  const plugins = await searchHeight();
  await page.goto("/settings/companies");
  await expect(page.getByRole("searchbox")).toBeVisible();
  expect(plugins).toBe(await searchHeight());
  expect(plugins).toBe(36);
});

test("one plugin's settings: its own card first with the switch beside its words, cards on the kit's rhythm, kicker labels, a back control", async ({ page }) => {
  await page.goto("/settings/plugins/example-pay");
  const card = page.getByRole("region", { name: "Example pay data" });
  const toggle = card.getByRole("checkbox", { name: "Use Example pay data" });
  await expect(toggle).toBeChecked();
  const words = card.getByText("Use Example pay data", { exact: true });
  await expect(words).toBeVisible();
  const [box, wordsBox] = [await toggle.boundingBox(), await words.boundingBox()];
  expect(box!.x + box!.width).toBeLessThan(wordsBox!.x);

  // Stacked cards sit the kit's one step apart (28), as Recipes' do; a grid
  // gap on the container would add to it and set them 48 apart.
  const gaps = await page.locator(".settings-content .settings-card").evaluateAll((cards) =>
    cards.slice(1).map((c, i) => Math.round(c.getBoundingClientRect().top - cards[i].getBoundingClientRect().bottom)));
  expect(gaps.length).toBeGreaterThan(2);
  expect(new Set(gaps)).toEqual(new Set([28]));

  // A value's label is the kicker Schedule, AI and Companies label one with.
  const label = page.getByText("How often", { exact: true });
  await expect(label).toHaveCSS("text-transform", "uppercase");
  await expect(label).toHaveCSS("font-family", /Mono/);

  // The way back is a control, not an underlined aside.
  const back = page.getByRole("button", { name: "All plugins" });
  await expect(back).toHaveCSS("text-decoration-line", "none");
  expect((await back.boundingBox())!.height).toBe(28);

  // Pause governs the schedule, so it sits on the Next update line; Start
  // makes an update now, so it sits on the Last update line.
  const next = factLine(page, "Next update");
  const last = factLine(page, "Last update");
  await expect(next.getByRole("button", { name: "Pause" })).toBeVisible();
  await expect(next.getByRole("button", { name: "Start" })).toHaveCount(0);
  await expect(last.getByRole("button", { name: "Start" })).toBeVisible();
  await expect(last.getByRole("button", { name: "Pause" })).toHaveCount(0);
  await expectInside(next.getByRole("button", { name: "Pause" }), next);
  await expectInside(last.getByRole("button", { name: "Start" }), last);
});

test("a paused plugin's Resume sits on the Next update line, beside the words it answers", async ({ page }) => {
  await mockGet(page, "/api/plugins/example-pay", (route) => route.fulfill({ json: pluginDetailFixture({
    ...pluginFixture({ paused: true, paused_at: "2026-07-13T08:00:00Z", next_update_at: null }),
    runs: [pluginFixture().last_run!] }) }));
  const sent: string[] = [];
  await mockApi(page, "POST", "/api/plugins/example-pay/resume", async (route) => {
    sent.push("resume");
    await route.fulfill({ json: done() });
  });
  await page.goto("/settings/plugins/example-pay");
  const next = factLine(page, "Next update");
  await expect(next).toContainText("Paused. Nothing updates on its own until you resume.");
  const resume = next.getByRole("button", { name: "Resume" });
  await expectInside(resume, next);
  // On the words' own line at a desktop width: the words and Resume share a row.
  const words = next.getByText("Paused. Nothing updates on its own until you resume.");
  const [wordsBox, resumeBox] = [await words.boundingBox(), await resume.boundingBox()];
  if (page.viewportSize()!.width > 640) {
    expect(Math.abs((wordsBox!.y + wordsBox!.height / 2) - (resumeBox!.y + resumeBox!.height / 2))).toBeLessThan(8);
  }
  await expect(factLine(page, "Last update").getByRole("button", { name: "Start" })).toBeVisible();
  await resume.click();
  await expect.poll(() => sent).toEqual(["resume"]);
});

test("what estimates did is said under the intro, above the search and the list", async ({ page }) => {
  await page.goto("/settings/plugins");
  const region = page.getByRole("region", { name: "Plugins" });
  const note = region.getByRole("note");
  await expect(note).toContainText("Estimates changed for 44 roles at 6 companies");
  const intro = region.getByText(msg("settings-plugins-section-intro"));
  const search = region.getByRole("searchbox", { name: "Search plugins" });
  const firstRow = region.getByTestId("plugin-row-example-pay");
  const [introBox, noteBox, searchBox, rowBox] = await Promise.all(
    [intro, note, search, firstRow].map(async (l) => (await l.boundingBox())!));
  expect(noteBox.y).toBeGreaterThanOrEqual(introBox.y + introBox.height);
  expect(searchBox.y).toBeGreaterThanOrEqual(noteBox.y + noteBox.height);
  expect(rowBox.y).toBeGreaterThan(noteBox.y + noteBox.height);
  // Nothing of it is left below the list.
  const more = region.getByText("More plugins", { exact: true });
  expect((await more.boundingBox())!.y).toBeGreaterThan(noteBox.y + noteBox.height);
});

test("More plugins shows the install command as code to copy, and no install control", async ({ page }) => {
  await page.goto("/settings/plugins");
  const region = page.getByRole("region", { name: "Plugins" });
  const command = region.locator("pre[data-copy='code']");
  await expect(command).toHaveText("cd backend && .venv/bin/python -m scripts.plugin install <plugin-folder>");
  // Selectable, as code a person copies: no control rule reaches it (WebKit spells it prefixed).
  const select = await command.evaluate((el) => {
    const style = getComputedStyle(el);
    return style.getPropertyValue("user-select") || style.getPropertyValue("-webkit-user-select");
  });
  expect(select).not.toBe("none");
  await expect(region.getByRole("button", { name: /install/i })).toHaveCount(0);
  // Wrapped, never scrolled: the phone run of this spec holds it to the card.
  const [cmdBox, regionBox] = [await command.boundingBox(), await region.boundingBox()];
  expect(cmdBox!.x + cmdBox!.width).toBeLessThanOrEqual(regionBox!.x + regionBox!.width);
});

test("with plugins not available yet, Coming soon stands where the list was and More plugins is unchanged", async ({ page }) => {
  await mockGet(page, "/api/plugins", (route) => route.fulfill({ json: pluginsFixture({ available: false, plugins: [] }) }));
  await page.goto("/settings/plugins");
  const region = page.getByRole("region", { name: "Plugins" });
  const soon = region.getByTestId("plugins-coming-soon");
  await expect(soon).toContainText(msg("settings-plugins-section-coming-soon"));
  await expect(soon).toContainText(msg("settings-plugins-section-coming-soon-note"));
  await expect(region.getByTestId(/^plugin-row-/)).toHaveCount(0);
  await expect(region.getByRole("searchbox")).toHaveCount(0);
  await expect(region.getByRole("checkbox")).toHaveCount(0);
  await expect(region.getByRole("button")).toHaveCount(0);
  await expect(region.getByText(msg("settings-plugins-section-more"))).toBeVisible();
  const command = region.locator("pre[data-copy='code']");
  await expect(command).toHaveText("cd backend && .venv/bin/python -m scripts.plugin install <plugin-folder>");
  // The sign sits above More plugins, inside the card, on a phone as on a desktop.
  const [soonBox, cmdBox, regionBox] = [await soon.boundingBox(), await command.boundingBox(), await region.boundingBox()];
  expect(soonBox!.y + soonBox!.height).toBeLessThanOrEqual(cmdBox!.y);
  expect(soonBox!.x + soonBox!.width).toBeLessThanOrEqual(regionBox!.x + regionBox!.width);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("a row and one plugin's settings say what it does and what it did in the plugin's own words", async ({ page }) => {
  const run = pluginRunStoppedFixture({ summary: "Read pay for 56 of 1,180 companies" });
  const plugin = pluginFixture({ description: "Pay by level and benefits from ladder.example", last_run: run });
  await mockGet(page, "/api/plugins", (route) => route.fulfill({ json: pluginsFixture({ plugins: [plugin] }) }));
  await mockGet(page, "/api/plugins/example-pay", (route) => route.fulfill({ json: pluginDetailFixture({
    ...plugin, runs: [run] }) }));
  await page.goto("/settings/plugins");
  const row = page.getByTestId("plugin-row-example-pay");
  await expect(row.getByText("Pay by level and benefits from ladder.example")).toHaveAttribute("translate", "no");
  await expect(page.getByTestId("plugin-facts-example-pay")).toContainText(": Read pay for 56 of 1,180 companies");
  await row.getByRole("button", { name: "Settings for Example pay data" }).click();
  await expect(page.getByTestId("plugin-last-update")).toContainText(": Read pay for 56 of 1,180 companies");
  await expect(page.getByText("Pay by level and benefits from ladder.example")).toBeVisible();
});

test("one plugin's settings: What it brings shows the numbers the plugin reports, in its own words, with when", async ({ page }) => {
  await mockGet(page, "/api/plugins/example-ladder", (route) => route.fulfill({ json: pluginDetailFixture({
    ...pluginAdoptingFixture(),
    reports: [
      { key: "absent", value: 912, label: "followed companies the site does not list", reported_at: "2026-07-12T15:09:00Z" },
      { key: "stale", value: 3, label: "ladders older than a year", reported_at: "2026-07-11T09:00:00Z" },
    ],
  }) }));
  await page.goto("/settings/plugins/example-ladder");
  const says = factLine(page, msg("settings-plugin-settings-reports"));
  await expect(says).toBeVisible();
  const absent = page.getByTestId("plugin-report-absent");
  await expect(absent).toContainText("912 followed companies the site does not list");
  const asOf = msg("settings-plugin-settings-report-at", { when: "" }).trim();
  await expect(absent.locator("small")).toContainText(new RegExp(`${asOf}\\W+(12 Jul 2026|Jul 12, 2026)`));
  await expect(page.getByTestId("plugin-report-stale")).toContainText("3 ladders older than a year");
  // The plugin's words are its own text, never translated.
  await expect(absent.locator('[data-copy="content"]')).toHaveText("followed companies the site does not list");
  await expectInside(absent, says);
});

test("a plugin that reports nothing shows no line for it", async ({ page }) => {
  await mockGet(page, "/api/plugins/example-ladder", (route) => route.fulfill({ json: pluginDetailFixture(
    pluginAdoptingFixture()) }));
  await page.goto("/settings/plugins/example-ladder");
  await expect(page.getByRole("heading", { name: "Example ladder data" })).toBeVisible();
  await expect(factLine(page, msg("settings-plugin-settings-reports"))).toHaveCount(0);
  await expect(page.getByTestId("plugin-reports")).toHaveCount(0);
});

test("one plugin's settings: What it brings says how many of the followed companies it has read, what the rest show and how long they take; Recent updates tells same-afternoon updates apart", async ({ page }) => {
  const runs = [pluginRunStoppedFixture(), pluginRunErroredFixture(), pluginRunContinuingFixture({
    started_at: "2026-07-12T15:05:00Z", ended_at: "2026-07-12T15:09:00Z" })];
  await mockGet(page, "/api/plugins/example-ladder", (route) => route.fulfill({ json: pluginDetailFixture({
    ...pluginAdoptingFixture(), runs }) }));
  await page.goto("/settings/plugins/example-ladder");
  await expect(page.getByRole("heading", { name: "Example ladder data" })).toBeVisible();
  const pay = page.getByTestId("plugin-slot-pay.levels");
  await expect(pay).toContainText("4 of 1,180 companies read");
  await expect(pay).toContainText("The other 1,176 show no estimate until they're read.");
  await expect(pay).not.toContainText("before it was a plugin");
  await expect(page.getByTestId("plugin-slot-company.benefits")).toContainText("0 of 1,180 companies read");
  await expect(factLine(page, "Left to read")).toContainText("About 21 hr of updates, at about 1 min a company");
  await expect(factLine(page, "Last update")).toContainText("after 4 of 1,180 companies");
  await expect(factLine(page, "Credit")).toContainText("Data source: Example ladder");

  const history = page.getByRole("region", { name: "Recent updates" });
  const times = await history.locator("time").allTextContents();
  expect(times).toHaveLength(3);
  expect(new Set(times).size).toBe(3);
  await expect(history.getByRole("listitem").nth(1)).toContainText(
    "ladder.example answered 503 three times in a row; the update gave up");
  await expect(history.getByRole("listitem").first()).not.toContainText("the run is stopped");
});
