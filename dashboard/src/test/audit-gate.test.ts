/* The dependency audit gate's decisions (scripts/audit-gate.mjs), fed an
   `npm audit --json` report shaped as npm writes it: a package's own advisories
   are objects in `via`, an inherited one is the name of the package it comes from. */
import { describe, expect, it } from "vitest";
import { auditProblems, findingsOf } from "../../scripts/audit/gate.mjs";

const TODAY = "2026-10-19";

const REPORT = {
  vulnerabilities: {
    "js-yaml": {
      via: [
        { source: 1, name: "js-yaml", title: "Quadratic merge keys", severity: "high", url: "https://github.com/advisories/GHSA-52cp-r559-cp3m" },
        { source: 2, name: "js-yaml", title: "A moderate one", severity: "moderate", url: "https://github.com/advisories/GHSA-aaaa-bbbb-cccc" },
      ],
    },
    // Inherits js-yaml's advisory: listed by name only, never counted twice.
    "@redocly/openapi-core": { via: ["js-yaml"] },
    nanoid: {
      via: [{ source: 3, name: "nanoid", title: "Loops on size zero", severity: "critical", url: "https://github.com/advisories/GHSA-2v37-7h3g-55p8" }],
    },
  },
};

const exception = (over: Record<string, string> = {}) => ({
  id: "GHSA-52cp-r559-cp3m", package: "js-yaml", reason: "build tooling only", expires: "2026-11-01", ...over,
});

describe("findingsOf", () => {
  it("keeps high and critical advisories once each and drops lower ones and inherited names", () => {
    expect(findingsOf(REPORT).map((f) => [f.package, f.id, f.severity])).toEqual([
      ["js-yaml", "GHSA-52cp-r559-cp3m", "high"],
      ["nanoid", "GHSA-2v37-7h3g-55p8", "critical"],
    ]);
  });

  it("finds nothing in a clean report", () => {
    expect(findingsOf({ vulnerabilities: {} })).toEqual([]);
  });
});

describe("auditProblems", () => {
  const found = findingsOf(REPORT);

  it("fails on every finding no exception accepts", () => {
    const out = auditProblems(found, [], TODAY);
    expect(out).toHaveLength(2);
    expect(out[0]).toContain("js-yaml: GHSA-52cp-r559-cp3m (high)");
  });

  it("accepts a finding a current exception names, and fails the rest", () => {
    expect(auditProblems(found, [exception()], TODAY)).toEqual([
      expect.stringContaining("nanoid: GHSA-2v37-7h3g-55p8 (critical)"),
    ]);
  });

  it("holds an exception to its package", () => {
    const out = auditProblems(found, [exception({ package: "yaml" })], TODAY);
    expect(out.some((l) => l.startsWith("js-yaml: GHSA-52cp-r559-cp3m"))).toBe(true);
    expect(out.some((l) => l.includes("matches no finding"))).toBe(true);
  });

  it("fails an expired exception; one expiring today still holds", () => {
    const one = found.slice(0, 1);
    expect(auditProblems(one, [exception({ expires: TODAY })], TODAY)).toEqual([]);
    expect(auditProblems(one, [exception({ expires: "2026-10-18" })], TODAY)).toEqual([
      "js-yaml: exception GHSA-52cp-r559-cp3m expired on 2026-10-18",
    ]);
  });

  it("fails an exception that matches nothing, so the list shrinks", () => {
    expect(auditProblems([], [exception()], TODAY)).toEqual([
      "exception GHSA-52cp-r559-cp3m (js-yaml) matches no finding; remove it",
    ]);
  });

  it("fails an entry with no reason or a date it cannot compare, and accepts nothing with it", () => {
    const one = found.slice(0, 1);
    const noReason = auditProblems(one, [exception({ reason: "" })], TODAY);
    expect(noReason[0]).toContain("missing reason");
    expect(noReason.some((l) => l.startsWith("js-yaml: GHSA-52cp-r559-cp3m"))).toBe(true);
    expect(auditProblems(one, [exception({ expires: "1 Nov 2026" })], TODAY)[0]).toContain("YYYY-MM-DD");
  });
});

