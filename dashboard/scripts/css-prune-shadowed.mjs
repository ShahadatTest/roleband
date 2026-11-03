#!/usr/bin/env node
/* css-prune-shadowed — delete rules that a later rule in the SAME file has
 * already fully overridden.
 *
 * Consolidating two sheets into one produces this: one pass moves the COLOUR
 * half of a rule into the co-located file, a later pass moves the whole rule in
 * after it. Both sit in one file, the later one wins every property, and the
 * earlier one is dead text that still reads like a decision.
 *
 * The proof is specificity-free, which is what makes it safe: two rules with the
 * SAME selector under the SAME at-rule scope have the same specificity by
 * construction, so source order alone decides, and any property the later rule
 * sets — directly, or through a shorthand that subsumes it — is a property the
 * earlier rule cannot deliver. A rule all of whose declarations are dead is
 * itself dead.
 *
 * Values are NOT required to match. A rule that only restates the same value is
 * noise; a rule whose value DIFFERS from the winner is a latent bug — someone
 * wrote two answers and the file's order picked one. Both are removed, and the
 * second kind is printed, because that is a decision someone should see.
 *
 * Usage: node scripts/css-prune-shadowed.mjs <file.css> [--write]
 */
import { readFileSync, writeFileSync } from "node:fs";
import { parse, walk, selectorParts } from "./css-span-parser.mjs";

const [file, ...flags] = process.argv.slice(2);
const WRITE = flags.includes("--write");
if (!file) { console.error("usage: css-prune-shadowed.mjs <file.css> [--write]"); process.exit(2); }

const src = readFileSync(file, "utf8");

/** Longhands a shorthand resets. Only the ones these sheets actually use. */
const SUBSUMES = {
  animation: ["animation-name", "animation-duration", "animation-timing-function", "animation-delay", "animation-iteration-count", "animation-direction", "animation-fill-mode", "animation-play-state"],
  background: ["background-color", "background-image", "background-repeat", "background-position", "background-size", "background-attachment", "background-origin", "background-clip"],
  border: ["border-color", "border-width", "border-style", "border-top", "border-right", "border-bottom", "border-left"],
  "border-radius": [],
  margin: ["margin-top", "margin-right", "margin-bottom", "margin-left"],
  padding: ["padding-top", "padding-right", "padding-bottom", "padding-left"],
  font: ["font-size", "font-weight", "font-family", "font-style", "line-height"],
  transition: ["transition-property", "transition-duration", "transition-timing-function", "transition-delay"],
  flex: ["flex-grow", "flex-shrink", "flex-basis"],
  inset: ["top", "right", "bottom", "left"],
};
const killers = (prop) =>
  new Set([prop, ...Object.entries(SUBSUMES).filter(([, hs]) => hs.includes(prop)).map(([s]) => s)]);

function declsOf(node) {
  const out = [];
  for (const c of node.children) {
    if (c.type !== "statement") continue;
    const m = c.text.match(/^\s*([-\w]+)\s*:\s*([\s\S]*)$/);
    if (m) out.push([m[1], m[2].replace(/\s+/g, " ").trim()]);
  }
  return out;
}

const rules = [];
for (const { node, ancestors } of walk(parse(src))) {
  if (node.type !== "rule") continue;
  if (ancestors.some((a) => a.type === "rule")) continue; // nested rules keep their parent
  const scope = ancestors.filter((a) => a.type === "atrule").map((a) => a.prelude).join(" && ");
  rules.push({
    node,
    scope,
    parts: selectorParts(node.prelude).map((p) => p.replace(/\s+/g, " ").trim()),
    decls: declsOf(node),
    line: src.slice(0, node.start).split("\n").length,
  });
}

/* A rule is dead when EVERY selector it carries is fully shadowed later. A
 * multi-part rule that is shadowed for only some of its parts stays: dropping it
 * would unstyle the others. */
const doomed = [];
const conflicts = [];
for (let i = 0; i < rules.length; i++) {
  const r = rules[i];
  if (!r.decls.length) continue;
  const later = rules.slice(i + 1).filter((o) => o.scope === r.scope);
  const shadowedFor = (part) => {
    const after = later.filter((o) => o.parts.includes(part));
    return r.decls.every(([p, v]) => {
      const k = killers(p);
      const hit = after.find((o) => o.decls.some(([q]) => k.has(q)));
      if (!hit) return false;
      const same = hit.decls.find(([q]) => q === p);
      if (same && same[1] !== v) {
        conflicts.push(`${file}:${r.line} ${part} { ${p}: ${v} }  is overruled by :${hit.line} { ${p}: ${same[1]} }`);
      }
      return true;
    });
  };
  if (r.parts.every(shadowedFor)) doomed.push(r);
}

console.log(`${file}: ${rules.length} top-level rules, ${doomed.length} fully shadowed by a later rule\n`);
for (const d of doomed) {
  console.log(`  :${d.line}  ${d.scope ? d.scope + " " : ""}${d.parts.join(", ")} { ${d.decls.map(([p, v]) => `${p}: ${v}`).join("; ")} }`);
}
if (conflicts.length) {
  console.log(`\n${conflicts.length} of those declarations did not merely repeat the winner — they DISAGREED with it.`);
  console.log("The file's order has been silently picking one. Each is a decision someone should see:");
  for (const c of [...new Set(conflicts)]) console.log("  " + c);
}

if (WRITE && doomed.length) {
  let text = src;
  for (const d of [...doomed].sort((a, b) => b.node.start - a.node.start)) {
    let from = d.node.start, to = d.node.end;
    while (to < text.length && (text[to] === " " || text[to] === "\t")) to++;
    if (text[to] === "\n") to++;
    const lineStart = text.lastIndexOf("\n", from - 1) + 1;
    if (text.slice(lineStart, from).trim() === "") from = lineStart;
    text = text.slice(0, from) + text.slice(to);
  }
  writeFileSync(file, text.replace(/\n{4,}/g, "\n\n\n"));
  console.log("\nwritten.");
} else if (!WRITE) {
  console.log("\ndry run — pass --write to apply.");
}
