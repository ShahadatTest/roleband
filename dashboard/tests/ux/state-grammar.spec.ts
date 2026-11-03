/* THE TWO STATES, read off the screens (docs/ui.md
   "Two states"). One option CHOSEN among others is gold on every screen, in
   every control: wash behind it, its name in the chosen ink. A thing's own ON
   state (a switch, the row it governs) is ink. The failure this guards is
   many looks for "selected" (gold tint, gold tint with ink text, a raised
   neutral segment, a neutral tint, an ink fill), each correct on its own
   screen and each different from its neighbour's.

   Each control is measured where it lives, against the tokens resolved in
   that same place, and every screen must resolve the same tokens: a material
   or scope that restated them would pass the first check and fail the second.
   The source half (no state CLASSES, no state painted outside the two token
   sets) is `src/design/state-grammar.test.ts`. */

import type { Locator } from "@playwright/test";
import { expect, test, type Page } from "./fixtures";
import { installEveryRoute } from "./routesHarness";
import { installSettingsRoutes } from "./settingsHarness";

test.beforeEach(async ({ page }) => {
  await installEveryRoute(page);
  await installSettingsRoutes(page);
});

type Paint = { wash: string; ink: string };

/** The two token sets as this element's own context resolves them. */
async function tokensAt(locator: Locator): Promise<{ chosen: Paint; on: Paint }> {
  return locator.evaluate((node) => {
    const read = (bg: string, fg: string) => {
      const probe = document.createElement("span");
      probe.style.backgroundColor = `var(${bg})`;
      probe.style.color = `var(${fg})`;
      node.parentElement!.appendChild(probe);
      const cs = getComputedStyle(probe);
      const out = { wash: cs.backgroundColor, ink: cs.color };
      probe.remove();
      return out;
    };
    return {
      chosen: read("--app-chosen-wash", "--app-chosen-text"),
      on: read("--app-on-wash", "--app-on-fill"),
    };
  });
}

/** What the control actually paints: its own background, and the colour of
 *  its NAME (the element carrying the words, which for a card is its label). */
async function painted(control: Locator, name: string | null): Promise<Paint> {
  return control.evaluate((node, nameSel: string | null) => {
    const words = (nameSel ? node.querySelector(nameSel) : node) as HTMLElement;
    return { wash: getComputedStyle(node).backgroundColor, ink: getComputedStyle(words).color };
  }, name);
}

type Case = {
  family: string;
  path: string;
  control: (page: Page) => Locator;
  name: string | null;
};

const CHOSEN: Case[] = [
  { family: "Settings tab bar", path: "/settings/schedule", control: (p) => p.getByRole("tab", { selected: true }).first(), name: null },
  { family: "Schedule day chip", path: "/settings/schedule", control: (p) => p.locator('.ui-chip[aria-pressed="true"]').first(), name: null },
  { family: "Insights segment", path: "/statistics/overview", control: (p) => p.locator('.ui-seg-btn[aria-pressed="true"]').first(), name: null },
  { family: "Profile option card", path: "/profile/direction", control: (p) => p.locator(".walk-cards label.select-card:has(> input:checked)").first(), name: ".select-card-label" },
  { family: "Topbar lens chip", path: "/", control: (p) => p.locator('.stat-chip[aria-current="page"]').first(), name: ".l" },
];

for (const theme of ["light", "dark"] as const) {
  test(`one option chosen is the same gold in every control on every screen (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("theme", t), theme);
    await page.setViewportSize({ width: 1280, height: 800 });
    let first: Paint | null = null;
    for (const c of CHOSEN) {
      await page.goto(c.path);
      const control = c.control(page);
      await expect(control, `${c.family}: nothing chosen rendered`).toBeVisible();
      const { chosen } = await tokensAt(control);
      // Transitions on background/colour settle within --app-duration-fast.
      await expect.poll(() => painted(control, c.name), { message: `${c.family} is not painted chosen` }).toEqual(chosen);
      first ??= chosen;
      expect(chosen, `${c.family}: this screen resolves the chosen tokens differently`).toEqual(first);
    }
    // Gold is not ink: the chosen set is the action colour, never the text colour.
    expect(first!.ink).toBe(theme === "dark" ? "rgb(232, 220, 172)" : "rgb(119, 84, 13)");
  });

  test(`a thing that is on is ink, the switch and the row it governs alike (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("theme", t), theme);
    await page.goto("/settings/companies");
    const track = page.locator(".ui-switch-track:checked").first();
    await expect(track).toBeAttached();
    const { on, chosen } = await tokensAt(track);
    await expect.poll(() => track.evaluate((n) => getComputedStyle(n).backgroundColor)).toBe(on.ink);
    const row = page.locator(".ledger-row:has(.ui-switch-track:checked)").first();
    await expect.poll(() => row.evaluate((n) => getComputedStyle(n).backgroundColor)).toBe(on.wash);
    // And on is not chosen: the two states never share a paint.
    expect(on.ink).not.toBe(chosen.ink);
  });
}
