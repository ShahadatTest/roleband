import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// Legacy-marker ratchet (docs/architecture.md).
//
// New code must build on src/ui/ primitives; old code migrates screen-by-screen
// in redesign order. This test freezes the amount of legacy hand-rolled UI so
// it can only go DOWN: when a screen migrates, lower its numbers in
// src/test/ratchet-baseline.json in the same change. Edit the baseline only
// downward — raising a number means new legacy code, which the adoption rule
// forbids (use Overlay/Popover/Dialog/Sheet, FilterSelect, Badge,
// AsyncBoundary instead).
//
// Markers (line-count per marker over src/**/*.{ts,tsx}, excluding src/ui/,
// src/test/, and *.test.* files):
// - overlay-escape: hand-rolled Escape-to-close key handling
//     (`key === "Escape"`). Replacement: Overlay and its shells, or
//     `useEscapeLayer` (src/ui/escapeLayer.ts) for a surface that is not one.
//     Zero, and it has to stay there: Escape is the topmost layer's alone,
//     and a listener of its own hears every press, so two surfaces act on
//     one press together: palette closed, screen stepped back.
// - overlay-scrim: hand-rolled backdrop elements (className containing
//     "scrim"). Replacement: Overlay's scrim contract.
// - loading-spinner: hand-rolled `className="loading"` spinner blocks
//     (system 1 of 2). Replacement: AsyncBoundary default state.
// - loading-skeleton: hand-rolled skeleton rows — `className="skel*"` or the
//     legacy SkeletonRows component (system 2 of 2). Replacement:
//     AsyncBoundary's skeleton slot.
// - badge-pill: inline chip/badge-*/tier/pill class families on className
//     lines. Replacement: Badge (tone x variant x size).
// - hand-rolled-button: a raw `<button>` element outside src/ui/. Replacement:
//     Button (variant primary | ghost | icon, src/ui/Button.tsx).
//     A primitive nobody adopts leaves every screen re-picking a class by
//     hand, and the app drifts into many button spellings. This marker stops
//     the next one: a new raw button fails here and the failure names the
//     primitive. Legitimate exceptions exist (a whole-row nav target, a table
//     cell that happens to be pressable); they are paid for by REPLACING an
//     existing hand-rolled button, never by raising the number.
//     The count is NOT a count of reinventions, so do not convert them by
//     hand on that reading. The ones this app blesses are
//     named in docs/ui.md with what each one is: the rail's
//     theme toggle (it shares its class with the NavLinks beside it), the
//     palette's `role="option"` rows, StatChip's lens shape (two of its three
//     shapes are anchors), the chronograph's drag handle (a dot on a dial), and
//     the ⌘K opener (a shortcut hint, 22px/8.5px — the primitive's sm rank
//     would make it 28px/13px). The sync split is a named compound control.
//     A change may lower the number, none may raise it, and zero is not the
//     goal.

const MARKERS: Record<string, (line: string) => boolean> = {
  "overlay-escape": (line) => /\bkey === ["']Escape["']/.test(line),
  // "backdrop" counts as "scrim": a hand-rolled overlay may spell it that way,
  // and the meter must see it.
  "overlay-scrim": (line) => line.includes("className=") && /scrim|backdrop/.test(line),
  "loading-spinner": (line) => /className="loading"/.test(line),
  "loading-skeleton": (line) => /className="skel/.test(line) || line.includes("SkeletonRows"),
  "badge-pill": (line) =>
    line.includes("className=") && /(\bchip\b|\bpill\b|\btier\b|badge-)/.test(line),
  // `<button` at end-of-line is the multi-line JSX form:
  //     <button
  //       className="intel-btn"
  // A pattern like /<button[\s>]/ requires a character AFTER the tag name, so
  // on a split line it matches nothing, and that form is precisely the one a
  // screen reaches for when it is adding its OWN props to its OWN button class.
  "hand-rolled-button": (line) => /<button(?=[\s>]|$)/.test(line),
};

const SELF = fileURLToPath(import.meta.url);
const SRC = join(dirname(SELF), "..");
const EXCLUDED_DIRS = new Set(["ui", "test"]);

function sourceFiles(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    const rel = relative(SRC, path);
    if (statSync(path).isDirectory()) {
      if (!(rel.split(sep).length === 1 && EXCLUDED_DIRS.has(name))) sourceFiles(path, acc);
      continue;
    }
    if (!/\.(ts|tsx)$/.test(name) || /\.test\.(ts|tsx)$/.test(name) || name.endsWith(".d.ts")) {
      continue;
    }
    acc.push(path);
  }
  return acc;
}

/* Comments are not code, and the meter must not count them. A comment that
 * mentions a `<button>` would otherwise score on `hand-rolled-button`. The
 * failure mode is worse than an off-by-one: deleting an accurate comment would
 * "improve" the ratchet with no code change, so the number could be bought
 * with prose.
 *
 * Comment characters are BLANKED rather than removed, so line numbering
 * survives for anything that reports a location. `//` counts only when it opens
 * the line, because `https://` is not a comment. */
function stripComments(source: string): string {
  const blanked = source.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
  return blanked
    .split("\n")
    .map((line) => (line.trimStart().startsWith("//") ? "" : line))
    .join("\n");
}

function countMarkers(): Record<string, number> {
  const counts = Object.fromEntries(Object.keys(MARKERS).map((k) => [k, 0]));
  for (const file of sourceFiles(SRC)) {
    for (const line of stripComments(readFileSync(file, "utf8")).split("\n")) {
      for (const [marker, matches] of Object.entries(MARKERS)) {
        if (matches(line)) counts[marker] += 1;
      }
    }
  }
  return counts;
}

const baseline: Record<string, number> = JSON.parse(
  readFileSync(join(SRC, "test", "ratchet-baseline.json"), "utf8"),
);

/* The legacy vocabulary is EXTINCT, and this is the rule for it. An emptied
 * ratchet stops being one, so it is given a rule instead of a number.
 *
 * The rule is extinction, not scarcity. These names were the app's whole
 * dying vocabulary; every one has a --app-* counterpart, and a stylesheet that
 * declares or consumes one of them again has either resurrected the second
 * namespace or is reading a variable nothing defines — which paints as
 * `unset`, silently. A count could be satisfied by trading one use for another.
 * This cannot: the list is history and can only ever be violated.
 *
 * Frozen deliberately, not derived. There is no file left to parse it out of,
 * and deriving it from anything still living would make the gate agree with
 * whatever the app happens to say.
 */
const EXTINCT_TOKENS = [
  "--bg", "--bg-elev", "--bg-elev-2", "--bg-sunken", "--bg-glass",
  "--surface", "--surface-hover", "--border", "--border-strong",
  "--text", "--text-muted", "--text-faint",
  "--accent", "--accent-ink", "--accent-soft", "--accent-line", "--accent-text",
  "--accent-glow", "--signal", "--good", "--good-soft", "--good-line",
  "--warn", "--warn-soft", "--danger", "--danger-soft", "--danger-ink",
  "--data-2", "--info", "--success", "--warning",
  "--shadow", "--shadow-pop", "--radius", "--radius-sm", "--radius-lg",
  "--sidebar-w", "--nav-w", "--ease", "--ease-silk",
  "--t-fast", "--t-med", "--t-slow", "--font", "--mono",
];

/** Every use of a dead name, as `file: --name (declared|consumed|named)`. */
function extinctTokenUses(): string[] {
  const found: string[] = [];
  /* Its OWN walk, not `sourceFiles`. That one excludes `src/ui/` and `src/test/`
   * because the marker scan is about hand-rolled UI in feature code, which is a
   * different question — a `var(--text)` in a primitive's inline style is
   * exactly as dead as one in a screen. Only `*.test.*` is skipped, and only
   * because a test naming a dead token is asserting its ABSENCE or building a
   * fixture; neither paints anything. */
  const files = (dir: string, acc: string[] = []): string[] => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) files(path, acc);
      else if (/\.(css|ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) && !name.endsWith(".d.ts")) {
        acc.push(path);
      }
    }
    return acc;
  };
  for (const file of files(SRC)) {
    if (file === SELF) continue; // EXTINCT_TOKENS itself is a list, not a use
    const source = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    const rel = relative(SRC, file);
    for (const name of EXTINCT_TOKENS) {
      // Word-boundary on the right: `--text` must not match `--text-muted`,
      // and `--app-border` must not match `--border`.
      const edge = "(?![\\w-])";
      if (new RegExp(`var\\(\\s*${name}${edge}`).test(source)) found.push(`${rel}: ${name} (consumed)`);
      if (new RegExp(`(?<![\\w-])${name}${edge}\\s*:`).test(source)) found.push(`${rel}: ${name} (declared)`);
      // A QUOTED name — `getPropertyValue("--bg-elev")`. No var() gate can see
      // this: a chart that resolves its palette by reading token names as
      // strings gets nothing back for a dead one, and an unresolved property
      // there does not fall back to another vocabulary, it falls through to a
      // hard-coded literal.
      if (new RegExp(`["'\`]${name}${edge}`).test(source)) found.push(`${rel}: ${name} (named)`);
    }
  }
  return found.sort();
}

/* Non-semantic click targets, BY FILE. A `<div onClick>` is invisible to the
 * keyboard and to assistive tech; the a11y lint preset refuses new ones, with
 * an EXACT per-file allowlist in eslint.config.js for the ones that exist.
 * This scan is the meter behind that allowlist: it names the files, so a
 * migration lowers a number it can see, and the eslint list and this count cannot drift
 * apart without one of them failing. Multi-line JSX is why this is not a
 * line marker: the handler usually sits on its own line under the tag. */
const CLICK_TARGET = /<(div|span|li|article|section|p|h[1-6]|tr|td|ul|ol)\b[^>]*?\sonClick=/g;
export function nonSemanticClickTargets(): Record<string, number> {
  const byFile: Record<string, number> = {};
  for (const file of sourceFiles(SRC)) {
    const hits = readFileSync(file, "utf8").match(CLICK_TARGET)?.length ?? 0;
    if (hits) byFile[relative(SRC, file)] = hits;
  }
  return byFile;
}

describe("legacy-marker ratchet", () => {
  const counts = countMarkers();

  it("baseline tracks exactly the markers this test measures", () => {
    // The dead tokens are a rule (see EXTINCT_TOKENS above), not a marker: a
    // rule has no number to commit.
    expect(Object.keys(baseline).sort()).toEqual(
      [...Object.keys(MARKERS), "click-target"].sort(),
    );
  });

  it("click-target: non-semantic click targets stay at or below the baseline, by file", () => {
    const byFile = nonSemanticClickTargets();
    const count = Object.values(byFile).reduce((a, b) => a + b, 0);
    const max = baseline["click-target"];
    const listing = Object.entries(byFile).map(([f, n]) => `  ${f}: ${n}`).join("\n");
    if (count < max) {
      console.log(`[ratchet] click-target improved: ${count} < baseline ${max}. Lower the baseline.\n${listing}`);
    }
    expect(
      count,
      `non-semantic click targets grew (${count} > baseline ${max}). A clickable thing is a ` +
        `<button>, a link, or a pattern with a keyboard contract (patterns/jobs/JobLinkRow), ` +
        `never a <div onClick>. Files:\n${listing}`,
    ).toBeLessThanOrEqual(max);
  });

  it("legacy-tokens: the dead vocabulary stays dead", () => {
    expect(
      extinctTokenUses(),
      `These names were a legacy :root scope that no longer exists.\n` +
        `Nothing declares them and nothing may: each has an\n` +
        `--app-* counterpart in src/design/tokens.css, and a var() reading one of\n` +
        `these resolves to nothing at all — it paints as \`unset\`, with no error\n` +
        `anywhere. If you need a value the promoted system does not have, that is\n` +
        `a token in tokens.css and a decision about the ramp, never a name from\n` +
        `here:`,
    ).toEqual([]);
  });

  for (const marker of Object.keys(MARKERS)) {
    it(`${marker}: count stays at or below the committed baseline`, () => {
      const count = counts[marker];
      const max = baseline[marker];
      if (count < max) {
        // A screen migration paid down debt — lock in the win.

        console.info(
          `[ratchet] ${marker} improved: ${count} < baseline ${max}. ` +
            `Lower it in src/test/ratchet-baseline.json in this change.`,
        );
      }
      expect(
        count,
        `${marker} grew (${count} > baseline ${max}). New code must use src/ui/ ` +
          `primitives instead of hand-rolled legacy patterns (AGENTS.md adoption rule).`,
      ).toBeLessThanOrEqual(max);
    });
  }
});
