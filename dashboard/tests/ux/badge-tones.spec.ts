/* ONE BADGE TONE TABLE. ui/Badge.css maps each tone to its channel
   colours, and no scope may restate the table: a restated copy drifts from
   the primitive, so a solid danger badge's ink and a warning outline's line
   would be one colour in one screen family and another in the next. The same
   badge, placed in each screen family that renders badges and in an overlay,
   must paint the same, and paint the primitive's tokens. The welcome screen
   renders none, so it never loads Badge's sheet and is not a family here. The source half is settings-doorway.test.ts ("declared
   once, in Badge's own sheet"). */

import { expect, test, type Page } from "./fixtures";
import { installEveryRoute } from "./routesHarness";
import { installSettingsRoutes } from "./settingsHarness";

test.beforeEach(async ({ page }) => {
  await installEveryRoute(page);
  await installSettingsRoutes(page);
});

const FAMILIES: [string, string][] = [
  ["Board", "/"],
  ["Settings", "/settings/schedule"],
];

/** A danger/solid and a warning/outline badge, as ui/Badge renders them,
 *  placed in the screen's main region and in an overlay portal. */
async function paint(page: Page, where: "main" | "overlay") {
  return page.evaluate((where) => {
    const host =
      where === "main"
        ? (document.querySelector("main") as HTMLElement)
        : Object.assign(document.body.appendChild(document.createElement("div")), {
            className: "ui-overlay app-overlay",
          });
    const box = document.createElement("div");
    box.innerHTML =
      '<span class="ui-badge ui-badge-danger ui-badge-solid ui-badge-md">3</span>' +
      '<span class="ui-badge ui-badge-warning ui-badge-outline ui-badge-md">w</span>' +
      '<span data-probe style="color: var(--app-danger-ink); border-top: 1px solid var(--app-warning-line)"></span>';
    host.appendChild(box);
    const [danger, warning, probe] = Array.from(box.children) as HTMLElement[];
    const out = {
      dangerInk: getComputedStyle(danger).color,
      warningLine: getComputedStyle(warning).boxShadow,
      tokenInk: getComputedStyle(probe).color,
      tokenLine: getComputedStyle(probe).borderTopColor,
    };
    box.remove();
    return out;
  }, where);
}

for (const theme of ["light", "dark"] as const) {
  test(`a badge paints Badge's own tones on every screen and in an overlay (${theme})`, async ({ page, isMobile }) => {
    test.skip(isMobile, "a cascade fact, the same at every width");
    await page.addInitScript((t) => localStorage.setItem("theme", t), theme);
    let first: Awaited<ReturnType<typeof paint>> | null = null;
    for (const [family, path] of FAMILIES) {
      await page.goto(path);
      await expect(page.locator("main").first()).toBeVisible();
      for (const where of ["main", "overlay"] as const) {
        const p = await paint(page, where);
        // The primitive's own tokens: the danger ink pair, the warning line.
        expect(p.dangerInk, `${family} ${where}: danger badge ink`).toBe(p.tokenInk);
        expect(p.warningLine, `${family} ${where}: warning outline`).toContain(p.tokenLine);
        first ??= p;
        expect(p, `${family} ${where} paints a badge differently`).toEqual(first);
      }
    }
  });
}
