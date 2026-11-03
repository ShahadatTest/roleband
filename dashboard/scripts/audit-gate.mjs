// Dependency audit gate: `npm run audit:check`.
//
// Runs `npm audit` over the production dependencies (what the built app ships)
// and fails on every advisory at high or critical severity that no current
// entry in audit-exceptions.json accepts. An entry names the advisory (its
// GHSA id), the package, the reason it does not reach RoleBand or what the
// upgrade waits on, and an expiry date (YYYY-MM-DD). An expired entry, a
// malformed one, and one that matches no finding fail too, so the list is
// reviewed again rather than outliving its reason.
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { auditProblems, FLOOR, findingsOf } from "./audit/gate.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const run = spawnSync("npm", ["audit", "--omit=dev", `--audit-level=${FLOOR}`, "--json"], {
  cwd: root, encoding: "utf8", maxBuffer: 64 * 1024 * 1024,
});
let report;
try {
  report = JSON.parse(run.stdout);
} catch {
  console.error(`npm audit gave no report (exit ${run.status}):\n${run.stderr}`);
  process.exit(1);
}
if (report.error) {
  console.error(`npm audit failed: ${report.error.summary ?? JSON.stringify(report.error)}`);
  process.exit(1);
}
const { exceptions } = JSON.parse(readFileSync(join(root, "audit-exceptions.json"), "utf8"));
const found = findingsOf(report);
const problems = auditProblems(found, exceptions, new Date().toISOString().slice(0, 10));
for (const line of problems) console.log(line);
if (problems.length) {
  console.log(`\n${problems.length} problem(s). Exceptions live in audit-exceptions.json.`);
  process.exit(1);
}
console.log(`dependency audit: ${found.length} finding(s) at ${FLOOR} or above, all excepted and current`);
