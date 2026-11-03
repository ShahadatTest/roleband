/* A count on a navigation item has one recipe (ui/CountBadge.css). The bell,
   rail and tab placements say where the badge sits, its colours and its
   size properties; none restates the face, weight, shape or numerals, or the
   three drift apart again. */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { rules } from "./cssRules";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");
const RECIPE = /\b(font-family|font-weight|border-radius|font-variant-numeric|display|place-items|line-height)\s*:/;

/** Every block whose selector list names `cls`, as `selector { body }`. */
function blocks(css: string, cls: string): string[] {
  return rules(css)
    .filter((rule) => rule.selectors.some((selector) => new RegExp(`\\.${cls}\\b`).test(selector)))
    .map((rule) => `${rule.selectors.join(", ")} { ${[...rule.decls].map(([key, value]) => `${key}: ${value};`).join(" ")} }`);
}

const fromFile = (file: string, cls: string) => blocks(readFileSync(join(SRC, file), "utf8"), cls);

describe("count badges share one recipe", () => {
  it.each([
    ["shell.css", "bell-badge"],
    ["shell.css", "rail-badge"],
    ["ui/TabBar.css", "ui-tabbar-badge"],
  ])("%s .%s sets placement only", (file, cls) => {
    const found = fromFile(file, cls);
    expect(found.length, `no rule for .${cls} in ${file}`).toBeGreaterThan(0);
    expect(found.filter((b) => RECIPE.test(b))).toEqual([]);
  });

  it("the recipe owns the face, weight and shape", () => {
    const [recipe] = fromFile("ui/CountBadge.css", "ui-count");
    for (const prop of ["font-family", "font-weight", "border-radius", "font-variant-numeric"]) {
      expect(recipe).toContain(`${prop}:`);
    }
  });

  it("the scan sees a restated recipe property (negative control)", () => {
    expect(blocks(".bell-badge { font-weight: 800; @media (hover: hover) { color: red; } }", "bell-badge")
      .filter((block) => RECIPE.test(block))).toHaveLength(1);
    expect(blocks(".rail { @media (hover: hover) { .rail-badge { border-radius: 2px; } } }", "rail-badge")
      .filter((block) => RECIPE.test(block))).toHaveLength(1);
    expect(blocks(".bell-badge { width: 12px; @media (hover: hover) { color: red; } }", "bell-badge")
      .filter((block) => RECIPE.test(block))).toEqual([]);
    expect(blocks(".unrelated { font-weight: 800; }", "bell-badge")).toEqual([]);
  });
});
