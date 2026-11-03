import { describe, expect, it } from "vitest";
import { DEFAULT_FILTERS, type Filters } from "../../api";
import {
  BOARD_MEMORY_SHAPE, BOARD_MODES, FILTER_FIELDS, MODE_FILTERS, MODE_PARAM, RESET_FILTERS,
  baselineFilters, baselineKey, boardMode, boardRequestFilters, countActiveFilters,
  countNarrowingFilters, countSituationalFilters, modeFromParam,
} from "./filters";
import { decodeShape, encodeShape } from "../../hooks/filterMemory";

const noLenses = { newSignalsOnly: false, repostsOnly: false };

describe("Board filter ownership", () => {
  it("classifies every default and optional transport field, without duplicate ownership", () => {
    expect(Object.keys(FILTER_FIELDS).sort()).toEqual([...Object.keys(DEFAULT_FILTERS), "ids"].sort());
    // The mapped `satisfies` in filters.ts also rejects an unclassified optional
    // Filters key, which a runtime DEFAULT_FILTERS comparison cannot see.
    expect(FILTER_FIELDS.ids.kind).toBe("transport");
    expect(FILTER_FIELDS.favorites_only.kind).toBe("transport");
  });

  it.each([
    ["company", ["google", "amazon"], 2], ["level_band", ["staff"], 1],
    ["family", ["swe", "pm"], 2], ["track", ["technical"], 1],
    ["location_group", ["uk", "silicon_valley"], 2], ["domain", ["ai"], 1],
    ["workplace_type", ["remote"], 1], ["base_min", 0, 1], ["base_max", 0, 1],
    ["posted_within_days", 7, 1],
    ["discloses_pay", true, 1], ["viewed", "unread", 1],
    // The two MODE fields move together and count as ONE: they
    // live in `More filters`, so "Closed" must not read as two filters.
    ["dismissed_only", true, 1], ["status", "closed", 1],
    ["q", "staff", 0], ["sort", "company", 0],
    ["order", "asc", 0], ["offset", 40, 0], ["include_related", true, 0],
    ["limit", 100, 0], ["ids", [101, 202], 0], ["favorites_only", true, 0],
  ] as [keyof Filters, Filters[keyof Filters], number][])("counts %s by its ownership", (key, value, expected) => {
    expect(countActiveFilters({ ...DEFAULT_FILTERS, [key]: value }, noLenses)).toBe(expected);
  });

  /* What the board REMEMBERS between visits is a rule, not a curated list:
     exactly the keys that narrow the list from the register. Stated as a
     derivation so that adding a `railFilter` without a decoder fails here by
     name, rather than silently shipping a filter that forgets itself. */
  it("remembers exactly the railFilter keys — no more, and none missing", () => {
    const narrowing = Object.entries(FILTER_FIELDS)
      .filter(([, field]) => field.kind === "railFilter")
      .map(([key]) => key)
      .sort();
    expect(Object.keys(BOARD_MEMORY_SHAPE).sort()).toEqual(narrowing);
  });

  it("keeps the mode, the query, the sort and the page out of memory", () => {
    // Each for its own reason (filters.ts says which), and each is the kind of
    // key somebody would reasonably add to the shape one day.
    const live: Filters = {
      ...DEFAULT_FILTERS, status: "closed", dismissed_only: true, q: "staff",
      sort: "company", order: "asc", offset: 40, limit: 100, include_related: true,
      favorites_only: true, new_today_only: true, company: ["openai"],
    };
    expect(encodeShape(BOARD_MEMORY_SHAPE, live)).toEqual({
      company: ["openai"], level_band: [], family: [], track: [], location_group: [],
      domain: [], workplace_type: [], base_min: null, base_max: null,
      posted_within_days: null, discloses_pay: false, viewed: "",
    });
  });

  it("restores a Level filter saved on Junior as Entry / Junior, once", () => {
    const restored = decodeShape(BOARD_MEMORY_SHAPE, { level_band: ["junior", "entry", "staff"] });
    expect(restored.level_band).toEqual(["entry", "staff"]);
    // Any other slug passes through untouched: the decoder folds one band only.
    expect(decodeShape(BOARD_MEMORY_SHAPE, { level_band: ["intern", "mid"] }).level_band).toEqual(["intern", "mid"]);
  });

  it("restores a stored blob into a board query, and refuses what it cannot vouch for", () => {
    const stored = {
      company: ["openai", 7], level_band: ["staff"], base_min: 200000,
      viewed: "unread", discloses_pay: "yes", status: "closed", q: "staff",
    };
    const restored = decodeShape(BOARD_MEMORY_SHAPE, stored);
    const filters: Filters = { ...DEFAULT_FILTERS, ...restored };
    // The good half of a mixed list survives; the bad values fall back.
    expect(filters.company).toEqual(["openai"]);
    expect(filters.level_band).toEqual(["staff"]);
    expect(filters.base_min).toBe(200000);
    expect(filters.viewed).toBe("unread");
    expect(filters.discloses_pay).toBe(false);
    // A key outside the shape cannot enter the query through memory at all —
    // a stored `status` must never decide which population the board shows.
    expect(filters.status).toBe(DEFAULT_FILTERS.status);
    expect(filters.q).toBe("");
    // ...and what came back is countable as ordinary filter state.
    expect(countActiveFilters(filters, noLenses)).toBe(4);
  });

  it("counts a comp pair once and takes external lenses from AppState, not stale projections", () => {
    const filters = { ...DEFAULT_FILTERS, base_min: 200000, base_max: 900000, new_today_only: true };
    expect(countActiveFilters(filters, noLenses)).toBe(1);
    const lenses = { newSignalsOnly: true, repostsOnly: true };
    expect(countActiveFilters(filters, lenses)).toBe(3);
    expect(boardRequestFilters(filters, noLenses).new_today_only).toBe(false);
    expect(boardRequestFilters(filters, lenses)).toMatchObject({ new_today_only: true, repost_today_only: true });
  });

  it("reset removes every narrowing field, preserving search/status/order, page size and transport", () => {
    const filters: Filters = {
      ...DEFAULT_FILTERS, company: ["google"], location_group: ["uk"], domain: ["ai"],
      level_band: ["staff"], family: ["swe"], track: ["technical"], workplace_type: ["remote"],
      base_min: 0, base_max: 900000, posted_within_days: 7, viewed: "read",
      dismissed_only: true, discloses_pay: true, new_today_only: true, repost_today_only: true,
      q: "platform", status: "closed", sort: "company", order: "asc", limit: 7,
      offset: 14, include_related: true, ids: [101], favorites_only: true,
    };
    // ...plus the mode, which only the route writes: one writer, so one place
    // it is written. MODE_FILTERS.open stands in for that write here.
    const reset = { ...filters, ...RESET_FILTERS, ...MODE_FILTERS.open };
    expect(countActiveFilters(reset, noLenses)).toBe(0);
    // The patch ALONE leaves the mode standing, which is the point.
    expect(countActiveFilters({ ...filters, ...RESET_FILTERS }, noLenses)).toBe(1);
    // Back on the open board as well, the QUERY still survives.
    expect(reset).toMatchObject({ q: "platform", status: "open", dismissed_only: false,
      sort: "company", order: "asc",
      limit: 7, offset: 0, include_related: false, ids: [101], favorites_only: true,
      new_today_only: false, repost_today_only: false });
    expect(filters.company).toEqual(["google"]);
  });

  it("baseline requests strip all constraints except query context", () => {
    const query: Filters = { ...DEFAULT_FILTERS, q: "platform", status: "closed", sort: "company", order: "asc" };
    const narrowed = { ...query, company: ["google"], base_min: 500000, viewed: "read" as const,
      new_today_only: true, ids: [101], favorites_only: true, include_related: true, offset: 60, limit: 20 };
    expect(baselineFilters(narrowed)).toEqual({ ...query, limit: 1 });
    expect(baselineKey(narrowed)).toBe(baselineKey(query));
    for (const patch of [{ q: "other" }, { status: "open" }, { sort: "first_seen" }, { order: "desc" }] satisfies Partial<Filters>[]) {
      expect(baselineKey({ ...query, ...patch })).not.toBe(baselineKey(query));
    }
    // User text containing NUL must not make two different queries collide.
    expect(baselineKey({ ...query, q: "a\u0000b", status: "c" }))
      .not.toBe(baselineKey({ ...query, q: "a", status: "b\u0000c" }));
  });

  it("the baseline belongs to ONE mode, so the fraction never counts the other piles", () => {
    const open = { ...DEFAULT_FILTERS, q: "platform" };
    const bin = { ...open, ...MODE_FILTERS.dismissed };
    expect(baselineFilters(bin)).toMatchObject(MODE_FILTERS.dismissed);
    expect(baselineKey(bin)).not.toBe(baselineKey(open));
  });
});

/* The mode: which population, not how it is narrowed. */
describe("Board modes", () => {
  it("round-trips every mode through the filters it sets", () => {
    for (const mode of BOARD_MODES) {
      expect(boardMode({ ...DEFAULT_FILTERS, ...MODE_FILTERS[mode] })).toBe(mode);
    }
  });

  it("the bin outranks the market: a role you marked stays in Not for me after it closes", () => {
    // MODE_FILTERS.dismissed deliberately clears `status` rather than pinning
    // it to open — a role dismissed in June must not vanish from the bin the
    // night its posting closes, which is the one place it has to stay.
    expect(MODE_FILTERS.dismissed.status).toBe("");
    expect(boardMode({ status: "closed", dismissed_only: true })).toBe("dismissed");
    expect(boardMode({ status: "open", dismissed_only: true })).toBe("dismissed");
  });

  it("round-trips through the query string, and an unknown value is the open board", () => {
    for (const mode of BOARD_MODES) {
      expect(modeFromParam(MODE_PARAM[mode])).toBe(mode);
    }
    // `useSearchParam` already whitelists, but the board must not depend on
    // that to stay on its feet: a hand-typed `?show=banana` is the open board.
    expect(modeFromParam("banana")).toBe("open");
    expect(modeFromParam("")).toBe("open");
    // Open is the FALLBACK, so the default board keeps a clean address — the
    // whole reason the top bar's plain `/` link can reach it.
    expect(MODE_PARAM.open).toBe("open");
  });

  it("is one of the situational filters the drawer counts, so no state hides behind a closed door", () => {
    expect(countSituationalFilters({ ...DEFAULT_FILTERS })).toBe(0);
    expect(countSituationalFilters({ ...DEFAULT_FILTERS, ...MODE_FILTERS.closed })).toBe(1);
    expect(countSituationalFilters({ ...DEFAULT_FILTERS, ...MODE_FILTERS.dismissed })).toBe(1);
    // ...and it adds to what is already in there rather than replacing it.
    expect(countSituationalFilters({ ...DEFAULT_FILTERS, ...MODE_FILTERS.closed, discloses_pay: true })).toBe(2);
  });

  it("counts the comp pair once behind the door, the way the summary counts it", () => {
    /* The floor and the ceiling are both in the drawer, so the drawer's own
       count has to group the pair the way `countNarrowingFilters` does.
       Counted per KEY, a range would put "More filters · 2" under
       "Filters · 1". */
    const floor = { ...DEFAULT_FILTERS, base_min: 500000 };
    const ceiling = { ...DEFAULT_FILTERS, base_max: 900000 };
    const range = { ...DEFAULT_FILTERS, base_min: 500000, base_max: 900000 };
    expect(countSituationalFilters(floor)).toBe(1);
    expect(countSituationalFilters(ceiling)).toBe(1);
    expect(countSituationalFilters(range)).toBe(1);
    // And the two numbers agree, which is the reason to group at all.
    const lenses = { newSignalsOnly: false, repostsOnly: false };
    expect(countNarrowingFilters(range, lenses)).toBe(1);
    // Grouping must not swallow unrelated filters standing beside it.
    expect(countSituationalFilters({ ...range, discloses_pay: true })).toBe(2);
  });

  it("is clearable but does not narrow: the fraction counts one and the undo the other", () => {
    // "34 of 34 closed roles" is a count wearing a fraction — the mode PICKED
    // the 34 rather than filtering them down — but Reset all must still offer
    // to take the reader back, so the two questions get two numbers.
    const lenses = { newSignalsOnly: false, repostsOnly: false };
    const closed = { ...DEFAULT_FILTERS, ...MODE_FILTERS.closed };
    expect(countNarrowingFilters(closed, lenses)).toBe(0);
    expect(countActiveFilters(closed, lenses)).toBe(1);
    // A real filter on top counts in both.
    const narrowed = { ...closed, company: ["amazon"] };
    expect(countNarrowingFilters(narrowed, lenses)).toBe(1);
    expect(countActiveFilters(narrowed, lenses)).toBe(2);
  });

  it("leaves the mode to its one writer: the reset patch does not carry it", () => {
    // The mode has one writer, the route. A second writer in this patch would
    // race it: the filters go open while `?show=closed` stays in the address bar.
    expect(RESET_FILTERS).not.toHaveProperty("status");
    expect(RESET_FILTERS).not.toHaveProperty("dismissed_only");
  });

});
