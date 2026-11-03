import { describe, expect, it } from "vitest";
import { currencyForPlaces, parseAmount } from "./PayFloorRow";

describe("a typed pay floor", () => {
  it("reads a yearly amount the ways people write one, in whole units", () => {
    for (const raw of ["250000", "250,000", "250 000", "250,000.00", "250k", "250K", " 250k "]) {
      expect(parseAmount(raw), raw).toBe(250_000);
    }
    expect(parseAmount("1.5m")).toBe(1_500_000);
    expect(parseAmount("187.5k")).toBe(187_500);
  });

  it("refuses what is not an amount, or not one we can read for sure", () => {
    // A European thousands separator, a sign, a negative, zero, words, two
    // units, and an amount over the API's bound.
    for (const raw of ["250.000", "$250,000", "-250000", "0", "0k", "abc", "250kk", "2.5.0", "", "100000001"]) {
      expect(parseAmount(raw), raw).toBeNull();
    }
  });
});

describe("the currency a new pay floor starts in", () => {
  const locations = [
    { slug: "europe", parent: null },
    { slug: "uk", parent: "europe" },
    { slug: "london", parent: "uk" },
    { slug: "germany", parent: "europe" },
    { slug: "berlin", parent: "germany" },
    { slug: "sweden", parent: "europe" },
    { slug: "united_states", parent: "north_america" },
    { slug: "silicon_valley", parent: "united_states" },
    { slug: "north_america", parent: null },
  ];

  it("is the first chosen place's country's, found from a metro or a city", () => {
    expect(currencyForPlaces(["london"], locations)).toBe("GBP");
    expect(currencyForPlaces(["berlin"], locations)).toBe("EUR");
    expect(currencyForPlaces(["silicon_valley", "london"], locations)).toBe("USD");
    expect(currencyForPlaces(["london", "silicon_valley"], locations)).toBe("GBP");
  });

  it("passes over a place the menu has no currency for, and falls back to USD", () => {
    // Sweden pays in kronor, which the menu does not offer; a region is no country.
    expect(currencyForPlaces(["sweden", "berlin"], locations)).toBe("EUR");
    expect(currencyForPlaces(["sweden"], locations)).toBe("USD");
    expect(currencyForPlaces(["europe"], locations)).toBe("USD");
    expect(currencyForPlaces([], locations)).toBe("USD");
    // A place the catalog does not know (a search result) reads as nothing.
    expect(currencyForPlaces(["city_2673730"], locations)).toBe("USD");
  });
});
