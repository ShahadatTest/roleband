import { describe, expect, it } from "vitest";
import { levelGuideFixture } from "../../test/fixtures";
import {
  closestLevel,
  defaultTrack,
  engineeringOnly,
  hiddenSpelling,
  levelHits,
  parseFrom,
  spellingKey,
} from "./levelsModel";
import { resolveCell } from "../../patterns/levels/levelGuide";

const companies = levelGuideFixture.companies;
const company = (slug: string) => companies.find((c) => c.slug === slug)!;
const hitsFor = (query: string, track = "technical") =>
  levelHits(companies, track, query).map((hit) => `${hit.slug}:${hit.level}`);

describe("level search", () => {
  it("matches whole spellings, so a short code never finds a longer one", () => {
    // A substring match on labels would find "L1" in "L8–L10" and "L10".
    expect(hitsFor("L1")).toEqual([]);
    expect(hitsFor("L10")).toEqual(["amazon:director_plus", "google:director_plus"]);
  });

  it("never invents a rung inside a range", () => {
    // Amazon's "L8–L10" spans L8 and L10; Amazon has no L9.
    expect(hitsFor("L9")).toEqual(["google:director_plus"]);
  });

  it("finds a rung its label hides, and an alias", () => {
    expect(hitsFor("Distinguished Engineer")).toEqual([
      "amazon:director_plus", "apple:director_plus", "nvidia:director_plus",
    ]);
    expect(hitsFor("66")).toEqual(["microsoft:principal"]);
    expect(hitsFor("sde ii")).toEqual(["amazon:mid"]);
  });

  it("reads a typed hyphen as the range's dash", () => {
    expect(spellingKey("63-64")).toBe(spellingKey("63–64"));
    expect(hitsFor("63-64")).toEqual(["microsoft:senior"]);
  });

  it("lists every company a shared code names, each at its own level", () => {
    expect(hitsFor("L5")).toEqual(["amazon:mid", "google:senior", "netflix:senior", "openai:staff"]);
  });

  it("reads a split level by the career track", () => {
    // Google's L8 is Principal for engineers and Director+ for managers.
    expect(hitsFor("L8")).toEqual(["amazon:director_plus", "google:principal"]);
    expect(hitsFor("L8", "management")).toEqual(["amazon:director_plus", "google:director_plus"]);
  });
});

describe("cells under a career track", () => {
  it("shows an engineering-only company's names under another track, marked", () => {
    expect(resolveCell(company("apple").levels.senior, "management")).toEqual({
      entry: { label: "ICT4", spellings: ["ICT4"] }, engineering: true,
    });
    expect(engineeringOnly(company("apple"), "management")).toBe(true);
    expect(engineeringOnly(company("google"), "management")).toBe(false);
    expect(engineeringOnly(company("apple"), "technical")).toBe(false);
  });

  it("names the level a skipped one reads as, nearest below first", () => {
    expect(closestLevel(company("amazon"), "staff", "technical")).toBe("L6");
    expect(closestLevel(company("netflix"), "director_plus", "technical")).toBe("L7");
    // Nothing below Apple's entry rung: intern reads the nearest above.
    expect(closestLevel(company("apple"), "intern", "technical")).toBe("ICT2");
  });

  it("shows a matched spelling only when the label does not already", () => {
    expect(hiddenSpelling("IC7+", "Distinguished Engineer")).toBe("Distinguished Engineer");
    expect(hiddenSpelling("IC7+", "IC7")).toBeNull();
    expect(hiddenSpelling("L7–L8", "L8")).toBeNull();
    expect(hiddenSpelling("65–67", "66")).toBe("66");
  });
});

describe("where a translation starts", () => {
  it("accepts only a level the company names", () => {
    expect(parseFrom("apple:senior", companies)).toEqual({ slug: "apple", level: "senior" });
    expect(parseFrom("amazon:staff", companies)).toBeNull();
    expect(parseFrom("nobody:senior", companies)).toBeNull();
    expect(parseFrom("apple:ceo", companies)).toBeNull();
  });

  it("opens on hands-on unless the person's tracks leave it out", () => {
    const order = ["technical", "management", "product_program", "business_customer"];
    // A fresh install has all four tracks.
    expect(defaultTrack(order, order)).toBe("technical");
    expect(defaultTrack([], order)).toBe("technical");
    expect(defaultTrack(["business_customer", "management"], order)).toBe("management");
  });
});
