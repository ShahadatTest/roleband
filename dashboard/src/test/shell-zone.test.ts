// @vitest-environment node
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RULE = "import/no-restricted-paths";

/* The shell tier's two boundaries, checked from the FAILING end.
 *
 * An import zone is the one kind of gate whose passing state is
 * indistinguishable from its broken state: a zone whose target directory does
 * not exist matches nothing and reports nothing, which reads exactly like a
 * clean tree. A list like `FEATURES` can name a deleted directory and omit
 * live ones with nothing saying so; the resolver and the parser settings have
 * the same shape.
 *
 * Renaming a tier is precisely when this bites: every zone naming the old
 * directory silently stops enforcing anything the moment it is gone. So both
 * shell zones carry a fixture that really commits the violation, and the rule
 * is required to fire on it by name.
 */
async function messagesFor(fixture: string) {
  // `ignore: false` — the fixtures are excluded from `npm run lint` precisely
  // because they violate the rules they exist to prove.
  const eslint = new ESLint({ cwd: ROOT, ignore: false });
  const results = await eslint.lintFiles([join(ROOT, fixture)]);
  expect(results.length, `${fixture} was not linted at all`).toBe(1);
  return results[0].messages.filter((m) => m.ruleId === RULE);
}

describe("the shell tier's import zones", () => {
  it("stops a primitive reaching up into the shell", async () => {
    const violations = await messagesFor("src/ui/zone-probe.fixture.ts");
    expect(
      violations.length,
      "A ui/ module imported src/shell/ and the zone said nothing. F1 depends " +
        "on tokens and services only; if this is silent, check that the ui zone " +
        "in eslint.config.js still names './src/shell' — a zone whose target or " +
        "source directory does not exist matches nothing and reports nothing.",
    ).toBeGreaterThan(0);
  });

  it("stops the shell importing a route", async () => {
    const violations = await messagesFor("src/shell/zone-probe.fixture.ts");
    expect(
      violations.length,
      "A shell module imported src/routes/ and the zone said nothing. The shell " +
        "is F6: App.tsx composes routes, chrome never reaches one.",
    ).toBeGreaterThan(0);
  });

  it("keeps both fixtures out of the linted tree, so `npm run lint` stays green", async () => {
    const eslint = new ESLint({ cwd: ROOT });
    for (const fixture of ["src/ui/zone-probe.fixture.ts", "src/shell/zone-probe.fixture.ts"]) {
      expect(await eslint.isPathIgnored(join(ROOT, fixture)), fixture).toBe(true);
    }
  });
});
