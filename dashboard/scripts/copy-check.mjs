// The copy linter (docs/copy.md, section 7).
//
//   npm run copy:check            report; exit 1 on any blocking problem
//   npm run copy:check -- --freeze  write today's literal violations and habit
//                                 counts as the baselines (first freeze, or after
//                                 a migration LOWERED them; the test refuses a rise)
//
// Two subjects:
// 1. The catalog, every locale: vocabulary, mechanics, the rules of each kind,
//    errors that end with a listed next step, two keys saying one thing,
//    pinned wording, and for translations: the same terms as English, one form
//    of address, every plural category the language needs, and the English
//    each was translated from (`<locale>/translated-from.json`): a translation
//    whose English changed since is stale.
//
//   npm run copy:check -- --translated es [id ...]
//                                 record the English a translation was made
//                                 from: every translation not yet recorded, and
//                                 each named id (re-translated after its English
//                                 changed); drop ids with no translation left
// 2. Every literal not yet migrated (the AST extractor): banned and retired
//    words and mechanics, against a NAMED baseline that only shrinks.
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import yaml from "js-yaml";
import { flatten,build } from "./gen-copy.mjs";
import { readLocale, manifestAt, branches, dependencies, semantic, pluralSelector, parity } from "./copy/catalog.mjs";
import { createRequire } from "node:module";
import { relative, sep } from "node:path";
import { extractFile, extractSource, extractStrings, fileHabits, sourceFiles } from "./copy/extract.mjs";

const ts = createRequire(import.meta.url)("typescript");

const DASH = join(dirname(fileURLToPath(import.meta.url)), "..");
export const SRC = join(DASH, "src");
export const COPY = join(SRC, "copy");
export const BASELINE = join(SRC, "test", "copy-check-baseline.json");
// Every literal the code held before its text moved to the catalog, reduced to
// letters and digits. A `wording=as-is` message must be made of these, which is
// what proves a move kept the text unchanged. Built once by asFound() from
// commit b8f19727, the tree before the codemod; never rebuild it from a later
// tree, which does not hold the text it vouches for.
export const AS_FOUND = join(SRC, "test", "copy-as-found.json");

/** Letters and digits only, placeholders and entities dropped. */
const skeleton = (t) => t.replace(/\{[^}]*\}/g, " ").replace(/&[a-z]+;/g, " ").replace(/[^\p{L}\p{N}]+/gu, "");

/** Today's literal skeletons, the as-found snapshot's content. A string the
 *  code BUILDS (a template, a `+` chain, a ternary choosing words) is recorded
 *  as each sentence it can render, with its values dropped, since that is what
 *  a message moved from it says. */
export function asFound(src = SRC, backendRoot = join(src, "..", "..", "backend", "tracker")) {
  const out = new Set();
  const lit = (n) => ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n);
  const isPlus = (n) => ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.PlusToken;
  const stringy = (n) => lit(n) || ts.isTemplateExpression(n) || isPlus(n) || (ts.isParenthesizedExpression(n) && stringy(n.expression)) || (ts.isConditionalExpression(n) && stringy(n.whenTrue) && stringy(n.whenFalse));
  // Every text a string expression can render, each ternary choosing on its own
  // (capped: a sentence with more choices than this is not one a message holds).
  const cross = (a, b) => a.flatMap((x) => b.map((y) => x + y)).slice(0, 256);
  const expand = (n) => {
    if (lit(n)) return [n.text];
    if (ts.isParenthesizedExpression(n)) return expand(n.expression);
    if (ts.isTemplateExpression(n)) return n.templateSpans.reduce((acc, sp) => cross(cross(acc, expand(sp.expression)), [sp.literal.text]), [n.head.text]);
    if (isPlus(n)) return cross(expand(n.left), expand(n.right));
    if (ts.isConditionalExpression(n) && stringy(n.whenTrue) && stringy(n.whenFalse)) return [...expand(n.whenTrue), ...expand(n.whenFalse)];
    return [" "];
  };
  // A string expression inside another one is part of that one's sentences.
  const contains = (p, n) => isPlus(p) || ts.isTemplateSpan(p) || (ts.isParenthesizedExpression(p) && stringy(p)) || (ts.isConditionalExpression(p) && p.condition !== n && stringy(p));
  for (const f of sourceFiles(src)) {
    const rel = relative(src, f).split(sep).join("/");
    if (rel.startsWith("copy/")) continue;
    const { sf, strings } = extractFile(rel, readFileSync(f, "utf8"));
    for (const s of strings) out.add(skeleton(s.text));
    (function visit(n) {
      if (!lit(n) && stringy(n) && !(n.parent && contains(n.parent, n))) for (const t of expand(n)) out.add(skeleton(t));
      // A JSX sentence: its text with each string-valued child's choices, other children dropped.
      if (ts.isJsxElement(n) || ts.isJsxFragment(n)) {
        const pieces = n.children.map((k) => {
          if (ts.isJsxText(k)) return [k.getFullText(sf)];
          if (ts.isJsxExpression(k) && k.expression && stringy(k.expression)) return expand(k.expression);
          return [" "];
        });
        for (const t of pieces.reduce((acc, p) => cross(acc, p), [""])) out.add(skeleton(t));
      }
      ts.forEachChild(n, visit);
    })(sf);
  }
  // Words, not identifiers: a string with a space or a capital first letter.
  for (const t of pythonStrings(backendRoot)) if (/\s|^[A-Z]/.test(t.trim()) && !/^(SELECT|INSERT|UPDATE|DELETE|WITH)\b/.test(t.trim())) out.add(skeleton(t));
  out.delete("");
  return [...out].sort();
}

/** The server's own English as of the same commit: every Python string literal
 *  in backend/tracker (f-string fields dropped, implicit concatenation joined),
 *  so a message moved from a server label or a notification sentence is proven
 *  verbatim the same way. Docstrings are skipped. */
export function pythonStrings(root) {
  if (!existsSync(root)) return [];
  const out = [];
  const files = [];
  (function walk(d) {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      const p = join(d, e.name);
      if (e.isDirectory()) { if (e.name !== "__pycache__") walk(p); }
      else if (e.name.endsWith(".py")) files.push(p);
    }
  })(root);
  const LIT = /(?<![\w"'])[fFrRbBuU]{0,2}("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')/g;
  for (const f of files) {
    const text = readFileSync(f, "utf8").replace(/"""[\s\S]*?"""|'''[\s\S]*?'''/g, " ").replace(/^\s*#.*$/gm, "");
    // Implicit concatenation ("a " "b") is one string: join adjacent literals.
    let run = "";
    let last = -1;
    for (const m of text.matchAll(LIT)) {
      const body = m[1].slice(1, -1).replace(/\{[^{}]*\}/g, " ");
      const between = last < 0 ? "" : text.slice(last, m.index);
      if (last >= 0 && /^[\s()]*$/.test(between)) run += body;
      else {
        if (run) out.push(run);
        run = body;
      }
      last = m.index + m[0].length;
    }
    if (run) out.push(run);
  }
  return out;
}

/** A message's whole shape: every variant's text, placeholders by position. */
function shape(pattern) {
  return pattern.elements
    .map((el) => {
      if (el.type === "TextElement") return el.value;
      const x = el.expression;
      if (x?.type === "SelectExpression") return `{${x.variants.map((v) => `[${v.key.name ?? v.key.value}]${shape(v.value)}`).join("|")}}`;
      if (x?.type === "StringLiteral") return x.parse().value;
      if (x?.type === "TermReference") return `{-${x.id.name}}`;
      return "{}";
    })
    .join("")
    .replace(/\s+/g, " ")
    .trim();
}

/** The text runs of a message, every variant's, each on its own. */
function textRuns(pattern) {
  const out = [];
  const walk = (p) => {
    for (const el of p.elements) {
      if (el.type === "TextElement") out.push(el.value);
      else if (el.expression?.type === "SelectExpression") for (const v of el.expression.variants) walk(v.value);
      else if (el.expression?.type === "StringLiteral") out.push(el.expression.parse().value);
    }
  };
  walk(pattern);
  return out;
}

/** The folder a count is kept for: a feature or pattern family, else a top-level directory. */
export const area = (file) => {
  const p = file.split("/");
  if ((p[0] === "features" || p[0] === "patterns") && p.length > 2) return `${p[0]}/${p[1]}`;
  return p.length > 1 ? p[0] : "(root)";
};

const escape = (w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function glossary(locale, root = COPY) {
  const path = join(root, locale, "glossary.yaml");
  return existsSync(path) ? yaml.load(readFileSync(path, "utf8")) ?? {} : {};
}

/** A word and its inflections, hyphen or space as a joiner: "scrape" also
 *  matches "scraping", "scraped", "scrapers"; "best match" also "best matches". */
function wordPattern(words, strategy = "inflections") {
  const forms = words.flatMap((w) => {
    if (strategy === "substring") return escape(w);
    const parts = w.split(/\s+/).map(escape);
    const last = parts.pop();
    const stem = last.replace(/e$/, "");
    const tails = `(?:${last}(?:s|es|d|ed|r|rs|er|ers)?|${stem}ing|${stem}ings)`;
    return [[...parts, tails].join("[\\s-]+")];
  });
  return forms.length ? new RegExp(strategy === "substring" ? `(${forms.join("|")})` : `(?<![\\p{L}])(${forms.join("|")})(?![\\p{L}])`, "iu") : null;
}

/** The vocabulary and mechanics problems in one piece of text. */
export function textProblems(text, rules, { withTerms = false } = {}) {
  const problems = [];
  const vocabularyText = (rules.allowed?.phrases ?? []).reduce((t, phrase) => t.split(phrase).join(" "), text);
  const vocab = [...(rules.banned ?? []), ...(rules.retired ?? []), ...(withTerms ? Object.values(rules.terms ?? {}).flatMap((t) => t.never ?? []) : [])];
  const hit = wordPattern(vocab, rules.matching ?? "inflections")?.exec(vocabularyText);
  if (hit) problems.push(["vocabulary", hit[1].toLowerCase()]);
  for (const bad of rules.mechanics?.forbid ?? []) if (text.includes(bad)) problems.push(["mechanics", bad === "—" ? "em-dash" : bad]);
  for (const [long, short] of Object.entries(rules.mechanics?.contractions ?? {})) {
    if (new RegExp(`\\b${escape(long)}\\b`).test(text)) problems.push(["mechanics", `${long} -> ${short}`]);
  }
  for (const word of rules.register?.forbidden ?? []) {
    if (new RegExp(rules.matching === "substring" ? escape(word) : `(?<![\\p{L}])${escape(word)}(?![\\p{L}])`, "iu").test(text)) problems.push(["register", word]);
  }
  return problems;
}

function termRefs(pattern, acc = new Set()) {
  for (const el of pattern.elements) {
    const x = el.expression;
    if (!x) continue;
    if (x.type === "TermReference") acc.add(x.id.name);
    if (x.type === "SelectExpression") {
      if (x.selector.type === "TermReference") acc.add(x.selector.id.name);
      for (const v of x.variants) termRefs(v.value, acc);
    }
  }
  return acc;
}

function pluralSelects(pattern, acc = []) {
  for (const el of pattern.elements) {
    const x = el.expression;
    if (x?.type !== "SelectExpression") continue;
    const keys = x.variants.map((v) => (v.key.type === "NumberLiteral" ? v.key.value : v.key.name));
    if (x.selector.type === "VariableReference" && pluralSelector(x)) acc.push(keys);
    for (const v of x.variants) pluralSelects(v.value, acc);
  }
  return acc;
}

/** Problems in the catalog. `blocking` fails the build; `reports` are for the deck. */
/** The English a message says, as its source with whitespace collapsed: a
    reflow or a comment is no change, a word or a variant is. */
export const legacyHash = (msg) => createHash("sha256").update(msg.src.slice(msg.pattern.span.start, msg.pattern.span.end).replace(/\s+/g, " ").trim()).digest("hex").slice(0,12);
export const sourceHash = (msg) => "v2:" + createHash("sha256").update(JSON.stringify({
  pattern: semantic(msg.pattern), terms: dependencies(msg), kind: msg.meta?.kind ?? null,
})).digest("hex");
/** Explicit migration: only records whose old English still matches qualify.
 * Does not acknowledge stale translations or alter translated wording. */
export function migrateFingerprints(root, locale) {
  const english = new Map(readLocale(root,"en").messages.map((m) => [m.id,m]));
  const from = readFrom(root,locale);
  for (const [id,hash] of Object.entries(from)) {
    if (String(hash).startsWith("v2:")) continue;
    const msg = english.get(id);
    if (!msg || legacyHash(msg) !== hash) throw new Error(`cannot migrate stale ${locale} ${id}`);
    from[id] = sourceHash(msg);
  }
  writeFileSync(fromPath(root,locale),JSON.stringify(from,null,1)+"\n");
}


const fromPath = (root, locale) => join(root, locale, "translated-from.json");
const readFrom = (root, locale) => (existsSync(fromPath(root, locale)) ? JSON.parse(readFileSync(fromPath(root, locale), "utf8")) : {});

/** Record the English each translation of `locale` was made from: every one not
    recorded yet, and each of `ids` (re-translated after its English changed).
    Ids with no translation left are dropped. A stale translation is never recorded
    unless named: naming it says it was checked against the new English. */
export function recordTranslated(root, locale, ids = []) {
  const byId = new Map(readLocale(root, "en").messages.map((m) => [m.id, m]));
  const translated = new Set(readLocale(root, locale).messages.map((m) => m.id).filter((id) => byId.has(id)));
  const unknown = ids.filter((id) => !translated.has(id));
  if (unknown.length) throw new Error(`${locale} does not translate ${unknown.join(", ")}`);
  const from = readFrom(root, locale);
  const recorded = [];
  for (const id of translated) {
    const hash = sourceHash(byId.get(id));
    if (from[id] === hash || (id in from && !ids.includes(id))) continue;
    from[id] = hash;
    recorded.push(id);
  }
  const dropped = Object.keys(from).filter((id) => !translated.has(id));
  for (const id of dropped) delete from[id];
  const sorted = Object.fromEntries(Object.keys(from).sort().map((id) => [id, from[id]]));
  writeFileSync(fromPath(root, locale), JSON.stringify(sorted, null, 1) + "\n");
  return { recorded, dropped };
}

export function checkCatalog(root = COPY, asFoundPath = AS_FOUND, catalogs = new Map()) {
  const blocking = [];
  const reports = [];
  const manifest = manifestAt(root);
  const enRules = glossary("en", root);
  const catalog = (code) => { if (!catalogs.has(code)) catalogs.set(code, readLocale(root, code)); return catalogs.get(code); };
  const en = catalog("en");
  const segmenters = new Map();
  const hashes = new Map(en.messages.map(m => [m.id, sourceHash(m)]));
  // The CLI/deck must enforce the compiler contract even when invoked alone.
  // Build in memory only: no generated files or backend twins are written.
  try { build({root,gen:join(root,'gen'),twin:false,catalogs}); }
  catch(error) { blocking.push(`catalog: structural: ${error.message}`); }
  const quarantinePath=join(root,'translation-quarantine.json');
  const quarantine=existsSync(quarantinePath)?JSON.parse(readFileSync(quarantinePath,'utf8')):{};
  const byId = new Map(en.messages.map((m) => [m.id, m]));
  const kinds = enRules.kinds ?? {};

  function kindProblems(msg, rules, text) {
    const kind = byId.get(msg.id)?.meta.kind;
    const rule = { ...kinds[kind], ...rules.kinds?.[kind] };
    if (!kinds[kind]) return [["no kind", `${kind ?? "missing"}`]];
    if (!rule) return [[`no kind`, `${kind ?? "missing"} (one of ${Object.keys(kinds).join(", ")})`]];
    const out = [];
    // Full-width marks end a Chinese sentence as the ASCII ones end an English one.
    const end = text.trimEnd().slice(-1);
    const stopped = /[.!?…:。！？：]/.test(end);
    if (rule.full_stop === "always" && !stopped) out.push(["kind", `${kind} ends with a full stop`]);
    if (rule.full_stop === "never" && /[.。]/.test(end)) out.push(["kind", `${kind} has no full stop`]);
    const words = text.split(/\s+/).filter(Boolean);
    // A translation's words are the language's own (Chinese has no spaces to count).
    const language = msg.file.split("/")[0];
    if (language !== "en" && !segmenters.has(language)) segmenters.set(language, new Intl.Segmenter(language, { granularity: "word" }));
    const count = language === "en" ? words.length : [...segmenters.get(language).segment(text)].filter((s) => s.isWordLike).length;
    if (rule.max_words && count > rule.max_words) out.push(["kind", `${kind} is at most ${rule.max_words} words`]);
    if (rule.case === "sentence" && msg.file.startsWith("en/")) {
      const proper = new Set(rules.proper_nouns ?? []);
      const shouting = words.slice(1).find((w) => /^\p{Lu}\p{Ll}/u.test(w) && !proper.has(w.replace(/[^\p{L}.]/gu, "")) && !w.startsWith("{"));
      if (shouting) out.push(["kind", `${kind} is sentence case ("${shouting}")`]);
    }
    if (rule.next_step === "required" && byId.get(msg.id)?.meta.next !== "none") {
      const sentences = text.split(/(?<=[.!?])\s+|(?<=[。！？])/).filter(Boolean);
      if (!(rules.next_steps ?? []).includes(sentences.at(-1)?.trim())) out.push(["next-step", `an error ends with a listed next step, or says next=none`]);
    }
    return out;
  }

  const report = (list, where, problems) => {
    for (const [rule, detail] of problems) list.push(`${where}: ${rule}: ${detail}`);
  };

  // English. A message moved as it was found (`wording=as-is`) keeps its wording
  // problems as a worklist, not a build failure: moving text and reviewing its
  // words are separate work. Structure still blocks: a kind, terms, duplicates,
  // pins, parity.
  const seen = new Map();
  let asIs = 0;
  const found = existsSync(asFoundPath) ? JSON.parse(readFileSync(asFoundPath, "utf8")).join("\n") : "";
  // A plural the code built by hand ("role" + "s") shows its plural form only in the catalog.
  const wasThere = (run) => {
    const k = skeleton(run);
    return !k || [k, k.replace(/e?s$/, "")].some((x) => x && found.includes(x));
  };
  for (const msg of en.messages) {
    const where = `${msg.file} ${msg.id}`;
    const wording = branches(msg.pattern, en.terms).flatMap((text) => [...textProblems(text, enRules, { withTerms: true }), ...kindProblems(msg, enRules, text)]);
    if (msg.meta.wording === "as-is") {
      asIs++;
      const fresh = textRuns(msg.pattern).find((run) => !wasThere(run));
      if (fresh !== undefined) blocking.push(`${where}: as-is: "${fresh.trim()}" is not text the code held on 2026-10-09; review its wording and drop wording=as-is`);
      report(blocking, where, wording.filter(([rule]) => rule === "no kind"));
      report(reports, `${where} (as-is)`, wording.filter(([rule]) => rule !== "no kind"));
    } else {
      report(blocking, where, wording);
    }
    // Every variant counts: a select that says "Delete" by default is not the plain "Delete".
    const same = `${msg.file}|${msg.meta.kind}|${shape(msg.pattern)}`;
    if (seen.has(same) && msg.meta["same-as"] !== seen.get(same)) blocking.push(`${msg.file} ${msg.id}: duplicate: says the same as ${seen.get(same)}; merge them or name it with same-as=`);
    else seen.set(same, msg.id);
  }
  const pinnedPath = join(root, "pinned.en.json");
  const pinned = existsSync(pinnedPath) ? JSON.parse(readFileSync(pinnedPath, "utf8")) : {};
  for (const [id, text] of Object.entries(pinned)) {
    const msg = byId.get(id);
    if (!msg) blocking.push(`pinned.en.json: ${id} is not in the catalog`);
    else if (flatten(msg.pattern, en.terms) !== text) blocking.push(`pinned.en.json: ${id} changed; pinned wording moves only with the owner ("${text}")`);
  }
  for (const msg of en.messages) if (msg.meta.kind === "consent" && !(msg.id in pinned)) blocking.push(`${msg.id}: consent wording must be pinned in pinned.en.json`);

  // Other locales
  for (const loc of manifest.locales.filter((l) => l.code !== "en" && l.status !== "pseudo")) {
    const rules = glossary(loc.code, root);
    const cat = catalog(loc.code);
    const target = loc.status === "complete" ? blocking : reports;
    const categories = new Intl.PluralRules(loc.code).resolvedOptions().pluralCategories;
    for (const msg of cat.messages) {
      const where = `${msg.file} ${msg.id}`;
      for (const text of branches(msg.pattern, cat.terms)) {
        report(blocking, where, textProblems(text, rules));
        report(target, where, kindProblems(msg, rules, text));
      }
      const english = byId.get(msg.id);
      if (english) {
        const quarantined=quarantine[loc.code]?.[msg.id]===JSON.stringify(semantic(msg.pattern));
        for (const error of parity(english,msg)) (quarantined?target:blocking).push(`${where}: contract: ${error}; ${quarantined?'English fallback until repaired':'repair required'}`);
        const want = termRefs(english.pattern);
        const have = termRefs(msg.pattern);
        for (const t of want) if (!have.has(t)) blocking.push(`${where}: parity: English uses the term -${t}; a translation uses it too, not a synonym`);
      }
      for (const keys of pluralSelects(msg.pattern)) {
        const missing = categories.filter((c) => !keys.includes(c));
        if (missing.length) target.push(`${where}: plural: ${loc.code} needs ${missing.join(", ")}`);
      }
    }
    // The English each translation was made from (`--translated` records it).
    const from = readFrom(root, loc.code);
    const how = `copy:check -- --translated ${loc.code}`;
    for (const msg of cat.messages) {
      const english = byId.get(msg.id);
      if (!english) continue;
      if (!(msg.id in from)) target.push(`${msg.file} ${msg.id}: untracked: no record of the English it was translated from; ${how}`);
      else if (from[msg.id] !== hashes.get(msg.id)) target.push(`${msg.file} ${msg.id}: stale: its English changed since it was translated; re-translate, then ${how} ${msg.id}`);
    }
    const translated = new Set(cat.messages.map((m) => m.id));
    const gone = Object.keys(from).filter((id) => !translated.has(id) || !byId.has(id)).length;
    if (gone) reports.push(`${loc.code}: translated-from.json records ${gone} messages it no longer translates; ${how}`);
    const missing = en.messages.filter((m) => !(manifest.englishOnly??[]).includes(m.id)&&!cat.messages.some((x) => x.id === m.id)).length;
    if (missing) reports.push(`${loc.code}: ${missing} of ${en.messages.length} messages not translated yet (${loc.status})`);
  }
  if (asIs) reports.push(`en: ${asIs} of ${en.messages.length} messages moved as-is, wording not reviewed yet`);
  const locations = new Map();
  for (const loc of manifest.locales.filter(l=>l.status !== "pseudo")) for (const msg of catalog(loc.code).messages)
    locations.set(`${msg.file} ${msg.id}`, {locale:loc.code,id:msg.id,file:msg.file,line:msg.src.slice(0,msg.node.span.start).split("\n").length});
  const diagnostic = (text,severity) => {
    const match = text.match(/^([^:]+?)(?: \(as-is\))?: ([^:]+): (.*)$/);
    const location = match ? locations.get(match[1]) : null;
    return {...(location ?? {locale:null,id:null,file:null,line:null}),severity,rule:match?.[2] ?? "inventory",detail:match?.[3] ?? text};
  };
  return { blocking, reports, diagnostics:[...blocking.map(t=>diagnostic(t,"blocking")),...reports.map(t=>diagnostic(t,"advisory"))], messages: en.messages.length, asIs };
}

/** Problems in the literals not yet migrated, as `rule|file|text` names. */
function literalProblems(strings) {
  const rules = glossary("en");
  const allowedFiles = new Set(rules.allowed?.files ?? []);
  const found = new Set();
  for (const s of strings) {
    if (allowedFiles.has(s.file) || s.file.startsWith("copy/")) continue;
    // `{expr}` is the code of a placeholder, not copy: "{result.in_scope_changed}" is no word.
    const words = s.text.replace(/\{[^}]*\}/g, "{}");
    for (const [rule, detail] of textProblems(words, rules)) found.add(`${rule}:${detail}|${s.file}|${s.text}`);
  }
  return [...found].sort();
}

/** The counts the ratchet freezes, per folder (`area`), so parallel sessions
 *  moving copy in different folders never touch the same baseline line. */
function countStrings(src, strings, habits = []) {
  const out = {};
  const add = (file, marker, n) => {
    if (!n) return;
    const a = (out[area(file)] ??= {});
    a[marker] = (a[marker] ?? 0) + n;
  };
  for (const s of strings) {
    if (s.file.startsWith("copy/")) continue;
    add(s.file, "literal-copy", 1);
    if (s.moduleScope) add(s.file, "module-scope-copy", 1);
  }
  for (const [file, found] of fileHabits(src)) for (const [k, n] of Object.entries(found)) add(file, k, n);
  for (const h of habits) add(h.file, h.habit, 1);
  return Object.fromEntries(Object.entries(out).sort(([a], [b]) => a.localeCompare(b)));
}

export function checkLiterals(src = SRC) {
  return literalProblems(extractStrings(src));
}

export function counts(src = SRC) {
  const { strings, habits } = extractSource(src);
  return countStrings(src, strings, habits);
}

/** One source inventory per check, so separate invocations always read fresh files. */
export function checkSource(src = SRC) {
  const { strings, habits } = extractSource(src);
  return { literals: literalProblems(strings), counts: countStrings(src, strings, habits), habits };
}

/** The per-folder counts summed. */
export const totals = (byArea) => {
  const t = {};
  for (const c of Object.values(byArea)) for (const [k, n] of Object.entries(c)) t[k] = (t[k] ?? 0) + n;
  return t;
};

export function ratchetProblems(now, literals, base) {
  const problems = literals.filter((l) => !base.literals.includes(l));
  for (const [area, markers] of Object.entries(now)) for (const [marker,n] of Object.entries(markers))
    if (n > (base.counts[area]?.[marker] ?? 0)) problems.push(`${area} ${marker}: ${n} > ${base.counts[area]?.[marker] ?? 0}`);
  return problems;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const at = process.argv.indexOf("--translated");
  if (at !== -1) {
    const [locale, ...ids] = process.argv.slice(at + 1).filter((x) => !x.startsWith("--"));
    if (!locale) throw new Error("usage: copy:check -- --translated <locale> [id ...]");
    const { recorded, dropped } = recordTranslated(COPY, locale, ids);
    console.log(`${locale}: recorded ${recorded.length} translations${dropped.length ? `, dropped ${dropped.length}` : ""}`);
  }
  const catalog = checkCatalog();
  const { literals, counts: now } = checkSource();
  const prior = existsSync(BASELINE) ? JSON.parse(readFileSync(BASELINE,"utf8")) : { counts: {}, literals: [] };
  const rises = ratchetProblems(now, literals, prior);
  if (process.argv.includes("--freeze") && catalog.blocking.length) throw new Error("refusing to freeze a catalog with blocking diagnostics");
  if (process.argv.includes("--freeze") && rises.length) throw new Error(`refusing to raise copy baselines: ${rises.join("; ")}`);
  if (process.argv.includes("--freeze")) {
    writeFileSync(BASELINE, JSON.stringify({ counts: now, literals }, null, 2) + "\n");
    console.log(`froze ${literals.length} literal problems and ${Object.keys(now).length} counts -> ${BASELINE}`);
  }
  const base = existsSync(BASELINE) ? JSON.parse(readFileSync(BASELINE, "utf8")) : { counts: {}, literals: [] };
  const fresh = literals.filter((l) => !base.literals.includes(l));
  for (const line of catalog.reports) console.log(`report  ${line}`);
  for (const line of catalog.blocking) console.log(`BLOCK   ${line}`);
  for (const line of fresh) console.log(`NEW     ${line}`);
  console.log(`copy:check ${catalog.messages} messages (${catalog.asIs} as-is); ${catalog.blocking.length} blocking; ${fresh.length} new literal problems (${literals.length} known); totals ${JSON.stringify(totals(now))}`);
  for (const line of rises) console.error(`RATCHET ${line}`);
  if (catalog.blocking.length || fresh.length || rises.length) process.exit(1);
}
