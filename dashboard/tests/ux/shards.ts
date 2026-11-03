import { readdirSync, readFileSync } from "node:fs";
import { join, sep } from "node:path";

export type Shard = { index: number; total: number };

/** `ROLEBAND_UX_SHARD=INDEX/TOTAL`, or none when the run is whole. */
export function uxShard(env: NodeJS.ProcessEnv = process.env): Shard | undefined {
  const value = env.ROLEBAND_UX_SHARD;
  if (value === undefined) return undefined;
  const match = /^(\d+)\/(\d+)$/.exec(value);
  const index = Number(match?.[1]);
  const total = Number(match?.[2]);
  if (!match || index < 1 || index > total) {
    throw new Error(`ROLEBAND_UX_SHARD takes INDEX/TOTAL with 1 <= INDEX <= TOTAL, not ${JSON.stringify(value)}`);
  }
  return { index, total };
}

/** The spec files split into `total` shards of about equal recorded time.
 *
 *  Playwright's own `--shard` cuts the test list into runs of equal COUNT, in
 *  file order, so the heavy specs that sort late all land on the last shard.
 *  Here each file goes whole, heaviest first, to the shard with the least time
 *  so far. A file with no recorded time weighs the median, so a new spec is
 *  still run and a stale weights file only costs balance, never coverage. Ties
 *  break by name and by shard number, so every runner computes the same split.
 */
export function splitSpecs(files: string[], weights: Record<string, number>, total: number): string[][] {
  const known = files.map((file) => weights[file]).filter((weight) => weight !== undefined).sort((a, b) => a - b);
  const fallback = known.length ? known[Math.floor(known.length / 2)] : 1;
  const weightOf = (file: string) => weights[file] ?? fallback;
  const order = [...new Set(files)].sort((a, b) => weightOf(b) - weightOf(a) || (a < b ? -1 : a > b ? 1 : 0));
  const shards = Array.from({ length: total }, () => ({ time: 0, files: [] as string[] }));
  for (const file of order) {
    const lightest = shards.reduce((best, shard) => (shard.time < best.time ? shard : best));
    lightest.time += weightOf(file);
    lightest.files.push(file);
  }
  return shards.map((shard) => shard.files.sort());
}

/** Seconds each spec file of `testDir` took in a recorded run, both projects
 *  together: `shard-weights.json` beside the specs (`scripts/ux-shard-weights.mjs`). */
export function recordedWeights(testDir: string): Record<string, number> {
  return JSON.parse(readFileSync(join(testDir, "shard-weights.json"), "utf8")) as Record<string, number>;
}

/** Playwright's default `testMatch`, which the shards replace: every file it
 *  would run must fall to one of them. */
const TEST_FILE = /\.(spec|test)\.[cm]?[jt]sx?$/;

/** The test files under `testDir`, as `/`-separated paths relative to it. */
export function testFiles(testDir: string): string[] {
  return readdirSync(testDir, { recursive: true, encoding: "utf8" })
    .map((file) => file.split(sep).join("/"))
    .filter((file) => TEST_FILE.test(file) && !file.split("/").includes("node_modules"))
    .sort();
}

/** The test files of `testDir` that fall to `shard`, each matched by its whole
 *  absolute path, as Playwright matches `testMatch`: `a.spec.ts` matches neither
 *  `b-a.spec.ts` nor `nested/a.spec.ts`. */
export function shardTestMatch(testDir: string, shard: Shard): RegExp[] {
  const escape = (path: string) => path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return splitSpecs(testFiles(testDir), recordedWeights(testDir), shard.total)[shard.index - 1]
    .map((file) => new RegExp(`^${escape(join(testDir, ...file.split("/")))}$`));
}
