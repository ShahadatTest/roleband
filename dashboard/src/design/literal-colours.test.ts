import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { rules } from "./cssRules";

/* LITERAL COLOURS ONLY FALL.
 *
 * A colour written as a literal in a declaration is a colour no token governs:
 * it does not follow the theme, the material or a retune, so a literal right
 * in one theme is wrong in the other. This ratchet keeps them from growing:
 * per sheet, the number of literal colours in ordinary
 * declarations may only fall. A sheet below its number must lower it here, so
 * the slack never lets a new one in.
 *
 * Not counted: custom-property DEFINITIONS (`--x: #fff`), which are palettes
 * by declaration (tokens.css, the register material, the topbar's and the
 * rail's own sets in shell.css), and `transparent`/`currentColor`, which are
 * not colours. What is counted is a literal painted directly: `color: #fff`,
 * `box-shadow: 0 0 8px rgba(...)`, a gradient stop.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");
const LITERAL = /#[0-9a-f]{3,8}\b|\brgba?\(|\bhsla?\(/gi;

/** Edit DOWNWARD only. */
const BASELINE: Record<string, number> = {
  "copy/review/review.css": 2,
  "features/job-detail/job-detail.css": 1,
  "features/statistics/statistics.css": 2, // a mask gradient's alpha stops, not colour
  "patterns/companies/company-chip.css": 6, // the chip's glass highlight
  "patterns/companies/company-logo.css": 1,
  "shell.css": 8, // the always-dark rail and palette surfaces
  "ui/Overlay.css": 1, // the scrim
};

function sheets(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name !== "gen" && name !== "node_modules") sheets(path, acc);
    } else if (name.endsWith(".css")) acc.push(path);
  }
  return acc;
}

function count(css: string): number {
  let n = 0;
  for (const rule of rules(css)) {
    for (const [prop, value] of rule.decls) {
      if (prop.startsWith("--")) continue;
      n += (value.match(LITERAL) ?? []).length;
    }
  }
  return n;
}

const COUNTS = Object.fromEntries(
  sheets(SRC)
    .map((path) => [relative(SRC, path).split(sep).join("/"), count(readFileSync(path, "utf8"))] as const)
    .filter(([, n]) => n > 0),
);

describe("literal colours only fall", () => {
  it("no sheet paints more literal colours than its frozen number", () => {
    const over = Object.entries(COUNTS)
      .filter(([file, n]) => n > (BASELINE[file] ?? 0))
      .map(([file, n]) => `${file}: ${n} (frozen at ${BASELINE[file] ?? 0}; paint from a token)`);
    expect(over).toEqual([]);
  });

  it("a sheet below its number has its number lowered", () => {
    const slack = Object.entries(BASELINE)
      .filter(([file, n]) => (COUNTS[file] ?? 0) < n)
      .map(([file, n]) => `${file}: ${COUNTS[file] ?? 0} (frozen at ${n}; lower it)`);
    expect(slack).toEqual([]);
  });

  it("counts what it claims to: painted literals, never palette definitions", () => {
    // Negative and positive controls: two painted literals count,
    // a palette definition and a token do not.
    expect(count(".a { box-shadow: 0 0 0 5px rgba(219, 203, 144, 0.06); }")).toBe(1);
    expect(count(".b { border-color: rgba(255, 132, 132, 0.28); color: #c64040; }")).toBe(2);
    expect(count(".c { --tb-danger: #c64040; color: var(--tb-danger); }")).toBe(0);
    expect(count(".d { /* was #fff */ border-color: color-mix(in srgb, var(--app-action) 6%, transparent); }")).toBe(0);
  });
});
