import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* Viewport breakpoints are a closed set, so a screen cannot pick a new one
 * without a check noticing.
 *
 * WHAT THIS GATE IS NOT. It is not a scale, and declaring one would be wrong:
 * the values disagree for a structural reason rather than a sloppy one.
 * Nearly every value outside the shell asks "how wide is this COMPONENT?"
 * while measuring the viewport, and the offset between the two steps at the
 * shell's own breakpoints. So a screen's number is a component width plus
 * whatever chrome was in force, and different screens sit behind different
 * chrome: two tabs of the same screen can make one decision at two numbers.
 *
 * The answer is `@container`, which the Board's column arms use
 * (`board-shell.test.ts` keeps them there), and this gate is the ratchet
 * toward it without a bulk rewrite: the set may only SHRINK. A new value fails by name; a value
 * whose last consumer migrates to `@container` must leave this list in the same
 * change, or it is permitted to come back.
 *
 * Deliberately NOT gated: `@container` widths. Those are the destination, and
 * freezing them would tax the migration this exists to encourage.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

/** A viewport threshold, wherever it is spelled. */
type Threshold = { px: number; where: string };

function files(dir: string, ext: RegExp, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) files(path, ext, acc);
    else if (ext.test(name)) acc.push(path);
  }
  return acc;
}

const rel = (file: string) => relative(SRC, file).split(sep).join("/");

/* Separated from the disk walk so the fixture below can run the real matcher
 * over modified text: a gate that has never been shown to fail is a gate nobody
 * has tested. */
export function scanCss(where: string, text: string): Threshold[] {
  const source = text.replace(/\/\*[\s\S]*?\*\//g, "");
  return [...source.matchAll(/@media\s*\((?:max|min)-width:\s*(\d+)px\)/g)].map((m) => ({
    px: Number(m[1]),
    where,
  }));
}

/* A CSS-only scan undercounts a width decided in TS. A threshold in a
 * `useMediaQuery`
 * string is the same decision as one in a media prelude and belongs in the
 * same frozen set. */
export function scanTs(where: string, text: string): Threshold[] {
  const source = text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  return [...source.matchAll(/\((?:max|min)-width:\s*(\d+)px\)/g)].map((m) => ({
    px: Number(m[1]),
    where,
  }));
}

export function viewportThresholds(): Threshold[] {
  const css = files(SRC, /\.css$/).flatMap((f) => scanCss(rel(f), readFileSync(f, "utf8")));
  /* Test files are excluded: they name widths inside assertions
     (`board-shell.test.ts` names container widths and the viewport widths it
     forbids), and scanning them would file those as viewport debt. */
  const ts = files(SRC, /\.tsx?$/)
    .filter((f) => !/\.test\.tsx?$/.test(f))
    .flatMap((f) => scanTs(rel(f), readFileSync(f, "utf8")));
  return [...css, ...ts];
}

/* The permitted literals, each with who owns it and what happens to it next.
 * `shell` values stay viewport questions -- the shell genuinely owns
 * "does the rail become a dock" -- and everything else is a container-query
 * candidate that should leave this list when its screen migrates.
 *
 * 1359 and 1360 are one boundary spelled twice, correctly: `RAIL_QUERY` and its
 * derived `RAIL_QUERY - 1`. They are the only pair in the app that is named
 * once and gated (`patterns/rail-shell.test.ts`), which is the pattern any
 * named threshold should follow -- `var()` is not permitted in a media feature
 * value and `@custom-media` has not shipped, so a TS constant plus a test IS
 * the only way to name one. */
const FROZEN: Record<number, string> = {
  1500: "job-detail wide reading measure — candidate: @container",
  1360: "shell — RAIL_QUERY (ui/FilterRail.tsx), gated",
  1359: "shell — RAIL_QUERY - 1 (patterns/rail-shell.css), gated",
  1240: "Profile walk's rail -> one column; top-stats third chip",
  1120: "shell — page gutter step (its only surviving content)",
  1100: "intelligence field/split stack — candidate: @container; job margin pill (MARGIN_QUERY, patterns/jobs/MarginBeacon.tsx), gated",
  1080: "schedule clock editor stack — candidate: @container (same decision as 1100)",
  980: "companies sector index; review decision bar — candidate: @container",
  /* Two consumers, not three: `.office-list` has no arm here because one would
     INVERT against the other — `.prof-shell` drops its 260px selector here, so
     the list would get wider at the pixel it lost a column. What is left is
     `.prof-shell` itself (deliberate: it holds two columns until its content is
     down to 501px, later than the 760 group, because it gives up navigation
     rather than a row grid) and `.offices-search`'s max-width uncap, which is
     monotonic in panel width and so merely fires early. */
  900: "company profiles shell (deliberate); offices search uncap — candidate: @container",
  860: "shell — rail -> bottom dock, toolbar unfreeze; filter sheet (SHEET_QUERY, patterns/FilterSurface.tsx), gated",
  760: "companies row / review ledger / statistics head — candidate: @container",
  700: "scope category toggle — candidate: @container",
  640: "ui/Card inset contract (card-inset.test.ts); overlays; intelligence",
  540: "shell — phone chrome (topbar labels out); settings head; statistics; board sort",
  520: "companies row -> card stack; schedule clock micro-type — candidate: @container",
};

describe("viewport breakpoints are a closed set, and it only shrinks", () => {
  const found = viewportThresholds();

  it("the scan can see a breakpoint at all", () => {
    /* Guards the scanner, not the codebase. Every assertion below passes for
       free if these regexes stop matching, and both have a shape that is easy
       to break: the CSS one tolerates the space in `@media (max-width: 860px)`
       and the TS one must not require it. */
    expect(found.filter((t) => t.where.endsWith(".css")).length).toBeGreaterThan(25);
    expect(found.filter((t) => !t.where.endsWith(".css")).length).toBeGreaterThan(2);
  });

  it("no screen invents a seventeenth breakpoint", () => {
    const strangers = found
      .filter((t) => !(t.px in FROZEN))
      .map((t) => `${t.px}px — ${t.where}`)
      .sort();
    expect(
      [...new Set(strangers)],
      "A viewport breakpoint outside the frozen set.\n" +
        "Almost always the honest fix is `@container` on the element that\n" +
        "actually cares about its own width — see\n" +
        "docs/ui.md If it really is a new SHELL\n" +
        "threshold, add it here with its owner and say why in the log.",
    ).toEqual([]);
  });

  it("a value whose last consumer went does not keep its slot", () => {
    const live = new Set(found.map((t) => t.px));
    const stale = Object.keys(FROZEN)
      .map(Number)
      .filter((px) => !live.has(px))
      .map((px) => `${px}px — ${FROZEN[px]}`);
    expect(
      stale,
      "Frozen breakpoints with no consumer left. Delete these rows in the same\n" +
        "change that removed their last use — a slot left open is permission for\n" +
        "the value to come back without a decision.",
    ).toEqual([]);
  });

  it("fails on a stranger, in both spellings", () => {
    /* The mutation fixture. Both matchers are exercised, because a CSS-only
       grep misses a threshold written inline in `useMediaQuery`. */
    expect(scanCss("fixture.css", "@media (max-width: 933px) { .x { color: red } }")).toEqual([
      { px: 933, where: "fixture.css" },
    ]);
    expect(scanTs("fixture.tsx", 'useMediaQuery("(max-width: 933px)")')).toEqual([
      { px: 933, where: "fixture.tsx" },
    ]);
    expect(933 in FROZEN).toBe(false);

    // A comment mentioning a width is documentation, not a breakpoint.
    expect(scanCss("fixture.css", "/* @media (max-width: 933px) was here */")).toEqual([]);
    expect(scanTs("fixture.tsx", '// "(max-width: 933px)" was here')).toEqual([]);

    // A container query is the destination, not the debt.
    expect(scanCss("fixture.css", "@container (max-width: 933px) { .x { color: red } }")).toEqual(
      [],
    );
  });
});
