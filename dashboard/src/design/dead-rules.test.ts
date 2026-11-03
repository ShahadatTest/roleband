import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { CompPackage, JobCompPackage } from "../api";

/* The dead-rules gate.
 *
 * A screen rebuild deletes components and leaves their CSS. Dead rules are
 * invisible precisely because they look deliberate, so a one-time sweep
 * re-rots on the next rebuild: a class selector is only as good as the test
 * that something still renders it.
 *
 * For every class selector in a stylesheet under src/, some non-test source
 * file must reference the class. Composed names — `ui-badge-${tone}`,
 * `is-${tone}` — are the one hard part: the gate
 * carries a FROZEN prefix allowlist, and adding a row is a claim that a
 * component composes that family by interpolation (the composing file is
 * named beside each row; rows whose composer dies must go with it). The
 * tradeoff is explicit: a dead `.is-*` variant hides behind its family row,
 * so keep the families narrow.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "..");

/* Derived from disk, not enumerated, so a new sheet is gated by default: a
 * hand-written list misses exactly the new sheets, which is the wrong
 * direction for a gate to fail in.
 *
 * EXEMPT is the escape hatch, and it is meant to stay near-empty: a sheet here
 * is one nothing checks. */
const EXEMPT: Record<string, string> = {};

function stylesheets(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) stylesheets(path, acc);
    else if (name.endsWith(".css")) acc.push(relative(SRC, path));
  }
  return acc;
}

const SHEETS = stylesheets(SRC)
  .filter((sheet) => !(sheet in EXEMPT))
  .sort();

/** Frozen: families built by interpolation, each with its composing file. */
const COMPOSED_PREFIXES: Record<string, string> = {
  "ui-badge-": "ui/Badge.tsx (`ui-badge-${tone} ui-badge-${variant} ui-badge-${size}`)",
  // Primitives that compose their modifier from a prop.
  "ui-btn-": "ui/Button.tsx (`ui-btn-${variant}` + `ui-btn-${size}`)",
  "ui-sheet-": "ui/Sheet.tsx (`ui-sheet-${side}`)",
  "ui-search-": "ui/SearchField.tsx (`ui-search-${size}`)",
  "is-": "ui/Card.tsx (`is-${tone}`), features/intelligence/IntelligenceSection.tsx (`is-${origin}`)",
  "assessment-": "features/review/DecisionConsole.tsx (`assessment-${answer.recommendation}`)",
  "row-": "features/review/ComparisonLedger.tsx (`row-${row.key}`)",
  "pkg-": "features/job-detail/JobCompPanel.tsx (`pkg-${c.kind}`)",
  "req-band-": "features/job-detail/JobRequirementsPanel.tsx (`req-band-${skill.importance_band}`)",
  "jd-section-": "features/job-detail/JobDescription.tsx (`jd-section-${section.key}`)",
  "role-": "features/job-detail/LineageStack.tsx (`role-${mem.role}`)",
  "co-change-": "patterns/companies/CompanyChip.tsx (`co-change-${dir}`)",
  "split-src-": "features/job-detail/JobCompPanel.tsx (`split-src-${pkg.split_source}`)",
  "fresh-": "features/company-profiles/CompanyProfilePanel.tsx (`fresh-${freshness}`)",
  "health-": "features/company-profiles/CompanyProfilesView.tsx (`health-${c.data_health}`)",
};

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) walk(path, out);
    else if (/\.(tsx?|html)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
      out.push(path);
    }
  }
  return out;
}

const referenceBlob = [...walk(SRC), join(SRC, "..", "index.html")]
  .map((f) => readFileSync(f, "utf8"))
  .join("\n");

function classesIn(css: string): Set<string> {
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const classes = new Set<string>();
  for (const [, selector] of stripped.matchAll(/([^{}]+)\{[^{}]*\}/g)) {
    for (const [, cls] of selector.matchAll(/\.([a-zA-Z][\w-]*)/g)) {
      classes.add(cls);
    }
  }
  return classes;
}

describe("dead rules", () => {
  it.each(SHEETS)("%s styles only classes something renders", (sheet) => {
    const css = readFileSync(join(SRC, sheet), "utf8");
    const dead = [...classesIn(css)]
      .filter((cls) => !referenceBlob.includes(cls))
      .filter((cls) => !Object.keys(COMPOSED_PREFIXES).some((p) => cls.startsWith(p)))
      .sort();
    expect(
      dead,
      `${sheet} styles classes no component references. Delete the rules — a ` +
        `dead rule is invisible because it looks deliberate — or, if a component ` +
        `composes the name by interpolation, add its family to COMPOSED_PREFIXES ` +
        `with the composing file.`,
    ).toEqual([]);
  });

  it("paints every value a provenance chip is composed from", () => {
    // The other direction from the gate above: a composed class with NO rule.
    // A wire value without its rule renders unstyled, so it looks exactly like
    // a different value. Every wire value must have its rule.
    const surfaces = readFileSync(join(SRC, "design/surfaces.css"), "utf8");
    const values = [
      ...(["measured", "cross_family", "heuristic"] as const satisfies readonly NonNullable<JobCompPackage["split_source"]>[]),
      ...(["measured", "heuristic", "mixed"] as const satisfies readonly CompPackage["split_source"][]),
    ];
    const unpainted = [...new Set(values)].filter(
      (value) => !new RegExp(`\\.split-src-${value}(?![\\w-])`).test(surfaces),
    );
    expect(unpainted, "split-src values with no rule in design/surfaces.css").toEqual([]);
  });

  it("lists no composed family whose composer is gone", () => {
    // The allowlist is frozen the same way DECOR_GLYPH_SELECTORS is: a row
    // whose composing interpolation is gone would quietly exempt a
    // whole family of future dead rules.
    const composers = [
      ["ui-badge-", "ui/Badge.tsx", /ui-badge-\$\{/],
      ["is-", "ui/Card.tsx", /is-\$\{/],
      ["assessment-", "features/review/DecisionConsole.tsx", /assessment-\$\{/],
      ["row-", "features/review/ComparisonLedger.tsx", /row-\$\{/],
      ["pkg-", "features/job-detail/JobCompPanel.tsx", /pkg-\$\{/],
      ["req-band-", "features/job-detail/JobRequirementsPanel.tsx", /req-band-\$\{/],
      ["jd-section-", "features/job-detail/JobDescription.tsx", /jd-section-\$\{/],
      ["role-", "features/job-detail/LineageStack.tsx", /role-\$\{/],
      ["co-change-", "patterns/companies/CompanyChip.tsx", /co-change-\$\{/],
      ["split-src-", "features/job-detail/JobCompPanel.tsx", /split-src-\$\{/],
      ["fresh-", "features/company-profiles/CompanyProfilePanel.tsx", /fresh-\$\{/],
      ["health-", "features/company-profiles/CompanyProfilesView.tsx", /health-\$\{/],
    ] as const;
    for (const [prefix, file, pattern] of composers) {
      expect(
        pattern.test(readFileSync(join(SRC, file), "utf8")),
        `COMPOSED_PREFIXES lists "${prefix}" but ${file} no longer composes it`,
      ).toBe(true);
    }
  });
});
