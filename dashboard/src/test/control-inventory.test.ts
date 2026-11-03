import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* The button-class allowlist (docs/ui.md).
 *
 * The `hand-rolled-button` ratchet counts raw <button> ELEMENTS in TSX. It
 * cannot see the other half of the problem, the one that multiplies spellings
 * of "a bordered neutral button": a screen quietly authoring its OWN button
 * CSS, such as a keycap with a bottom skirt invented for one screen, which
 * reads as a stray shadow under one button in the whole app.
 *
 * What is frozen is the SET of class names, not a count: a name that is not
 * on the list is a new spelling and fails, and a name on the list that does
 * not exist is a migration that forgot to bank its win. Exact match both
 * ways, the same contract as tests/fixtures/route_table.json.
 *
 * A class is IN SCOPE when it paints a box and declares `cursor: pointer` —
 * "this is a clickable thing with chrome of its own". That is deliberately
 * behavioural rather than name-based: a class without `btn` in its name is
 * still a button, and a name-matching gate would let it through.
 *
 * Being on the list is an inventory entry, NOT an endorsement. Three kinds of
 * entry are legitimate long-term — the whole-row targets (docs/ui.md), the
 * non-button controls (`.pager`; the switch is `ui/Switch`), and `src/ui/`'s own
 * vocabulary, which is why src/ui/ is excluded from the scan entirely. Every
 * other entry is debt to migrate.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

function styleSheets(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) styleSheets(path, acc);
    else if (name.endsWith(".css")) acc.push(path);
  }
  return acc;
}

/** Every class that paints a clickable box, outside the primitive tier. */
export function clickableClasses(): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const file of styleSheets(SRC)) {
    const rel = relative(SRC, file);
    if (rel.split(sep)[0] === "ui") continue;
    const source = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    // Innermost {...} blocks: `[^{}]` cannot cross a brace, so an @media
    // prelude is skipped and the rule inside it is matched on its own.
    for (const [, selector, body] of source.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (!/cursor:\s*pointer/.test(body)) continue;
      if (!/\b(border|background|min-height|padding)\b/.test(body)) continue;
      for (const one of selector.split(",")) {
        // The SUBJECT of the selector, not its context: `.form .is-leading`
        // is a rule about `.is-leading`, and blaming `.form` would freeze a
        // layout class as if it were a control.
        const classes = [...one.matchAll(/\.([a-zA-Z][\w-]*)/g)].map((m) => m[1]);
        const subject = classes[classes.length - 1];
        if (!subject) continue;
        const where = found.get(subject) ?? [];
        if (!where.includes(rel)) where.push(rel);
        found.set(subject, where);
      }
    }
  }
  return found;
}

const baseline: string[] = JSON.parse(
  readFileSync(join(SRC, "test", "control-inventory-baseline.json"), "utf8"),
);

describe("button-class allowlist", () => {
  const found = clickableClasses();

  it("baseline is sorted and unique, so a diff reads as a diff", () => {
    expect(baseline).toEqual([...new Set(baseline)].sort());
  });

  it("no screen authors a button class that is not already inventoried", () => {
    const added = [...found.keys()].filter((n) => !baseline.includes(n)).sort();
    expect(
      added,
      `New clickable class(es) with chrome of their own: ` +
        added.map((n) => `.${n} (${found.get(n)!.join(", ")})`).join("; ") +
        `. Render <Button variant="primary|ghost|icon|link|danger"> from ` +
        `src/ui/Button.tsx instead — see docs/ui.md for the ` +
        `variant that fits and "Control rules" for why a screen-local button class ` +
        `is never the answer. If the control genuinely is not a button (a ` +
        `whole-row target, a switch), add it to ` +
        `src/test/control-inventory-baseline.json with a line in docs/ui.md`,
    ).toEqual([]);
  });

  it("a class retired by a migration is banked in the same change", () => {
    const stale = baseline.filter((n) => !found.has(n)).sort();
    expect(
      stale,
      `These names are in the allowlist but no longer style anything: ` +
        stale.map((n) => `.${n}`).join(", ") +
        `. Delete them from src/test/control-inventory-baseline.json in this ` +
        `change — an allowlist entry with nothing behind it is a slot a future ` +
        `screen can re-fill without argument.`,
    ).toEqual([]);
  });
});
