import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* Screen contracts for the Company-profiles feature. Same shape as
 * review-scope.test.ts: the stylesheet reaches into no dead or legacy
 * namespace, sizes all type from the ramp, and the route mounts both markers
 * the shared layers key on: the promoted-system attribute AND the register
 * material on `body` (as Companies and Intelligence do).
 */

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "company-profiles.css"), "utf8");
const strip = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, "");

describe("company-profiles screen contracts", () => {
  it("consumes only the app system or its own locally declared plumbing", () => {
    const source = strip(css);
    expect(source).not.toMatch(/--settings-|--ledger-|--profile-/);
    const declared = new Set(
      [...source.matchAll(/^\s*(--[\w-]+)\s*:/gm)].map((m) => m[1]),
    );
    const consumed = [...source.matchAll(/var\((--[\w-]+)/g)].map((m) => m[1]);
    expect(consumed.length).toBeGreaterThan(0);
    const foreign = consumed.filter(
      (token) => !token.startsWith("--app-") && !declared.has(token),
    );
    expect(foreign).toEqual([]);
    expect([...declared].filter((token) => token.startsWith("--app-"))).toEqual([]);
  });

  it("the sheet parses: balanced comments and braces", () => {
    // A malformed comment does not throw: the browser silently DROPS the
    // rule that follows it, so an override reads as "applied" in the source
    // and does nothing on the page. Orphaned prose between a `*/` and the
    // selector is invisible to everything but a computed-style reading, so
    // this structural check pins the exact failure mode.
    const opens = (css.match(/\/\*/g) ?? []).length;
    const closes = (css.match(/\*\//g) ?? []).length;
    expect({ opens, closes }).toEqual({ opens: closes, closes });
    // Nothing may sit between a comment's close and the next rule.
    expect(strip(css)).not.toMatch(/\*\//);
    const body = strip(css);
    expect((body.match(/\{/g) ?? []).length).toBe((body.match(/\}/g) ?? []).length);
  });

  it("sizes every rule from the scale — no raw px font-size", () => {
    const literals = [...strip(css).matchAll(/font-size:\s*([\d.]+px)/g)].map((m) => m[1]);
    expect(literals).toEqual([]);
    expect([...css.matchAll(/font-size:\s*var\(--app-type-/g)].length).toBeGreaterThan(25);
  });

  it("the route mounts the promoted-system marker and wears the register material", () => {
    // Without the attribute, surfaces.css/overlays.css are inert on this
    // screen; without the body material, the action set stays gold and the
    // screen falls out of the register material.
    const view = readFileSync(join(here, "CompanyProfilesView.tsx"), "utf8");
    expect(view).toContain('data-design-system="app"');
    expect(view).toContain('useBodyAttribute("data-material", "register")');
    expect(view).toContain('import { useBodyAttribute } from "../../hooks/useBodyAttribute"');
  });

  it("imports the material it wears and the controls it borrows", () => {
    // Setting data-material="register" does nothing unless the sheet that
    // defines the override is in the bundle. Relying on tabs.tsx eagerly
    // importing Companies would be an undeclared dependency a code-split turns
    // into a screen with none of the material's paper. The toolbar's switch is
    // ui/Switch, so only a `ledger-` class here would reach into the sheet.
    const view = readFileSync(join(here, "CompanyProfilesView.tsx"), "utf8");
    expect(view).toContain('import "../../design/materials/register-material.css"');
    if (/className="ledger-/.test(view)) {
      expect(view).toContain('import "../../design/materials/register-material.css"');
    }
  });

  it("recognition text wears whisper by function, never the chrome floor", () => {
    // Type by function: field labels and source chips are identified, not
    // read. Set at `label`, they would flatten the ramp's dynamic range.
    const rule = (selector: string) => {
      const m = strip(css).match(
        new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}[^{]*\\{([^}]*)\\}`),
      );
      return m ? m[1] : "";
    };
    for (const selector of [".prof-field-l", ".src-chip", ".fresh-dot"]) {
      expect(rule(selector)).toMatch(/font-size:\s*var\(--app-type-whisper\)/);
    }
  });
});
