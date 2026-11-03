import { describe, expect, it } from "vitest";
import { narrowedBy, type NarrowingFilter } from "./emptyFilters";

/* The defect this function exists to make impossible: a message that names one
 * filter while several are narrowing, or that names a filter holding nothing
 * back. */
describe("narrowedBy", () => {
  const f = (
    key: string,
    active: boolean,
    released: number,
  ): NarrowingFilter<string> => ({ key, active, released });

  it("blames every active filter that is actually holding rows back", () => {
    // Search "stripe" with Tracked only on: both narrow, and naming only the
    // search would tell the user a catalog company does not exist.
    expect(
      narrowedBy([f("query", true, 2), f("tracked", true, 2), f("planned", false, 0)]).map(
        (r) => r.key,
      ),
    ).toEqual(["query", "tracked"]);
  });

  it("does not blame an active filter that releases nothing", () => {
    // `showPlanned` is off, but a search already forces planned rows visible,
    // so releasing it changes nothing and it is not the reason.
    expect(narrowedBy([f("query", true, 3), f("planned", true, 0)]).map((r) => r.key)).toEqual([
      "query",
    ]);
  });

  it("does not blame an inactive filter, however much it would release", () => {
    expect(narrowedBy([f("tracked", false, 135)])).toEqual([]);
  });

  it("blames nothing when the underlying set is itself empty", () => {
    // Distinct state, different recovery: widening a filter cannot help.
    expect(narrowedBy([f("query", true, 0), f("tracked", true, 0)])).toEqual([]);
  });

  it("keeps the caller's order, which is the order the copy reads in", () => {
    expect(narrowedBy([f("b", true, 1), f("a", true, 1)]).map((r) => r.key)).toEqual(["b", "a"]);
  });

  it("carries each blamed filter's release count, so the copy can state it", () => {
    expect(narrowedBy([f("tracked", true, 2)])[0].released).toBe(2);
  });
});
