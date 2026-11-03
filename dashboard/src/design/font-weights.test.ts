import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* Mono weights must be weights we LOAD.
 *
 * IBM Plex Sans is a VARIABLE face here, so any weight it is asked for is the
 * weight it paints. IBM Plex Mono is not: `@fontsource/ibm-plex-mono` ships
 * static faces, one file per weight, and a weight nobody imported is not
 * synthesised — CSS font matching walks to the nearest face present. The
 * design says one thing and the screen shows another, and nothing can tell.
 *
 * Every mono declaration asks for a loaded face. One that did not would paint
 * something other than what it says, so it fails here: move it to a loaded
 * weight, or import its face in main.tsx.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

/* CSS Fonts 4 font matching, the part that matters here: for a desired weight
 * ABOVE 500 the browser searches UPWARD first and only then downward. So the
 * face an unloaded weight paints depends on the whole loaded set, and adding a
 * face can repaint declarations that have nothing to do with it:
 *
 *     loaded 400/500/600     ->  550, 640, 650, 750, 800 all paint 600
 *     loaded 400/500/600/700 ->  550 paints 600; 640/650/750/800 paint 700
 *
 * A gate that only asks "is this weight loaded?" cannot see that move.
 *
 * So a known unloaded weight would be recorded with the face it paints, and a
 * new face that changed one would fail by name. None is left: the list is
 * empty and stays so. */
const KNOWN_UNLOADED: Record<number, number> = {};

/** The face a request actually resolves to, per CSS Fonts 4 font matching. Pinned to
 *  measured browser behaviour by the fixture below -- an algorithm nobody
 *  checked against a real engine is a second guess, not a gate. */
export function paintedFace(asked: number, loaded: Iterable<number>): number | null {
  const faces = [...loaded].sort((a, b) => a - b);
  if (faces.includes(asked)) return asked;
  const up = (from: number, to = Infinity) => faces.find((w) => w >= from && w <= to) ?? null;
  const down = (from: number) => [...faces].reverse().find((w) => w < from) ?? null;
  if (asked >= 400 && asked <= 500) return up(asked, 500) ?? down(asked) ?? up(501);
  if (asked < 400) return ([...faces].reverse().find((w) => w <= asked) ?? null) ?? up(asked);
  return up(asked) ?? down(asked);
}

function sheets(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) sheets(path, acc);
    else if (name.endsWith(".css")) acc.push(path);
  }
  return acc;
}

/** Weights imported in main.tsx. */
function loadedMonoWeights(): Set<number> {
  const main = readFileSync(join(SRC, "main.tsx"), "utf8");
  return new Set(
    [...main.matchAll(/@fontsource\/ibm-plex-mono\/(\d+)\.css/g)].map((m) => Number(m[1])),
  );
}

/** Every `font-weight` set in a rule that also selects the mono family, with
 *  `var(--token)` resolved against the app scope AND against the sheet's own
 *  declarations.
 *
 *  The second lookup matters: the Board comp numeral is
 *  `var(--row-numeral-weight, ...)`, a property its own sheet sets, and a
 *  skipped `var()` would hide it from this sweep. A local property has as
 *  many values as the rules that set it (rest and `.is-viewed` here), so every one is a request:
 *  a weight the row asks for in ANY state has to be a face we load.
 *
 *  An unresolvable `var()` is REPORTED rather than dropped — a request the
 *  scanner cannot price is the one shape that must never read as "fine". */
function monoWeightRequests(): { weight: number | null; where: string }[] {
  const tokens = readFileSync(join(SRC, "design", "tokens.css"), "utf8");
  const out: { weight: number | null; where: string }[] = [];
  for (const file of sheets(SRC)) {
    const source = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    const scopes = [tokens, source];
    const values = (name: string): number[] => {
      const hits = scopes.flatMap((scope) => [
        ...scope.matchAll(new RegExp(`${name}\\s*:\\s*(\\d+)\\s*;`, "g")),
      ]);
      return [...new Set(hits.map((m) => Number(m[1])))];
    };
    for (const block of source.matchAll(/\{([^{}]*)\}/g)) {
      const body = block[1];
      if (!/font-family:[^;]*(--app-font-mono|--mono)/.test(body)) continue;
      const weight = body.match(/font-weight:\s*([^;]+)/)?.[1]?.trim();
      if (!weight) continue;
      const where = `${relative(SRC, file).split(sep).join("/")}: ${weight}`;
      const literal = weight.match(/^(\d+)$/);
      if (literal) {
        out.push({ weight: Number(literal[1]), where });
        continue;
      }
      // Every state the property is set in, plus a literal fallback if present.
      const names = [...weight.matchAll(/var\((--[\w-]+)/g)].map((m) => m[1]);
      const asked = names.flatMap(values);
      const fallback = weight.match(/,\s*(\d+)\s*\)/);
      if (fallback) asked.push(Number(fallback[1]));
      if (asked.length === 0) out.push({ weight: null, where });
      for (const value of new Set(asked)) out.push({ weight: value, where });
    }
  }
  return out;
}

describe("mono font weights", () => {
  const loaded = loadedMonoWeights();

  it("loads the weight the signed system asks for", () => {
    const tokens = readFileSync(join(SRC, "design", "tokens.css"), "utf8");
    const whisper = Number(tokens.match(/--app-type-whisper-weight:\s*(\d+)/)![1]);
    expect(loaded, `whisper asks for ${whisper}; main.tsx imports ${[...loaded].join(", ")}`).toContain(whisper);
  });

  it("the Board's comp numeral asks for a weight that exists", () => {
    const board = readFileSync(join(SRC, "patterns", "jobs", "job-row.css"), "utf8");
    const rest = Number(board.match(/--row-numeral-weight:\s*(\d+)/)![1]);
    expect(loaded).toContain(rest);
  });

  it("prices every mono request, including the ones behind a local property", () => {
    // A request the scanner cannot resolve is not a pass.
    const unpriced = monoWeightRequests().filter((r) => r.weight === null);
    expect(
      unpriced.map((r) => r.where),
      "this mono font-weight names a custom property nothing defines, so no " +
        "face can be checked against it. Define it, or write the weight.",
    ).toEqual([]);
  });

  it("no NEW mono declaration asks for a face nobody loads", () => {
    const unexpected = monoWeightRequests().filter(
      (r) => r.weight != null && !loaded.has(r.weight) && !(r.weight in KNOWN_UNLOADED),
    );
    expect(
      unexpected.map((r) => r.where),
      "mono is static: an unimported weight paints the nearest loaded face, not the one written. " +
        "Use a loaded weight, or import the face in main.tsx and say so.",
    ).toEqual([]);
  });

  /* Ground truth, measured rather than derived: each row is what Chromium AND
     WebKit actually painted for that (asked, loaded) pair, read off canvas
     bitmaps compared byte-for-byte against the loaded faces, with a control
     asserting the loaded faces render distinctly -- a probe that could not tell
     them apart could not report agreement either. The three-face rows are the
     set without 700; the four-face rows are the set main.tsx loads. */
  it.each([
    [550, [400, 500, 600], 600],
    [640, [400, 500, 600], 600],
    [650, [400, 500, 600], 600],
    [750, [400, 500, 600], 600],
    [800, [400, 500, 600], 600],
    [550, [400, 500, 600, 700], 600],
    [640, [400, 500, 600, 700], 700],
    [650, [400, 500, 600, 700], 700],
    [750, [400, 500, 600, 700], 700],
    [800, [400, 500, 600, 700], 700],
    // The rule that makes this counter-intuitive: at or below 500 the search
    // runs UP to 500 first, so 450 takes 500 while 640 takes 700.
    [450, [400, 500, 600, 700], 500],
    [300, [400, 500, 600, 700], 400],
  ])("resolves %i against %j the way a browser does", (asked, faces, painted) => {
    expect(paintedFace(asked, faces)).toBe(painted);
  });

  it("says what each unloaded weight paints, so a new face cannot repaint it in silence", () => {
    // Loading a face changes the SET, and the set is what every unloaded
    // request resolves against: adding 700 moves 640/650/750/800 from 600 to
    // 700 in declarations that have nothing to do with the face. Recording the
    // consequence is what makes that visible; recording only the debt hides it.
    const drifted = Object.entries(KNOWN_UNLOADED)
      .map(([asked, painted]) => ({ asked: Number(asked), painted, now: paintedFace(Number(asked), loaded) }))
      .filter((row) => row.now !== row.painted);
    expect(
      drifted.map((r) => `${r.asked} painted ${r.painted}, now paints ${r.now}`),
      "a font face was added or removed and it moved what an EXISTING declaration " +
        "paints. That is a visual change on every rule asking for these weights. " +
        "Decide it deliberately, then update KNOWN_UNLOADED to the new truth.",
    ).toEqual([]);
  });

  it("the known-unloaded list is exactly what is still wrong, so it can only shrink", () => {
    const asked = new Set(
      monoWeightRequests()
        .map((r) => r.weight)
        .filter((w): w is number => w != null && !loaded.has(w)),
    );
    expect([...asked].sort((a, b) => a - b)).toEqual(
      Object.keys(KNOWN_UNLOADED).map(Number).sort((a, b) => a - b),
    );
  });
});
