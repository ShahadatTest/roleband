import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* Screen contracts for the second wearer of the register material.
 *
 * Intelligence consumes the ONE app system (--app-* at :root) and wears the
 * register material (design/materials/register-material.css) through the
 * same body attribute Companies sets. The contrast guarantees live with the
 * tokens (design/tokens.test.ts iterates materials × grounds); what must stay
 * true here is narrower: this stylesheet reaches into no dead or legacy
 * namespace, sizes all type from the ramp, and the screen actually mounts
 * the material it is styled for.
 */

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "IntelligenceSection.css"), "utf8");
const material = readFileSync(
  join(here, "..", "..", "design", "materials", "register-material.css"),
  "utf8",
);
const strip = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, "");

describe("intelligence screen contracts", () => {
  it("consumes only the app system or its own local plumbing", () => {
    // The invariant is that this file reaches into no OTHER vocabulary: not
    // the dead --ledger-/--settings- spellings, not a bare legacy :root token
    // from styles.css. A variable this stylesheet both defines and consumes
    // (a layout column shared by two rules, say) is local plumbing and cannot
    // drift with another system.
    const source = strip(css);
    expect(source).not.toMatch(/--settings-|--ledger-/);
    const declared = new Set(
      [...source.matchAll(/^\s*(--[\w-]+)\s*:/gm)].map((m) => m[1]),
    );
    const consumed = [...source.matchAll(/var\((--[\w-]+)/g)].map((m) => m[1]);
    expect(consumed.length).toBeGreaterThan(0);
    const foreign = consumed.filter(
      (token) => !token.startsWith("--app-") && !declared.has(token),
    );
    expect(foreign).toEqual([]);
    // And the local ones are genuinely local: never a redefinition of a token
    // the shared system owns.
    expect([...declared].filter((token) => token.startsWith("--app-"))).toEqual([]);
  });

  it("sizes every rule from the scale — no raw px font-size", () => {
    const literals = [...strip(css).matchAll(/font-size:\s*([\d.]+px)/g)].map((m) => m[1]);
    expect(literals).toEqual([]);
    expect([...css.matchAll(/font-size:\s*var\(--app-type-/g)].length).toBeGreaterThan(15);
  });

  it("the material file mounts on the register attribute", () => {
    // The material carries layout only (no token, so no dark
    // twin): the sticky headers' padding rule is what the attribute mounts.
    expect(material).toMatch(/body\[data-material="register"\] \.settings-design-system/);
  });

  it("the component sets exactly that attribute", () => {
    const tsx = readFileSync(join(here, "IntelligenceSection.tsx"), "utf8");
    expect(tsx).toContain('useBodyAttribute("data-material", "register")');
    expect(tsx).toContain('import { useBodyAttribute } from "../../hooks/useBodyAttribute"');
  });
});
