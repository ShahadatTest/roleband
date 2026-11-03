import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { rules } from "./cssRules";

/* THE TWO STATES (docs/ui.md "Two states").
 *
 * One state wears one look on every screen: a chosen tab, chip, segment, card,
 * company profile or pay band is the same state, so it paints the same. A
 * paint keyed on a CLASS (`.on`, `.is-current`, `.selected`) that a component
 * sets beside the real state can disagree with that state.
 *
 * This is the source half. It holds three things:
 *   1. No selector keys a state on a state-word class. Paint is keyed on what
 *      the element IS: `aria-pressed`, `aria-selected`, `aria-current`,
 *      `aria-checked`, `:checked` (a card on its own input, `:has(> input:checked)`),
 *      or `data-chosen` on decoration that mirrors a choice.
 *   2. A rule keyed on a CHOSEN state paints colour only from `--app-chosen-*`;
 *      words under the chosen thing may also be secondary prose
 *      (`--app-text-muted`/`-faint`). A rule keyed on an ON state (a switch,
 *      the row it governs) paints only from `--app-on-*`. Literal colours fail.
 *   3. The tokens say what the rule says: chosen is the action colour, on is
 *      ink and never gold, and no material restates either set.
 * Focus rules are out of scope here (the focus ring is its own family).
 * The behaviour half is `tests/ux/state-grammar.spec.ts`.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

function sheets(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name !== "gen" && name !== "node_modules") sheets(path, acc);
    } else if (name.endsWith(".css")) acc.push(path);
  }
  return acc;
}

const SHEETS = sheets(SRC).map((path) => ({
  file: relative(SRC, path).split(sep).join("/"),
  css: readFileSync(path, "utf8"),
}));

/** A state-word class: `.on`, `.is-on`, `.active`, `.selected`, `.is-current`,
 *  `.ui-selected` ... A pseudo-class (`:active`, `:checked`) is the element's
 *  own state and is not matched; neither is a word that only starts with one
 *  (`.on-band`, `.active-filters`). */
const STATE_CLASS = /\.(?:is-|ui-)?(?:on|active|selected|current|picked|checked)(?![\w-])/;

/** Remove `:not(...)` (nesting-aware): a negated state is the REST state. */
function withoutNegations(selector: string): string {
  let out = "";
  for (let i = 0; i < selector.length; i++) {
    if (selector.startsWith(":not(", i)) {
      let depth = 0;
      for (; i < selector.length; i++) {
        if (selector[i] === "(") depth++;
        else if (selector[i] === ")" && --depth === 0) break;
      }
      continue;
    }
    out += selector[i];
  }
  return out;
}

/** The selector's subject: the compound after the last top-level combinator. */
function subject(selector: string): string {
  let depth = 0, cut = 0;
  for (let i = 0; i < selector.length; i++) {
    const c = selector[i];
    if (c === "(" || c === "[") depth++;
    else if (c === ")" || c === "]") depth--;
    else if (depth === 0 && /[\s>+~]/.test(c)) cut = i + 1;
  }
  return selector.slice(cut);
}

const ON = /\.ui-switch-track:checked/;
const CHOSEN = /\[aria-(?:pressed|selected|checked)="true"\]|\[aria-current(?!="false")|:checked|\[data-chosen\]/;

type Kind = "chosen" | "on";
function stateOf(selector: string): Kind | null {
  const s = withoutNegations(selector);
  if (/:focus(?:-visible|-within)?\b/.test(s)) return null;
  if (ON.test(s)) return "on";
  return CHOSEN.test(s.replace(ON, "")) ? "chosen" : null;
}

const COLOUR_PROPS = /^(?:color|background(?:-color)?|border(?:-(?:top|right|bottom|left))?(?:-color)?|box-shadow|outline(?:-color)?|fill|stroke|accent-color|text-decoration-color)$/;

/** Named exceptions: a file, the selector they cover, the extra tokens it may
 *  use, and why. Each must still match a rule (a dead exception fails). */
const EXCEPTIONS = [
  {
    file: "ui/Button.css",
    selector: /\.ui-btn-danger\[aria-pressed="true"\]/,
    tokens: /^--app-danger(?:-ink)?$/,
    why: "a destructive MODE is pressed in the danger hue: the rank is the meaning",
  },
  {
    file: "shell.css",
    selector: /\.rail-item\[aria-current="page"\]/,
    tokens: /^--rail-accent(?:-[a-z]+)?$/,
    why: "the rail is fixed-dark in both themes, so it paints the chosen grammar from its own dark copy of the set",
  },
  {
    file: "features/scope/walk/walk.css",
    selector: /\.(?:walk-mode-option|select-card)/,
    tokens: /^--walk-mode-(?:ink|soft|line)$/,
    why: "the two Interests lists: 'interested' resolves to the chosen set, 'not interested' to the danger hue, one grammar in two hues",
  },
];

type Finding = { at: string; detail: string };

function audit(): { classes: Finding[]; paints: Finding[]; usedExceptions: Set<number> } {
  const classes: Finding[] = [];
  const paints: Finding[] = [];
  const usedExceptions = new Set<number>();
  for (const { file, css } of SHEETS) {
    for (const rule of rules(css)) {
      for (const selector of rule.selectors) {
        const at = `${file}:${rule.line} ${selector}`;
        if (STATE_CLASS.test(selector)) classes.push({ at, detail: "keys a state on a class" });
        const kind = stateOf(selector);
        if (!kind) continue;
        const chosenSubject = stateOf(subject(selector)) !== null;
        const allowed =
          kind === "on"
            ? /^--app-on-(?:fill|wash)$/
            : chosenSubject
              ? /^--app-chosen-(?:wash|line|text|mark)$/
              : /^--app-(?:chosen-(?:wash|line|text|mark)|text-muted|text-faint)$/;
        const exception = EXCEPTIONS.findIndex((e) => e.file === file && e.selector.test(selector));
        for (const [prop, value] of rule.decls) {
          if (!COLOUR_PROPS.test(prop)) continue;
          if (/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(|color-mix\(/i.test(value)) {
            paints.push({ at, detail: `${prop}: ${value} (a literal colour)` });
            continue;
          }
          for (const [, token] of value.matchAll(/var\((--[\w-]+)/g)) {
            if (allowed.test(token)) continue;
            if (exception >= 0 && EXCEPTIONS[exception].tokens.test(token)) {
              usedExceptions.add(exception);
              continue;
            }
            paints.push({ at, detail: `${prop}: ${value} (${kind} paints only ${allowed.source})` });
          }
        }
      }
    }
  }
  return { classes, paints, usedExceptions };
}

const result = audit();
const show = (fs: Finding[]) => fs.map((f) => `${f.at}  ->  ${f.detail}`);

describe("the two states", () => {
  it("keys no state on a class: paint follows the element's own state", () => {
    expect(show(result.classes)).toEqual([]);
  });

  it("paints a chosen thing only gold, and a thing that is on only ink", () => {
    expect(show(result.paints)).toEqual([]);
  });

  it("every named exception still covers a live rule", () => {
    const dead = EXCEPTIONS.filter((_, i) => !result.usedExceptions.has(i)).map((e) => `${e.file} ${e.selector}`);
    expect(dead).toEqual([]);
  });

  it("reads the rules it claims to: the chosen tab, the switch, a card on its own input", () => {
    // A gate that matched nothing would pass everything. These are the
    // anchors: if the parser or the detectors drift, this fails first.
    const kinds = SHEETS.flatMap(({ file, css }) =>
      rules(css).flatMap((r) => r.selectors.map((s) => `${file} ${s} => ${stateOf(s)}`)),
    );
    expect(kinds).toContain('ui/TabBar.css .ui-tab[aria-selected="true"] => chosen');
    expect(kinds).toContain("ui/Switch.css .ui-switch-track:checked => on");
    expect(kinds).toContain("features/scope/ScopeSection.css .select-card:has(> input:checked) => chosen");
    expect(kinds).toContain("features/companies/CompaniesSection.css .ledger-row:has(.ui-switch-track:checked) => on");
  });
});

describe("the detectors fail the shapes they exist to catch", () => {
  // Negative controls: each line is a rule shape the gate must reject. If a
  // detector stops matching its shape, the gate is decoration.
  it.each([
    ".select-card.on",
    ".ledger-row.is-on",
    ".job-row.selected",
    ".review-decision-option.is-current",
    ".rail-item.active",
    ".pay-band.is-picked",
    ".ui-filterselect-option.ui-selected",
  ])("%s is a state class", (selector) => {
    expect(STATE_CLASS.test(selector)).toBe(true);
  });

  it.each([".sync-stream-total.on-band", ".ui-btn:active", ".active-filters", ".ui-switch-track:checked"])(
    "%s is not a state class",
    (selector) => {
      expect(STATE_CLASS.test(selector)).toBe(false);
    },
  );

  it("a negated state is the rest state, and a state under a descendant is still the state", () => {
    expect(stateOf('.walk-mode-option:not(:has(> input:checked)):hover .walk-mode-title')).toBeNull();
    expect(stateOf('.ui-seg-btn[aria-pressed="true"]')).toBe("chosen");
    expect(stateOf('.job-row:has(.jr-compare[aria-pressed="true"]) .job-title')).toBe("chosen");
    expect(stateOf(".ledger-row:has(.ui-switch-track:checked) .ledger-name")).toBe("on");
    expect(stateOf('.lineage-dot[aria-current="false"]')).toBeNull();
  });
});

describe("the tokens say what the rule says", () => {
  const tokens = readFileSync(join(SRC, "design", "tokens.css"), "utf8");
  const declared = (name: string) => tokens.match(new RegExp(`${name}:\\s*([^;]+);`))?.[1]?.trim();

  it("chosen is the action colour; on is ink, never gold", () => {
    expect(declared("--app-chosen-wash")).toBe("var(--app-action-soft)");
    expect(declared("--app-chosen-line")).toBe("var(--app-action-edge)");
    expect(declared("--app-chosen-text")).toBe("var(--app-action-text)");
    expect(declared("--app-chosen-mark")).toBe("var(--app-action)");
    expect(declared("--app-on-fill")).toBe("var(--app-text)");
    expect(declared("--app-on-wash")).toBe("var(--app-selected)");
  });

  it("declares each state token once, at :root, so the theme blocks carry it", () => {
    for (const name of ["--app-chosen-wash", "--app-chosen-line", "--app-chosen-text", "--app-chosen-mark", "--app-on-fill", "--app-on-wash"]) {
      expect(tokens.match(new RegExp(`${name}:`, "g")) ?? [], name).toHaveLength(1);
    }
  });

  it("no stylesheet but tokens.css restates a state token (a material may not re-tint a state)", () => {
    const restated = SHEETS.filter(({ file }) => file !== "design/tokens.css").flatMap(({ file, css }) =>
      [...css.matchAll(/(--app-(?:chosen|on)-[\w-]+)\s*:/g)].map((m) => `${file}: ${m[1]}`),
    );
    expect(restated).toEqual([]);
  });
});

describe("components set no state class either", () => {
  // A class with no rule behind it is inert today and a hook for the next
  // sheet tomorrow. Scanned where they were written: a conditional.
  const COND_STATE_CLASS = /\?\s*["'`]\s*(?:is-|ui-)?(?:on|active|selected|current|picked|checked)["'`]/;

  function tsx(dir: string, acc: string[] = []): string[] {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) {
        if (name !== "gen" && name !== "test") tsx(path, acc);
      } else if (name.endsWith(".tsx") && !name.includes(".test.")) acc.push(path);
    }
    return acc;
  }

  it("the detector catches the shapes that shipped", () => {
    for (const line of ['${on ? " on" : ""}', 'selected === mark.key ? "selected" : ""', '`${isActive ? "active" : ""}`', '{current ? " is-current" : ""}']) {
      expect(COND_STATE_CLASS.test(line), line).toBe(true);
    }
  });

  it("no component adds a state-word class conditionally", () => {
    const hits = tsx(SRC).flatMap((path) =>
      readFileSync(path, "utf8")
        .split("\n")
        .map((line, i) => ({ line, i }))
        // An attribute's VALUE is not a class (`data-flow={on ? "on" : "off"}`).
        .filter(({ line }) => COND_STATE_CLASS.test(line) && !/\b(?:data|aria)-[\w-]+=\{[^}]*\?/.test(line))
        .map(({ line, i }) => `${relative(SRC, path)}:${i + 1} ${line.trim()}`),
    );
    expect(hits).toEqual([]);
  });
});
