/* Canonical parsed catalog and semantic contracts. Shared by compiler,
 * diagnostics, source fingerprints and the review export. */
import { parse } from "@fluent/syntax";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
export class CopyError extends Error {}
export const camel = (id) => id.replace(/[-.]([a-z0-9])/g, (_, c) => c.toUpperCase());
const lit = (s) => JSON.stringify(s);
const MAX_VARIANTS = 4096;
export function combinations(a,b) {
  if (a.length*b.length > MAX_VARIANTS) throw new CopyError(`branch combinations exceed ${MAX_VARIANTS}; split the message`);
  return a.flatMap(x=>b.map(y=>[x,y]));
}

/** `# kind=label width=148px note="Keep it verbatim"` -> { kind, width, note }. */
export function metadata(comment) {
  const meta = {};
  for (const m of (comment ?? "").matchAll(/([a-z-]+)=("([^"]*)"|\S+)/g)) meta[m[1]] = m[3] ?? m[2];
  return meta;
}

/** Parse every .ftl of one locale; Junk is an error, not a dropped message. */
export function readLocale(root, locale) {
  const dir = join(root, locale);
  const files = existsSync(dir) ? readdirSync(dir).filter((f) => f.endsWith(".ftl")).sort() : [];
  const terms = new Map();
  const seen = new Set();
  const messages = []; // { id, file, pattern, comment, meta, src, node, eager }
  const eager = new Set(); // files whose resource comment says `eager`
  const keyed = new Set(); // files whose resource comment says `keyed`
  const fail = (file, src, node, msg) => {
    const line = node?.span ? src.slice(0, node.span.start).split("\n").length : "?";
    throw new CopyError(`${file}:${line}: ${msg}`);
  };
  for (const file of files) {
    const src = readFileSync(join(dir, file), "utf8");
    const ast = parse(src, { withSpans: true });
    for (const e of ast.body) {
      const where = `${locale}/${file}`;
      if (e.type === "Junk") fail(where, src, e, e.annotations.map((a) => `${a.code} ${a.message}`).join("; "));
      if (e.type === "ResourceComment" && /^eager\b/m.test(e.content)) eager.add(where);
      if (e.type === "ResourceComment" && /^keyed\b/m.test(e.content)) keyed.add(where);
      if (e.type === "Term") {
        if (terms.has(e.id.name)) fail(where, src, e, `term -${e.id.name} defined twice`);
        terms.set(e.id.name, { node: e, file: where, src });
      }
      if (e.type === "Message") {
        const comment = e.comment?.content ?? "";
        const at = { file: where, src, comment, meta: metadata(comment), eager: eager.has(where) };
        if (e.value) messages.push({ id: e.id.name, pattern: e.value, node: e, ...at });
        for (const a of e.attributes) messages.push({ id: `${e.id.name}.${a.id.name}`, pattern: a.value, node: a, ...at });
      }
    }
  }
  for (const msg of messages) {
    if (seen.has(msg.id)) fail(msg.file, msg.src, msg.node, `${msg.id} defined twice`);
    seen.add(msg.id);
    msg.terms = terms;
  }
  return { files, terms, messages, keyed };
}


export const pluralSelector = (x) => x.variants.some((v) => v.key.type === "NumberLiteral" ||
  ["zero", "one", "two", "few", "many"].includes(v.key.name));

export function contract(pattern) {
  const display = new Set(), variables = new Set(), selectors = new Map(), terms = new Set();
  function walk(x, role = "display") {
    if (!x || typeof x !== "object") return;
    if (x.type === "VariableReference") { variables.add(x.id.name); if (role === "display") display.add(x.id.name); return; }
    if (x.type === "TermReference") terms.add(x.id.name);
    if (x.type === "SelectExpression") {
      walk(x.selector, "selector");
      if (x.selector.type === "VariableReference") selectors.set(x.selector.id.name, {
        numeric: pluralSelector(x), keys: x.variants.map((v) => v.key.name ?? v.key.value),
        default: x.variants.find((v) => v.default)?.key.name ?? x.variants.find((v) => v.default)?.key.value,
      });
      x.variants.forEach((v) => walk(v.value)); return;
    }
    for (const [k, v] of Object.entries(x)) if (k !== "span") {
      if (Array.isArray(v)) v.forEach((z) => walk(z, role)); else if (typeof v === "object") walk(v, role);
    }
  }
  walk(pattern);
  return { display, variables, selectors, terms };
}
// Display obligations for each semantic branch. Plural categories can vary
// by grammar; explicit number cases and string choices retain their meaning.
function displayed(pattern, choices) {
  const result = new Set();
  function walk(x) {
    if (!x || typeof x !== "object") return;
    if (x.type === "VariableReference") { result.add(x.id.name); return; }
    if (x.type === "SelectExpression") {
      const name=x.selector.type === "VariableReference" ? x.selector.id.name : null;
      const selected=name && choices[name] !== undefined
        ? [x.variants.find(v => String(v.key.name ?? v.key.value) === String(choices[name])) ?? x.variants.find(v=>v.default)] : x.variants;
      selected.forEach(v=>walk(v.value));return;
    }
    for (const [k,v] of Object.entries(x)) if (k !== "span") {
      if (Array.isArray(v)) v.forEach(walk);else if (typeof v === "object")walk(v);
    }
  }
  walk(pattern);return result;
}
export function parity(english, translated) {
  const want = contract(english.pattern), have = contract(translated.pattern), errors = [];
  for (const v of have.variables) if (!want.variables.has(v)) errors.push(`uses $${v}, which English does not pass`);
  for (const v of want.display) if (!have.display.has(v)) errors.push(`omits displayed $${v}`);
  let cases=[{}];
  for (const [v, selector] of want.selectors) {
    const own = have.selectors.get(v);
    if (selector.numeric) {
      const exact=selector.keys.filter(k=>/^[-0-9]/.test(k));
      if(exact.some(k=>!own?.keys.includes(k)))errors.push(`omits exact numeric cases for $${v}`);
      if(exact.length)cases=combinations(cases,[...exact,"__other__"]).map(([a,k])=>({...a,[v]:k}));
      continue;
    }
    if (!own || own.numeric || selector.keys.some((k) => !own.keys.includes(k)) || own.default !== selector.default)
      errors.push(`changes semantic branches for $${v}`);
    cases=combinations(cases,selector.keys).map(([a,k])=>({...a,[v]:k}));
  }
  for(const choices of cases) for(const v of displayed(english.pattern,choices))
    if(!displayed(translated.pattern,choices).has(v)&&!errors.includes(`omits displayed $${v}`))
      errors.push(`omits displayed $${v} in ${JSON.stringify(choices)}`);
  return [...new Set(errors)];
}
export function manifestAt(root) {
  const manifest = JSON.parse(readFileSync(join(root, "locales.json"), "utf8"));
  const codes = new Set();
  for (const l of manifest.locales ?? []) {
    if (codes.has(l.code)) throw new CopyError(`duplicate locale ${l.code}`);
    codes.add(l.code);
    if (!["complete", "beta", "pseudo"].includes(l.status) || (l.dir && !["ltr", "rtl"].includes(l.dir)))
      throw new CopyError(`invalid locale declaration ${l.code}`);
    if (l.status !== "pseudo") {
      try { if (Intl.getCanonicalLocales(l.code)[0] !== l.code) throw new Error(); }
      catch { throw new CopyError(`noncanonical locale ${l.code}`); }
    } else if (!["en-XA", "keys"].includes(l.code)) throw new CopyError(`unknown pseudo locale ${l.code}`);
  }
  if (!codes.has("en")) throw new CopyError("English locale is required");
  function walk(code, stack = []) {
    if (stack.includes(code)) throw new CopyError(`fallback cycle: ${[...stack, code].join(" -> ")}`);
    const l = manifest.locales.find((x) => x.code === code);
    if (!l) throw new CopyError(`unknown fallback ${code}`);
    for (const f of l.fallback ?? []) walk(f, [...stack, code]);
  }
  manifest.locales.forEach((l) => {
    for(const f of l.fallback ?? []) if (manifest.locales.find(x=>x.code === f)?.status === "pseudo") throw new CopyError(`pseudo fallback ${f}`);
    walk(l.code);
  });
  for (const tag of manifest.regions ?? []) {
    try { if (Intl.getCanonicalLocales(tag)[0] !== tag) throw new Error(); }
    catch { throw new CopyError(`invalid region ${tag}`); }
  }
  return manifest;
}
// Semantic JSON excludes parser spans, comments and whitespace reflow.
export function semantic(x) {
  if (Array.isArray(x)) return x.map(semantic);
  if (!x || typeof x !== "object") return x;
  return Object.fromEntries(Object.entries(x).filter(([k]) => !["span", "comment"].includes(k)).map(([k,v]) =>
    [k, k === "value" && typeof v === "string" ? v.replace(/\s+/g, " ") : semantic(v)]));
}
export function dependencies(msg) {
  const found = new Map();
  function visit(id, stack) {
    if (stack.includes(id)) throw new CopyError(`${msg.file}: term cycle ${[...stack,id].join(" -> ")}`);
    const term = msg.terms?.get(id);
    if (!term) throw new CopyError(`${msg.file}: unknown term -${id}`);
    found.set(id, semantic(term.node));
    for (const next of contract(term.node).terms) visit(next, [...stack,id]);
  }
  for (const id of contract(msg.pattern).terms) visit(id, []);
  return Object.fromEntries([...found].sort(([a],[b]) => a.localeCompare(b)));
}
// Enumerate complete rendered branches, respecting term literal arguments.
export function branches(pattern, terms, scope = {}, stack = []) {
  const cross = (a,b) => combinations(a,b).map(([x,y])=>x+y);
  const expr = (x) => {
    if (x.type === "VariableReference") return [scope[x.id.name] ?? `{$${x.id.name}}`];
    if (x.type === "StringLiteral") return [x.parse().value];
    if (x.type === "NumberLiteral") return [x.value];
    if (x.type === "Placeable") return expr(x.expression);
    if (x.type === "TermReference") {
      if (stack.includes(x.id.name)) throw new CopyError(`term cycle -${x.id.name}`);
      const t = terms.get(x.id.name); if (!t) throw new CopyError(`unknown term -${x.id.name}`);
      const args = Object.fromEntries((x.arguments?.named ?? []).map((n) => [n.name.name, expr(n.value)[0]]));
      const p = x.attribute ? t.node.attributes.find((a) => a.id.name === x.attribute.name)?.value : t.node.value;
      return branches(p, terms, args, [...stack,x.id.name]);
    }
    if (x.type === "SelectExpression") {
      const value = x.selector.type === "VariableReference" ? scope[x.selector.id.name] : expr(x.selector)[0];
      const chosen = value === undefined ? x.variants : [x.variants.find((v) => String(v.key.name ?? v.key.value) === String(value)) ?? x.variants.find((v) => v.default)];
      return chosen.flatMap((v) => branches(v.value,terms,scope,stack));
    }
    return [""];
  };
  return pattern.elements.reduce((out,el) => cross(out,el.type === "TextElement" ? [el.value] : expr(el.expression)),[""]);
}
