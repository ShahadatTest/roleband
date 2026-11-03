import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* Contract for the shared two-column shell.
 *
 * The composition is stated ONCE, so its contract is too, and each screen is
 * checked for the one thing it still owns.
 *
 * The physics that HOLD (does the register actually clear the bar, does the
 * wheel chain) are geometry and live in the UX suite. What lives here is the
 * shape that makes them possible.
 */

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..");
const read = (path: string) => readFileSync(join(src, path), "utf8");
const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");

const shellCss = strip(read("patterns/rail-shell.css"));

/** The block for a top-level selector, i.e. its first `{ ... }`. */
function rule(source: string, selector: string): string {
  const at = source.indexOf(`${selector} {`);
  expect(at, `${selector} not found`).toBeGreaterThan(-1);
  const open = source.indexOf("{", at);
  return source.slice(open + 1, source.indexOf("}", open));
}

/** Every screen wearing the shell, with the token its rail must pin under. */
const WEARERS = [
  {
    screen: "features/opportunities/BoardScreen.tsx",
    sheet: "features/opportunities/board-shell.css",
    arm: ".board-shell",
    token: "--board-toolbar-h",
  },
  {
    screen: "features/notifications/NotificationScreen.tsx",
    sheet: "features/notifications/notification-screen.css",
    arm: ".notif-shell",
    token: "--notif-toolbar-h",
  },
];

describe("the shared rail shell", () => {
  it("owns the register column's physics, stated once", () => {
    const rail = rule(shellCss, ".rail-shell-rail");
    expect(rail).toMatch(/position:\s*sticky/);
    expect(rail).toMatch(/max-height:\s*calc\(100dvh/);
    expect(rail).toMatch(/overflow:\s*hidden auto/);
    // One scroll everywhere: a gesture that exhausts the rail must CHAIN into
    // the page, never die at the rail's edge.
    expect(rail).not.toMatch(/overscroll-behavior/);
    // `align-items: start` is what lets a sticky child stick at all.
    expect(rule(shellCss, ".rail-shell")).toMatch(/align-items:\s*start/);
  });

  it("names the rail-mode boundary ONCE, in ui/FilterRail, and its arm matches", () => {
    const query = read("ui/FilterRail.tsx").match(/export const RAIL_QUERY = "([^"]+)"/)?.[1];
    expect(query).toBe("(min-width: 1360px)");
    // The sheet-side guard for the frame between a resize and the re-render.
    expect(shellCss).toMatch(/@media \(max-width: 1359px\)/);
  });

  it.each(WEARERS)("$arm composes the pattern instead of restating it", (wearer) => {
    const screen = read(wearer.screen);
    expect(screen).toContain('from "../../patterns/RailShell"');
    expect(screen).toMatch(/<RailShell\b/);
    // Never a hand-rolled aside per screen.
    expect(screen).not.toMatch(/<aside[^>]*aria-label="Filters"/);
  });

  it.each(WEARERS)("$arm fills --rail-shell-top from its own measured bar", (wearer) => {
    // Both halves matter. The shared sheet's `var(--rail-shell-top, 0px)`
    // fallback means a screen that forgets this arm does not fail loudly --
    // its register silently pins at the scrollport edge, under the toolbar it
    // was supposed to clear. So the arm is asserted per wearer, by name.
    const arm = rule(strip(read(wearer.sheet)), wearer.arm).replace(/\s+/g, " ").trim();
    expect(arm).toContain(`--rail-shell-top: var(${wearer.token})`);
    // And the token it names is measured, not a literal the bar can outgrow.
    expect(read(wearer.screen)).toContain(`property: "${wearer.token}"`);
  });
});
