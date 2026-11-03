import { describe, expect, it } from "vitest";
import type { DisclosedBand } from "../../../api";
import { bandEmployers, bandScale, bandsByLevel, exclusionNote, levelSummary } from "./compBands";

const band = (over: Partial<DisclosedBand> = {}): DisclosedBand => ({
  company: "google",
  level_band: "staff",
  low: 262_000,
  high: 365_000,
  reqs: 18,
  ...over,
});

describe("bandsByLevel", () => {
  it("makes one row per level with its median band, one vote per band, never per role", () => {
    const rows = bandsByLevel([
      band({ level_band: "senior", low: 200_000, high: 280_000, reqs: 50 }),
      band(),
      band({ company: "apple", low: 240_000, high: 340_000, reqs: 1 }),
      band({ company: "google-deepmind", low: 207_000, high: 301_000, reqs: 1 }),
    ]);

    expect(rows.map((r) => [r.level, r.bands.length, r.employers, r.reqs])).toEqual([
      ["senior", 1, 1, 50],
      ["staff", 3, 3, 20],
    ]);
    // Median of [207K, 240K, 262K] and [301K, 340K, 365K]: Google's 18 reqs weigh nothing extra.
    expect([rows[1].low, rows[1].high]).toEqual([240_000, 340_000]);
  });

  it("keeps the bands of roles whose level we cannot place on their own row, named as such", () => {
    const rows = bandsByLevel([
      band({ level_band: "principal", low: 210_000, high: 300_000 }),
      band({ level_band: "unstated", company: "apple", low: 250_000, high: 350_000 }),
    ]);
    expect(rows.map((r) => r.level)).toEqual(["principal", "unstated"]);
    const said = levelSummary(rows[1], [], null);
    expect(said).toMatch(/^Level not placed: 1 range from 1 employer/);
    expect(said).not.toMatch(/Mid-level/);
  });

  it("averages the middle two of an even count", () => {
    const [row] = bandsByLevel([band({ low: 200_000, high: 300_000 }), band({ company: "x", low: 300_000, high: 400_000 })]);
    expect([row.low, row.high]).toEqual([250_000, 350_000]);
  });
});

describe("bandScale", () => {
  it("rounds the ends to a step every band fits inside", () => {
    const { min, max, ticks } = bandScale([band({ low: 207_000, high: 365_000 }), band({ low: 140_000, high: 520_000 })]);
    expect(min).toBeLessThanOrEqual(140_000);
    expect(max).toBeGreaterThanOrEqual(520_000);
    expect(ticks[0]).toBe(min);
    expect(ticks[ticks.length - 1]).toBe(max);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    expect(ticks.length).toBeLessThanOrEqual(8);
  });

  it("has no ticks with no bands", () => {
    expect(bandScale([]).ticks).toEqual([]);
  });
});

describe("bandEmployers", () => {
  it("lists each employer once, most open roles on its bands first", () => {
    const options = bandEmployers([
      band({ company: "apple", reqs: 3 }),
      band({ company: "google", reqs: 4, level_band: "senior" }),
      band({ company: "google", reqs: 4 }),
    ]);
    expect(options).toEqual([
      { value: "google", label: "Google", count: 8 },
      { value: "apple", label: "Apple", count: 3 },
    ]);
  });
});

const none = { unclear: 0, total: 0, not_usd: 0, not_yearly: 0, implausible: 0 };

describe("exclusionNote", () => {
  it("says how many bands sit off the yearly dollar scale, currency and period together", () => {
    const text = exclusionNote({ ...none, not_usd: 3, not_yearly: 2 });
    expect(text).toBe(
      "5 more roles post their base salary in another currency or per hour or month, so they are not on this yearly dollar scale.",
    );
  });

  it("keeps the unclear note apart and singular when one role is left", () => {
    const text = exclusionNote({ ...none, unclear: 1, not_yearly: 1 });
    expect(text).toBe(
      "1 more role posts a range but never says whether it includes bonus or equity, so it is not shown. " +
        "1 more role posts its base salary in another currency or per hour or month, so it is not on this yearly dollar scale.",
    );
  });

  it("says nothing for total or implausible rows, which the page never promised", () => {
    expect(exclusionNote({ ...none, total: 4, implausible: 2 })).toBe("");
  });
});
