import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* Screen contracts for the Companies register.
 *
 * These are contracts about THIS screen's rules, not about a token scope —
 * the scope contracts (contrast on every ground of every material, the decor
 * structural gate, the type-ramp shape) live with the tokens in
 * design/tokens.test.ts. What must stay true here:
 * the register sizes all type from the ramp, keeps rows min-height driven,
 * derives its sticky tiers instead of guessing them, and actually mounts the
 * material it is styled for.
 */

const here = dirname(fileURLToPath(import.meta.url));
const component = readFileSync(join(here, "CompaniesSection.css"), "utf8");
const material = readFileSync(join(here, "..", "..", "design", "materials", "register-material.css"), "utf8");
const strip = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, "");

describe("companies register", () => {
  it("sizes every rule from the scale — no raw px font-size survives", () => {
    // One literal invites the next, and the screen drifts into unrelated
    // sizes. The scale is only a scale if nothing opts out of it.
    const literals = [...strip(component).matchAll(/font-size:\s*([\d.]+px)/g)].map((m) => m[1]);
    expect(literals).toEqual([]);
    expect([...component.matchAll(/font-size:\s*var\(--app-type-/g)].length).toBeGreaterThan(12);
  });

  it("gives rows a minimum height, never a fixed one", () => {
    // WCAG 1.4.12: at line-height 1.5 a fixed-height row overflows its content.
    expect(strip(component)).toMatch(/\.ledger-row\s*\{[^}]*min-height:\s*var\(--register-row\)/);
    expect(strip(component)).not.toMatch(/\.ledger-row\s*\{[^}]*[^-]height:\s*var\(--register-row\)/);
  });

  it("derives every sticky tier from the bands above it instead of guessing", () => {
    // A hand-typed offset drifts into an overlap as soon as a row height
    // changes. Three tiers (toolbar, column header, sector head), so each
    // offset must be the SUM of what is frozen above it, never a literal.
    const css = strip(component);
    expect(css).toMatch(/--register-sticky-colhead:\s*var\(--register-toolbar-h\)/);
    expect(css).toMatch(
      /--register-sticky-sector:\s*calc\(\s*var\(--register-toolbar-h\)\s*\+\s*var\(--register-colhead-h\)\s*\)/,
    );
    expect(css).toMatch(/top:\s*var\(--register-sticky-colhead\)/);
    expect(css).toMatch(/top:\s*var\(--register-sticky-sector\)/);
    // No tier may be offset by a raw number: a literal here is an overlap
    // waiting to happen. `top: 0` is the toolbar itself and the narrow
    // override that unfreezes it, which are offsets against nothing.
    const offsets = [...css.matchAll(/\n\s*top:\s*([^;]+);/g)].map((m) => m[1].trim());
    // Guard the guard: a scan that found nothing would pass the filter below
    // while proving nothing about the sheet.
    expect(offsets.length).toBeGreaterThanOrEqual(4);
    expect(offsets.filter((value) => /\d/.test(value) && value !== "0")).toEqual([]);
  });

  it("gives the frozen toolbar a fallback height it can defend without JS", () => {
    // The measured height (CompaniesSection.tsx) corrects wrapping; the CSS
    // default has to be RIGHT on its own for the frame before the first
    // measurement, so it is stated as the band's arithmetic — top air, one
    // control, the gap above the register — not as a rounded literal.
    expect(strip(component)).toMatch(
      /--register-toolbar-h:\s*calc\(\s*var\(--app-space-2\)\s*\+\s*var\(--app-control-md\)\s*\+\s*var\(--app-space-4\)\s*\)/,
    );
  });

  it("pays for the frozen toolbar's air in padding, so the band covers it", () => {
    // Margins are transparent: rows would travel through the gap the toolbar
    // holds open above the register while the column header was still on its
    // way to its offset. The band has to own that space.
    const toolbar = strip(component).match(/\n\.ledger-toolbar\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(toolbar).toMatch(/position:\s*sticky/);
    expect(toolbar).toMatch(/padding:\s*var\(--app-space-2\)\s+0\s+var\(--app-space-4\)/);
    expect(toolbar).not.toMatch(/margin-bottom/);
    // And it must be opaque, or the rows show through it.
    expect(toolbar).toMatch(/background-color:\s*var\(--app-canvas\)/);
  });

  it("keeps the register arithmetic local plumbing, not system tokens", () => {
    // Row and header heights are this screen's layout arithmetic (manifest
    // carveOuts.localPlumbing): declared and consumed only in this stylesheet.
    // Promoted to --app-* they would masquerade as design decisions, and
    // --ledger-* is not a namespace any token scope declares.
    expect(strip(component)).not.toMatch(/--ledger-/);
    const declared = new Set(
      [...strip(component).matchAll(/^\s*(--register-[\w-]+)\s*:/gm)].map((m) => m[1]),
    );
    for (const consumed of strip(component).matchAll(/var\((--register-[\w-]+)/g)) {
      expect(declared.has(consumed[1]), `${consumed[1]} consumed but not declared here`).toBe(true);
    }
  });

  it("the material file mounts on the register attribute", () => {
    // The material carries layout only (no token, so no dark
    // twin): the sticky headers' padding rule is what the attribute mounts.
    expect(material).toMatch(/body\[data-material="register"\] \.settings-design-system/);
  });

  it("the component sets exactly that attribute", () => {
    const tsx = readFileSync(join(here, "CompaniesSection.tsx"), "utf8");
    expect(tsx).toContain('useBodyAttribute("data-material", "register")');
    expect(tsx).toContain('import { useBodyAttribute } from "../../hooks/useBodyAttribute"');
  });
});
