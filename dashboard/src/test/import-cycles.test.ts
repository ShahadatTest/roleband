// @vitest-environment node
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const FIXTURE = join(ROOT, "src", "test", "cycle-fixture");

/* `import/no-cycle` is an error with no allowlist, which makes it the one gate
 * whose passing state is indistinguishable from its broken state: a clean tree
 * reports nothing, and so does a rule that has silently stopped resolving.
 *
 * The rule needs `settings['import/parsers']` to parse the modules a file
 * imports; the resolver alone only answers which FILE a specifier names.
 * Configured with the resolver and nothing else, a two-file cycle in `src/`
 * lints clean, and `npm run lint` says "no issues" for the opposite reason.
 * Deleting that one settings key would do it, and no other test in this suite
 * would notice.
 *
 * So the gate is checked from the failing end: lint a pair of modules that
 * really do import each other and require the error by name.
 */
describe("the import cycle gate", () => {
  it("reports a real cycle, so a silently inert rule cannot pass as a clean tree", async () => {
    // `ignore: false` — the fixture is excluded from `npm run lint` precisely
    // because it violates the rule it exists to prove.
    const eslint = new ESLint({ cwd: ROOT, ignore: false });
    const results = await eslint.lintFiles([
      join(FIXTURE, "first.ts"),
      join(FIXTURE, "second.ts"),
    ]);

    expect(results.length, "the fixture files were not linted at all").toBe(2);
    const cycles = results.flatMap((r) =>
      r.messages.filter((m) => m.ruleId === "import/no-cycle"),
    );
    expect(
      cycles.length,
      "`import/no-cycle` did not fire on a pair of modules that import each " +
        "other. The rule is configured but enforcing nothing — check that " +
        "settings['import/parsers'] is still present in eslint.config.js, " +
        "since without it the rule cannot parse a file's dependencies and " +
        "every cycle in src/ reports clean.",
    ).toBeGreaterThan(0);
  });

  it("keeps the fixture excluded from the linted tree, so `npm run lint` stays green", async () => {
    // The mirror of the check above: if the exclusion were dropped, lint would
    // fail on a file that is *supposed* to violate the rule.
    const eslint = new ESLint({ cwd: ROOT });
    expect(await eslint.isPathIgnored(join(FIXTURE, "first.ts"))).toBe(true);
  });
});
