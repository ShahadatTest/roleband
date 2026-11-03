import { describe, expect, it } from "vitest";
import { ageAggregateNote, employerDated, listedFor } from "./ageCopy";

describe("age captions", () => {
  it("captions one posting's listed age, and never as days open", () => {
    expect(listedFor(null)).toBeNull();
    expect(listedFor(0)).toBe("Listed today");
    expect(listedFor(1)).toBe("Listed for 1 day");
    expect(listedFor(170)).toBe("Listed for 170 days");
  });

  it("states an age aggregate's employer-dated share as a whole percent", () => {
    expect(employerDated(null)).toBeNull();
    expect(employerDated(0)).toBe("0% dated by the employer");
    expect(employerDated(466 / 640)).toBe("73% dated by the employer");
    expect(employerDated(1)).toBe("100% dated by the employer");
    expect(ageAggregateNote(null)).toBeNull();
    expect(ageAggregateNote(0.5)).toBe("Counted from when each role was first listed · 50% dated by the employer");
  });
});
