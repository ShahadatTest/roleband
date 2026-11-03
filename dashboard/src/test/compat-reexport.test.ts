import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* Compatibility-re-export gate: no compatibility re-export.
 *
 * When a module MOVES, the cheap move is to leave a one-line
 * `export { X } from "<new home>"` behind so no caller has to change. Each one
 * makes the old tier look inhabited: a file keeps importing a primitive from
 * the old tier long after the primitive left, so the layer lint sees a legal
 * edge and the next screen copies the wrong spelling.
 *
 * The gate is not "no re-exports": a BARREL is a tier's front door and its
 * whole job is to re-export (src/ui/index.ts). The distinguishing fact is that
 * a barrel is the module its neighbours are addressed THROUGH, while a shim is
 * a module nothing lives in. So the allowlist is by name, and it is short.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

// Front doors: a tier barrel that callers address the tier through. Anything
// else that is nothing but re-exports is a shim.
const BARRELS = new Set([
  "ui/index.ts",
  // Public formatting tier: independent implementation modules keep
  // currency/input/region code lazy. Consumers address this API, not its internals.
  "copy/format.ts",
  // The app shell's door into the typed client:
  // shell modules import `shellApi` and its types here, never `api/index.ts`,
  // and tests stand the mocked `api` in for this module (src/test/setup.ts).
  "api/shell.ts",
]);

function sourceFiles(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      sourceFiles(path, acc);
      continue;
    }
    if (!/\.(ts|tsx)$/.test(name) || /\.test\.(ts|tsx)$/.test(name) || name.endsWith(".d.ts")) {
      continue;
    }
    acc.push(path);
  }
  return acc;
}

// A module whose entire body — comments and blank lines aside — is
// `export ... from "…"` statements.
const RE_EXPORT_ONLY =
  /^(\s*export\s+(?:type\s+)?(?:\{[^}]*\}|\*)\s+from\s+["'][^"']+["'];?\s*)+$/;

function reExportOnlyModules(): string[] {
  const found: string[] = [];
  for (const file of sourceFiles(SRC)) {
    const rel = relative(SRC, file).split(sep).join("/");
    if (BARRELS.has(rel)) continue;
    const body = readFileSync(file, "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^[ \t]*\/\/.*$/gm, "");
    const code = body
      .split("\n")
      .filter((l) => l.trim())
      .join(" ");
    if (code && RE_EXPORT_ONLY.test(code)) found.push(rel);
  }
  return found;
}

describe("compatibility re-exports", () => {
  it("no module exists only to forward its exports somewhere else", () => {
    const shims = reExportOnlyModules();
    expect(
      shims,
      `these modules are nothing but re-exports:\n${shims.map((s) => `  src/${s}`).join("\n")}\n` +
        `A moved module updates its callers in the same change. Leaving a forwarding ` +
        `file behind keeps the old tier looking inhabited and teaches the next screen ` +
        `the wrong import path. A real tier ` +
        `barrel belongs in BARRELS above, with a reason.`,
    ).toEqual([]);
  });

  it("the scan can actually see a re-export module", () => {
    // Guards the regex, not the codebase: this assertion is what fails if the
    // pattern stops matching the shape it exists to catch, which would make the
    // gate above pass forever on an empty result.
    const shim = 'export { CompanyChip } from "../patterns/companies/CompanyChip";';
    expect(RE_EXPORT_ONLY.test(shim)).toBe(true);
    expect(RE_EXPORT_ONLY.test('export * from "./x";')).toBe(true);
    expect(RE_EXPORT_ONLY.test('export type { A } from "./x";')).toBe(true);
    expect(RE_EXPORT_ONLY.test('export function f() {} export { g } from "./x";')).toBe(false);
  });

  it("the barrel allowlist names modules that exist", () => {
    for (const rel of BARRELS) {
      expect(() => readFileSync(join(SRC, rel), "utf8"), `stale barrel entry: ${rel}`).not.toThrow();
    }
  });
});
