import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* Sans weight is a RANK, and a rank only means something while it is scarce.
 *
 * IBM Plex Sans is a variable face here, so every weight renders; this is not
 * the mono problem (`font-weights.test.ts`, where an unloaded weight silently
 * paints as its nearest neighbour). It is worse in one way: every weight
 * renders, and almost none is distinguishable. A 20-unit step is invisible at
 * 13-16px, so several weights that all label the NAME of a row or the TITLE of
 * a block carry no signal; size and colour do the work and weight is noise.
 *
 * Four roles carry weight (`--app-weight-*`, tokens.css), and this gate is what
 * stops a literal arriving beside them.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

/** Graphics, not text: a company's letterform in a well. Exempt by name
 *  because the argument above is about type ranks, and that is not setting
 *  type. */
const GRAPHIC_EXEMPT = new Set(["ui/CompanyIcon.css"]);


/* **A sans font-weight literal is not allowed.** Roles only.
 *
 * If a genuine new rank is ever needed, it is a token in tokens.css and a
 * decision about the ramp — not a number in a screen's stylesheet. */

function sheets(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) sheets(path, acc);
    else if (name.endsWith(".css")) acc.push(path);
  }
  return acc;
}

/** The file that DEFINES the four roles. `--app-weight-name: 600` is the ramp,
 *  not an escape from it; everywhere else a weight literal inside a custom
 *  property is the same sixteenth rank wearing a name. */
const RAMP = "design/tokens.css";

/** Scan one stylesheet's TEXT. Separated from the disk walk so the mutation
 *  fixture below can run the real matcher over a modified copy of a real file —
 *  a gate that has never been shown to fail is a gate nobody has tested. */
export function scanSource(rel: string, text: string): { weight: number; where: string }[] {
  const out: { weight: number; where: string }[] = [];
  if (GRAPHIC_EXEMPT.has(rel)) return out;
  const source = text.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const [, selector, body] of source.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    // A rule that names the mono family is the other gate's business.
    if (/font-family:[^;]*(--app-font-mono|--mono)/.test(body)) continue;
    if (GRAPHIC_EXEMPT.has(`${rel}:${selector.trim()}`)) continue;
    const at = (w: string, how: string) =>
      out.push({ weight: Number(w), where: `${rel}  ${selector.trim().slice(0, 44)}${how}` });

    for (const [, w] of body.matchAll(/font-weight:\s*(\d{3})\b/g)) at(w, "");

    /* Two forms that render exactly like a bare literal:

       `font-weight: var(--app-weight-name, 650)` — the fallback is live CSS the
       moment the token is absent, which is precisely when it is hardest to
       notice, and

       `--row-weight: 650` used by a `font-weight: var(--row-weight)` — a literal
       that moved one line up and kept its name. */
    for (const [, w] of body.matchAll(/font-weight:\s*var\([^)]*,\s*(\d{3})\s*\)/g)) {
      at(w, "  (var() fallback)");
    }
    if (rel !== RAMP) {
      for (const [, prop, w] of body.matchAll(/(--[\w-]*weight[\w-]*)\s*:\s*(\d{3})\b/gi)) {
        at(w, `  (${prop})`);
      }
    }
  }
  return out;
}

export function sansWeightLiterals(): { weight: number; where: string }[] {
  return sheets(SRC).flatMap((file) =>
    scanSource(relative(SRC, file).split(sep).join("/"), readFileSync(file, "utf8")),
  );
}

/** How many sans rules set their weight from a role: the scanner's own proof
 *  of life when no literals are left to find. */
function sansWeightRoleUses(): number {
  let n = 0;
  for (const file of sheets(SRC)) {
    const source = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    n += [...source.matchAll(/font-weight:\s*var\(--app-weight-/g)].length;
  }
  return n;
}

/* Named escapes, each for a stated reason rather than as debt. The list may
 * only shrink. The resting title
 * is `--app-weight-name`, the role the ramp literally describes as "a row's
 * name", with no literal fallback under it.
 *
 * The two numerals are MONO, and the sans ramp is not their ramp — a mono
 * weight is governed by whether we LOAD the face, which is font-weights.test.ts's
 * job (both 500 and 400 are loaded). This scanner cannot tell a custom property's
 * family from the declaration alone, which is why they surface here at all.
 *
 * The read title is the one real question. 500 is `--app-weight-ui`'s number,
 * but a title is not a control, and filing it there would make the ramp mean
 * less to every later reader. The row uses 600/500 as an emphasis PAIR
 * (unread/read) and the ramp has no quiet-name rank to spell the
 * second half. Adding one is a decision about the ramp. */
const KNOWN_ESCAPES = [
  "400 — patterns/jobs/job-row.css  .job-row.is-viewed  (--row-numeral-weight)",
  "500 — patterns/jobs/job-row.css  .job-row  (--row-numeral-weight)",
  "500 — patterns/jobs/job-row.css  .job-row.is-viewed  (--row-title-weight)",
];

describe("sans weight is a rank, not a dial", () => {
  const found = sansWeightLiterals();

  it("the scan can see a sans weight at all", () => {
    // Guards the scanner, not the codebase: with zero literals left, the
    // assertion below passes for free if this regex ever stops matching. So
    // count what the app DOES set — the roles — and require the scanner to
    // find them.
    expect(sansWeightRoleUses()).toBeGreaterThan(80);
  });

  it("has not grown a new escape, and has not left a paid-off one named", () => {
    const seen = found.map((f) => `${f.weight} — ${f.where}`).sort();
    const stale = KNOWN_ESCAPES.filter((entry) => !seen.includes(entry));
    expect(
      stale,
      "these escapes no longer exist — delete them from KNOWN_ESCAPES so the list " +
        "cannot become permanent permission for something nobody is doing",
    ).toEqual([]);
  });

  it("sets sans weight from a role, never a literal", () => {
    expect(
      found.map((f) => `${f.weight} — ${f.where}`).filter((e) => !KNOWN_ESCAPES.includes(e)),
      `sans font-weight is one of four roles: --app-weight-body (400, prose), ` +
        `-ui (500, controls), -name (600, a row's name or a block's title, h1-h3), ` +
        `-strong (700, emphasis). A literal is a sixteenth rank nobody can see — ` +
        `the app had 16 of them across 146 declarations, five of which all meant ` +
        `"this is a name". Pick the role this text plays. A genuinely new rank is a ` +
        `token in tokens.css and a decision about the ramp.`,
    ).toEqual([]);
  });
});

/* The gate, shown failing. A matcher that has never produced a finding is
 * indistinguishable from one that cannot. These apply each defect to an
 * in-memory copy and require the matcher to name it.
 */
describe("the matcher fails for each defect it claims to catch", () => {
  const cases: [string, string][] = [
    ["a bare literal", ".x { font-weight: 650; }"],
    ["a var() fallback", ".x { font-weight: var(--app-weight-name, 650); }"],
    ["a literal hidden in a custom property", ".x { --x-weight: 650; }"],
  ];

  it.each(cases)("catches %s", (_label, css) => {
    expect(scanSource("features/probe/probe.css", css).map((f) => f.weight)).toEqual([650]);
  });

  it("does not fire on a role, which is the whole point of having roles", () => {
    expect(scanSource("features/probe/probe.css", ".x { font-weight: var(--app-weight-name); }")).toEqual([]);
  });

  it("leaves the ramp alone, where the roles are DEFINED", () => {
    // `--app-weight-name: 600` in tokens.css is the ramp, not an escape from it.
    expect(scanSource("design/tokens.css", ":root { --app-weight-name: 600; }")).toEqual([]);
  });

  it("still defers mono to the other gate", () => {
    const css = ".x { font-family: var(--app-font-mono); font-weight: 650; }";
    expect(scanSource("features/probe/probe.css", css)).toEqual([]);
  });
});
