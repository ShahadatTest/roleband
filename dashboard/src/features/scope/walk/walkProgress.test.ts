import { describe, expect, it } from "vitest";
import type { ScopeCatalog } from "../../../api";
import { UNSTATED_LEVEL, type ScopeAxesSelection, type ScopeIndex } from "../scopeCells";
import { progressOf } from "./walkProgress";

/* The walk's funnel and roles whose level isn't stated: they are
   part of the market the funnel starts from, and the Level step keeps them
   only when the person ticks the choice. */

const catalog = {
  categories: [{ slug: "technology", display: "Technology", groups: [{ slug: "software_engineering" }] }],
  levels: [{ slug: "staff", display: "Staff", order: 4 }],
  tracks: [{ slug: "technical", display: "Technical (IC)", order: 2 }],
  locations: [{ slug: "uk", display: "United Kingdom" }],
  scope_cells: { cities: [] },
} as unknown as ScopeCatalog;

const index: ScopeIndex = {
  ready: true,
  companies: ["acme"],
  missingCompanies: [],
  staleCompanies: [],
  cells: [
    { role: "software_engineering", band: "staff", track: "technical", locations: ["uk"], domains: [], count: 3 },
    { role: "software_engineering", band: UNSTATED_LEVEL, track: "technical", locations: ["uk"], domains: [], count: 2 },
  ],
};

const draft = (includeUnstatedLevel: boolean): ScopeAxesSelection => ({
  roles: new Set(["software_engineering"]),
  bands: new Set(["staff"]),
  tracks: new Set(["technical"]),
  locations: new Set(["uk"]),
  domains: new Set(),
  includeUnstatedLevel,
});

describe("the walk funnel and roles whose level isn't stated", () => {
  it("counts them in the market the funnel starts from", () => {
    expect(progressOf(index, catalog, draft(false)).total).toBe(5);
  });

  it("keeps them at the Level step only when the person includes them", () => {
    const off = progressOf(index, catalog, draft(false));
    expect(off.kept.accountable).toBe(5);
    expect(off.kept.level).toBe(3);
    expect(progressOf(index, catalog, draft(true)).kept.level).toBe(5);
  });
});
