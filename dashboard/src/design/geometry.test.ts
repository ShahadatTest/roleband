import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* The geometry gate.
 *
 * A tokenised type ramp needs tokenised positions: when the boxes grow with
 * the type and the distances between them are literals, the screen congests
 * and every fix uncovers one more forgotten number. Four scales cover it
 * (space, control, radius, icon), and this file is what keeps literals out.
 *
 * The rule it enforces is narrow on purpose: rhythm properties in the four tab
 * stylesheets carry no bare px in the 4-48px band. Below 4px is a hairline or
 * an optical nudge; above 48px is an SVG dimension or a max-width. Neither is
 * composition rhythm, and forcing them onto a scale would be cargo cult.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "..");
const read = (rel: string) => readFileSync(join(SRC, rel), "utf8");
const strip = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, "");

/** Stylesheets that render the four Settings tabs. settings.css is excluded:
 *  most of it is the quarantined Profile/Welcome families, which render on
 *  other routes and move on their own schedule. */
const TAB_STYLESHEETS = [
  "design/materials/register-material.css",
  "features/companies/CompaniesSection.css",
  "features/intelligence/IntelligenceSection.css",
  "features/company-profiles/company-profiles.css",
  "features/settings/ScheduleSection.css",
  "ui/Card.css",
  /* A shared primitive, not a tab stylesheet, read because it renders across
     the Companies board. Primitive sheets join this list one at a time, once
     their literals are gone. */
  "ui/CompanyIcon.css",
] as const;

const RHYTHM_PROPS = [
  "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
  "padding-inline", "padding-block",
  "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
  "margin-inline", "margin-block",
  "gap", "row-gap", "column-gap",
  "border-radius",
];

function literalsIn(source: string): string[] {
  const out: string[] = [];
  for (const prop of RHYTHM_PROPS) {
    const re = new RegExp(`(?:^|[;{\\s])${prop}:\\s*([^;}]+)`, "g");
    for (const match of strip(source).matchAll(re)) {
      const value = match[1];
      if (/var\(|calc\(|clamp\(|env\(/.test(value)) continue;
      for (const px of value.matchAll(/(\d+(?:\.\d+)?)px/g)) {
        const n = Number(px[1]);
        if (n > 3 && n <= 48) out.push(`${prop}: ${value.trim()}`);
      }
    }
  }
  return out;
}

describe("settings geometry", () => {
  it.each(TAB_STYLESHEETS)("%s sizes rhythm from the scales, not literals", (file) => {
    const found = literalsIn(read(file));
    expect(
      found,
      `${file} sets rhythm with bare px. Use --*-space-1..6 for distance, ` +
        `--*-control-{sm,md,lg}(-pad) for a control's height AND its horizontal ` +
        `inset together, or --*-radius-{sm,md,lg,xl}. Found:\n  ${found.join("\n  ")}`,
    ).toEqual([]);
  });

  /* A CONTROL's own box, which the rhythm scan above cannot see.
   *
   * `height` is deliberately NOT in RHYTHM_PROPS: most heights in these sheets
   * are glyph dimensions — a 7px status dot, a 9px legend swatch, an 18px drag
   * grip — and forcing those onto a spacing scale is the cargo cult the file
   * header warns about.
   *
   * But a control's height IS on a scale ("--*-control-{sm,md,lg}(-pad) for a
   * control's height AND its horizontal inset together"), and a field off it
   * sits beside a `ui/Select` at a rank the scale does not have.
   *
   * So the scan is narrowed twice, and both narrowings are the point:
   *   - SUBJECT: a form control element, or a rule that declares
   *     `cursor: pointer`. A dot is neither.
   *   - BAND: 26-48px, the range a control box can plausibly occupy. Below it
   *     is a glyph inside a control (a 15px checkbox, a 24px drag grip);
   *     above it is a row or a panel.
   */
  const CONTROL_BAND: [number, number] = [26, 48];

  it("sizes a control's own box from the control scale", () => {
    const offScale: string[] = [];
    for (const file of TAB_STYLESHEETS) {
      const source = strip(read(file));
      for (const [, selector, body] of source.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
        const isControl =
          /(^|[\s>+~(])(input|select|textarea|button)\b/.test(selector) ||
          /cursor:\s*pointer/.test(body);
        if (!isControl) continue;
        for (const [, value] of body.matchAll(/(?:^|[;\s])(?:min-)?height:\s*([^;}]+)/g)) {
          if (/var\(|calc\(|clamp\(|%|auto/.test(value)) continue;
          const px = value.match(/(\d+(?:\.\d+)?)px/);
          if (!px) continue;
          const n = Number(px[1]);
          if (n < CONTROL_BAND[0] || n > CONTROL_BAND[1]) continue;
          offScale.push(`${file}  ${selector.trim().slice(0, 60)} -> height: ${value.trim()}`);
        }
      }
    }
    expect(
      offScale,
      `these controls size their own box with a bare px instead of ` +
        `--app-control-{sm,md,lg}. A height the scale does not have is how a ` +
        `screen ends up 2px out of step with the primitive beside it, and the ` +
        `inset drifts with it. Found:\n  ${offScale.join("\n  ")}`,
    ).toEqual([]);
  });

  it("gives every heading its own leading instead of inheriting prose", () => {
    // A heading is not prose. A rule that sets a type role but no line-height
    // inherits the body's 1.5, so a card heading sits in a box half again its
    // own size. That is loose where the screen is supposed to read tight, and
    // it is invisible in the source because the number simply is not there.
    //
    // Scoped to h1/h2/h3 on purpose: for a heading, prose leading is always
    // wrong, so the rule needs no exceptions. Body-like text inheriting 1.5 is
    // correct and stays unchecked. Grouped by selector so a media-query
    // override that only resizes may lean on its base rule's leading.
    const withLeading = new Set<string>();
    const setsRole = new Map<string, string>();

    for (const file of TAB_STYLESHEETS) {
      const source = strip(read(file));
      for (const rule of source.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
        const selector = rule[1].trim().replace(/\s+/g, " ");
        const body = rule[2];
        // The LAST compound must be the heading. `.intel-sel h3 small` targets
        // the small, not the h3, and inherits its leading legitimately.
        const targets = selector
          .split(",")
          .some((part) => /(^|[\s>+~])h[123]([.:#[][^\s>+~]*)?$/.test(part.trim()));
        if (!targets) continue;
        if (/font-size:\s*var\(--app-type-/.test(body)) {
          setsRole.set(`${file}  ${selector}`, selector);
        }
        if (/line-height:/.test(body)) withLeading.add(selector);
      }
    }

    expect(setsRole.size, "no heading rules found — the matcher has drifted").toBeGreaterThan(4);

    const bare = [...setsRole.entries()]
      .filter(([, selector]) => !withLeading.has(selector))
      .map(([where]) => where);

    expect(
      bare,
      "these heading rules set a size but no line-height, so they inherit the " +
        "body's 1.5 and render in a box half again their size:\n  " +
        bare.join("\n  "),
    ).toEqual([]);
  });

  it("keeps a control's height and its horizontal inset in step", () => {
    // Splitting the pair makes buttons tall and narrow: a height that grows
    // while the padding stays loses side-room, and the corners read sharper on
    // a bigger box. Every tier must define both halves.
    const tokens = read("design/tokens.css");
    for (const tier of ["sm", "md", "lg"]) {
      expect(tokens, `--app-control-${tier} is not defined`).toMatch(
        new RegExp(`--app-control-${tier}:\\s*\\d+px`),
      );
      expect(tokens, `--app-control-${tier}-pad is not defined`).toMatch(
        new RegExp(`--app-control-${tier}-pad:\\s*\\d+px`),
      );
    }
  });

  it("keeps the space scale monotonic and open at the top", () => {
    // A linear 4/8/12/16/20 compresses as it grows (ratios 2, 1.5, 1.33,
    // 1.25), so its widest steps, the ones that carry macro rhythm, are the
    // least distinguishable from each other.
    const tokens = read("design/tokens.css");
    const steps = [1, 2, 3, 4, 5, 6].map((n) => {
      const m = tokens.match(new RegExp(`--app-space-${n}:\\s*(\\d+)px`));
      expect(m, `--app-space-${n} is not defined`).toBeTruthy();
      return Number(m![1]);
    });
    for (let i = 1; i < steps.length; i++) {
      expect(steps[i], `space-${i + 1} must exceed space-${i}`).toBeGreaterThan(steps[i - 1]);
    }
    const ratios = steps.slice(1).map((v, i) => v / steps[i]);
    expect(Math.min(...ratios.slice(1)), "the scale flattens at the top").toBeGreaterThanOrEqual(1.3);
  });
});
