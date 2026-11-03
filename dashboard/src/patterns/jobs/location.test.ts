import { describe, expect, it } from "vitest";
import { postingPlaces, primaryLocation } from "./location";

/* The row's city line. Sources publish a run of cities in one
   string and then the same cities again as entries; the row shows the first
   and counts the rest, once each. */
describe("primaryLocation", () => {
  it("takes the posting's first city and counts the distinct others", () => {
    expect(primaryLocation(["San Francisco, CA | New York City, NY", "New York City, NY", "San Francisco, CA"]))
      .toEqual({ city: "San Francisco, CA", others: ["New York City, NY"] });
    expect(primaryLocation(["Seattle, Washington, USA; Bellevue, Washington, USA"]))
      .toEqual({ city: "Seattle, Washington, USA", others: ["Bellevue, Washington, USA"] });
    expect(primaryLocation(["London, UK"])).toEqual({ city: "London, UK", others: [] });
  });

  it("has no city to show when the posting names none", () => {
    expect(primaryLocation([])).toEqual({ city: null, others: [] });
    expect(primaryLocation(["", " | "])).toEqual({ city: null, others: [] });
  });
});

/* Every surface that lists a posting's places reads this list. */
describe("postingPlaces", () => {
  it("splits the joined strings and keeps each place once, in the source's order", () => {
    expect(postingPlaces(["San Francisco, CA | New York City, NY", "New York City, NY"]))
      .toEqual(["San Francisco, CA", "New York City, NY"]);
    expect(postingPlaces(["Seattle, WA; Bellevue, WA", "London, UK"]))
      .toEqual(["Seattle, WA", "Bellevue, WA", "London, UK"]);
  });

  it("keeps a place the source names only once, and drops empty pieces", () => {
    expect(postingPlaces(["Remote (US)"])).toEqual(["Remote (US)"]);
    expect(postingPlaces(["", " | "])).toEqual([]);
  });
});
