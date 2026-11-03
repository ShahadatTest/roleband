import { expect } from "./fixtures";
import type { Locator, Page } from "@playwright/test";

/* What the browser PAINTS at a control, as its own hit-testing reports it.
 *
 * `toBeVisible()` is a box and `visibility`, never occlusion. A toast buried
 * under an opaque cover passes it: it has a box, nothing hides it, and nothing
 * on screen can reach it. Where the claim
 * is "the reader can see this and act on it", assert what is on top at the
 * control's centre, and act there with a real pointer. */
async function paintedAtCentre(locator: Locator): Promise<boolean> {
  return locator.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return hit !== null && (hit === el || el.contains(hit));
  });
}

export async function expectOnTop(locator: Locator, what: string) {
  await expect
    .poll(() => paintedAtCentre(locator), { message: `${what} is not what is painted at its own centre` })
    .toBe(true);
}

/* A pointer at the control's centre with no actionability checks and no
   `force`: the event lands on whatever is painted there, so a control that is
   covered is simply not clicked and the assertion after it fails. */
export async function pointAndClick(page: Page, locator: Locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error("the control has no box to point at");
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
}

/* Everything painted over a cover that is not the cover or the layer that
   ranks above it. A cover is modal and opaque — the screen — so a 9x9 sweep of
   the viewport must land on nothing else. Under the layer scale a cover ranks
   BELOW a dialog or popover (ui/Overlay.css), so one left open on the list
   underneath floats over the cover instead of being buried by it; this is
   the sweep that sees that. `data-above-cover` is ui/Overlay's ABOVE_COVER,
   spelled out because a spec cannot import a module that imports CSS. */
export async function strangersOver(cover: Locator): Promise<string[]> {
  return cover.evaluate((dialog) => {
    const found: string[] = [];
    for (let i = 1; i < 10; i += 1) {
      for (let j = 1; j < 10; j += 1) {
        const x = (innerWidth * i) / 10;
        const y = (innerHeight * j) / 10;
        const hit = document.elementFromPoint(x, y);
        if (!hit || dialog.contains(hit) || hit.closest("[data-above-cover]")) continue;
        found.push(`${Math.round(x)},${Math.round(y)} ${hit.tagName.toLowerCase()}.${[...hit.classList].join(".")}`);
      }
    }
    return found;
  });
}
