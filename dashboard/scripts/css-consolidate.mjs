#!/usr/bin/env node
/* css-consolidate — move a CSS family out of two forked sheets into one
 * co-located file, carrying its `@media` wrappers and its comments.
 *
 * Three ways a mover goes wrong, and where each is answered here:
 *
 *   1. Regex over innermost `{}` pairs. settings.css NESTS most of
 *      itself inside `.settings-design-system {…}`, so a rule that follows
 *      DECLARATIONS in its parent parses as a selector of
 *      `min-width: 0; flex: 1; .stage-band` and is silently skipped.
 *      -> `parse()` is brace-accurate and string/comment aware.
 *
 *   2. Parse to a tree and render the tree back. Brace-accurate, and it
 *      destroys every comment, which in this repo are the documentation.
 *      -> nothing is ever re-rendered. Every emitted byte is a verbatim slice
 *      of the source, and the "no unique comment lost" check refuses to write
 *      when a comment removed from a source is found nowhere else.
 *
 *   3. Splice spans but skip `@media` blocks. The rules inside a block are
 *      ordinary children, so the walk still reaches them and moves them
 *      WITHOUT their wrapper: a max-width override becomes unconditional, and
 *      no gate that does not read layout notices.
 *      -> a rule is emitted under its full reconstructed at-rule chain, and
 *      the "every media rule kept its wrapper" check fails if a rule that had
 *      an at-rule ancestor lands at top level.
 *
 * Asking only "did anything foreign arrive?" and never "did everything intended
 * leave?" lets `leaked: none` be accurate on a half-done job. Both directions
 * are checked here.
 *
 * Usage:  node scripts/css-consolidate.mjs <config.json> [--write]
 * Dry by default; prints the plan and every assertion it ran.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { parse, walk, selectorParts } from "./css-span-parser.mjs";

const [configPath, ...flags] = process.argv.slice(2);
const WRITE = flags.includes("--write");
if (!configPath) {
  console.error("usage: css-consolidate.mjs <config.json> [--write]");
  process.exit(2);
}
const cfg = JSON.parse(readFileSync(configPath, "utf8"));

const files = new Map();
function load(path) {
  if (!files.has(path)) {
    const text = readFileSync(path, "utf8");
    files.set(path, { path, text, tree: parse(text), cuts: [] });
  }
  return files.get(path);
}

const countComments = (s) => (s.match(/\/\*/g) ?? []).length;

/* ---------------------------------------------------------------- selectors */

/** settings.css nests under `.settings-design-system`; that marker is SCOPE,
 *  not identity, so it is stripped before two sheets are compared. */
function unscope(sel) {
  return sel
    .replace(/^body\.settings-design-system\s*/, "")
    .replace(/^\.settings-design-system\s*/, "")
    .replace(/^&\s*/, "")
    .replace(/\s+/g, " ")
    .trim();
}

/* Ownership is decided by the LEFTMOST class of a selector part — the thing the
 * rule is scoped to — not by every class in it.
 *
 * Requiring every class to match looks safer and is wrong in both directions.
 * It skips `.stage-cell.gated`, `.stage-marker.lock`, `.stage-cell.lit` —
 * compounds whose second class is a state modifier with no rules of its own —
 * and so leaves part of the family behind. And it
 * does not catch a selector list whose parts have DIFFERENT owners (the two
 * halves of `.select-card input, .scope-category-head > input`), which is a
 * per-part question, answered by splitting parts.
 *
 * What is still worth knowing is when a moved rule reaches into another
 * family's markup. That is reported rather than blocked, because reaching a
 * primitive (`.ui-btn`, `.ui-search`) is normal and reaching an unmigrated
 * family is not — a distinction only a person can make. */
function leadClass(part) {
  const m = part.match(/\.(-?[_a-zA-Z][\w-]*)/);
  return m ? m[1] : null;
}
function classesOf(part) {
  return [...part.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)].map((m) => m[1]);
}
function familyOf(part, families) {
  const lead = leadClass(part);
  if (!lead) return null;
  return families.find((f) => matches(lead, f)) ?? null;
}
function matches(cls, family) {
  return cls === family || cls.startsWith(family + "-") || cls.startsWith(family + "--");
}

/* ------------------------------------------------------------------ extract */

/** Widen a node's span backwards over the comment block that documents it.
 *  A comment is claimed only when nothing but whitespace separates it from
 *  both the rule below and the previous node above — so a comment already
 *  trailing another rule stays put. */
function withLeadingComments(text, start, floor) {
  let at = start;
  for (;;) {
    let k = at - 1;
    while (k >= floor && /\s/.test(text[k])) k--;
    if (k < floor + 1 || text[k] !== "/" || text[k - 1] !== "*") break;
    const open = text.lastIndexOf("/*", k - 1);
    if (open < floor) break;
    // Refuse a comment that shares its line with code before it.
    const lineStart = text.lastIndexOf("\n", open) + 1;
    if (text.slice(lineStart, open).trim() !== "") break;
    at = lineStart;
  }
  return at;
}

/** Strip the common leading indentation so a rule lifted out of a nested
 *  block sits flush in its new file. */
function dedent(block) {
  const lines = block.split("\n");
  const widths = lines
    .filter((l) => l.trim())
    .map((l) => l.match(/^[ \t]*/)[0].length);
  const cut = widths.length ? Math.min(...widths) : 0;
  return lines.map((l) => l.slice(0, cut).trim() === "" ? l.slice(cut) : l.trimStart()).join("\n").trimEnd();
}

/* Two things never move, whatever family they name:
 *  - a part explicitly scoped to the Settings body attribute. That scope IS the
 *    rule's point (a portal surface repainted only under the Settings marker),
 *    so settings.css is its right home, not a shared sheet.
 *  - anything the config excludes by name. */
const excluded = (p) =>
  /\[data-settings-design-system/.test(p) ||
  (cfg.exclude ?? []).some((x) => classesOf(p).some((c) => matches(c, x)));

const plan = [];   // { key, chain, selector, source, text, comments }
const problems = [];
const reaches = [];

for (const src of cfg.sources) {
  const file = load(src.path);
  const nodes = walk(file.tree);
  // Sort deepest-last so a parent's span is cut before we consider children.
  for (let idx = 0; idx < nodes.length; idx++) {
    const { node, ancestors } = nodes[idx];
    if (node.type !== "rule") continue;
    if (ancestors.some((a) => a.type === "rule" && !/settings-design-system/.test(a.prelude))) {
      continue; // a rule nested under a real selector keeps its parent's meaning
    }
    const chain = ancestors.filter((a) => a.type === "atrule").map((a) => a.prelude);
    const parts = selectorParts(node.prelude).map(unscope);
    const mine = parts.filter((p) => familyOf(p, cfg.families) && !excluded(p));
    if (!mine.length) continue;

    if (mine.length !== parts.length) {
      // The failure to avoid: a multi-part selector matches if ANY part does, and
      // the whole rule moves, unscoping a family that has not migrated. Split
      // instead — take our parts, leave theirs.
      problems.push(
        `SPLIT ${src.path}: "${node.prelude}" -> moving [${mine}], leaving [${parts.filter((p) => !mine.includes(p))}]`,
      );
    }

    for (const part of mine) {
      const foreign = classesOf(part)
        .slice(1)
        .filter((c) => !cfg.families.some((f) => matches(c, f)) && !/^ui-/.test(c));
      if (foreign.length) {
        reaches.push(`${src.path}:${file.text.slice(0, node.start).split("\n").length} "${part}" reaches .${foreign.join(" .")}`);
      }
    }

    const prev = idx > 0 ? nodes[idx - 1] : null;
    const floor = ancestors.length ? ancestors[ancestors.length - 1].bodyStart : 0;
    const commentFloor = Math.max(floor, prev && prev.node.end <= node.start ? prev.node.end : floor);
    const from = withLeadingComments(file.text, node.start, commentFloor);
    const raw = file.text.slice(from, node.end);
    const body = file.text.slice(node.bodyStart, node.bodyEnd);
    const lead = file.text.slice(from, node.start);

    file.cuts.push({ start: from, end: node.end, keepParts: parts.filter((p) => !mine.includes(p)), node });

    for (const sel of mine) {
      plan.push({
        key: `${chain.join(" && ")}||${sel}`,
        chain,
        selector: sel,
        source: src.name,
        sourcePath: src.path,
        // Re-emitted verbatim: the lead comments, the selector list we kept,
        // and the body exactly as written.
        text: dedent(lead) + (dedent(lead) ? "\n" : "") + `${mine.join(", ")} {${body}}`,
        comments: countComments(raw),
        rawComments: countComments(raw),
        allParts: mine,
        node,
        line: file.text.slice(0, node.start).split("\n").length,
      });
    }
  }
}

/* --------------------------------------------------------- pick one winner */

/* Deduping happens ACROSS sheets, never within one. Two rules for the same
 * selector in the same sheet are cumulative — settings.css states `.loc-search`
 * twice, once for its margin and once for its width — so collapsing them to
 * "the winner" silently drops a declaration (here, the `width: 100%` that
 * makes the locations search the step's dominant control).
 * Across sheets the fork IS the thing being removed, so the preferred sheet
 * takes the whole selector and the other copy dies. */
const byKey = new Map();
for (const p of plan) {
  if (!byKey.has(p.key)) byKey.set(p.key, []);
  byKey.get(p.key).push(p);
}

const prefer = cfg.prefer;
const emitted = new Map();
const dropped = [];
const seenRule = new Set();

for (const [, copies] of byKey) {
  const preferred = copies.filter((c) => c.source === prefer);
  const winners = preferred.length ? preferred : copies;
  for (const c of copies) if (!winners.includes(c)) dropped.push(c);
  for (const w of winners) {
    const ruleId = `${w.sourcePath}||${w.line}||${w.allParts.join(", ")}`;
    if (seenRule.has(ruleId)) continue; // a multi-part rule reaches here once per part
    seenRule.add(ruleId);
    emitted.set(ruleId, w);
  }
}

/* ------------------------------------------------------------------- emit */

const chains = new Map();
for (const w of emitted.values()) {
  const k = JSON.stringify(w.chain);
  if (!chains.has(k)) chains.set(k, { chain: w.chain, rules: [] });
  chains.get(k).rules.push(w);
}

/** Base rules first, then width media widest-first (so a narrower override
 *  still wins), then the preference queries. Same order the source sheets
 *  used, reconstructed rather than assumed. */
function chainRank(chain) {
  if (!chain.length) return [0, 0];
  const w = chain.join(" ").match(/max-width:\s*(\d+)/);
  if (w) return [1, -Number(w[1])];
  return [2, 0];
}
const ordered = [...chains.values()].sort((a, b) => {
  const [ra, sa] = chainRank(a.chain);
  const [rb, sb] = chainRank(b.chain);
  return ra - rb || sa - sb;
});

let out = "";
for (const { chain, rules } of ordered) {
  const bodies = rules.map((r) => r.text).join("\n");
  if (!chain.length) {
    out += bodies + "\n";
  } else {
    // The at-rule chain the rule was found under.
    const open = chain.map((c, i) => "  ".repeat(i) + c + " {").join("\n");
    const close = chain.map((_, i) => "  ".repeat(chain.length - 1 - i) + "}").join("\n");
    const indent = "  ".repeat(chain.length);
    const inner = bodies.split("\n").map((l) => (l.trim() ? indent + l : l)).join("\n");
    out += `${open}\n${inner}\n${close}\n`;
  }
  out += "\n";
}

/* ------------------------------------------------------------------- cut */

function applyCuts(file) {
  const cuts = [...file.cuts].sort((a, b) => b.start - a.start);
  let text = file.text;
  for (const c of cuts) {
    const replacement = c.keepParts.length
      ? `${c.keepParts.join(", ")} {${text.slice(c.node.bodyStart, c.node.bodyEnd)}}`
      : "";
    let from = c.start, to = c.end;
    if (!replacement) {
      // swallow the rule's own line if nothing else is on it
      while (to < text.length && (text[to] === " " || text[to] === "\t")) to++;
      if (text[to] === "\n") to++;
      const lineStart = text.lastIndexOf("\n", from - 1) + 1;
      if (text.slice(lineStart, from).trim() === "") from = lineStart;
    }
    text = text.slice(0, from) + replacement + text.slice(to);
  }
  // Drop at-rule blocks that the cuts emptied.
  for (;;) {
    const before = text;
    text = text.replace(/^([ \t]*)@[^{}\n]*\{\s*\}[ \t]*\n/gm, "");
    text = text.replace(/\n{4,}/g, "\n\n\n");
    if (text === before) break;
  }
  return text;
}

/* -------------------------------------------------------------- assertions */

const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok, detail });
  if (!ok) process.exitCode = 1;
}

const destPath = cfg.destination;
const destBefore = readFileSync(destPath, "utf8");
const destAfter = destBefore.replace(/\s*$/, "\n") + "\n" + cfg.banner.trimEnd() + "\n\n" + out.trimEnd() + "\n";

// 1. no unique comment is lost.
//    Count-conservation is the WRONG invariant here: when a selector is forked,
//    the losing copy is cut and never re-emitted, so the total legitimately
//    falls. What may never happen is a comment disappearing from the repo
//    entirely — in this codebase the comment above a rule is the reason the
//    rule exists. So: every distinct comment removed from
//    a source must still be findable, either in what we emit or in what stays.
const norm = (c) => c.replace(/\s+/g, " ").trim();
const commentsOf = (text) => (text.match(/\/\*[\s\S]*?\*\//g) ?? []).map(norm);

const removed = new Set();
const kept = new Set(commentsOf(out).concat(commentsOf(destBefore)));
for (const f of files.values()) {
  const after = applyCuts(f);
  const beforeSet = commentsOf(f.text);
  const afterSet = commentsOf(after);
  for (const c of afterSet) kept.add(c);
  const afterCounts = new Map();
  for (const c of afterSet) afterCounts.set(c, (afterCounts.get(c) ?? 0) + 1);
  for (const c of beforeSet) {
    const n = afterCounts.get(c) ?? 0;
    if (n > 0) afterCounts.set(c, n - 1);
    else removed.add(c);
  }
}
const lostComments = [...removed].filter((c) => !kept.has(c));
check(
  "no unique comment lost",
  lostComments.length === 0,
  lostComments.map((c) => "  " + c.slice(0, 110)).join("\n"),
);

// 2. nothing foreign arrived
const leaked = [];
for (const { node, ancestors } of walk(parse(out))) {
  if (node.type !== "rule") continue;
  for (const p of selectorParts(node.prelude)) {
    if (!familyOf(unscope(p), cfg.families)) leaked.push(p);
  }
}
check("no foreign selector reached the destination", leaked.length === 0, leaked.join(", "));

// 3. everything with an at-rule ancestor kept one: a max-width override
//    emitted at top level becomes unconditional.
const wantWrapped = new Set(
  [...emitted.values()]
    .filter((w) => w.chain.length)
    .map((w) => `${w.chain.join(" && ")}||${w.allParts.join(", ")}`),
);
// A selector may legitimately appear both at top level and under a wrapper
// (`.stage-rail` states its base and its stacked override). Only a MISSING
// wrapper is a defect, so track the two shapes separately.
const wantTop = new Set(
  [...emitted.values()].filter((w) => !w.chain.length).map((w) => w.allParts.join(", ")),
);
const seenWrapped = new Set();
const unwrapped = [];
for (const { node, ancestors } of walk(parse(out))) {
  if (node.type !== "rule") continue;
  const sel = selectorParts(node.prelude).map(unscope).join(", ");
  const chain = ancestors.filter((a) => a.type === "atrule").map((a) => a.prelude);
  if (chain.length) seenWrapped.add(`${chain.join(" && ")}||${sel}`);
  else if (!wantTop.has(sel)) unwrapped.push(`${sel} (emitted at top level, wanted a wrapper)`);
}
for (const k of wantWrapped) {
  if (!seenWrapped.has(k)) unwrapped.push(`${k} (never emitted under its wrapper)`);
}
check("every media rule kept its wrapper", unwrapped.length === 0, unwrapped.join("\n       "));

// 4. everything intended actually left
const remaining = [];
for (const f of files.values()) {
  const after = applyCuts(f);
  for (const { node, ancestors } of walk(parse(after))) {
    if (node.type !== "rule") continue;
    if (ancestors.some((a) => a.type === "rule" && !/settings-design-system/.test(a.prelude))) continue;
    for (const p of selectorParts(node.prelude)) {
      const part = unscope(p);
      if (familyOf(part, cfg.families) && !excluded(part)) remaining.push(`${f.path}: ${p}`);
    }
  }
}
check("no family selector left behind", remaining.length === 0, remaining.join("\n    "));

// 5. no declaration lost from the preferred sheet. Dropping the LEGACY copy is
//    the point of the move; dropping a property the surviving copy never had is
//    a silent visual change, so the two are separated and both are printed.
const declsOf = (node) => {
  const out = new Map();
  for (const c of node.children) {
    if (c.type !== "statement") continue;
    const m = c.text.match(/^\s*([-\w]+)\s*:\s*([\s\S]*)$/);
    if (m) out.set(m[1], m[2].replace(/\s+/g, " ").trim());
  }
  return out;
};
const propsOf = (node) => [...declsOf(node).keys()];

const emittedProps = new Map();
for (const w of emitted.values()) {
  for (const sel of w.allParts) {
    const k = `${w.chain.join(" && ")}||${sel}`;
    if (!emittedProps.has(k)) emittedProps.set(k, new Set());
    for (const pr of propsOf(w.node)) emittedProps.get(k).add(pr);
  }
}
const emittedDecls = new Map();
for (const w of emitted.values()) {
  for (const sel of w.allParts) {
    const k = `${w.chain.join(" && ")}||${sel}`;
    if (!emittedDecls.has(k)) emittedDecls.set(k, new Map());
    for (const [pr, v] of declsOf(w.node)) emittedDecls.get(k).set(pr, v);
  }
}
const lostDeclarations = [];
const forkDeltas = [];
const valueDeltas = [];
for (const d of dropped) {
  const have = emittedProps.get(d.key) ?? new Set();
  const kept = emittedDecls.get(d.key) ?? new Map();
  const missing = propsOf(d.node).filter((pr) => !have.has(pr));
  if (missing.length) {
    const line = `${d.key.replace("||", " :: ")} — dropped copy had {${missing.join(", ")}}, kept copy does not`;
    if (d.source === prefer) lostDeclarations.push(line);
    else forkDeltas.push(line);
  }
  for (const [pr, v] of declsOf(d.node)) {
    const k = kept.get(pr);
    if (k !== undefined && k !== v) {
      valueDeltas.push(`${d.key.replace("||", " :: ")}\n       ${pr}: ${v}  ->  ${k}`);
    }
  }
}
check("no declaration lost from the kept sheet", lostDeclarations.length === 0, lostDeclarations.join("\n       "));

/* ---------------------------------------------------------------- report */

console.log(`families : ${cfg.families.join(" ")}`);
console.log(`sources  : ${cfg.sources.map((s) => s.path).join(", ")}`);
console.log(`prefer   : ${prefer}`);
console.log(`dest     : ${destPath}`);
console.log(`\nmoved ${emitted.size} rules under ${chains.size} wrapper(s):`);
for (const { chain, rules } of ordered) {
  console.log(`  ${chain.length ? chain.join(" > ") : "(top level)"} — ${rules.length} rules`);
}
if (valueDeltas.length) {
  console.log(`\nvalue deltas (${valueDeltas.length}) — the dying copy said one thing, the kept copy says`);
  console.log("another. Every one of these renders differently. Look at the screen:");
  for (const d of valueDeltas) console.log("  " + d);
}
if (forkDeltas.length) {
  console.log("\nfork deltas — the dying copy declared something the kept copy does not.");
  console.log("Each is a deliberate visual change; check it on screen:");
  for (const d of forkDeltas) console.log("  " + d);
}
if (reaches.length) {
  console.log("\ncross-family reach — a moved rule names a class outside its family.");
  console.log("Fine for a ui/ primitive; check any unmigrated family here:");
  for (const r of [...new Set(reaches)]) console.log("  " + r);
}
if (problems.length) {
  console.log("\nsplits:");
  for (const p of problems) console.log("  " + p);
}
const forkedKeys = new Set(dropped.map((d) => d.key));
const singles = [...emitted.values()].filter((w) => !w.allParts.some((sel) => forkedKeys.has(`${w.chain.join(" && ")}||${sel}`)));
console.log(`\n${emitted.size - singles.length} of ${emitted.size} moved rules were FORKED (the duplication this removes).`);
console.log(`${singles.length} existed in one sheet only and move to keep the family whole:`);
for (const w of singles) console.log(`  ${w.sourcePath}:${w.line} ${w.chain.length ? "@ " + w.chain.join(" > ") + " " : ""}${w.allParts.join(", ")}`);

console.log("\nassertions:");
for (const r of results) {
  console.log(`  ${r.ok ? "ok  " : "FAIL"} ${r.name}${r.detail ? `\n       ${r.detail}` : ""}`);
}

if (process.exitCode) {
  console.log("\nrefusing to write: an assertion failed.");
  process.exit(1);
}

if (WRITE) {
  for (const f of files.values()) writeFileSync(f.path, applyCuts(f));
  writeFileSync(destPath, destAfter);
  console.log("\nwritten.");
} else {
  console.log("\ndry run — pass --write to apply. Destination addition:\n");
  console.log(out.split("\n").map((l) => "  | " + l).join("\n"));
}
