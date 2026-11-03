import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { rules } from "./cssRules";

/* A read-only label has one owner: ui/Badge, whose sheet holds its geometry.
 *
 * Two recipes for the same thing on one row drift apart, in size and in tone,
 * and nothing notices until a row looks wrong. So no sheet but ui/Badge.css
 * may shape a badge (radius, padding, height, type), and the old hand-written
 * `chip badge-*` labels may not come back. Layout around a badge (display,
 * gap, margin, flex) and the ink a washed ground needs stay with the screen.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");
const OWNER = "ui/Badge.css";
const GEOMETRY = /(?:^|[;\s{])(border-radius|padding(?:-[a-z]+)?|min-height|height|font-size|font-weight|line-height)\s*:/;

function files(dir: string, ext: RegExp, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) files(path, ext, acc);
    else if (ext.test(name)) acc.push(path);
  }
  return acc;
}

const rel = (file: string) => relative(SRC, file).split(sep).join("/");

/** Every rule outside the owner whose selector reaches a badge and whose body
 *  sets a geometry property. */
export function badgeGeometryOutsideOwner(where: string, css: string): string[] {
  if (where === OWNER) return [];
  const found: string[] = [];
  for (const rule of rules(css)) {
    const selector = rule.selectors.join(", ");
    if (!/\.ui-badge(?![\w-]*count)/.test(selector)) continue;
    const prop = [...rule.decls.keys()].find((name) => GEOMETRY.test(`${name}:`));
    if (prop) found.push(`${where}: ${selector} { ${prop} }`);
  }
  return found;
}

/** A hand-written label class, in a sheet or in markup. */
export function handWrittenLabels(where: string, text: string): string[] {
  return [...text.matchAll(/(?<![\w-])\.?badge-(band|loc|repost|match|twin|unconfirmed)\b/g)].map(
    (m) => `${where}: ${m[0]}`,
  );
}

describe("badge geometry has one sheet", () => {
  it("no sheet but ui/Badge.css shapes a badge", () => {
    const hits = files(SRC, /\.css$/).flatMap((f) => badgeGeometryOutsideOwner(rel(f), readFileSync(f, "utf8")));
    expect(hits, "shape the badge in ui/Badge.css (a variant or a shape), not from a screen").toEqual([]);
  });

  it("no hand-written chip label comes back", () => {
    const hits = files(SRC, /\.(css|tsx?)$/)
      .filter((f) => !f.endsWith("badge-geometry.test.ts"))
      .flatMap((f) => handWrittenLabels(rel(f), readFileSync(f, "utf8")));
    expect(hits, "a read-only row label is <Badge shape=\"tag\">").toEqual([]);
  });

  it("finds the shapes it exists to refuse", () => {
    // The reach-in this gate replaced, and a padding nudge from a screen.
    expect(badgeGeometryOutsideOwner("patterns/jobs/job-page.css",
      ".board-main .ui-badge { border-radius: 4px; font-weight: 600; }")).toHaveLength(1);
    expect(badgeGeometryOutsideOwner("features/x.css", ".x .ui-badge-tag { padding: 0 2px; }")).toHaveLength(1);
    // Layout and ink are the screen's.
    expect(badgeGeometryOutsideOwner("features/x.css", ".x .ui-badge { display: inline-flex; gap: 4px; margin-top: 0; }")).toEqual([]);
    expect(badgeGeometryOutsideOwner("features/x.css", ".cmp-cell .ui-badge-tag { color: red; }")).toEqual([]);
    expect(badgeGeometryOutsideOwner(OWNER, ".ui-badge-tag { padding: 2px 7px; }")).toEqual([]);
    expect(handWrittenLabels("x.tsx", '<span className="chip badge-repost">')).toHaveLength(1);
    expect(handWrittenLabels("x.css", ".badge-twin { color: red }")).toHaveLength(1);
    expect(handWrittenLabels("x.tsx", '<span className="ui-badge-warning">')).toEqual([]);
  });

  it("rejects badge geometry around nested rules while allowing owner geometry and screen layout", () => {
    const nested = ".x .ui-badge { padding: 0 2px; @media (hover: hover) { color: red; } }";
    expect(badgeGeometryOutsideOwner("features/x.css", nested)).toHaveLength(1);
    expect(badgeGeometryOutsideOwner("features/x.css",
      ".x { @media (hover: hover) { .ui-badge { font-weight: 600; } } }")).toHaveLength(1);
    expect(badgeGeometryOutsideOwner(OWNER, nested)).toEqual([]);
    expect(badgeGeometryOutsideOwner("features/x.css",
      ".x .ui-badge { margin: 0; @media (hover: hover) { color: red; } }")).toEqual([]);
  });
});
