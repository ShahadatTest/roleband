import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* Where a fact's evidence is allowed to live.
 *
 * A test that reads a stylesheet as TEXT is not testing the app; it is testing
 * what the app's source SAYS. That is the right instrument for exactly four
 * kinds of fact, all of which a browser either cannot see or cannot see
 * cheaply:
 *
 *   token-vocabulary — computed style shows `16px` whether it came from
 *     --app-space-4 or a literal, and `line-height: 1.5` whether it was
 *     declared or inherited. The distinction only exists in the source.
 *   selector-absence — you cannot render the rule that ISN'T there. A gate
 *     against a fork, a dead selector, or a doorway class nobody passes has
 *     no DOM to look at.
 *   cascade — which rule WON, and by how much. The browser paints the winner
 *     and says nothing about the margin, so a 0-2-0 tie decided by load order
 *     looks identical to a rule that outranks its rival.
 *   ownership — which module imports/declares what. An architecture fact.
 *
 * Everything else — interaction, focus behaviour, geometry as PAINTED,
 * accessibility — belongs in a component test or a Playwright spec, where it
 * is measured rather than read.
 *
 * Two gates, because the charter alone would be self-certifying.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");
const UX = join(SRC, "..", "tests", "ux");

function walk(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, acc);
    else acc.push(path);
  }
  return acc;
}

const rel = (path: string) => relative(SRC, path).split(sep).join("/");
const ALL = walk(SRC);

/* ── 1. The charter ──────────────────────────────────────────────────────────
 *
 * Every source-scanning test, by name and by the fact class that earns it the
 * instrument. Named rather than counted, for the same reason one-definition.ts
 * names its pairs: a count is satisfied by trading one entry for another, and
 * the whole question here is WHICH fact each file is asserting.
 *
 * Adding a row is the review. If the honest answer is "it renders and then
 * checks what it looks like", the file does not belong here at all.
 *
 * The seven `.tsx` rows are HYBRIDS, and they are the pattern the rest of this
 * charter is arguing for rather than an exception to it: ui/Button, Select,
 * TabBar, Toast and friends render for every behavioural fact (focus, keys,
 * aria, disabled) and read the sheet for the two facts rendering cannot reach —
 * "paints --app-* only" and "sizes from the control scale, never a literal".
 * Same file, one instrument each, chosen by what the fact is.
 */
type FactClass = "token-vocabulary" | "selector-absence" | "cascade" | "ownership";

const CHARTER: Record<string, FactClass> = {
  // The closed SET of viewport literals. A browser can show that a layout
  // reflowed; it cannot show which of sixteen numbers declared the arm, and it
  // certainly cannot see the seventeenth that has not been written yet. Where
  // the reflow LANDS is painted geometry and stays in the UX suite -- which is
  // the division this gate's own subject argues for.
  "design/breakpoints.test.ts": "token-vocabulary",
  // Which sheet may shape a read-only label: an ownership fact about where a
  // recipe lives, which no single render shows.
  "design/badge-geometry.test.ts": "ownership",
  // A width named in TS and its stylesheet twin: two spellings of one number
  // (no var() in a media feature), which nothing rendered at one width shows.
  "design/breakpoint-twins.test.ts": "token-vocabulary",
  // Which sheet may state a count badge's face and shape: an ownership fact
  // about where a recipe lives, which no single render shows.
  "design/count-badge.test.ts": "ownership",
  // Which icon files the page and its manifest name, and that each ships at the
  // size it declares: a browser shows one favicon and never reports a touch
  // icon or a manifest icon that is missing or mis-sized.
  "shell/appIcons.test.ts": "ownership",
  // Which value a provider passes: a fact about how the source builds it,
  // which one render cannot show (it re-renders the same either way).
  "context/provider-values.test.ts": "ownership",
  "design/card-inset.test.ts": "token-vocabulary",
  "design/dead-rules.test.ts": "selector-absence",
  "design/filter-grammar.test.ts": "token-vocabulary",
  "design/font-weights.test.ts": "token-vocabulary",
  "design/one-definition.test.ts": "selector-absence",
  "design/sans-weights.test.ts": "token-vocabulary",
  "design/state-grammar.test.ts": "token-vocabulary",
  "design/focus-ring.test.ts": "token-vocabulary",
  "design/literal-colours.test.ts": "token-vocabulary",
  // No screen shows a caught error's own message: an absence, with no DOM to
  // render until a request fails on a screen nobody tested.
  "features/intelligence/dialog-error.test.ts": "selector-absence",
  // No link writes the short /job/:id where the company is known.
  "routing/paths.test.ts": "selector-absence",
  "design/primitive-states.test.ts": "selector-absence",
  "design/tokens.test.ts": "token-vocabulary",
  "features/companies/register.test.ts": "token-vocabulary",
  "features/company-profiles/profiles-scope.test.ts": "token-vocabulary",
  "features/compare/ownership.test.ts": "ownership",
  "features/intelligence/intelligence-scope.test.ts": "token-vocabulary",
  "features/job-detail/ownership.test.ts": "ownership",
  "features/notifications/ownership.test.ts": "ownership",
  "features/opportunities/board-shell.test.ts": "token-vocabulary",
  "features/opportunities/ownership.test.ts": "ownership",
  "features/review/review-scope.test.ts": "token-vocabulary",
  "features/saved/ownership.test.ts": "ownership",
  "hooks/read-state.test.ts": "ownership",
  "patterns/jobs/board-focus.test.ts": "cascade",
  // Which module composes the shell and which sheet states its physics --
  // an architecture fact. The painted consequence (does the register clear
  // the bar) is geometry and is measured in the UX suite.
  "patterns/rail-shell.test.ts": "ownership",
  // Which screens own a page identity and which are tab shells -- an
  // architecture fact about composition, not about what any of them look like.
  "patterns/page-header.test.ts": "ownership",
  "patterns/jobs/row-grammar.test.ts": "token-vocabulary",
  "route-registry.test.ts": "ownership",
  "ui/SettingsDesignSystemRoot.test.tsx": "token-vocabulary",
  "design/geometry.test.ts": "token-vocabulary",
  "design/settings-doorway.test.ts": "selector-absence",
  "shell.test.ts": "token-vocabulary",
  "test/compat-reexport.test.ts": "ownership",
  // Which origin a Playwright route pattern may match -- a fact about what
  // the spec source DECLARES, and deliberately not a run. A green suite is
  // evidence about ONE serving mode: the unanchored patterns this forbids
  // are inert against a build and hijack dev-server source modules, so the
  // mode that stays green is exactly the mode that cannot see them.
  "test/ux-route-patterns.test.ts": "ownership",
  // The product language: whether a visible string uses the lexicon's word
  // is a fact about what the source SAYS, not what a browser paints. The
  // scan runs in scripts/copy-check.mjs; this test reads its named baseline.
  "test/copy-check.test.ts": "token-vocabulary",
  // The skill-category names against the backend catalog's category set: a
  // fact about two vocabularies agreeing, which nothing rendered can show.
  // Canonical message contracts and source usages are ownership facts.
  "copy/contracts.test.ts": "ownership",
  "copy/skills.test.ts": "token-vocabulary",
  // The notification keys against the backend's frozen registry: which keys a
  // server may send and with which parameters, a contract no render can show.
  // The samples half of the same file renders every key and compares text.
  "api/notificationText.test.ts": "token-vocabulary",
  // The edge list is an OWNERSHIP fact: which module may import which tier.
  // Nothing renders here — the claim is about the dependency graph, and the
  // scan exists to prune a row that has stopped describing a real import.
  "test/layer-edges.test.ts": "ownership",
  // Which module is imported for its EFFECT alone: a dependency-graph fact.
  // What such an import does at runtime is beside the point; the claim is
  // that package.json "sideEffects" names it, or the production build drops
  // it, and no render in the dev server can show that.
  "test/side-effects.test.ts": "ownership",
  // WHICH SHEET may declare a property. shell.css owns the global element
  // layer, so it owns what may be selected; the behaviour that rule produces
  // is a Playwright spec (tests/ux/selection.spec.ts), because a source scan
  // cannot see a drag.
  "design/selection.test.ts": "ownership",
  "test/control-inventory.test.ts": "selector-absence",
  "test/ratchet.test.ts": "selector-absence",
  "test/source-evidence.test.ts": "ownership",
  "ui/Button.test.tsx": "token-vocabulary",
  "ui/SearchField.test.tsx": "token-vocabulary",
  "ui/Segmented.test.tsx": "token-vocabulary",
  "ui/Select.test.tsx": "token-vocabulary",
  "ui/TabBar.test.tsx": "token-vocabulary",
  "ui/Toast.test.tsx": "token-vocabulary",
};

describe("the source-scan charter", () => {
  const scanners = ALL
    .filter((p) => /\.test\.tsx?$/.test(p))
    .filter((p) => /\breadFileSync\b/.test(readFileSync(p, "utf8")))
    .map(rel)
    .sort();

  it("classifies every test that reads source instead of rendering it", () => {
    const unlisted = scanners.filter((f) => !(f in CHARTER));
    expect(
      unlisted,
      "these tests read source files but claim no fact class. A source scan is " +
        "for token-vocabulary, selector-absence, cascade or ownership only — if " +
        "the fact is interaction, focus, painted geometry or accessibility, " +
        "render it instead (component test or Playwright spec):\n  " +
        unlisted.join("\n  "),
    ).toEqual([]);
  });

  it("keeps no charter row for a test that stopped scanning source", () => {
    // Same pruning rule as one-definition's allowlist: a list of reasons must
    // not be allowed to become a list of debt.
    const stale = Object.keys(CHARTER).filter((f) => !scanners.includes(f));
    expect(
      stale,
      `these charter rows no longer describe a source-scanning test. Delete ` +
        `them:\n  ${stale.join("\n  ")}`,
    ).toEqual([]);
  });
});

/* ── 2. The browser twin ─────────────────────────────────────────────────────
 *
 * A cascade or vocabulary fact usually has a painted consequence, and the file
 * that reads the source is supposed to say where that consequence is measured.
 * board-focus.test.ts is the model: "the browser half is board-shell.spec.ts,
 * which measures the painted outline after click-then-Escape".
 *
 * A pointer nobody checks rots: splitting or renaming a spec leaves every file
 * that named it pointing at nothing, and every other gate stays green. So the
 * names are resolved.
 */
describe("a spec named in the source", () => {
  const specs = new Set(readdirSync(UX).filter((f) => f.endsWith(".spec.ts")));

  it("is a spec that exists", () => {
    const dangling: string[] = [];
    for (const path of ALL.filter((p) => /\.(tsx?|css)$/.test(p))) {
      const source = readFileSync(path, "utf8");
      for (const [, name] of source.matchAll(/([a-z0-9-]+\.spec\.ts)\b/g)) {
        if (!specs.has(name)) dangling.push(`${rel(path)} -> ${name}`);
      }
    }
    expect(
      dangling,
      "these files point at a Playwright spec that is not in tests/ux/. The " +
        "pointer is the only thing saying where the painted half of the fact " +
        "is measured, so a stale one is worse than none:\n  " +
        dangling.join("\n  "),
    ).toEqual([]);
  });

  it("is pointed at by the source at all, so the rule above is not vacuous", () => {
    const pointers = ALL
      .filter((p) => /\.(tsx?|css)$/.test(p))
      .filter((p) => /[a-z0-9-]+\.spec\.ts\b/.test(readFileSync(p, "utf8")));
    expect(pointers.length).toBeGreaterThan(2);
  });
});
