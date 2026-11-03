import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { SKILL_CATEGORY, skillCategory } from "./skills";

const CATALOG = resolve(__dirname, "../../../backend/tracker/skills/catalog.yaml");

describe("skill category names", () => {
  it("name every category the backend catalog uses, and nothing it does not", () => {
    const used = new Set([...readFileSync(CATALOG, "utf8").matchAll(/^\s*category:\s*([a-z_]+)\s*$/gm)].map((m) => m[1]));
    expect(used.size).toBeGreaterThan(5);
    expect([...used].filter((c) => !(c in SKILL_CATEGORY))).toEqual([]);
    expect(Object.keys(SKILL_CATEGORY).filter((c) => !used.has(c))).toEqual([]);
  });

  it("never prints a slug for a known category", () => {
    expect(skillCategory("ml_ai")).toBe("ML / AI");
    expect(skillCategory("process")).toBe("Process");
    expect(skillCategory(null)).toBeNull();
  });
});
