import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* The Board row's grammar:
 * the position first, then ONE line of plain facts; colour for state only.
 * The sheet-level half of that contract — the DOM half lives in
 * JobCard.test.tsx.
 */

const here = dirname(fileURLToPath(import.meta.url));
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "");
const board = strip(readFileSync(join(here, "job-row.css"), "utf8"));
const surfaces = strip(readFileSync(join(here, "..", "..", "design", "surfaces.css"), "utf8"));

function rule(source: string, selector: string): string {
  const at = source.indexOf(`${selector} {`);
  expect(at, `${selector} not found`).toBeGreaterThan(-1);
  const open = source.indexOf("{", at);
  return source.slice(open + 1, source.indexOf("}", open));
}

const tokens = strip(readFileSync(join(here, "..", "..", "design", "tokens.css"), "utf8"));

/* A weight anchor, whether it is written as a literal or as a ramp role.
 * These comparisons are about RANK — is the read title lighter than the rest
 * title, is the numeral lighter than the title — so the role has to be priced
 * rather than pattern-matched. Reading the literal only would break the
 * contract the moment a value moved onto the role it belongs to, which is
 * backwards: adopting the ramp should not cost a screen its contract. */
function weight(block: string, property: string): number {
  const raw = block.match(new RegExp(`${property}:\\s*([^;]+)`))?.[1]?.trim();
  expect(raw, `${property} not set`).toBeTruthy();
  const literal = raw!.match(/^(\d+)$/);
  if (literal) return Number(literal[1]);
  const role = raw!.match(/var\((--app-weight-[\w-]+)\)/);
  expect(role, `${property} is neither a literal nor a ramp role: ${raw}`).toBeTruthy();
  const value = tokens.match(new RegExp(`${role![1]}\\s*:\\s*(\\d+)`));
  expect(value, `${role![1]} is not defined in tokens.css`).toBeTruthy();
  return Number(value![1]);
}

describe("row grammar", () => {
  /* The facts sit at the FACT FLOOR. The
     company, the level and the track describe the row's primary string, and
     the ramp's rule for that is `meta`; micro is for the asides beside them
     (the region, the age). One line, never two: a row that wraps its facts
     is taller than its neighbours, and a column of uneven rows cannot be
     scanned. */
  it("the meta line is one line at the fact floor, muted, and separates facts with a middot, not a box", () => {
    const meta = rule(board, ".job-meta");
    expect(meta).toMatch(/font-size:\s*var\(--app-type-meta\)/);
    expect(meta).toMatch(/color:\s*var\(--row-ink-2, var\(--app-text-muted\)\)/);
    expect(meta).toMatch(/flex-wrap:\s*nowrap/);
    expect(rule(board, ".job-fact + .job-fact::before")).toMatch(/content:\s*"·"/);
    expect(board).not.toMatch(/\.job-eyebrow\s*\{/);
    // A fact that does not fit truncates; the company and the level never do.
    expect(rule(board, ".job-fact")).toMatch(/text-overflow:\s*ellipsis/);
    expect(rule(board, ".job-band,\n.job-fact-company")).toMatch(/flex:\s*none/);
  });

  /* The row is a two-line grid: the position, the city and the
     numeral on line one; the facts, the region and the age on line two. The
     lines align across cells because every cell states them from the same
     two tokens, and the grid starts its cells at the top rather than
     centring them into the seam between the lines. The age has no column of
     its own — it is the numeral's second line — which leaves the city the
     width it needs. */
  it("every cell states its two lines from the row's line tokens, and the age lives under the numeral", () => {
    const list = rule(board, ".job-list");
    expect(list).toMatch(/--row-line-1:\s*calc\(var\(--app-type-name\) \* 1\.25\)/);
    expect(list).toMatch(/--row-line-2:\s*calc\(var\(--app-type-meta\) \* 1\.25\)/);
    // Four tracks: role | location | comp | actions.
    expect(list.match(/--row-cols:\s*([^;]+);/)![1].trim().split(/\s+/).filter((t) => t !== "minmax(0,")).toHaveLength(4);
    expect(rule(board, ".job-row")).toMatch(/align-items:\s*start/);
    for (const first of [".jr-loc .job-location", ".comp"]) {
      expect(rule(board, first), first).toMatch(/line-height:\s*var\(--row-line-1\)/);
    }
    for (const second of [".job-meta", ".jr-loc .job-loc-group", ".jr-age"]) {
      expect(rule(board, second), second).toMatch(/line-height:\s*var\(--row-line-2\)/);
    }
    expect(rule(board, ".jr-comp")).toMatch(/flex-direction:\s*column/);
    expect(board).not.toMatch(/\.col-age\b/);
    expect(board).not.toMatch(/\.jr-meta-row\b/);
  });

  /* Under a pointer the verbs rest invisible; state does not. A saved star
     is a fact about the row and stays lit through the pressed rank. */
  it("row actions rest invisible on a pointer device, except a pressed one", () => {
    const hover = board.slice(board.indexOf("@media (hover: hover)"));
    const arm = hover.slice(0, hover.indexOf("\n}\n"));
    expect(arm).toMatch(/\.job-row \.jr-actions \.ui-btn \{[^}]*opacity:\s*0;/);
    expect(arm).toMatch(/\.job-row \.jr-actions \.ui-btn\[aria-pressed="true"\],[\s\S]*opacity:\s*1;/);
    expect(arm).toMatch(/\.job-row:focus-within \.jr-actions \.ui-btn/);
  });

  it("the band's emphasis is weight, never hue", () => {
    const band = rule(board, ".job-band");
    // The role, not the number: `ui` IS 500, and the contract is
    // "the band is emphasised by weight", which the role states and a literal
    // only implied.
    expect(band).toMatch(/font-weight:\s*var\(--app-weight-ui\)/);
    expect(band).not.toMatch(/color:/);
    expect(band).not.toMatch(/background/);
  });

  it("the company chip is text with a mark: no plate, no border, no fill", () => {
    const chip = rule(surfaces, '[data-design-system="app"] .chip-co');
    expect(chip).toMatch(/background:\s*transparent/);
    expect(chip).toMatch(/border:\s*0/);
    expect(chip).toMatch(/padding:\s*0/);
    expect(chip).toMatch(/color:\s*inherit/);
  });

  it("the row lights the mark on hover and never at rest", () => {
    expect(rule(board, ".job-row:hover .ui-company-icon")).toMatch(/color:\s*var\(--brand-l\)/);
    expect(board).not.toMatch(/\.job-row \.ui-company-icon\s*\{/);
  });

  it("the comp numeral stands alone: the per-row sparkline is gone", () => {
    expect(board).not.toMatch(/\.comp-bar/);
  });

  /* The viewed state is one scale, shifted. Dimming the title alone inverts
     the row: the comp numeral becomes the loudest mark on a row the reader
     has already opened, and the title falls onto its own meta line's ink. A
     structural contract is the only form the inversion cannot come back in:
     no element can dim on its own, and none can stay lit on its own. */
  it("viewed shifts the row's scale; it does not patch one element", () => {
    const row = rule(board, ".job-row");
    expect(row).toMatch(/--row-ink:\s*var\(--app-text\)/);
    expect(row).toMatch(/--row-ink-2:\s*var\(--app-text-muted\)/);
    expect(row).toMatch(/--row-ink-3:\s*var\(--app-text-faint\)/);
    const restTitle = weight(row, "--row-title-weight");
    const restNumeral = weight(row, "--row-numeral-weight");

    const viewed = rule(board, ".job-row.is-viewed");
    expect(viewed).toMatch(/--row-ink:\s*var\(--app-text-muted\)/);
    expect(viewed).toMatch(/--row-ink-2:\s*var\(--app-text-faint\)/);
    // faint is the last step tokens.test.ts holds to AA: the scale stops there.
    expect(viewed).not.toMatch(/--row-ink-3:/);
    // Weight is the second retreat channel: a shape cue, so 1.4.1
    // holds without a ratio; both anchors must step DOWN, and together.
    const viewedTitle = weight(viewed, "--row-title-weight");
    const viewedNumeral = weight(viewed, "--row-numeral-weight");
    expect(viewedTitle).toBeLessThan(restTitle);
    expect(viewedNumeral).toBeLessThan(restNumeral);
    // Read is a retreat state; a ground fill is the ADVANCE channel (hover /
    // selected / focus), and the tint is invisible on the canvas anyway. No
    // viewed rule may fill.
    expect(viewed).not.toMatch(/background/);
    // Both anchors read their weight from the row's scale, so neither can be
    // patched alone. The fallbacks are asserted for what they RESOLVE to
    // rather than by text: a fallback is where an unchosen rank or an
    // unloaded mono face sits unnoticed.
    expect(rule(board, ".job-title")).toMatch(/font-weight:\s*var\(--row-title-weight, [^;]+\)/);
    expect(rule(board, ".comp")).toMatch(/font-weight:\s*var\(--row-numeral-weight, [^;]+\)/);

    // The position and the numeral share one step, so neither can outrank the
    // other in either state.
    expect(rule(board, ".job-title")).toMatch(/color:\s*var\(--row-ink, var\(--app-text\)\)/);
    expect(rule(board, ".comp")).toMatch(/color:\s*var\(--row-ink, var\(--app-text\)\)/);
    expect(rule(board, ".jr-loc")).toMatch(/color:\s*var\(--row-ink-2, /);
    expect(rule(board, ".jr-age")).toMatch(/color:\s*var\(--row-ink-3, /);

    // No element may opt out of the scale by naming a base ink for itself.
    expect(board).not.toMatch(/\.job-row\.is-viewed \.job-title/);
    expect(board).not.toMatch(/\.job-row\.is-viewed [^{]*\{[^}]*color:/);
    expect(board).not.toMatch(/\.job-row\.is-viewed[^{]*\{[^}]*background/);
  });

  it("location is the city over its region on the grid, no middot and no pin; the card joins them on one line", () => {
    expect(rule(board, ".jr-loc")).toMatch(/flex-direction:\s*column/);
    expect(board).not.toMatch(/\.jr-loc \.job-location svg/);
    // The middot exists only in the card arm, where the two share a line.
    const middot = board.indexOf(".jr-loc .job-loc-group::before {");
    expect(middot).toBeGreaterThan(board.indexOf("@media (max-width: 860px)"));
    // A posting's other cities are a count in the aside ink, never a second line.
    expect(rule(board, ".jr-loc .job-loc-more")).toMatch(/color:\s*var\(--row-ink-3, /);
  });

  /* The rank order INSIDE the row. The position is what the reader
     came for, so it wears the ramp's primary-row role — the same role the
     notification row's title wears, so a job headline is never set smaller
     than the notice that a scrape finished — and nothing beside it on the row
     may outweigh it, or the eye scans the salary column instead of the
     roles. */
  it("the position is the row's primary content, at the name role, in both lists", () => {
    expect(rule(board, ".job-title")).toMatch(/font-size:\s*var\(--app-type-name\)/);
    const notif = strip(
      readFileSync(join(here, "..", "..", "features", "notifications", "notification-row.css"), "utf8"),
    );
    expect(rule(notif, ".notif-copy strong")).toMatch(/font-size:\s*var\(--app-type-name\)/);
    // A heading is not prose: it sets its own line-height, under the body's 1.5.
    const lh = Number(rule(board, ".job-title").match(/line-height:\s*([\d.]+)/)![1]);
    expect(lh).toBeLessThan(1.5);
  });

  it("the numeral is the second fact, never the loudest mark: meta size, lighter than the title, both states", () => {
    expect(rule(board, ".comp")).toMatch(/font-size:\s*var\(--app-type-meta\)/);
    const weights = (selector: string) => {
      const block = rule(board, selector);
      return {
        title: weight(block, "--row-title-weight"),
        numeral: weight(block, "--row-numeral-weight"),
      };
    };
    const rest = weights(".job-row");
    const viewed = weights(".job-row.is-viewed");
    expect(rest.numeral).toBeLessThan(rest.title);
    expect(viewed.numeral).toBeLessThan(viewed.title);
    // Plex Mono is static faces: a weight nobody loaded paints as its
    // neighbour, and the design then says one thing while the screen shows
    // another (font-weights.test.ts). The numeral asks only for loaded faces.
    const main = readFileSync(join(here, "..", "..", "main.tsx"), "utf8");
    const loaded = new Set([...main.matchAll(/@fontsource\/ibm-plex-mono\/(\d+)\.css/g)].map((m) => Number(m[1])));
    expect(loaded).toContain(rest.numeral);
    expect(loaded).toContain(viewed.numeral);
    // Including the fallback. It never engages while the row sets the
    // property, which is exactly why an unloaded weight there would go
    // unnoticed until the day the row stops setting it.
    const fallback = Number(
      rule(board, ".comp").match(/font-weight:\s*var\(--row-numeral-weight,\s*(\d+)\s*\)/)![1],
    );
    expect(loaded, `the .comp fallback asks for ${fallback}`).toContain(fallback);
  });

  it("the city is a decision fact at the fact floor; the group is the aside", () => {
    expect(rule(board, ".jr-loc")).toMatch(/font-size:\s*var\(--app-type-meta\)/);
    expect(rule(board, ".jr-loc .job-loc-group")).toMatch(/font-size:\s*var\(--app-type-micro\)/);
  });

  it("the title and its meta line are separated by a space token, not a literal pinch", () => {
    expect(rule(board, ".jr-role")).toMatch(/gap:\s*var\(--app-space-1\)/);
    expect(rule(board, ".job-row")).toMatch(/padding:\s*var\(--app-space-3\) /);
  });
});
