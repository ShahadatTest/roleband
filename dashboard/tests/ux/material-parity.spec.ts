/* THE REGISTER SCREENS ARE THE APP. Followed companies, AI and
   Company profiles wear `data-material="register"`, which restates no token.
   A material that restates an opaque surface, opaque hairlines and its own
   tempo leaves the panels looking the same (the opaque values are the app's
   own pre-mixed onto the canvas) but changes everything on the bare canvas (a
   ghost button's edge, a switch's off track, a search field), lighter there
   than on any other screen, the switch and row actions moving at a different
   speed, and the dialogs: opaque paper at the card radius where every other
   dialog, the same form on Plugins included, is `ui/Dialog`'s glass.

   The same controls, placed in each register screen and in Plugins (a Settings
   tab that never wore the material), must paint and move the same, both
   themes. The source half is `tokens.test.ts` ("a material restates no app
   token"). */

import { expect, test, type Page } from "./fixtures";
import { installEveryRoute } from "./routesHarness";
import { installSettingsRoutes } from "./settingsHarness";

test.beforeEach(async ({ page }) => {
  await installEveryRoute(page);
  await installSettingsRoutes(page);
});

const REFERENCE = "/settings/plugins";
const REGISTER = ["/settings/companies", "/settings/intelligence", "/company"];

async function measure(page: Page, path: string) {
  await page.goto(path);
  const root = page.locator(".settings-content, .prof-main").first();
  await expect(root).toBeVisible();
  return root.evaluate((host) => {
    const box = document.createElement("div");
    box.innerHTML =
      '<button class="ui-btn ui-btn-ghost ui-btn-sm" data-p="ghost">G</button>' +
      '<label class="ui-switch"><input class="ui-switch-track" type="checkbox" data-p="switch"></label>';
    host.appendChild(box);
    const overlay = document.body.appendChild(document.createElement("div"));
    overlay.className = "ui-overlay";
    overlay.innerHTML = '<div class="ui-dialog app-overlay" data-p="dialog"></div>';
    const q = (sel: string, root: ParentNode) => getComputedStyle(root.querySelector(`[data-p="${sel}"]`)!);
    const ghost = q("ghost", box);
    const track = q("switch", box);
    const dialog = q("dialog", overlay);
    const out = {
      ghostBorder: ghost.borderTopColor,
      switchOffTrack: track.backgroundColor,
      switchTempo: track.transitionDuration,
      dialogPaint: dialog.backgroundColor,
      dialogRadius: dialog.borderTopLeftRadius,
      dialogBlur: dialog.backdropFilter,
    };
    box.remove();
    overlay.remove();
    return out;
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`the register screens paint and move like every other screen (${theme})`, async ({ page, isMobile }) => {
    test.skip(isMobile, "a cascade fact, the same at every width");
    await page.addInitScript((t) => localStorage.setItem("theme", t), theme);
    await page.setViewportSize({ width: 1280, height: 800 });
    const reference = await measure(page, REFERENCE);
    // The reference is the primitives' own: glass dialogs, the app's tempo.
    expect(reference.switchTempo).toBe("0.18s");
    expect(reference.dialogBlur).not.toBe("none");
    for (const path of REGISTER) {
      expect(await measure(page, path), `${path} differs from ${REFERENCE}`).toEqual(reference);
    }
  });
}
