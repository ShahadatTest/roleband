// Writes tests/ux/shard-weights.json, the seconds each spec file takes, from the
// JSON reports of a green CI run (its playwright-results-* artifacts), so the
// browser shards stay balanced as specs grow.
//
//   node scripts/ux-shard-weights.mjs <results.json>...
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const out = join(dirname(fileURLToPath(import.meta.url)), "..", "tests", "ux", "shard-weights.json");
const reports = process.argv.slice(2);
if (!reports.length) {
  console.error("usage: node scripts/ux-shard-weights.mjs <results.json>...");
  process.exit(2);
}

const seconds = {};
function walk(suite) {
  for (const spec of suite.specs ?? []) {
    // A path below tests/ux/, as shards.ts names the files it splits.
    const file = spec.file.replaceAll("\\", "/");
    for (const test of spec.tests) {
      for (const result of test.results) seconds[file] = (seconds[file] ?? 0) + result.duration / 1000;
    }
  }
  for (const child of suite.suites ?? []) walk(child);
}
for (const report of reports) {
  for (const suite of JSON.parse(readFileSync(report, "utf8")).suites) walk(suite);
}

const sorted = Object.fromEntries(Object.keys(seconds).sort().map((file) => [file, Math.round(seconds[file] * 10) / 10]));
writeFileSync(out, `${JSON.stringify(sorted, null, 2)}\n`);
console.log(`${Object.keys(sorted).length} spec files, ${Math.round(Object.values(sorted).reduce((a, b) => a + b, 0))} s in all -> ${out}`);
