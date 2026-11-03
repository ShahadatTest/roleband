import { describe, expect, it } from "vitest";
import { placeGroups, placeGroupsBeyond } from "./placeGroups";


describe("placeGroups", () => {
  it("keeps a job's taxonomy places and drops the GeoNames city codes stored after them", () => {
    expect(placeGroups(["london", "uk", "europe", "city_2643743"])).toEqual(["london", "uk", "europe"]);
    expect(placeGroups(["city_2673730"])).toEqual([]);
  });
});

describe("placeGroupsBeyond", () => {
  it("keeps the metro area a city lies in and drops the country and region its text already states", () => {
    expect(placeGroupsBeyond(
      ["silicon_valley", "united_states", "north_america", "city_5400075"],
      ["Sunnyvale, CA, USA"],
    )).toEqual(["silicon_valley"]);
  });

  it("drops a metro area the place text names itself", () => {
    expect(placeGroupsBeyond(["london", "uk", "europe", "city_2643743"], ["London, UK"])).toEqual([]);
    expect(placeGroupsBeyond(["new_york", "united_states", "north_america"], ["new york, ny"])).toEqual([]);
  });

  it("keeps each metro of a posting listed in several", () => {
    expect(placeGroupsBeyond(
      ["silicon_valley", "pacific_northwest", "united_states", "north_america"],
      ["Mountain View, CA, USA", "Kirkland, WA, USA"],
    )).toEqual(["silicon_valley", "pacific_northwest"]);
  });

  it("shows nothing for a place outside every metro, or one the text names only as a region", () => {
    expect(placeGroupsBeyond(["germany", "europe", "city_2950159"], ["Berlin, Germany"])).toEqual([]);
    expect(placeGroupsBeyond(["europe", "middle_east", "africa"], ["EMEA"])).toEqual([]);
  });
});
