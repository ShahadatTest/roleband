import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* Selection is declared in one place.
 *
 * What may be selected is decided by what an element IS — a control's label is
 * not prose — and that is stated once, in shell.css, beside `button { cursor:
 * pointer }`, the focus ring and `::selection`. A copy per sheet would each
 * decide alone, down to whether to ship the `-webkit-` prefix.
 *
 * This is the source half. It cannot see whether the rule WORKS, only whether
 * it is still the only one; tests/ux/selection.spec.ts measures the behaviour,
 * including the negative controls that stop the whole thing from being
 * satisfied by making the app uncopyable. Neither gate is sufficient alone.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

/** The sheet that owns the global element layer. Nothing else may declare it. */
const OWNER = "shell.css";

/* Empty, and meant to stay so. A drag surface needs more than CSS anyway (the
 * drag still STARTS a selection), so it takes `dragSurface` from src/ui/ rather
 * than a sheet of its own. A row added here is a claim
 * that some surface genuinely cannot say it in markup. */
const ALLOWED: { file: string; why: string }[] = [];

function stylesheets(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) stylesheets(path, acc);
    else if (name.endsWith(".css")) acc.push(path);
  }
  return acc;
}

/** Declarations only — a mention inside a comment is prose about the rule. */
function declarations(css: string): { prop: string; line: number }[] {
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
  const out: { prop: string; line: number }[] = [];
  for (const m of stripped.matchAll(/(^|[;{}\s])(-webkit-user-select|user-select)\s*:/g)) {
    out.push({ prop: m[2], line: stripped.slice(0, m.index).split("\n").length });
  }
  return out;
}

const SHEETS = stylesheets(SRC).map(
  (p) => [relative(SRC, p).split(sep).join("/"), readFileSync(p, "utf8")] as const,
);

describe("selection is declared in one place", () => {
  it("declares user-select only in the sheet that owns the element layer", () => {
    const allowed = new Set([OWNER, ...ALLOWED.map((a) => a.file)]);
    const strays = SHEETS.flatMap(([file, css]) =>
      allowed.has(file)
        ? []
        : declarations(css).map((d) => `${file}:${d.line} declares ${d.prop}`),
    );
    expect(
      strays,
      `Selection follows what an element IS, and shell.css says so for the whole\n` +
        `app: a role (button, summary, label, [role="tab"]…), the anchor shapes\n` +
        `that are controls, and [aria-hidden="true"].\n\n` +
        `A screen that needs a region unselectable marks the region in MARKUP —\n` +
        `data-selection="chrome" — and an island back on with data-selection=\n` +
        `"content". A drag surface takes dragSurface from src/ui/, because CSS\n` +
        `cannot stop a drag from starting a selection it then sweeps.\n` +
        `See docs/ui.md.\n  ${strays.join("\n  ")}`,
    ).toEqual([]);
  });

  it("never ships an unprefixed declaration alone", () => {
    /* No autoprefixer in this build (there is no postcss config), so a rule
       written without `-webkit-user-select` simply does not reach Safari, and
       nothing in CI would say so. Counted per rule block. */
    const bad: string[] = [];
    for (const [file, css] of SHEETS) {
      const stripped = css.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
      for (const block of stripped.matchAll(/\{([^{}]*)\}/g)) {
        const body = block[1];
        const plain = /(^|[;\s])user-select\s*:/.test(body);
        const webkit = /-webkit-user-select\s*:/.test(body);
        if (plain !== webkit) {
          const line = stripped.slice(0, block.index).split("\n").length;
          bad.push(`${file}:${line} has ${plain ? "user-select" : "-webkit-user-select"} without its pair`);
        }
      }
    }
    expect(
      bad,
      `Both spellings or neither. Safari still needs the prefix and this build\n` +
        `has no autoprefixer, so half a declaration is a rule that silently does\n` +
        `not apply on one engine:\n  ${bad.join("\n  ")}`,
    ).toEqual([]);
  });

  it("keeps no allowlist row that has stopped being true", () => {
    const stale = ALLOWED.filter(
      (a) => !SHEETS.some(([file, css]) => file === a.file && declarations(css).length > 0),
    ).map((a) => `${a.file} — no longer declares user-select; delete the row`);
    expect(stale).toEqual([]);
  });
});
