import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { rules } from "./cssRules";

/* A PRIMITIVE OWNS ITS STATES (docs/ui.md rule 2,
 * "never redefine a shared class in a feature sheet").
 *
 * A feature sheet that repaints a primitive's state (a `ui/Button` icon's hover
 * in the danger hue, `.ui-btn.cmp-remove:not(:disabled):hover`) gives one
 * control two looks for one state. A different look for a state is a variant
 * of the primitive, added once with its whole state set.
 *
 * This fails any rule outside `src/ui/` whose selector names a `ui-` primitive
 * class together with a state (`:hover`, `:active`, `:focus*`, `:disabled`,
 * `[aria-*]`) and paints a colour. Geometry and opacity stay legal: a row may
 * reveal its actions (`.jr-actions .ui-btn` opacity) without repainting them.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");
const STATE = /:(?:hover|active|focus(?:-visible|-within)?|disabled)\b|\[aria-[a-z]+/;
const PRIMITIVE = /\.ui-[a-z]+(?:-[a-z]+)*/;
const COLOUR = /^(?:color|background(?:-color|-image)?|border(?:-(?:top|right|bottom|left))?(?:-color)?|box-shadow|outline(?:-color)?|fill|stroke)$/;

function sheets(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name !== "gen" && name !== "node_modules") sheets(path, acc);
    } else if (name.endsWith(".css")) acc.push(path);
  }
  return acc;
}

function findings(file: string, css: string): string[] {
  const out: string[] = [];
  for (const rule of rules(css)) {
    for (const selector of rule.selectors) {
      // The subject's compound: a state on an ANCESTOR (`.row:hover .ui-btn`)
      // is the row's state, not the primitive's.
      const compounds = selector.split(/\s*[\s>+~]\s*(?![^(]*\))/);
      const subject = compounds[compounds.length - 1];
      if (!PRIMITIVE.test(subject) || !STATE.test(subject)) continue;
      const painted = [...rule.decls.keys()].filter((p) => COLOUR.test(p));
      if (painted.length) out.push(`${file}:${rule.line} ${selector} paints ${painted.join(", ")}`);
    }
  }
  return out;
}

describe("a primitive owns its states", () => {
  it("no sheet outside ui/ repaints a primitive's state", () => {
    const hits = sheets(SRC)
      .map((path) => relative(SRC, path).split(sep).join("/"))
      .filter((file) => !file.startsWith("ui/"))
      .flatMap((file) => findings(file, readFileSync(join(SRC, file), "utf8")));
    expect(hits).toEqual([]);
  });

  it("catches the shape it exists for, and lets a row reveal its actions", () => {
    // Negative control: a feature sheet repainting a primitive's hover.
    expect(findings("x.css", ".ui-btn.cmp-remove:not(:disabled):hover { color: var(--app-danger); border-color: var(--app-danger); }")).toHaveLength(1);
    // Positive controls: opacity is not a repaint; an ancestor's hover is the ancestor's.
    expect(findings("x.css", ".job-row .jr-actions .ui-btn[aria-pressed=\"true\"] { opacity: 1; }")).toEqual([]);
    expect(findings("x.css", ".job-row:hover .ui-btn { opacity: 1; }")).toEqual([]);
  });
});
