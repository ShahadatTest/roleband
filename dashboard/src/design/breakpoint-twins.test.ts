/* A threshold decided in TS has a CSS twin that styles the same layout at the
   same width: `var()` cannot sit in a media feature, so the pair is two
   spellings of one number, and this holds them together. Each constant is
   matched against the arm of its stylesheet that styles what it decides. */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { SHEET_QUERY } from "../patterns/FilterSurface";
import { MARGIN_QUERY } from "../patterns/jobs/MarginBeacon";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

/** The body of every `@media <query> {` arm in a stylesheet, joined. */
function arms(file: string, query: string): string {
  const css = readFileSync(join(SRC, file), "utf8");
  const head = `@media ${query} {`;
  const out: string[] = [];
  for (let at = css.indexOf(head); at >= 0; at = css.indexOf(head, at + head.length)) {
    let depth = 0;
    let end = at + head.length - 1;
    for (; end < css.length; end++) {
      if (css[end] === "{") depth++;
      else if (css[end] === "}" && --depth === 0) break;
    }
    out.push(css.slice(at + head.length, end));
  }
  return out.join("\n");
}

describe("each JS threshold and its CSS twin name one width", () => {
  it.each([
    ["SHEET_QUERY", SHEET_QUERY, "ui/FilterRail.css", ".filter-pop"],
    ["MARGIN_QUERY", MARGIN_QUERY, "patterns/jobs/margin.css", "--job-margin"],
  ])("%s %s is the arm in %s that styles %s", (_name, query, file, styles) => {
    expect(arms(file, query), `${file} has no @media ${query} arm styling ${styles}`).toContain(styles);
  });

  it("the arm reader finds nothing for a width no stylesheet uses (negative control)", () => {
    expect(arms("ui/FilterRail.css", "(max-width: 861px)")).toBe("");
  });
});
