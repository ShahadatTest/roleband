/* ONE FOCUS RING (docs/ui.md "One focus ring"). Wherever
   the keyboard lands, the same ring says so: a solid outline of
   `--app-ring-width` in `--app-action`, the action colour of the surface it
   sits on (the fixed-dark rail's own `--rail-accent`). Other looks fail: a
   soft halo or a tinted outline falls under the 3:1 a focus indicator needs
   (1.4.11), and a left bar on a Board row is the same mark as a row picked
   for Compare.

   Name-blind on purpose: the sweep Tabs through every screen family and judges
   whatever takes focus, so a control added next month is covered without being
   listed. A ring may be drawn somewhere other than the focused element in
   exactly two ways, both named here: by a CARRIER (an ancestor that IS the
   control the user sees, because the focused element is hidden or is only its
   text) and, for SVG marks, as a STROKE on the shape (an outline on an SVG `g`
   draws its bounding box). The source half is `src/design/focus-ring.test.ts`. */

import { expect, test, type Page } from "./fixtures";
import { installEveryRoute } from "./routesHarness";
import { installSettingsRoutes } from "./settingsHarness";

const SCREENS = [
  "/",
  "/favorites",
  "/statistics/overview",
  "/profile/direction",
  "/settings/companies",
  "/settings/intelligence",
  "/settings/schedule",
  "/settings/plugins",
  "/company",
  "/review",
  "/notifications",
  "/welcome",
];

/** Focused element -> the ancestor that draws its ring. Kept in step with the
 *  carrier list in `src/design/focus-ring.test.ts`. */
const CARRIERS: [string, string][] = [
  [".ui-search-input", ".ui-search"],
  [".filter-search-row input", ".filter-search-row"],
  [".cluster-card-select", ".cluster-card"],
];

async function focusedRing(page: Page) {
  return page.evaluate(async (carriers) => {
    const el = document.activeElement as HTMLElement | SVGElement | null;
    if (!el || el === document.body) return null;
    const box = el.getBoundingClientRect();
    if (box.width === 0 && box.height === 0) return null;
    const owners = carriers.flatMap(([focused, carrier]) => {
      const owner = el.matches(focused) ? el.closest(carrier) : null;
      return owner ? [owner] : [];
    });
    // Computed styles flush pending transitions before their completion is awaited.
    const shapes = el instanceof SVGElement ? Array.from(el.querySelectorAll("*")) : [];
    const transitions = [el, ...owners, ...shapes].flatMap((node) => {
      getComputedStyle(node).outlineColor;
      return node.getAnimations().filter((animation) => animation instanceof CSSTransition);
    });
    await Promise.all(transitions.map((animation) => animation.finished.catch(() => {})));
    const sig = `${el.tagName.toLowerCase()}${el.classList.length ? "." + Array.from(el.classList).slice(0, 2).join(".") : ""}`;

    // The gold of the surface the ring sits on.
    const rail = el.closest(".nav-rail");
    const probe = document.createElement("span");
    probe.style.color = rail ? "var(--rail-accent)" : "var(--app-action)";
    (rail ?? document.body).appendChild(probe);
    const gold = getComputedStyle(probe).color;
    probe.remove();

    const rings = (node: Element) => {
      const cs = getComputedStyle(node);
      return cs.outlineStyle === "solid" && parseFloat(cs.outlineWidth) >= 2 && cs.outlineColor === gold;
    };
    const describe = (node: Element) => {
      const cs = getComputedStyle(node);
      return `outline ${cs.outlineStyle} ${cs.outlineWidth} ${cs.outlineColor}; shadow ${cs.boxShadow.slice(0, 60)}`;
    };

    if (rings(el)) return { sig, ok: true };
    if (owners.some(rings)) return { sig, ok: true };
    if (el instanceof SVGElement) {
      const stroked = Array.from(el.querySelectorAll("*")).some((shape) => {
        const cs = getComputedStyle(shape);
        return cs.stroke === gold && parseFloat(cs.strokeWidth) >= 2;
      });
      if (stroked) return { sig, ok: true };
    }
    return { sig, ok: false, what: describe(el) };
  }, CARRIERS);
}

const STOPS = 60;

test.use({ reducedMotion: "reduce" });

test.beforeEach(async ({ page }) => {
  await installEveryRoute(page);
  await installSettingsRoutes(page);
});

for (const theme of ["light", "dark"] as const) {
  for (const path of SCREENS) {
    test(`every keyboard stop on ${path} wears the one ring (${theme})`, async ({ page, isMobile }) => {
      test.skip(isMobile, "Tab order is a desktop keyboard contract; WebKit's Tab skips links by default");
      test.setTimeout(60_000);
      await page.addInitScript((t) => localStorage.setItem("theme", t), theme);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(path);
      await expect(page.locator("h1").first()).toBeVisible();

      const failures = new Map<string, string>();
      let judged = 0;
      for (let i = 0; i < STOPS; i++) {
        await page.keyboard.press("Tab");
        // Read on the rendering frame; reduced motion removes transition-duration waits.
        await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
        const verdict = await focusedRing(page);
        if (!verdict) continue;
        judged++;
        if (!verdict.ok && !failures.has(verdict.sig)) failures.set(verdict.sig, verdict.what!);
      }

      // A sweep that judged nothing would pass every screen.
      expect(judged, `${path}: the keyboard reached nothing`).toBeGreaterThan(5);
      expect([...failures].map(([sig, what]) => `${sig}: ${what}`), `${path} (${theme})`).toEqual([]);
    });
  }
}

for (const theme of ["light", "dark"] as const) {
  test(`a focused button paints its ring with normal motion (${theme})`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.addInitScript((value) => localStorage.setItem("theme", value), theme);
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.keyboard.press("Tab");
    await page.getByRole("button").first().focus();
    await expect.poll(async () => (await focusedRing(page))?.ok ?? false).toBe(true);
  });
}

test("the ring verifier refuses a control whose painted ring is removed", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.keyboard.press("Tab");
  await page.getByRole("button").first().focus();
  await expect.poll(async () => (await focusedRing(page))?.ok ?? false).toBe(true);
  await page.addStyleTag({ content: "button:focus-visible { outline: none !important; box-shadow: none !important; }" });
  expect((await focusedRing(page))?.ok).toBe(false);
});
