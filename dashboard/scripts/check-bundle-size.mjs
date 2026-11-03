// Bundle gate. Runs after `vite build` (`npm run build`); `--record` rewrites the
// recorded startup state (`npm run bundle:record`).
//
// STARTUP (`index` in bundle-baseline.json): the entry chunk, every chunk it
// imports statically, and their CSS, found by `isEntry` in the build's own
// report (scripts/bundle/plugins.mjs), never by file name. Two checks:
//   SIZE: raw bytes (nothing compresses responses in transport, and parse cost
//   is raw) against the RECORDED measure, failing beyond `slack` in either
//   direction and above `cap`. A change that moves the shell
//   records the new number with `bundle:record`; the per-module delta printed
//   here, and `startup-modules.json` in the diff, are the attribution, so no
//   prose rides with the number. Growth is never invisible: it is one number
//   in the diff.
//   BOUNDARY: a second build with every lazy import stubbed. A module or
//   export of our source in the real shell and not in the stubbed one is there
//   only because a lazy screen uses it, and fails by name unless
//   shell-boundary.json lists it as infrastructure (with its reason) or as
//   known debt (shrink-only).
//
// Every other entry is a named lazy chunk with a `{ bytes, why }` ceiling:
// it may not grow without the reason changing with it.
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { budgetProblems } from "./copy/budgets.mjs";
import { boundaryProblems, confinementProblems, driftProblems, lazyOnly, moduleDelta, snapshotOf } from "./bundle/gate.mjs";
import { startupOf } from "./bundle/graph.mjs";
import { REPORT_PATH, stubLazy } from "./bundle/plugins.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = resolve(root, process.env.ROLEBAND_DIST_OUT || "dist");
const assets = join(dist, "assets");
const record = process.argv.includes("--record");
const baselinePath = join(root, "bundle-baseline.json");
const modulesPath = join(root, "startup-modules.json");
const boundaryPath = join(root, "shell-boundary.json");
const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
const boundary = JSON.parse(readFileSync(boundaryPath, "utf8"));
const kib = (n) => `${(n / 1024).toFixed(1)} KiB`;
const fmt = (n) => n.toLocaleString("en-US");
const writeJson = (path, value) => writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`);
// One module per line, so a change to the startup chunk reads as the lines of
// the modules it touched.
const writeSnapshot = (path, value) =>
  writeFileSync(path, `{\n${Object.entries(value).map(([k, v]) => `  ${JSON.stringify(k)}: ${JSON.stringify(v)}`).join(",\n")}\n}\n`);

let failed = false;
const fail = (line) => {
  failed = true;
  console.error(`bundle gate: ${line}`);
};

// ---- startup: the two builds ---------------------------------------------
const reportPath = join(dist, REPORT_PATH);
if (!existsSync(reportPath)) throw new Error(`bundle gate: ${REPORT_PATH} missing; build with vite.config.ts (startupReport plugin)`);
const report = JSON.parse(readFileSync(reportPath, "utf8"));
const { build } = await import("vite");
const scratch = mkdtempSync(join(tmpdir(), "roleband-stubbed-"));
let stubbed;
try {
  const output = await build({
    root,
    configFile: join(root, "vite.config.ts"),
    logLevel: "error",
    build: { write: false, outDir: scratch, emptyOutDir: false },
    plugins: [stubLazy()],
  });
  stubbed = startupOf((Array.isArray(output) ? output[0] : output).output, root);
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
const recordedModules = existsSync(modulesPath) ? JSON.parse(readFileSync(modulesPath, "utf8")) : {};
const snapshot = snapshotOf(report.modules, stubbed.modules);

// ---- startup: size ------------------------------------------------------
const bytesOf = (files) => files.reduce((sum, file) => sum + statSync(join(dist, file)).size, 0);
const measured = { js: bytesOf(report.js), css: bytesOf(report.css) };
const startup = baseline.index;
if (record) {
  startup.js = measured.js;
  startup.css = measured.css;
  writeJson(baselinePath, baseline);
}
for (const problem of driftProblems(measured, startup)) fail(problem);
const delta = moduleDelta(snapshot, recordedModules);
if (failed || record) {
  for (const row of delta.slice(0, 20)) {
    console.log(`  ${row.delta > 0 ? "+" : ""}${fmt(row.delta)}\t${row.module} (${fmt(row.before)} -> ${fmt(row.after)} pre-minify)`);
  }
  if (delta.length > 20) console.log(`  ... ${delta.length - 20} more modules changed`);
}
console.log(
  `bundle gate: startup ${kib(measured.js)} js + ${kib(measured.css)} css (recorded ${fmt(startup.js)} + ${fmt(startup.css)} B, ` +
    `slack ${fmt(startup.slack)}, cap ${fmt(startup.cap)}): ${startup.why}`,
);

// ---- startup: boundary --------------------------------------------------
const found = lazyOnly(report.modules, stubbed.modules);
const { failures, warnings, stale, shed } = boundaryProblems(found, boundary, recordedModules);
for (const line of failures) fail(line);
for (const line of confinementProblems(report.modules, boundary.confined)) fail(line);
for (const line of warnings) console.warn(`bundle gate (warning): ${line}`);
if (record) {
  // Recording prunes paid-off debt, and files as debt only what the shell
  // itself stopped using (`shed`); a leak that newly entered still fails.
  const keep = boundary.debt.filter((d) => found.some((pair) => pair.module === d.module && (pair.export ?? null) === (d.export ?? null)));
  boundary.debt = [...keep, ...shed].sort((a, b) => a.module.localeCompare(b.module) || (a.export ?? "").localeCompare(b.export ?? ""));
  writeJson(boundaryPath, boundary);
  writeSnapshot(modulesPath, snapshot);
  if (stale.length) console.log(`bundle gate: ${stale.length} paid-off debt entr${stale.length === 1 ? "y" : "ies"} removed from shell-boundary.json`);
  if (shed.length) console.log(`bundle gate: ${shed.length} export(s) the shell stopped using filed as debt in shell-boundary.json`);
} else {
  for (const line of stale) fail(line);
}
const stubbedBytes = Object.values(stubbed.modules).reduce((sum, info) => sum + info.bytes, 0);
console.log(
  `bundle gate: shell boundary ${failures.length} new, ${boundary.debt.length} debt, ` +
    `${boundary.infrastructure.length} infrastructure entries; stubbed shell ${fmt(stubbedBytes)} B pre-minify`,
);

// ---- named lazy chunks --------------------------------------------------
const files = readdirSync(assets).filter((f) => f.endsWith(".js"));
const sizeOf = (prefix) => {
  const match = files.filter((f) => f.startsWith(`${prefix}-`));
  if (match.length !== 1) throw new Error(`bundle gate: expected one ${prefix}-*.js, found ${match.length}`);
  return statSync(join(assets, match[0])).size;
};
for (const [name, entry] of Object.entries(baseline)) {
  if (name === "index") continue;
  const { bytes: ceiling, why } = entry;
  if (typeof ceiling !== "number" || !why) {
    throw new Error(`bundle gate: ${name} needs { bytes, why } — a ceiling without a reason is a number nobody can review`);
  }
  const size = sizeOf(name);
  if (size > ceiling) {
    fail(
      `${name} is ${kib(size)}, over its ${kib(ceiling)} ceiling by ${size - ceiling} B.\n` +
        `  Ceiling set because: ${why}\n` +
        `  Split or lazy-load it. To RAISE it, change bytes and why together in bundle-baseline.json — the reason is the review.`,
    );
  } else if (size < ceiling * 0.98) {
    console.log(`[bundle gate] ${name} improved: ${kib(size)} < ceiling ${kib(ceiling)}. Lower bundle-baseline.json.`);
  } else {
    console.log(`bundle gate: ${name} ${kib(size)} / ${kib(ceiling)} — ${why}`);
  }
}

// ---- language chunks ----------------------------------------------------
const locales = JSON.parse(readFileSync(join(root, "src/copy/locales.json"), "utf8")).locales;
const languages = JSON.parse(readFileSync(join(root, "copy-bundle-baseline.json"), "utf8"));
for (const { code } of locales.filter((l) => l.code !== "en")) {
  const matches = files.filter((f) => f.startsWith(`${code}-`));
  if (matches.length !== 1) throw new Error(`copy bundle: expected one lazy ${code} chunk, found ${matches.length}`);
  const problems = budgetProblems(code, readFileSync(join(assets, matches[0]), "utf8"), languages[code]);
  if (problems.length) fail(`copy bundle: ${problems.join("; ")}`);
  else console.log(`copy bundle: ${code} raw/gzip within declared budget`);
}
for (const code of Object.keys(languages)) if (!locales.some((l) => l.code === code)) throw new Error(`copy bundle: stale budget ${code}`);
if (failed) process.exit(1);
