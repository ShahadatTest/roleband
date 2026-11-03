import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* The filter grammar: every filter surface —
 * the Board's inline register, the FilterSelect popover, the Companies index
 * — is built from four text roles, and no two adjacent roles share a tier
 * AND every other channel. What this pins:
 *
 *  - a KICKER whispers and is muted (the register's ink);
 *  - a GROUP HEAD is a row you open: body, sentence case, muted, on the 32px
 *    row grid — never whisper (a disclosure with a count is control text);
 *  - a ROW is body / sentence, in the popover exactly as inline;
 *  - a FACT beside a row or head sits at the fact floor (meta), mono;
 *  - state is INK, never weight, on every one of them.
 */

const here = dirname(fileURLToPath(import.meta.url));
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "");
const board = strip(readFileSync(join(here, "..", "patterns", "jobs", "job-row.css"), "utf8"));
// The register anatomy is the shared ui/FilterRail sheet (Board + Notifications).
const rail = strip(readFileSync(join(here, "..", "ui", "FilterRail.css"), "utf8"));
const filterSelect = strip(readFileSync(join(here, "..", "ui", "FilterSelect.css"), "utf8"));
const offices = strip(readFileSync(join(here, "..", "features", "company-profiles", "CompanyOffices.css"), "utf8"));
const companies = strip(
  readFileSync(join(here, "..", "features", "companies", "CompaniesSection.css"), "utf8"),
);
const tabbar = strip(readFileSync(join(here, "..", "ui", "TabBar.css"), "utf8"));
const countBadge = strip(readFileSync(join(here, "..", "ui", "CountBadge.css"), "utf8"));

/** The first block whose selector line is exactly `selector`. */
function rule(source: string, selector: string): string {
  const at = source.indexOf(`${selector} {`);
  expect(at, `${selector} not found`).toBeGreaterThan(-1);
  const open = source.indexOf("{", at);
  return source.slice(open + 1, source.indexOf("}", open));
}

const WHISPER = /font-size:\s*var\(--app-type-whisper\)/;
const BODY = /font-size:\s*var\(--app-type-body\)/;
const META = /font-size:\s*var\(--app-type-meta\)/;
const UPPER = /text-transform:\s*uppercase/;
const MONO = /font-family:\s*var\(--app-font-mono\)/;

describe("filter grammar — the Board register", () => {
  it("a kicker whispers in the register's muted ink", () => {
    const kicker = rule(rail, ".filter-group h3");
    expect(kicker).toMatch(WHISPER);
    expect(kicker).toMatch(UPPER);
    expect(kicker).toMatch(/color:\s*var\(--app-text-muted\)/);
  });

  it("a group head is a row you open: body, sentence case, muted, 32px — never whisper", () => {
    const head = rule(rail, ".filter-group h3.filter-head");
    expect(head).toMatch(BODY);
    expect(head).toMatch(/text-transform:\s*none/);
    expect(head).toMatch(/font-family:\s*var\(--app-font-sans\)/);
    // `body` IS 400 — the group head is prose, which is the claim.
    expect(head).toMatch(/font-weight:\s*var\(--app-weight-body\)/);
    expect(head).toMatch(/min-height:\s*32px/);
    expect(head).toMatch(/color:\s*var\(--app-text-muted\)/);
    expect(head).not.toMatch(WHISPER);
  });

  it("the head's count is a fact: meta, mono, headline weight, action ink", () => {
    const count = rule(rail, ".filter-title-count");
    expect(count).toMatch(META);
    expect(count).toMatch(MONO);
    expect(count).toMatch(/font-weight:\s*600/);
    expect(count).toMatch(/color:\s*var\(--app-action-text\)/);
  });

  it("a value's count sits at the fact floor, not the chrome floor", () => {
    const count = rule(rail, ".check-row .cnt");
    expect(count).toMatch(META);
    expect(count).toMatch(MONO);
    expect(count).not.toMatch(/--app-type-label/);
  });

  it("the column heads share the register's ink with the kickers", () => {
    expect(rule(board, ".list-head")).toMatch(/color:\s*var\(--app-text-muted\)/);
  });

  it("open, hover and focus change the head's INK and never its weight", () => {
    const at = rail.indexOf('.filter-title[aria-expanded="true"]');
    expect(at).toBeGreaterThan(-1);
    const open = rail.indexOf("{", at);
    const state = rail.slice(open + 1, rail.indexOf("}", open));
    expect(state).toMatch(/color:\s*var\(--app-text\)/);
    expect(state).not.toMatch(/font-weight/);
    expect(state).not.toMatch(/font-size/);
  });
});

/* A count is a fact wherever it renders: the tab bar's pill reads at the
   same size as every other count beside a name. */
describe("filter grammar — a count is a fact wherever it is", () => {
  it("the tab bar's count sits at the fact floor, in the data voice", () => {
    // The placement picks the size; the count recipe (ui/CountBadge.css) is the voice.
    const badge = rule(tabbar, ".ui-tabbar-badge");
    expect(badge).toMatch(/--ui-count-type:\s*var\(--app-type-meta\)/);
    expect(badge).not.toMatch(/--app-type-label/);
    const recipe = rule(countBadge, ".ui-count");
    expect(recipe).toMatch(/font-size:\s*var\(--ui-count-type/);
    expect(recipe).toMatch(MONO);
    expect(recipe).toMatch(/font-variant-numeric:\s*tabular-nums/);
  });

});

describe("filter grammar — the popover is the inline group", () => {
  it("an option is the value row: body, muted, 32px; selection by ink", () => {
    const option = rule(filterSelect, ".ui-filterselect-option");
    expect(option).toMatch(BODY);
    expect(option).toMatch(/min-height:\s*32px/);
    expect(option).toMatch(/color:\s*var\(--app-text-muted\)/);
    expect(option).not.toMatch(/font-size:\s*12px/);
    const selected = rule(filterSelect, '.ui-filterselect-option[aria-selected="true"]');
    expect(selected).toMatch(/color:\s*var\(--app-chosen-text\)/);
    expect(selected).not.toMatch(/font-weight/);
  });

  it("an option's count is a fact: meta, mono", () => {
    const count = rule(filterSelect, ".ui-filterselect-count");
    expect(count).toMatch(META);
    expect(count).toMatch(MONO);
  });
});

describe("filter grammar — facts elsewhere", () => {
  it("the offices country count is a fact, not an uppercase label", () => {
    const meta = rule(offices, ".offices-country-meta");
    expect(meta).toMatch(META);
    expect(meta).toMatch(MONO);
    expect(meta).not.toMatch(UPPER);
  });

  it("the Companies index (the reference) keeps the head/fact pair the Board now shares", () => {
    expect(rule(companies, ".ledger-index-label")).toMatch(WHISPER);
    const count = rule(companies, ".ledger-index-row b");
    expect(count).toMatch(META);
    expect(count).toMatch(MONO);
    expect(count).toMatch(/font-weight:\s*600/);
  });
});
