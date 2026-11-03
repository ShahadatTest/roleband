import { describe, expect, it } from "vitest";
import {
  EMPTY_SCOPE_INDEX,
  buildScopeIndex,
  cellPasses,
  countByOption,
  countByRole,
  countUnderScope,
  INCLUDE_UNSTATED_LEVEL_DEFAULT,
  placeAdmits,
  UNSTATED_LEVEL,
} from "./scopeCells";
import type { ScopeAxesSelection, ScopeCellsPayload } from "./scopeCells";
import levelBasisGate from "../../../../backend/tests/fixtures/level_basis_gate.json";

/* The client half of the gate. Its backend twin is
   `backend/tests/test_scope_cells.py`, and the cases below are deliberately the
   same shapes: a posting in two places, a multi-label posting, and an
   unclassified posting, which is the one that passes a narrowed domain axis. */

const PAYLOAD: ScopeCellsPayload = {
  ready: true,
  companies: ["acme", "globex"],
  missing_companies: ["initech"],
  stale_companies: [], partial_companies: [],
  scanned_places: {},
  unplaced: 0,
  roles: ["product_management", "ml_ai_research"],
  bands: ["senior", "staff"],
  tracks: ["product_program", "technical"],
  cities: [],
  location_sets: [
    ["silicon_valley", "united_states"],
    ["uk"],
    ["singapore"],
  ],
  domain_sets: [[], ["ai_ml"], ["ai_ml", "cloud_infra"]],
  cells: [
    // product_management / staff / product_program, Bay Area, unclassified
    [0, 1, 0, 0, 0, 5],
    // product_management / senior / product_program, UK, ai_ml
    [0, 0, 0, 1, 1, 3],
    // ml_ai_research / staff / technical, Bay Area, ai_ml + cloud_infra
    [1, 1, 1, 0, 2, 7],
    // ml_ai_research / staff / technical, Singapore, ai_ml
    [1, 1, 1, 2, 1, 2],
  ],
};

function selection(overrides: Partial<ScopeAxesSelection> = {}): ScopeAxesSelection {
  return {
    roles: new Set(["product_management", "ml_ai_research"]),
    bands: new Set(["senior", "staff"]),
    tracks: new Set(["product_program", "technical"]),
    locations: new Set(["silicon_valley", "uk", "singapore"]),
    domains: new Set<string>(),
    ...overrides,
  };
}

describe("the \"not interested in\" veto", () => {
  const index = buildScopeIndex(PAYLOAD);
  it("drops a cell tagged with an excluded subject whatever else it is about, and keeps untagged cells", () => {
    // All worlds on: without the veto every cell passes.
    expect(countUnderScope(index, selection())).toBe(17);
    // cloud_infra sits on one cell, next to ai_ml: the veto still drops it.
    expect(countUnderScope(index, selection({ excluded: new Set(["cloud_infra"]) }))).toBe(10);
    // ai_ml is on three cells; the untagged one survives.
    expect(countUnderScope(index, selection({ excluded: new Set(["ai_ml"]) }))).toBe(5);
    // The veto wins over an interest in the cell's other subject.
    expect(countUnderScope(index, selection({ domains: new Set(["ai_ml"]), excluded: new Set(["cloud_infra"]) }))).toBe(10);
  });

  it("stays out of the per-subject counts, which ask what a subject would bring", () => {
    const perSubject = countByOption(index, selection({ excluded: new Set(["cloud_infra"]) }), "domains");
    expect(perSubject.get("cloud_infra")).toBe(7);
  });
});

describe("buildScopeIndex", () => {
  it("decodes the interning back to slugs", () => {
    const index = buildScopeIndex(PAYLOAD);
    expect(index.ready).toBe(true);
    expect(index.companies).toEqual(["acme", "globex"]);
    expect(index.missingCompanies).toEqual(["initech"]);
    expect(index.cells).toHaveLength(4);
    expect(index.cells[0]).toEqual({
      role: "product_management",
      band: "staff",
      track: "product_program",
      locations: ["silicon_valley", "united_states"],
      domains: [],
      count: 5,
    });
  });

  it("is empty rather than throwing when the payload is absent", () => {
    expect(buildScopeIndex(undefined)).toBe(EMPTY_SCOPE_INDEX);
    expect(buildScopeIndex(null)).toBe(EMPTY_SCOPE_INDEX);
  });

  it("drops a row pointing outside its dictionaries instead of blanking the screen", () => {
    const index = buildScopeIndex({
      ...PAYLOAD,
      cells: [...PAYLOAD.cells, [9, 0, 0, 0, 0, 4], [0, 0, 0, 0, 0, 0]],
    });
    expect(index.cells).toHaveLength(4);
    expect(countUnderScope(index, selection())).toBe(17);
  });
});

describe("the gate", () => {
  const index = buildScopeIndex(PAYLOAD);

  it("counts every posting when nothing narrows", () => {
    expect(countUnderScope(index, selection())).toBe(5 + 3 + 7 + 2);
  });

  it("drops a role that is not selected", () => {
    expect(countUnderScope(index, selection({ roles: new Set(["product_management"]) })))
      .toBe(8);
  });

  it("matches a location set by OVERLAP, not containment", () => {
    // The Bay Area cells are stored as [silicon_valley, united_states];
    // selecting either must find them.
    expect(countUnderScope(index, selection({ locations: new Set(["united_states"]) })))
      .toBe(5 + 7);
    expect(countUnderScope(index, selection({ locations: new Set(["silicon_valley"]) })))
      .toBe(5 + 7);
    expect(countUnderScope(index, selection({ locations: new Set(["uk"]) }))).toBe(3);
  });

  it("lets an unclassified posting through a narrowed domain axis", () => {
    // The 5 unclassified ones pass whatever is selected; only the ai_ml cells
    // join them.
    expect(countUnderScope(index, selection({ domains: new Set(["ai_ml"]) })))
      .toBe(5 + 3 + 7 + 2);
    expect(countUnderScope(index, selection({ domains: new Set(["cloud_infra"]) })))
      .toBe(5 + 7);
    expect(countUnderScope(index, selection({ domains: new Set(["payments_fintech"]) })))
      .toBe(5);
  });

  it("admits nothing when a non-domain axis is emptied", () => {
    for (const axis of ["roles", "bands", "tracks", "locations"] as const) {
      expect(countUnderScope(index, selection({ [axis]: new Set<string>() }))).toBe(0);
    }
  });

  it("admits everything when the DOMAIN axis is emptied", () => {
    expect(countUnderScope(index, selection({ domains: new Set<string>() }))).toBe(17);
  });

  it("asks per-role without requiring the role to be selected", () => {
    const byRole = countByRole(index, selection({ roles: new Set<string>() }));
    expect(byRole.get("product_management")).toBe(8);
    expect(byRole.get("ml_ai_research")).toBe(9);
    // ...while the whole-gate count still honours the empty axis.
    expect(countUnderScope(index, selection({ roles: new Set<string>() }))).toBe(0);
  });
});

describe("what one option contributes", () => {
  const index = buildScopeIndex(PAYLOAD);

  it("counts postings carrying the option that clear the OTHER four axes", () => {
    // Narrow to the UK and product_program; only the 3 UK product_management
    // postings survive, and they are ai_ml.
    const narrow = selection({
      locations: new Set(["uk"]),
      tracks: new Set(["product_program"]),
    });
    const perLocation = countByOption(index, narrow, "locations");
    // Silicon Valley still has the 5 product_program postings behind it,
    // because the location axis is the one being asked about.
    expect(perLocation.get("silicon_valley")).toBe(5);
    expect(perLocation.get("united_states")).toBe(5);
    expect(perLocation.get("uk")).toBe(3);
    // Singapore holds only technical postings, which the track axis still cuts.
    expect(perLocation.has("singapore")).toBe(false);
  });

  it("does not count an already-selected option as the whole radar", () => {
    // The trap: asking "what would the total become" makes every ticked card
    // read the full total.
    const perTrack = countByOption(index, selection(), "tracks");
    expect(perTrack.get("product_program")).toBe(8);
    expect(perTrack.get("technical")).toBe(9);
    expect(countUnderScope(index, selection())).toBe(17);
  });

  it("attributes a multi-label posting to each of its worlds", () => {
    const perDomain = countByOption(index, selection(), "domains");
    // The 7 Bay Area research postings carry both worlds.
    expect(perDomain.get("ai_ml")).toBe(7 + 3 + 2);
    expect(perDomain.get("cloud_infra")).toBe(7);
    // ...which is exactly why these do not sum to the 17 on the radar: the 5
    // unclassified postings belong to no world, and 7 are counted twice.
    expect([...perDomain.values()].reduce((a, b) => a + b, 0)).not.toBe(17);
  });

  it("omits an option the cells never mention rather than calling it zero", () => {
    expect(countByOption(index, selection(), "domains").has("payments_fintech"))
      .toBe(false);
  });
});

describe("cellPasses", () => {
  it("is the single place the axes are ANDed", () => {
    const [cell] = buildScopeIndex(PAYLOAD).cells;
    expect(cellPasses(cell, selection())).toBe(true);
    expect(cellPasses(cell, selection({ bands: new Set(["senior"]) }))).toBe(false);
    expect(cellPasses(cell, selection({ tracks: new Set(["technical"]) }))).toBe(false);
    expect(cellPasses(cell, selection({ locations: new Set(["uk"]) }))).toBe(false);
    expect(cellPasses(cell, selection({ roles: new Set(["ml_ai_research"]) }))).toBe(false);
    expect(
      cellPasses(cell, selection({ roles: new Set(["ml_ai_research"]) }), "roles"),
    ).toBe(true);
  });
});


describe("places excepted inside the included ones", () => {
  // The same places the backend test resolves (`test_place_exceptions.py`),
  // as the cells carry them: every place with its parents.
  const parents = new Map([
    ["new_york", "united_states"], ["austin", "united_states"], ["united_states", "north_america"],
    ["london", "uk"], ["uk", "europe"], ["germany", "europe"],
  ]);
  const postings: Record<string, string[]> = {
    nyc: ["new_york", "united_states", "north_america"],
    remote_us: ["united_states", "north_america"],
    nyc_or_austin: ["new_york", "austin", "united_states", "north_america"],
    nyc_or_london: ["new_york", "united_states", "north_america", "london", "uk", "europe"],
    london: ["london", "uk", "europe"],
    berlin: ["germany", "europe"],
  };
  const kept = (included: string[], excepted: string[]) => Object.keys(postings)
    .filter((key) => placeAdmits(postings[key], new Set(included), new Set(excepted), parents));

  it("drops a role only when every place it names is excepted", () => {
    expect(kept(["united_states"], ["new_york"])).toEqual(["remote_us", "nyc_or_austin"]);
  });

  it("never admits a place outside the included ones", () => {
    expect(kept(["united_states"], ["new_york"])).not.toContain("nyc_or_london");
    expect(kept(["united_states", "uk"], ["new_york"])).toContain("nyc_or_london");
  });

  it("lets the more specific answer win", () => {
    expect(kept(["europe", "london"], ["uk"])).toEqual(["nyc_or_london", "london", "berlin"]);
  });

  it("is the plain overlap with no exceptions", () => {
    expect(kept(["united_states"], [])).toEqual(["nyc", "remote_us", "nyc_or_austin", "nyc_or_london"]);
  });

  it("counts through the gate", () => {
    const index = buildScopeIndex({
      ready: true, companies: ["acme"], missing_companies: [], stale_companies: [], partial_companies: [], scanned_places: {}, unplaced: 0,
      roles: ["software_engineering"], bands: ["staff"], tracks: ["technical"],
      location_sets: [postings.nyc, postings.remote_us, postings.nyc_or_austin],
      cities: [], domain_sets: [[]],
      cells: [[0, 0, 0, 0, 0, 5], [0, 0, 0, 1, 0, 3], [0, 0, 0, 2, 0, 2]],
    });
    const selection = {
      roles: new Set(["software_engineering"]), bands: new Set(["staff"]), tracks: new Set(["technical"]),
      locations: new Set(["united_states"]), domains: new Set<string>(), placeParents: parents,
    };
    expect(countUnderScope(index, selection)).toBe(10);
    expect(countUnderScope(index, { ...selection, excepted: new Set(["new_york"]) })).toBe(5);
  });
});

/* A posting that states no level. The cases are the backend's own:
   `backend/tests/fixtures/level_basis_gate.json` is read by
   `test_level_basis.py` against the Python gate and the SQL gate over both
   tables, and here against the cell gate, so the three cannot drift apart. */
describe("a posting that states no level", () => {
  const trackBands = new Map(
    Object.entries(levelBasisGate.track_bands).map(([track, bands]) => [track, new Set(bands)]),
  );
  const cells = levelBasisGate.postings.map((posting) => ({
    id: posting.id,
    cell: {
      role: posting.family, band: posting.cell_band, track: posting.track,
      locations: ["uk"], domains: [], count: 1,
    },
  }));
  const selectionFor = (scope: (typeof levelBasisGate.scopes)[number]): ScopeAxesSelection => ({
    roles: new Set(["software_engineering", "engineering_management"]),
    bands: new Set(scope.bands),
    tracks: new Set(["technical", "management"]),
    locations: new Set(["uk"]),
    domains: new Set(),
    includeUnstatedLevel: scope.include_unstated_level,
    ...(scope.answers
      ? {
        answers: new Map(scope.answers.map((answer) => [answer.track, "any" as const])),
        trackBands,
      }
      : {}),
  });

  it("starts where the server starts when nobody has said", () => {
    expect(INCLUDE_UNSTATED_LEVEL_DEFAULT).toBe(levelBasisGate.include_unstated_level_default);
  });

  it("is carried by the cells under its own key, never under Mid", () => {
    expect(UNSTATED_LEVEL).toBe("unstated");
    const unstated = levelBasisGate.postings.filter((posting) => posting.basis === "none");
    expect(unstated.length).toBeGreaterThan(0);
    for (const posting of unstated) expect(posting.cell_band).toBe(UNSTATED_LEVEL);
  });

  for (const scope of levelBasisGate.scopes) {
    it(`admits what the server admits: ${scope.name}`, () => {
      const admitted = cells.filter(({ cell }) => cellPasses(cell, selectionFor(scope))).map(({ id }) => id);
      expect(admitted.sort()).toEqual([...scope.passes].sort());
    });
  }

  it("is counted on its own beside the rungs, whatever the switch says", () => {
    const index = { ...EMPTY_SCOPE_INDEX, ready: true, cells: cells.map(({ cell }) => cell) };
    const scope = levelBasisGate.scopes[0];
    const byBand = countByOption(index, { ...selectionFor(scope), includeUnstatedLevel: false }, "bands");
    // Two that state no level and one whose level we cannot place.
    expect(byBand.get(UNSTATED_LEVEL)).toBe(3);
    expect(byBand.get("mid")).toBe(2);
  });
});
