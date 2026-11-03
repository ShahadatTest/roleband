import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { rules, type Rule } from "./cssRules";

/* One definition per rule.
 *
 * Two sheets describing the same component render nothing wrong while they
 * agree, which is precisely the hazard: a change to either screen has to be
 * made twice, and a change made once leaves the two screens to drift apart
 * silently. Whichever sheet
 * loads last wins, so the drift shows up as a rendering difference nobody edited.
 *
 * The gate is by NAME, not by count. A number would let a new fork in as long as
 * an old one left in the same change; naming the survivors means a new one fails
 * with the selector printed.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

/* ------------------------------------------------------------------ parsing */

/** selector + the at-rule conditions it sits under. Two rules share a key only
 *  when they really do describe the same element in the same circumstances. */
function keys(css: string): Map<string, Rule[]> {
  const map = new Map<string, Rule[]>();
  for (const r of rules(css)) {
    for (const sel of r.selectors) {
      const k = r.scope ? `${r.scope} :: ${sel}` : sel;
      if (!map.has(k)) map.set(k, []);
      map.get(k)!.push(r);
    }
  }
  return map;
}

function stylesheetPaths(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) stylesheetPaths(path, acc);
    else if (name.endsWith(".css")) acc.push(path);
  }
  return acc;
}

/* --------------------------------------------------- the two-sheet contract */

/* Every stylesheet under src/, read once. */
const SHEETS = (() => {
  const all = stylesheetPaths(SRC);
  return all.map((p) => [relative(SRC, p).split(sep).join("/"), readFileSync(p, "utf8")] as const);
})();


/* ------------------------------------------------------- keyframe ownership */

/* Loaded for every route from `main.tsx`, so a keyframe defined in one of these
 * is reachable from anywhere. Everything else is a lazy chunk. This is that
 * import block, and nothing else may be added without adding the import. */
const ALWAYS_LOADED = new Set([
  "design/tokens.css",
  "design/overlays.css",
  "design/surfaces.css",
  "design/dataviz.css",
  "shell.css",
]);

describe("an animation resolves wherever its rule renders", () => {
  const sheets = SHEETS;

  const defined = new Map<string, string[]>();
  for (const [file, css] of sheets) {
    for (const m of css.matchAll(/@keyframes\s+([\w-]+)/g)) {
      if (!defined.has(m[1])) defined.set(m[1], []);
      defined.get(m[1])!.push(file);
    }
  }

  it("defines every keyframe exactly once", () => {
    // Two definitions of one name is a global collision decided by load order.
    const twice = [...defined].filter(([, files]) => files.length > 1);
    expect(twice.map(([n, f]) => `${n} in ${f.join(" + ")}`)).toEqual([]);
  });

  it("resolves every animation reference from the sheet that renders it", () => {
    const unresolved: string[] = [];
    for (const [file, css] of sheets) {
      if (ALWAYS_LOADED.has(file)) continue;
      for (const m of css.matchAll(/animation(?:-name)?\s*:\s*([^;}]+)/g)) {
        for (const token of m[1].split(",")) {
          const name = token.trim().split(/\s+/).find((t) => defined.has(t));
          if (!name) continue;
          const homes = defined.get(name)!;
          const reachable = homes.some((h) => h === file || ALWAYS_LOADED.has(h));
          if (!reachable) unresolved.push(`${file} uses @keyframes ${name}, defined only in ${homes.join(", ")}`);
        }
      }
    }
    // A rule whose keyframes live in a lazy sheet the route never loads
    // animates nothing, silently.
    expect([...new Set(unresolved)]).toEqual([]);
  });
});

/* ------------------------------------------------- one definition per sheet */

/** Longhands a shorthand resets — only the ones these sheets actually use. */
const SUBSUMES: Record<string, string[]> = {
  animation: ["animation-name", "animation-duration", "animation-timing-function", "animation-delay", "animation-iteration-count", "animation-direction", "animation-fill-mode", "animation-play-state"],
  background: ["background-color", "background-image", "background-repeat", "background-position", "background-size", "background-attachment"],
  border: ["border-color", "border-width", "border-style"],
  margin: ["margin-top", "margin-right", "margin-bottom", "margin-left"],
  padding: ["padding-top", "padding-right", "padding-bottom", "padding-left"],
  font: ["font-size", "font-weight", "font-family", "font-style", "line-height"],
  transition: ["transition-property", "transition-duration", "transition-timing-function", "transition-delay"],
  flex: ["flex-grow", "flex-shrink", "flex-basis"],
  inset: ["top", "right", "bottom", "left"],
};
const overriders = (prop: string) =>
  new Set([prop, ...Object.entries(SUBSUMES).filter(([, hs]) => hs.includes(prop)).map(([s]) => s)]);

describe.each(SHEETS)("%s states a rule once", (_file, css) => {
  const all = rules(css);

  it("has no rule a later one has already overridden in full", () => {
    /* Two rules with the same selector under the same at-rule conditions have
     * the same specificity by construction, so source order alone decides. Any
     * property the later one sets — directly or through a shorthand — is one the
     * earlier cannot deliver, and a rule whose every declaration is dead is dead
     * text that still reads like a decision. */
    const dead: string[] = [];
    for (let i = 0; i < all.length; i++) {
      const r = all[i];
      if (!r.decls.size || !r.selectors.length) continue;
      const later = all.slice(i + 1).filter((o) => o.scope === r.scope);
      const shadowed = r.selectors.every((sel) => {
        const after = later.filter((o) => o.selectors.includes(sel));
        return [...r.decls.keys()].every((prop) => {
          const kill = overriders(prop);
          return after.some((o) => [...o.decls.keys()].some((q) => kill.has(q)));
        });
      });
      if (shadowed) dead.push(`:${r.line} ${r.scope ? r.scope + " " : ""}${r.selectors.join(", ")}`);
    }
    expect(dead, `Fully overridden by a later rule in the same file — delete, or\nmerge into the rule that wins:\n  ${dead.join("\n  ")}`).toEqual([]);
  });

  it("declares a base rule before the @media that overrides it", () => {
    /* A media override and the base rule it overrides have the SAME specificity,
     * so a base rule written after the query wins over it — at every width. The
     * query still applies its other declarations, which is what makes this so
     * quiet: the rule half-works, and only at the widths nobody reads the
     * file at. */
    const beaten: string[] = [];
    all.forEach((m, i) => {
      if (!m.scope) return;
      for (const outer of all.slice(i + 1)) {
        if (outer.scope !== "") continue;
        const shared = m.selectors.filter((s) => outer.selectors.includes(s));
        if (!shared.length) continue;
        for (const prop of m.decls.keys()) {
          const kill = overriders(prop);
          if ([...outer.decls.keys()].some((q) => kill.has(q))) {
            beaten.push(`:${m.line} ${m.scope} { ${shared.join(", ")} { ${prop} } } is beaten by :${outer.line}`);
          }
        }
      }
    });
    expect([...new Set(beaten)], `A later unconditional rule outranks these media overrides:\n  ${[...new Set(beaten)].join("\n  ")}`).toEqual([]);
  });
});

/* ------------------------------------------------- one definition, any pair */

/* The rule is app-wide: a selector belongs to ONE sheet. Two sheets naming
 * it means the winner is decided by load order, which no author controls.
 * Exceptions are listed, never counted.
 */
/* Each row is a selector two sheets share with disjoint properties, so load
 * order decides nothing; `why` says which sheet owns which half. */
const CROSS_SHEET_ALLOWED: { selector: string; files: string[]; why: string }[] = [
  {
    selector: ".eyebrow",
    files: ["design/surfaces.css", "shell.css"],
    why: "disjoint properties, one owner each. surfaces.css owns what a kicker LOOKS like; shell.css owns whether it is text a reader may take, which is the global element layer's question and is answered there for every control and every piece of declared decoration at once. The two never name the same property, so load order decides nothing. It is here and not on the element because a kicker has no component to carry the mark -- 26 call sites apply the class by hand.",
  },
  {
    selector: ".notif-item",
    files: ["features/notifications/notification-bell.css", "features/notifications/notification-row.css"],
    why: "a deliberate split the sheets document: notification-row.css owns the row anatomy both consumers share, notification-bell.css owns the bell's own padded plate. Disjoint properties, one owner each.",
  },
];

describe("a selector belongs to one sheet", () => {
  const where = new Map<string, Set<string>>();
  for (const [file, css] of SHEETS) {
    for (const [key] of keys(css)) {
      if (!where.has(key)) where.set(key, new Set());
      where.get(key)!.add(file);
    }
  }

  const allowed = new Map(CROSS_SHEET_ALLOWED.map((a) => [a.selector, a]));

  it("names every selector that lives in two", () => {
    const forks: string[] = [];
    for (const [key, files] of where) {
      if (files.size < 2) continue;
      const ok = allowed.get(key);
      const list = [...files].sort();
      if (ok && list.join() === [...ok.files].sort().join()) continue;
      forks.push(`${key}\n       in ${list.join(", ")}`);
    }
    expect(
      forks,
      `A selector written in two sheets is decided by load order, not by its\n` +
        `author. Move the family into one sheet (scripts/css-consolidate.mjs), or\n` +
        `add it to CROSS_SHEET_ALLOWED with the reason it is not a fork:\n  ${forks.join("\n  ")}`,
    ).toEqual([]);
  });

  it("keeps no allowlist row that has stopped being true", () => {
    // An exception nobody can retire is how a list of reasons becomes a list of
    // debt. Each row has to still name a real two-sheet selector.
    const stale = CROSS_SHEET_ALLOWED.filter((a) => {
      const files = where.get(a.selector);
      return !files || files.size < 2;
    }).map((a) => `${a.selector} — no longer in two sheets; delete the row`);
    expect(stale).toEqual([]);
  });
});
