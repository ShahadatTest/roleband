import { describe, expect, it } from "vitest";
import { roundCount } from "./counts";

describe("a large count as a round number", () => {
  it("rounds down, so one count reads as one number on every screen", () => {
    expect(roundCount(12_500)).toBe(12_000);
    expect(roundCount(12_999)).toBe(12_000);
    expect(roundCount(9_960)).toBe(9_900);
    expect(roundCount(2_920)).toBe(2_900);
    expect(roundCount(10_000)).toBe(10_000);
    expect(roundCount(999)).toBe(999);
    expect(roundCount(35)).toBe(35);
  });
});
