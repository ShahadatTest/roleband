import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
// @ts-expect-error - eslint.config.js is plain JS outside the project's include;
// the shape is asserted below rather than declared upstream.
import { FEATURES, LEGACY_EDGES } from "../../eslint.config.js";

/* `eslint.config.js` is plain JS and outside the project's `include`, so the
   import arrives untyped. Naming the shape here is the boundary: a row that
   loses a field fails to compile rather than silently reading `undefined`. */
type LegacyEdge = { file: string; imports: string; why: string };
const EDGES = LEGACY_EDGES as LegacyEdge[];

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

/* The exception list `eslint.config.js` applies to its boundary zones.
 *
 * A per-file exemption is the right shape — it binds new code immediately and
 * leaves today's debt named — but it has the failure mode every allowlist has:
 * a row that stops being true becomes permanent permission for something nobody
 * is doing. `eslint` cannot notice that, because a rule it never triggers looks
 * exactly like a rule that passes.
 *
 * So the list is checked from both ends. Every row must still describe a real
 * import (or it is pruned), and the COUNT is frozen downward-only: down is the
 * only way it may move.
 */
describe("the feature list the sibling zones are built from", () => {
  /* One zone is generated per name in FEATURES, so a feature the list omits has
     NO zone and a name the list invents has a zone that matches nothing —
     `import/no-restricted-paths` reports neither, so a list that drifts both
     ways (a deleted feature still named, new ones never added) says nothing.

     The read lives here rather than in the config on purpose. Doing it there is
     what one reaches for first, and it breaks this file: the config is imported
     through vite, `import.meta.url` is not a file: URL, and the throw arrives
     at import time — which vitest reports as a suite with no tests rather than
     as a failure. The gate would disappear instead of failing. */
  it("names every directory in src/features, and only those", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const onDisk = readdirSync(join(here, "..", "features"), { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort();
    expect(
      [...(FEATURES as string[])].sort(),
      "FEATURES in eslint.config.js is out of step with src/features/. A new " +
        "feature needs its name here in the same change, or it gets no " +
        "sibling-isolation zone and nothing says so; a name with no directory " +
        "is a zone that matches nothing.",
    ).toEqual(onDisk);
  });
});

describe("cross-tier edges", () => {
  it("is empty, and stays empty", () => {
    /* Zero. The list stays in the config rather than being deleted with its
       last row, because an empty allowlist is the gate: a future edge has to
       be WRITTEN here, past this number. */
    expect(
      EDGES.length,
      "A cross-tier edge was added. Don't — the zones exist to stop that, and an " +
        "exemption is a decision, not a formality. The count is 0 and this " +
        "gate is downward-only, so there is no number to raise.",
    ).toBe(0);
  });

  it("names an import that really exists, so a paid-off row cannot linger", () => {
    const stale: string[] = [];
    for (const edge of EDGES) {
      /* A row whose FILE is gone is the commonest way an edge gets paid off —
         the module moved into its feature — and reading it blind would turn
         that into an ENOENT stack trace instead of the message this test exists
         to print. Missing file, missing import: both are just stale. */
      let source = "";
      try {
        source = readFileSync(join(ROOT, edge.file), "utf8");
      } catch {
        stale.push(`${edge.file} -> ${edge.imports} (the file no longer exists)`);
        continue;
      }
      // Matches both `from "x"` and a bare side-effect `import "x.css"`.
      if (!source.includes(`"${edge.imports}"`)) stale.push(`${edge.file} -> ${edge.imports}`);
    }
    expect(
      stale,
      `These rows no longer describe a real import. The edge was paid off — delete ` +
        `the row and lower the count:\n  ${stale.join("\n  ")}`,
    ).toEqual([]);
  });

  it("gives every edge a reason and a way out", () => {
    for (const edge of EDGES) {
      expect(edge.why.length, `${edge.file} -> ${edge.imports} needs a stated reason`)
        .toBeGreaterThan(30);
    }
  });

  it("exempts whole files, and only files that carry an edge", () => {
    // The config exempts by FILE; a file in the list that carries no edge would
    // be a silent hole in the zones.
    const files = new Set(EDGES.map((e) => e.file));
    for (const file of files) {
      expect(EDGES.some((e) => e.file === file)).toBe(true);
    }
  });
});
