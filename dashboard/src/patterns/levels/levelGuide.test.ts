import { describe, expect, it } from "vitest";
import { levelGuideFixture } from "../../test/fixtures";
import { ladderOf, levelCode, rungWords } from "./levelGuide";

const ladder = (slug: string) => ladderOf(levelGuideFixture, slug);

describe("a company's code for a level", () => {
  it("reads a cell split by track with the role's track", () => {
    // Google's L8 is Principal on the engineering ladder and Director+ for everyone else.
    expect(levelCode(ladder("google"), "principal", "technical")).toBe("L7–L8");
    expect(levelCode(ladder("google"), "director_plus", "technical")).toBe("L9–L10");
    expect(levelCode(ladder("google"), "principal", "management")).toBe("L7");
    expect(levelCode(ladder("google"), "director_plus", "management")).toBe("L8–L10");
    // A company-wide cell is the same on every track.
    expect(levelCode(ladder("google"), "senior", "management")).toBe("L5");
  });

  it("shows none on a flat ladder, even at a rung its guide names", () => {
    expect(ladder("meta")?.levels.entry).toBeDefined();
    expect(levelCode(ladder("meta"), "entry", "technical")).toBeNull();
    expect(levelCode(ladder("meta"), "senior", "technical")).toBeNull();
  });

  it("shows none for a level the ladder skips, never a neighbour's", () => {
    // Amazon goes L6 (Senior) to L7 (Principal): no Staff rung.
    expect(levelCode(ladder("amazon"), "staff", "technical")).toBeNull();
    expect(levelCode(ladder("amazon"), "senior", "technical")).toBe("L6");
    expect(levelCode(ladder("amazon"), "principal", "technical")).toBe("L7");
  });

  it("never lends an engineering code to another track", () => {
    expect(levelCode(ladder("apple"), "senior", "technical")).toBe("ICT4");
    expect(levelCode(ladder("apple"), "senior", "management")).toBeNull();
  });

  it("finds a ladder a company shares, and none for a company without one", () => {
    expect(ladderOf(levelGuideFixture, "google-deepmind")?.slug).toBe("google");
    expect(ladderOf(levelGuideFixture, "stripe")).toBeUndefined();
    expect(ladderOf(null, "google")).toBeUndefined();
    expect(levelCode(undefined, "senior", "technical")).toBeNull();
  });
});

describe("a row of codes read as rung words", () => {
  it("cuts the role every code repeats", () => {
    expect(rungWords(["Software Engineer", "Senior Software Engineer", "Staff Software Engineer", "Senior Staff Software Engineer"]))
      .toEqual(["Software Engineer", "Senior", "Staff", "Senior Staff"]);
  });
  it("leaves codes that share no ending, or share only part of one", () => {
    expect(rungWords(["ICT4", "ICT5", "Distinguished Engineer"])).toEqual(["ICT4", "ICT5", "Distinguished Engineer"]);
    expect(rungWords(["Engineer II", "Senior Engineer"])).toEqual(["Engineer II", "Senior Engineer"]);
  });
  it("leaves a lone code whole", () => {
    expect(rungWords(["Staff Software Engineer"])).toEqual(["Staff Software Engineer"]);
  });
});
