/* THE KEYBOARD'S PLACE IN A LIST WEARS THE ONE RING. In the command
   palette and in FilterSelect, focus stays in the field and the option a
   keyboard user is on is marked by `aria-activedescendant` (FilterSelect) or
   `aria-selected` (the palette). Enter acts on that option, so it is the
   keyboard's position. A tint (a hover grey, a gold wash) sits far under the
   3:1 against the list that a focus indicator needs (WCAG 1.4.11), so it
   wears the app's one ring, drawn inside, and no other option does. */

import type { Locator } from "@playwright/test";
import { expect, test, type Page } from "./fixtures";
import { installEveryRoute } from "./routesHarness";
import { installSettingsRoutes } from "./settingsHarness";

test.beforeEach(async ({ page }) => {
  await installEveryRoute(page);
  await installSettingsRoutes(page);
});

async function ring(page: Page, option: Locator) {
  const gold = await page.evaluate(() => {
    const probe = document.body.appendChild(document.createElement("span"));
    probe.style.color = "var(--app-action)";
    const value = getComputedStyle(probe).color;
    probe.remove();
    return value;
  });
  const cs = await option.evaluate((el) => {
    const s = getComputedStyle(el);
    return { style: s.outlineStyle, width: parseFloat(s.outlineWidth), color: s.outlineColor, offset: parseFloat(s.outlineOffset) };
  });
  return { ...cs, gold };
}

for (const theme of ["light", "dark"] as const) {
  test(`the palette's active option wears the one ring, and only it does (${theme})`, async ({ page, isMobile }) => {
    test.skip(isMobile, "the palette is a keyboard surface");
    await page.addInitScript((t) => localStorage.setItem("theme", t), theme);
    await page.goto("/");
    // The shell listens once it has rendered (the palette readiness rule).
    await expect(page.getByRole("article").first()).toBeVisible({ timeout: 15_000 });
    await page.keyboard.press("ControlOrMeta+k");
    const palette = page.getByRole("dialog", { name: "Command palette" });
    await expect(palette).toBeVisible();
    await page.keyboard.press("ArrowDown");
    const active = palette.getByRole("option", { selected: true });
    await expect(active).toHaveCount(1);
    await expect.poll(async () => (await ring(page, active)).style).toBe("solid");
    const r = await ring(page, active);
    expect(r.width).toBeGreaterThanOrEqual(2);
    expect(r.color).toBe(r.gold);
    expect(r.offset).toBeLessThan(0);
    const other = palette.getByRole("option", { selected: false }).first();
    expect((await ring(page, other)).style).toBe("none");
    // Focus stays in the field, and the field draws no ring of its own: the
    // dialog shows one ring, on the option Enter runs.
    await expect(page.getByLabel("Command query")).toBeFocused();
    const ringed = await palette.evaluate((root) =>
      [root, ...root.querySelectorAll("*")]
        .filter((el) => getComputedStyle(el).outlineStyle !== "none")
        .map((el) => el.getAttribute("role") ?? el.tagName.toLowerCase()));
    expect(ringed).toEqual(["option"]);
  });

  test(`FilterSelect's active option wears the one ring, and only it does (${theme})`, async ({ page, isMobile }) => {
    test.skip(isMobile, "the list is a keyboard surface");
    await page.addInitScript((t) => localStorage.setItem("theme", t), theme);
    await page.goto("/statistics/overview");
    const trigger = page.locator(".ui-filterselect-trigger").first();
    await expect(trigger).toBeVisible();
    await trigger.click();
    const list = page.getByRole("listbox").first();
    await expect(list).toBeVisible();
    // The focused element names the active option: the search box when there
    // is one, else the list. The arrows move it.
    const focused = page.locator(":focus");
    await expect(focused).toHaveAttribute("aria-activedescendant", /.+/);
    const first = await focused.getAttribute("aria-activedescendant");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await expect(focused).not.toHaveAttribute("aria-activedescendant", first!);
    const id = await focused.getAttribute("aria-activedescendant");
    const active = page.locator(`[id="${id}"]`);
    await expect(active).toHaveRole("option");
    await expect.poll(async () => (await ring(page, active)).style).toBe("solid");
    const r = await ring(page, active);
    expect(r.width).toBeGreaterThanOrEqual(2);
    expect(r.color).toBe(r.gold);
    expect(r.offset).toBeLessThan(0);
    const others = await list.getByRole("option").evaluateAll((els, activeId) =>
      els.filter((e) => e.id !== activeId).map((e) => getComputedStyle(e).outlineStyle), id);
    expect(new Set(others)).toEqual(new Set(["none"]));
  });
}
