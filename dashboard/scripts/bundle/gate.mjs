// The startup gate's decisions, pure.
//
// Two questions, kept apart because each is blind to the other:
//   SIZE: is the startup payload what was recorded? A recorded raw measure
//   with a small slack, both directions, so growth is one number in the diff
//   and the per-module delta printed beside it says where it came from.
//   BOUNDARY: does the shell carry code only a lazy screen uses? Answered by
//   NAME from two builds, the real one and one with every lazy import
//   stubbed. A byte count can say the shell grew; only this can say what to
//   move.

const fmt = (n) => n.toLocaleString("en-US");

/** `measured` = { js, css } raw bytes; `recorded` = bundle-baseline.json `index`. */
export function driftProblems(measured, recorded) {
  const problems = [];
  for (const kind of ["js", "css"]) {
    const delta = measured[kind] - recorded[kind];
    if (Math.abs(delta) > recorded.slack) {
      problems.push(
        `startup ${kind} is ${fmt(measured[kind])} B, ${delta > 0 ? "+" : ""}${fmt(delta)} B from the recorded ` +
          `${fmt(recorded[kind])} (slack ${fmt(recorded.slack)}). Run \`npm run bundle:record\`; the module delta ` +
          `below is the attribution, and the pull request says why.`,
      );
    }
  }
  if (measured.js > recorded.cap) {
    problems.push(`startup js ${fmt(measured.js)} B is over the cap ${fmt(recorded.cap)} B. The cap moves only with a maintainer's agreement on the pull request, which says why.`);
  }
  return problems;
}

/** Per-module pre-minify bytes now against the recorded snapshot, largest change first. */
export function moduleDelta(now, recorded) {
  const names = new Set([...Object.keys(now), ...Object.keys(recorded)]);
  return [...names]
    .map((module) => {
      const before = recorded[module]?.bytes ?? 0;
      const after = now[module]?.bytes ?? 0;
      return { module, before, after, delta: after - before };
    })
    .filter((row) => row.delta !== 0)
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta) || a.module.localeCompare(b.module));
}

const ours = (module) => module.startsWith("src/");

/**
 * What the real shell carries that the stubbed shell does not: a whole module
 * (`{ module }`) or one export of a module both carry (`{ module, export }`).
 * Our source only: a third-party module is not ours to split, and it is still
 * counted by the size check.
 */
export function lazyOnly(full, stubbed) {
  const found = [];
  for (const [module, info] of Object.entries(full)) {
    if (!ours(module) || info.bytes === 0) continue;
    const shell = stubbed[module];
    if (!shell) {
      found.push({ module, lazyImporters: info.lazyImporters ?? [] });
      continue;
    }
    for (const name of info.exports) {
      if (!shell.exports.includes(name)) found.push({ module, export: name, lazyImporters: info.lazyImporters ?? [] });
    }
  }
  return found;
}

/**
 * `confined` = shell-boundary.json: directories the startup chunk may take only
 * the listed modules from. For what a graph diff cannot see: the bundler never
 * tree-shakes an object by method, so a domain object the shell imports for
 * one call ships whole, with every method a screen adds, and the stubbed build
 * carries it too. A rule by NAME on the module does see it.
 */
export function confinementProblems(full, confined = []) {
  return confined.flatMap((rule) => {
    const inside = Object.keys(full)
      .filter((module) => module.startsWith(rule.dir) && !rule.allow.includes(module) && full[module].bytes > 0)
      .sort();
    return inside.length
      ? [`${inside.join(", ")} entered the startup chunk; from ${rule.dir} only ${rule.allow.join(", ")} may: ${rule.why}`]
      : [];
  });
}

const label = (pair) => (pair.export ? `${pair.module} \`${pair.export}\`` : pair.module);
const same = (a, b) => a.module === b.module && (a.export ?? null) === (b.export ?? null);

/**
 * The startup-modules.json snapshot: per startup module its pre-minify bytes,
 * the exports the real build kept, and `shell`, the exports the STUBBED build
 * kept (null when the stubbed shell does not carry the module at all).
 */
export function snapshotOf(full, stubbed) {
  return Object.fromEntries(
    Object.entries(full)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([module, info]) => [module, { bytes: info.bytes, exports: info.exports, shell: stubbed[module]?.exports ?? null }]),
  );
}

/**
 * `boundary` = shell-boundary.json: `infrastructure` (what the shell provides to
 * screens by design, each with `why`; `exports` omitted = the whole module) and
 * `debt` (known leaks, shrink by hand). `recorded` = the startup-modules.json
 * snapshot, whose `shell` field is what the STUBBED shell used at the last
 * record: a pair the shell itself used then and only lazy code uses now (the
 * shell stopped using it) is a warning, since that change shrank the shell,
 * and `bundle:record` files it as debt. Anything else is a failure; recording
 * cannot launder a leak, because a lazy-only export is never in `shell`.
 */
export function boundaryProblems(found, boundary, recorded) {
  const allowed = (pair) =>
    boundary.infrastructure.some(
      (entry) => entry.module === pair.module && (!entry.exports || (pair.export && entry.exports.includes(pair.export))),
    );
  // One line per module and verdict: the move is per module, not per export.
  const groups = new Map();
  for (const pair of found) {
    if (allowed(pair) || boundary.debt.some((d) => same(d, pair))) continue;
    const shellUsed = recorded[pair.module]?.shell;
    const carried = Boolean(shellUsed && (!pair.export || shellUsed.includes(pair.export)));
    const key = `${carried}\n${pair.module}`;
    if (!groups.has(key)) groups.set(key, { carried, module: pair.module, exports: [], whole: false, lazyImporters: pair.lazyImporters });
    const group = groups.get(key);
    if (pair.export) group.exports.push(pair.export);
    else group.whole = true;
  }
  const failures = [];
  const warnings = [];
  const shed = [];
  for (const group of groups.values()) {
    const what = group.whole ? group.module : `${group.module} {${group.exports.join(", ")}}`;
    const who = group.lazyImporters.length
      ? ` Lazy importers: ${group.lazyImporters.slice(0, 4).join(", ")}${group.lazyImporters.length > 4 ? ", ..." : ""}.`
      : "";
    const line =
      `${what} is in the startup chunk only because lazy code uses it.${who} Move it to a module the shell ` +
      `does not import; if the shell provides it to screens by design, add it to shell-boundary.json ` +
      `"infrastructure" with the reason.`;
    (group.carried ? warnings : failures).push(line);
    if (group.carried) shed.push(...(group.whole ? [{ module: group.module }] : group.exports.map((name) => ({ module: group.module, export: name }))));
  }
  const stale = boundary.debt
    .filter((d) => !found.some((pair) => same(d, pair)))
    .map((d) => `${label(d)} is no longer a leak: delete it from shell-boundary.json "debt" (shrink-only).`);
  return { failures, warnings, stale, shed };
}
