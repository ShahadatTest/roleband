import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* The card inset.
 *
 * The app has ONE card: a 1px hairline, `--app-radius-lg`, an opaque ground.
 * Its inset follows the card's depth, never the screen it is on:
 *   space-5 (28)  a card that spans its column
 *   space-4 (20)  a card in a multi-column grid — the grid declares it
 *   space-3 (14)  a block nested inside a card
 *
 * This gate does not try to infer a card's DEPTH from source — that is a
 * rendering fact, and the browser asserts it (tests/ux). What it freezes is the
 * VOCABULARY: a card's inset is one of those three steps, named. A literal, or
 * a fourth step, is a screen inventing a card of its own.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

/* Excluded: most of settings.css is the Profile/Welcome families, which
 * render on other routes and still carry card literals; listing them here
 * would freeze the debt instead of the rule. The rule reaches every other
 * sheet. */
const NOT_YET_MIGRATED = new Set(["design/settings.css"]);

/** The three steps a card's inset may take. */
const ALLOWED = ["--app-space-5", "--app-space-4", "--app-space-3"];

/* Not every bordered, rounded box is a card, and the scan says so by SIZE
 * rather than by name. `padding: 0` is a frame whose rows carry their own
 * inset (`.review-history-list`, a <ul> with overflow hidden). Anything below
 * the smallest card step is a bar, a notice or a chip — `.review-decision-bar`
 * is a sticky grid of controls at space-2 — and those are a different object
 * on a different scale. */
const NOT_A_CARD = (padding: string) =>
  /^0(px)?$/.test(padding.trim()) ||
  /var\(--app-space-(1|2)\)/.test(padding) ||
  /^(?:[0-9]|1[0-3])px/.test(padding.trim());

function sheets(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) sheets(path, acc);
    else if (name.endsWith(".css")) acc.push(path);
  }
  return acc;
}

/** Rules that paint the card: hairline + the card radius + an inset. */
export function cardRules(): { file: string; selector: string; padding: string }[] {
  const found: { file: string; selector: string; padding: string }[] = [];
  for (const file of sheets(SRC)) {
    const rel = relative(SRC, file).split(sep).join("/");
    if (NOT_YET_MIGRATED.has(rel)) continue;
    const source = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    for (const [, selector, body] of source.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (selector.trim().startsWith("@")) continue;
      if (!/(?:^|[;\s])border:\s*1px/.test(body)) continue;
      if (!/border-radius:\s*var\(--app-radius-lg\)/.test(body)) continue;
      const pad = body.match(/(?:^|[;\s])padding:\s*([^;}]+)/);
      if (!pad) continue;
      const padding = pad[1].trim();
      if (NOT_A_CARD(padding)) continue;
      found.push({ file: rel, selector: selector.trim().replace(/\s+/g, " "), padding });
    }
  }
  return found;
}

/* No named exceptions. A row here names a card that sits off the scale,
 * and the pruning assertion below deletes a row whose card is gone. */
const KNOWN_OFF_SCALE: Record<string, string> = {};

/** Rules that only re-pad a card (no hairline or radius of their own), with
 *  whether they sit under the narrow arm (`max-width: 640px`). A responsive
 *  override is where an inset drifts, and the scan above cannot see it. */
export function cardPaddingOverrides(): { file: string; selector: string; padding: string; narrow: boolean }[] {
  const cards = new Set(cardRules().flatMap((r) => r.selector.split(",").map((s) => s.trim())));
  const found: { file: string; selector: string; padding: string; narrow: boolean }[] = [];
  for (const file of sheets(SRC)) {
    const rel = relative(SRC, file).split(sep).join("/");
    if (NOT_YET_MIGRATED.has(rel)) continue;
    const source = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    const narrowArms = [...source.matchAll(/@media\s*\(max-width:\s*640px\)\s*\{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}/g)]
      .map((m) => [m.index!, m.index! + m[0].length] as const);
    for (const match of source.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const [, selector, body] = match;
      if (selector.trim().startsWith("@") || /border-radius/.test(body)) continue;
      const pad = body.match(/(?:^|[;\s])padding:\s*([^;}]+)/);
      if (!pad) continue;
      const names = selector.split(",").map((s) => s.trim());
      if (!names.some((name) => cards.has(name))) continue;
      const at = match.index!;
      found.push({ file: rel, selector: selector.trim(), padding: pad[1].trim(),
                   narrow: narrowArms.some(([start, end]) => at > start && at < end) });
    }
  }
  return found;
}

describe("the card inset", () => {
  const rules = cardRules().filter((r) => !(r.selector.trim() in KNOWN_OFF_SCALE));

  it("every named exception still exists, and still needs the exception", () => {
    // The same discipline the decor allowlist keeps: a row that
    // matches nothing is describing code that has moved on, and an exception
    // list nobody prunes stops being a record and starts being an excuse.
    const all = cardRules();
    for (const [selector, why] of Object.entries(KNOWN_OFF_SCALE)) {
      const hit = all.find((r) => r.selector.trim() === selector);
      expect(hit, `stale exception: ${selector} is no longer a card rule — drop the row`).toBeTruthy();
      expect(
        ALLOWED.some((step) => hit!.padding.includes(step)),
        `${selector} is on the scale now (${hit!.padding}) — drop the row. Reason kept: ${why}`,
      ).toBe(false);
    }
  });

  it("finds the cards, so the assertion below is about something", () => {
    // A selector change or a radius rename would empty this scan silently, and
    // an empty scan passes every assertion it makes.
    expect(rules.length).toBeGreaterThanOrEqual(6);
  });

  it("re-pads a card below 640px with space-4 on every side, never a mix", () => {
    const overrides = cardPaddingOverrides();
    // The control: the scan finds the narrow card override it exists for.
    expect(overrides.some((o) => o.narrow && o.selector === ".settings-card")).toBe(true);
    const offenders = overrides
      .filter((o) => o.narrow && o.padding !== "var(--app-space-4)")
      .map((o) => `${o.file}  ${o.selector} (below 640px) -> padding: ${o.padding}`);
    expect(offenders, offenders.join("\n")).toEqual([]);
  });

  it("uses one of the three named steps, never a literal or a fourth value", () => {
    const offenders = rules
      .filter((r) => !ALLOWED.some((step) => r.padding.includes(step)))
      .map((r) => `${r.file}  ${r.selector.slice(0, 52)} -> padding: ${r.padding}`);
    expect(
      offenders,
      `a card's inset is --app-space-5 (spans its column), space-4 (in a ` +
        `multi-column grid) or space-3 (nested inside a card). A literal or a ` +
        `fourth value is a screen inventing its own card — which is how the app ` +
        `arrived at three insets for one surface. Found:\n  ${offenders.join("\n  ")}`,
    ).toEqual([]);
  });
});
