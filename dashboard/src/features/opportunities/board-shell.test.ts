import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* Screen contract for the Board's one-scroll layout.
 *
 * The Board scrolls the way Settings > Companies scrolls: `.main` is the ONE
 * scroller, the toolbar docks at the top via the SHARED `.app-toolbar` recipe
 * (surfaces.css), and the column head and filter register pin beneath it at
 * the toolbar's measured height. Whether that HOLDS is a geometry question
 * and lives in the UX suite; what lives here is the shape of the sheets that
 * make it possible, each a way the layout breaks:
 *
 *  - a screen restating the docked-toolbar physics locally, so the two
 *    screens drift (the whole reason the recipe is shared);
 *  - a sticky offset over a scroll-pad, resting 22px low;
 *  - a pinned band with a floating-card frame sliding under it: the shadow
 *    is a Gaussian, the band is a rectangle, and a cover only relocates the
 *    seam;
 *  - an offset stated as a literal where the band's height can wrap;
 *  - a column arm keyed to the viewport when the rail varies the table's
 *    width independently of it.
 */

const here = dirname(fileURLToPath(import.meta.url));
const sheet = [
  join(here, "board-shell.css"),
  // The two-column shell is shared with Notifications; the
  // Board's arm on it stays in board-shell.css, the physics live here.
  join(here, "..", "..", "patterns", "rail-shell.css"),
  join(here, "..", "..", "patterns", "jobs", "job-page.css"),
  join(here, "..", "..", "patterns", "jobs", "job-row.css"),
].map((path) => readFileSync(path, "utf8")).join("\n");
const css = sheet.replace(/\/\*[\s\S]*?\*\//g, "");
const surfacesSheet = readFileSync(join(here, "..", "..", "design", "surfaces.css"), "utf8");
const surfaces = surfacesSheet.replace(/\/\*[\s\S]*?\*\//g, "");

/** The block for a top-level selector, i.e. its first `{ ... }`. */
function rule(source: string, selector: string): string {
  const at = source.indexOf(`${selector} {`);
  expect(at, `${selector} not found in the sheet`).toBeGreaterThan(-1);
  const open = source.indexOf("{", at);
  return source.slice(open + 1, source.indexOf("}", open));
}

describe("the board's one-scroll layout", () => {
  it("docks the toolbar through the shared recipe, stated once", () => {
    // The Board renders the class; surfaces.css owns the physics; changing
    // one changes Settings' idiom and the Board together.
    const toolbar = readFileSync(join(here, "BoardToolbar.tsx"), "utf8");
    expect(toolbar).toContain('className="board-toolbar app-toolbar"');

    const recipe = rule(surfaces, '[data-design-system="app"] .app-toolbar');
    expect(recipe).toMatch(/position:\s*sticky/);
    expect(recipe).toMatch(/top:\s*0/);
    // The settings air ("pudding"): space-2 above the controls, space-4 held
    // open below, as PADDING inside the frozen band; the negative margin
    // hands the space-2 back to the flow.
    expect(recipe).toMatch(/padding:\s*var\(--app-space-2\)\s+0\s+var\(--app-space-4\)/);
    expect(recipe).toMatch(/margin-top:\s*calc\(-1 \* var\(--app-space-2\)\)/);
    // The page's own ground, so the band is invisible until rows slide behind.
    expect(recipe).toMatch(/background-color:\s*var\(--app-canvas\)/);
    expect(recipe).toMatch(/background-image:\s*var\(--app-ambient-image\)/);
    expect(recipe).toMatch(/background-attachment:\s*fixed,\s*fixed/);

    // And the Board's sheets do NOT restate the physics: no board-toolbar
    // block may declare its own position or padding, the drift the shared
    // class exists to prevent.
    const local = [...css.matchAll(/\.board-toolbar[^,{]*\{([^}]*)\}/g)].map((m) => m[1]);
    for (const block of local) {
      expect(block).not.toMatch(/position:/);
      expect(block).not.toMatch(/padding/);
    }
  });

  it("keeps `.main` the one scroller, with the sticky edge on the scrollport edge", () => {
    const root = rule(css, ".main.board-main");
    // No overflow override: the base `.main { overflow-y: auto }` is the page.
    expect(root).not.toMatch(/overflow/);
    expect(root).not.toMatch(/display:\s*flex/);
    // A sticky offset resolves against the content box; the scroll-pad is
    // zeroed so `top: 0` docks flush.
    expect(root).toMatch(/padding-top:\s*0/);
    // The hero pays its own top air instead, in the one page-header rule
    // every tab shares (surfaces.css), not a board-local margin.
    // The page measure is one rule for every child, the hero included.
    expect(rule(css, ".board-main > *")).not.toMatch(/margin-top/);
    const surfaces = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../../design/surfaces.css"), "utf8");
    expect(surfaces).toMatch(/\.main > \.page-hero\s*\{[^}]*margin-top:\s*var\(--app-space-5\)/);
  });

  it("pins the column head and the register at the toolbar's measured height", () => {
    const head = rule(css, ".list-head");
    const rail = rule(css, ".rail-shell-rail");
    expect(head).toMatch(/position:\s*sticky/);
    expect(rail).toMatch(/position:\s*sticky/);
    expect(head).toMatch(/top:\s*var\(--board-toolbar-h\)/);
    // The shared rail pins at its own property, and the Board's arm is what
    // fills it from the MEASURED bar. Asserted as the pair: the shared sheet
    // alone would pin at the 0px fallback on every screen, and the arm alone
    // would set a property nothing reads. Both halves, or the register rests
    // under the toolbar it is supposed to clear.
    expect(rail).toMatch(/top:\s*var\(--rail-shell-top, 0px\)/);
    expect(rule(css, ".board-shell")).toMatch(/--rail-shell-top:\s*var\(--board-toolbar-h\)/);
    // The default is the shared recipe's own arithmetic, gated on the docked
    // bar existing: Saved renders the same root with no bar, and its head
    // pins at the scrollport edge (0px). BoardScreen corrects the arithmetic
    // by measurement where the bar wraps.
    expect(rule(css, ".main.board-main")).toMatch(/--board-toolbar-h:\s*0px/);
    expect(rule(css, ".main.board-main:has(> .board-toolbar)")).toMatch(
      /--board-toolbar-h:\s*calc\(var\(--app-space-2\) \+ var\(--app-control-md\) \+ var\(--app-space-4\)\)/,
    );
    const route = readFileSync(join(here, "BoardScreen.tsx"), "utf8");
    expect(route).toContain('import { useMeasuredCssSize } from "../../hooks/useMeasuredCssSize"');
    expect(route).toContain('useMeasuredCssSize({ rootRef, elementRef: toolbarRef, property: "--board-toolbar-h" })');
    expect(route).toContain("toolbarRef={toolbarRef}");
    expect(route).not.toContain("setProperty(");
    // And nothing sticky in this sheet is offset by a raw number.
    const frozen = [...css.matchAll(/\{([^}]*position:\s*sticky[^}]*)\}/g)].map((m) => m[1]);
    expect(frozen.length).toBeGreaterThanOrEqual(2);
    const literals = frozen
      .map((block) => block.match(/\n\s*top:\s*([^;]+);/)?.[1].trim() ?? "")
      .filter((value) => /^[\d.]+px$/.test(value));
    expect(literals).toEqual([]);
  });

  it("wears the ledger treatment: nothing under a pinned band carries a frame", () => {
    // The Gaussian rule: a band over a shadow can only relocate the seam, so
    // the list has no shadow, and no radius, surface fill, or inner
    // scrollport either. Rows on the page's ground, hairlines,
    // one closing edge. Structurally Settings > Companies' table.
    const list = rule(css, ".job-list");
    expect(list).not.toMatch(/box-shadow/);
    expect(list).not.toMatch(/border-radius/);
    expect(list).not.toMatch(/background/);
    expect(list).not.toMatch(/overflow/);
    expect(list).toMatch(/border-bottom:\s*1px solid var\(--app-border\)/);
    // The pinned head is plain opaque canvas + wash, nothing translucent.
    const head = rule(css, ".list-head");
    expect(head).toMatch(/background-color:\s*var\(--app-canvas\)/);
    expect(head).toMatch(/background-image:\s*var\(--app-ambient-image\)/);
    expect(head).toMatch(/background-attachment:\s*fixed,\s*fixed/);
    expect(head).not.toMatch(/backdrop-filter/);
    expect(head).not.toMatch(/glass/);
  });

  it("lets the register overflow into its own valve, without trapping the wheel", () => {
    const rail = rule(css, ".rail-shell-rail");
    expect(rail).toMatch(/max-height:\s*calc\(100dvh/);
    expect(rail).toMatch(/overflow:\s*hidden auto/);
    // One scroll everywhere: a gesture that exhausts the rail must CHAIN into
    // the page, never die at the rail's edge.
    expect(rail).not.toMatch(/overscroll-behavior/);
  });

  it("keys the column arms to the table's own width, not the viewport", () => {
    expect(rule(css, ".job-list")).toMatch(/container-type:\s*inline-size/);
    expect(css).toMatch(/@container \(max-width: 1088px\)/);
    expect(css).toMatch(/@container \(max-width: 940px\)/);
    expect(css).not.toMatch(/@media \(max-width: 1240px\)/);
    expect(css).not.toMatch(/@media \(max-width: 1120px\)/);
  });

  it("unfreezes the shared toolbar below the card breakpoint, in the shared sheet", () => {
    // A wrapped bar would spend a phone viewport on chrome; the arm lives with
    // the recipe so every consumer unfreezes together. Longhands, never the
    // `background` shorthand.
    const narrow = surfacesSheet.slice(surfacesSheet.indexOf("@media (max-width: 860px)"));
    const arm = narrow.slice(narrow.indexOf(".app-toolbar"));
    const block = arm.slice(0, arm.indexOf("}"));
    expect(block).toMatch(/position:\s*relative/);
    expect(block).toMatch(/background-color:\s*transparent/);
    expect(block).toMatch(/background-image:\s*none/);
    expect(block).not.toMatch(/\n\s*background:/);
  });

  it("names the rail-mode boundary ONCE, in ui/FilterRail, and the sheet's arm matches it", () => {
    const rail = readFileSync(join(here, "..", "..", "ui", "FilterRail.tsx"), "utf8");
    const query = rail.match(/export const RAIL_QUERY = "([^"]+)"/)?.[1];
    expect(query).toBe("(min-width: 1360px)");
    const route = readFileSync(join(here, "BoardScreen.tsx"), "utf8");
    // BoardScreen consumes the constant; a second literal would drift.
    expect(route).not.toMatch(/const RAIL_QUERY\s*=/);
    expect(route).toMatch(/RAIL_QUERY/);
    expect(css).toMatch(/@media \(max-width: 1359px\)/);
  });
});
