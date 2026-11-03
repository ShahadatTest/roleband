// Moves user-visible text from the source into the catalog, word for word
// (docs/copy.md, section 3). Moving and rewording are separate work: the
// move keeps text as it is; a separate copy pass rewords it. So every
// message written here says exactly what the code said,
// carries `wording=as-is`, and English behaviour is unchanged by construction:
// a literal becomes a call that returns the same string.
//
//   node scripts/copy/codemod.mjs [--getters] [--exclude a.tsx,b.ts] [--dry] <src-relative prefix>...
//
// `--getters` also moves module-scope object properties, as getters.
//
// What it moves (the strings scripts/copy/extract.mjs reports, nothing else):
// - JSX text. Alone in its element it becomes `{fn()}`; text interleaved with
//   `{expr}` or inline elements becomes ONE message through <Msg>, each
//   expression or element a placeholder rendered exactly as before.
// - String and template literals in function scope: attributes that are copy,
//   props, returns, ternary branches, call arguments. A template's placeholders
//   are passed as String(expr), which is what a template literal does.
// - `n === 1 ? "role" : "roles"` and `role${n === 1 ? "" : "s"}` become one
//   plural message (English plural rules say "one" for exactly 1).
// What it leaves for a person: module scope (needs getters), a string the same
// file also compares, code-like props, comments inside a sentence, unknown
// entities, text with braces or line breaks.
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { readLocale } from "../gen-copy.mjs";
import { extractFile, sourceFiles } from "./extract.mjs";

const ts = createRequire(import.meta.url)("typescript");
const DASH = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SRC = join(DASH, "src");
const COPY = join(SRC, "copy");

/** Which catalog file a source file's messages go to: longest prefix wins. */
export const SURFACES = [
  ["features/scope/welcome/", "welcome"],
  ["features/opportunities/", "radar"],
  ["features/job-detail/", "role"],
  ["features/saved/", "saved"],
  ["features/compare/", "compare"],
  ["features/notifications/", "notifications"],
  ["features/scope/", "profile"],
  ["features/companies/", "companies"],
  ["features/company-profiles/", "profiles"],
  ["features/settings/", "settings"],
  ["features/intelligence/", "ai"],
  ["features/review/", "duplicates"],
  ["features/statistics/", "insights"],
  ["features/sync/", "scan"],
  ["patterns/jobs/", "jobs"],
  ["patterns/", "shared"],
  ["ui/", "shared"],
  ["shell/KeyboardShortcuts", "shortcuts"], // lazy: the sheet loads on "?"
  ["routes/ReviewRoute", "duplicates"],
  ["routes/SettingsRoute", "settings"],
];
const surfaceOf = (rel) => SURFACES.find(([p]) => rel.startsWith(p))?.[1] ?? null;

// Attributes whose string is shown or read aloud; anything else is left alone.
const COPY_ATTR = /^(aria-label|aria-valuetext|aria-roledescription|ariaLabel|alt|title|placeholder|label|[a-z]*(Label|Title|Text|Hint|Note|Message|Caption|Description|Placeholder|Tip|Heading|Summary|Intro|Kicker)|tip|empty|note|intro|summary|caption|hint|description|kicker|heading|emptyText|line|fact|facts|figure|subtitle|eyebrow|legend|loading|failed)$/;
// Object properties whose string is data, not copy, even when it reads as words.
const CODE_PROP = /^(value|id|key|slug|type|kind|status|mode|code|field|sort|order|tone|variant|icon|href|to|path|param|query|unit|format|tab|stage|section|route|name|css|font|fontFamily|color|className|testId|event|action|method|category|lens|scope|role|model|provider|base_url|baseUrl|url|endpoint|api_key|apiKey|host|locale|currency)$/;
const CODE_CALLEE = /^(css|fontFamily|setProperty|navigate|track)$/;
const KEY_NAMES = /^(Arrow(Left|Right|Up|Down)|Home|End|Enter|Escape|Esc|Tab|Space|Backspace|Delete|PageUp|PageDown|ApiError)$/;

const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ", ldquo: "“", rdquo: "”", lsquo: "‘", rsquo: "’", mdash: "—", ndash: "–", hellip: "…", middot: "·", times: "×", rarr: "→", larr: "←", rsaquo: "›", lsaquo: "‹", raquo: "»", laquo: "«", bull: "•", copy: "©", deg: "°", minus: "−", thinsp: " ", ensp: " ", emsp: " " };

/** Decode HTML entities as the JSX transform does; null when one is unknown. */
function decode(s) {
  let bad = false;
  const out = s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
    if (e[0] === "#") return String.fromCodePoint(e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10));
    if (e in ENTITIES) return ENTITIES[e];
    bad = true;
    return m;
  });
  return bad ? null : out;
}

/** What React renders for a JSX text node (Babel's cleanJSXElementLiteralChild). */
function jsxText(raw) {
  const lines = raw.split(/\r\n|\n|\r/);
  let lastNonEmpty = 0;
  lines.forEach((l, i) => { if (/[^ \t]/.test(l)) lastNonEmpty = i; });
  let str = "";
  lines.forEach((line, i) => {
    let t = line.replace(/\t/g, " ");
    if (i !== 0) t = t.replace(/^[ ]+/, "");
    if (i !== lines.length - 1) t = t.replace(/[ ]+$/, "");
    if (t) {
      if (i !== lastNonEmpty) t += " ";
      str += t;
    }
  });
  return decode(str);
}

const camel = (id) => id.replace(/[-.]([a-z0-9])/g, (_, c) => c.toUpperCase());
const kebab = (s) => s.replace(/([a-z0-9])([A-Z])/g, "$1-$2").replace(/[^A-Za-z0-9]+/g, "-").toLowerCase().replace(/^-|-$/g, "");
const slug = (text) => {
  const words = text.replace(/\{[^}]*\}/g, " ").normalize("NFKD").replace(/[^\x00-\x7f]/g, "").toLowerCase().match(/[a-z0-9]+/g) ?? [];
  return words.slice(0, 5).join("-") || "text";
};
/** A Fluent string literal: only \" \\ and \uXXXX escapes exist. */
const fluentString = (v) => `"${[...v].map((ch) => (ch === '"' || ch === "\\" ? `\\${ch}` : ch < " " ? `\\u${ch.charCodeAt(0).toString(16).padStart(4, "0").toUpperCase()}` : ch)).join("")}"`;
const fluentSafe = (t) => !/[{}\n\r]/.test(t) && !/^[[*.]/.test(t);

/** A name for a placeholder, from the expression it stands for. */
function nameOf(expr, sf) {
  let e = expr;
  while (e && (ts.isParenthesizedExpression(e) || ts.isAsExpression(e) || ts.isNonNullExpression(e))) e = e.expression;
  let n = "value";
  if (!e) n = "value";
  else if (ts.isIdentifier(e)) n = e.text;
  else if (ts.isPropertyAccessExpression(e)) n = e.name.text;
  else if (ts.isElementAccessExpression(e)) return nameOf(e.expression, sf);
  else if (ts.isCallExpression(e)) {
    // `title.toLowerCase()` stands for the title.
    if (!e.arguments.length && ts.isPropertyAccessExpression(e.expression)) return nameOf(e.expression.expression, sf);
    const a = e.arguments[0];
    if (a && (ts.isIdentifier(a) || ts.isPropertyAccessExpression(a))) return nameOf(a, sf);
    n = ts.isPropertyAccessExpression(e.expression) ? e.expression.name.text : ts.isIdentifier(e.expression) ? e.expression.text : "value";
  } else if (ts.isJsxElement(e) || ts.isJsxSelfClosingElement(e)) {
    const tag = (ts.isJsxElement(e) ? e.openingElement : e).tagName.getText(sf);
    n = tag.split(".").pop();
  }
  n = n.replace(/[^A-Za-z0-9_]/g, "");
  if (!/^[A-Za-z]/.test(n)) n = "value";
  return n[0].toLowerCase() + n.slice(1);
}

/** Unique placeholder names within one message. */
function namer() {
  const seen = new Map();
  return (base) => {
    const k = seen.get(base) ?? 0;
    seen.set(base, k + 1);
    return k ? `${base}${k + 1}` : base;
  };
}

const PLURAL_ONE = (cond, sf) => {
  // `x === 1` / `1 === x` -> [x, true]; `x !== 1` -> [x, false]
  let c = cond;
  while (ts.isParenthesizedExpression(c)) c = c.expression;
  if (!ts.isBinaryExpression(c)) return null;
  const op = c.operatorToken.kind;
  if (op !== ts.SyntaxKind.EqualsEqualsEqualsToken && op !== ts.SyntaxKind.ExclamationEqualsEqualsToken) return null;
  const one = (n) => ts.isNumericLiteral(n) && n.text === "1";
  const subject = one(c.right) ? c.left : one(c.left) ? c.right : null;
  if (!subject) return null;
  return { subject, isOne: op === ts.SyntaxKind.EqualsEqualsEqualsToken, text: subject.getText(sf) };
};
const isStrLit = (n) => n && (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n));

function kindFor(node, plain, sf) {
  const shape = /[.!?]$/.test(plain.trim()) ? "sentence" : "label";
  let p = node.parent;
  while (p && (ts.isParenthesizedExpression(p) || ts.isConditionalExpression(p) || ts.isJsxExpression(p) || ts.isTemplateSpan(p) || ts.isTemplateExpression(p))) {
    if (ts.isJsxExpression(p) && p.parent && ts.isJsxAttribute(p.parent)) break;
    p = p.parent;
  }
  if (p && ts.isJsxAttribute(p)) {
    const a = p.name.getText(sf);
    // An intrinsic element's title is a tooltip; a component's (PageHeader, EmptyState) is its heading.
    const intrinsic = /^[a-z]/.test(p.parent.parent.tagName.getText(sf));
    if (/^(aria-|ariaLabel|alt)/.test(a)) return "aria";
    if ((a === "title" && intrinsic) || a === "tip" || /Tip$/.test(a)) return "tooltip";
    if (a === "title") return /[.!?]$/.test(plain.trim()) ? "sentence" : "heading";
    return shape;
  }
  if (p && ts.isPropertyAssignment(p)) {
    const k = p.name.getText(sf).replace(/["']/g, "");
    if (/aria/i.test(k)) return "aria";
    if (/^(title|tip|tooltip)$/i.test(k)) return "tooltip";
    if (/error|fail/i.test(k)) return "error";
  }
  if (p && ts.isCallExpression(p)) {
    const callee = p.expression.getText(sf).split(".").pop();
    if (/error|fail/i.test(callee)) return "error";
    if (/notice|toast|push|message|note/i.test(callee)) return "toast";
  }
  return shape;
}

function jsxKind(parentTag, plain) {
  const t = parentTag ?? "";
  if (/^h[1-6]$/.test(t)) return "heading";
  if (/^(button|Button|IconButton)$/.test(t)) return "button";
  if (/^(a|Link|NavLink)$/.test(t)) return "link";
  if (/^(th|dt|legend|label|caption)$/.test(t)) return "label";
  return /[.!?]$/.test(plain.trim()) ? "sentence" : "label";
}

/** The catalog: existing ids, and the messages this run adds, per surface file. */
export class Catalog {
  constructor() {
    const en = readLocale(COPY, "en");
    this.ids = new Set(en.messages.map((m) => m.id));
    this.added = new Map(); // surface -> [{ id, kind, body, file }]
    this.byBody = new Map(); // `${surface}|${kind}|${body}` -> id
    this.byShape = new Map(); // the same with placeholder names erased -> id (a twin says same-as=)
    this.existingText = new Map(); // `${surface}|${kind}|${flat}` -> id
    for (const m of en.messages) {
      const surface = m.file.replace(/^en\//, "").replace(/\.ftl$/, "");
      const flat = m.pattern.elements.every((e) => e.type === "TextElement") ? m.pattern.elements.map((e) => e.value).join("").trim() : null;
      if (flat !== null) this.existingText.set(`${surface}|${m.meta.kind}|${flat}`, m.id);
    }
  }

  /** The id for this text, reusing one that already says it in the same file and kind. */
  add(surface, file, kind, body, plain, constant) {
    const key = `${surface}|${kind}|${body}`;
    if (this.byBody.get(key)) return this.byBody.get(key);
    if (constant && this.existingText.has(`${surface}|${kind}|${body}`)) return this.existingText.get(`${surface}|${kind}|${body}`);
    const stem = kebab(basename(file).replace(/\.(tsx?|mjs)$/, "")).replace(new RegExp(`^${surface}-`), "");
    let id = `${surface}-${stem}-${slug(plain)}`.replace(/-+/g, "-");
    for (let n = 2; this.ids.has(id); n++) id = `${surface}-${stem}-${slug(plain)}-${n}`;
    this.ids.add(id);
    this.byBody.set(key, id);
    // Two sources saying the same words with differently named values (FilterRail's
    // `{ $title }`, FilterSelect's `{ $label }`) keep their own signatures, named as twins.
    const shapeKey = `${surface}|${kind}|${body.replace(/\$[A-Za-z0-9_]+/g, "$")}`;
    const sameAs = this.byShape.get(shapeKey);
    if (!sameAs) this.byShape.set(shapeKey, id);
    if (!this.added.has(surface)) this.added.set(surface, []);
    this.added.get(surface).push({ id, kind, body, file, sameAs });
    return id;
  }

  write() {
    for (const [surface, list] of this.added) {
      const path = join(COPY, "en", `${surface}.ftl`);
      let out = existsSync(path) ? readFileSync(path, "utf8").replace(/\n*$/, "\n") : `## ${surface}: moved as it was found (wording=as-is)\n`;
      let group = null;
      for (const m of list) {
        if (m.file !== group) {
          out += `\n## ${m.file}\n`;
          group = m.file;
        }
        out += `# kind=${m.kind} wording=as-is${m.sameAs ? ` same-as=${m.sameAs}` : ""}\n${m.id} = ${m.body}\n`;
      }
      writeFileSync(path, out);
    }
  }
}

/** Rewrite one file; returns its new text, or null when nothing moved. */
export function transform(rel, text, catalog, log = () => {}, { getters = false } = {}) {
  const surface = surfaceOf(rel);
  if (!surface) return null;
  const { sf, strings } = extractFile(rel, text);
  if (!strings.length) return null;

  // Strings this file also uses as code (compared, switched on, indexed): in
  // another language a rendered one would stop matching, so neither moves.
  const codeTexts = new Set();
  (function scan(n) {
    if (isStrLit(n)) {
      const p = n.parent;
      if ((ts.isBinaryExpression(p) && /^(===|!==|==|!=)$/.test(p.operatorToken.getText(sf))) || ts.isCaseClause(p) || ts.isElementAccessExpression(p)) codeTexts.add(n.text);
    }
    ts.forEachChild(n, scan);
  })(sf);

  const copyNodes = new Map(strings.map((s) => [s.node, s]));
  // A chart series' `name` is its legend and tooltip label, not an identifier.
  const codeProp = (key) => CODE_PROP.test(key) && !(key === "name" && rel.startsWith("features/statistics/charts/"));
  const edits = []; // { start, end, gen }
  const fns = new Set();
  let usesMsg = false;
  const overlaps = (s, e) => edits.some((x) => (s < x.end && e > x.start) && !((s <= x.start && e >= x.end) || (s >= x.start && e <= x.end)));
  const addEdit = (start, end, gen) => {
    if (overlaps(start, end)) return false;
    edits.push({ start, end, gen });
    return true;
  };
  const rewrite = (s, e) => {
    const inner = edits.filter((x) => x.start >= s && x.end <= e).sort((a, b) => a.start - b.start || b.end - a.end);
    let out = "";
    let at = s;
    for (const x of inner) {
      if (x.start < at) continue; // nested in one already taken
      out += text.slice(at, x.start) + x.gen();
      at = x.end;
    }
    return out + text.slice(at, e);
  };
  const fnFor = (id) => {
    const name = camel(id);
    fns.add(name);
    return name;
  };
  // A clash with a local name fails tsc, and the run reverts that file.
  const message = (node, kind, body, plain, constant) => fnFor(catalog.add(surface, rel, kind, body, plain, constant));
  const callArgs = (args) => (args.length ? `{ ${args.map(([k, v]) => `${k}: ${v}`).join(", ")} }` : "");
  const skip = (node, why) => log(`${rel}:${sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1} skipped (${why})`);

  // 1. JSX children: a sentence is one message.
  const handledText = new Set();
  // A JSX text node's own characters, whitespace included (getText() drops the
  // leading run, and with it the space in "Tap the {icon} on any role").
  const raw = (k) => text.slice(k.pos, k.end);
  function children(el) {
    const kids = el.children;
    const tag = ts.isJsxElement(el) ? el.openingElement.tagName.getText(sf) : null;
    const items = kids.map((k) => {
      if (ts.isJsxText(k)) {
        const r = jsxText(raw(k));
        return { k, t: "T", r, copy: copyNodes.has(k) && r !== null };
      }
      if (ts.isJsxExpression(k) && !k.expression) return { k, t: "C" }; // a comment
      return { k, t: ts.isJsxExpression(k) ? "E" : "X" };
    });
    const copyIdx = items.map((it, i) => (it.copy ? i : -1)).filter((i) => i >= 0);
    if (!copyIdx.length) return;
    if (items.some((it) => it.t === "T" && it.r === null && copyNodes.has(it.k))) return skip(el, "unknown entity");
    let a = copyIdx[0];
    let b = copyIdx.at(-1);
    // Values and punctuation written against the text ("{count} roles",
    // "Stale ({n})") belong to its sentence; an element at either end does not.
    // A line break between them means the next thing is its own line, not this sentence.
    const joins = (it) => it.t === "E" || (it.t === "T" && !it.copy && it.r !== null);
    const breakBefore = (it) => it.t === "T" && /^\s*[\r\n]/.test(raw(it.k));
    const breakAfter = (it) => it.t === "T" && /[\r\n]\s*$/.test(raw(it.k));
    while (a > 0 && joins(items[a - 1]) && !breakBefore(items[a]) && !breakAfter(items[a - 1])) a--;
    while (b < items.length - 1 && joins(items[b + 1]) && !breakAfter(items[b]) && !breakBefore(items[b + 1])) b++;
    const span = items.slice(a, b + 1);
    // Whitespace at the outer edges stays in the code, where it renders as before.
    const first = span[0];
    const last = span.at(-1);
    const start = first.t === "T" ? first.k.pos + raw(first.k).match(/^\s*/)[0].length : first.k.getStart(sf);
    const end = last.t === "T" ? last.k.end - raw(last.k).match(/\s*$/)[0].length : last.k.end;
    if (span.length === 1) {
      const core = first.r.trim();
      if (!fluentSafe(core)) return skip(first.k, "braces or special start");
      const fn = message(first.k, jsxKind(tag, core), core, core, true);
      handledText.add(first.k);
      addEdit(start, end, () => `{${fn}()}`);
      return;
    }
    if (span.some((it) => it.t === "C")) return skip(el, "comment inside a sentence");
    // Text is text; a ternary choosing between strings is the message's select;
    // any other expression or element is a placeholder rendered as it was.
    const parts = span.map((it) => {
      if (it.t === "T") return { t: "text", v: it.r };
      const c = it.t === "E" && choiceOf(it.k.expression);
      if (c) return { t: "choice", c };
      return it.t === "E" ? { t: "elem", e: it.k.expression } : { t: "elem", e: it.k };
    });
    const gen = compose(el, parts, { jsx: true, kind: (plain) => jsxKind(tag, plain) });
    if (!gen) return;
    for (const it of span) if (it.t === "T") handledText.add(it.k);
    addEdit(start, end, gen);
  }

  // 2. Literals. One composer for every shape a string is built in: a literal,
  // a template, a `+` chain whose first operand is a string, and a plural
  // ternary (`n === 1 ? a : b`) inside any of them, whose branches may be
  // literals or templates. Its parts are text, a value (passed as String(x),
  // exactly what concatenation and templates do) or one plural.
  const done = new Set();
  const unparen = (e) => {
    while (e && ts.isParenthesizedExpression(e)) e = e.expression;
    return e;
  };
  const isPlus = (n) => ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.PlusToken;
  const leftmost = (n) => (isPlus(n) ? leftmost(n.left) : n);
  const stringy = (n) => isStrLit(n) || ts.isTemplateExpression(n) || (isPlus(n) && stringy(unparen(leftmost(n))));
  /** The strings a ternary (or a chain of them) chooses between, each with the
   *  path of conditions that picks it; null when a branch is not a string. */
  const leavesOf = (c, path = []) => {
    const out = [];
    for (const [b, taken] of [[c.whenTrue, true], [c.whenFalse, false]]) {
      const u = unparen(b);
      const here = [...path, [c.condition, taken]];
      if (ts.isConditionalExpression(u)) {
        const inner = leavesOf(u, here);
        if (!inner) return null;
        out.push(...inner);
      } else if (stringy(u)) out.push({ node: u, path: here });
      else return null;
    }
    return out;
  };
  /** A ternary choosing between strings: a plural when it tests `=== 1`. */
  const choiceOf = (e) => {
    const c = unparen(e);
    return c && ts.isConditionalExpression(c) && leavesOf(c) ? c : null;
  };

  /** Parts of a string expression, or null when one is not a string shape. */
  function partsOf(n, inChoice = false) {
    n = unparen(n);
    const c = !inChoice && choiceOf(n);
    if (c) return [{ t: "choice", c }];
    if (isStrLit(n)) return [{ t: "text", v: n.text }];
    if (ts.isTemplateExpression(n)) {
      const out = [{ t: "text", v: n.head.text }];
      for (const sp of n.templateSpans) {
        const ch = !inChoice && choiceOf(sp.expression);
        out.push(ch ? { t: "choice", c: ch } : { t: "arg", e: sp.expression });
        out.push({ t: "text", v: sp.literal.text });
      }
      return out;
    }
    if (isPlus(n) && stringy(unparen(leftmost(n)))) {
      const flat = [];
      (function walk(x) {
        if (isPlus(x)) {
          walk(x.left);
          walk(x.right);
        } else flat.push(x);
      })(n);
      const out = [];
      for (const op of flat) {
        const u = unparen(op);
        const ch = !inChoice && choiceOf(u);
        if (ch) out.push({ t: "choice", c: ch });
        else if (stringy(u)) out.push(...partsOf(u, inChoice));
        else out.push({ t: "arg", e: op });
      }
      return out;
    }
    return null;
  }

  /** The message for some parts, and a function writing the code that says it;
   *  null (after logging why) to leave the string alone. */
  function compose(node, parts, { jsx = false, kind } = {}) {
    const name = namer();
    const code = (n) => rewrite(n.getStart(sf), n.getEnd());
    // Each choice: its selector, its keys and its branches (parts of their own).
    const selects = [];
    for (const p of parts.filter((x) => x.t === "choice")) {
      const c = p.c;
      done.add(c);
      const leaves = leavesOf(c);
      const rule = leaves.length === 2 && PLURAL_ONE(c.condition, sf);
      const ordered = rule && !rule.isOne ? [leaves[1], leaves[0]] : leaves;
      const branches = ordered.map((l) => partsOf(l.node, true));
      if (branches.some((b) => !b)) return skip(node, "a choice branch is not a string"), null;
      const keys = rule ? ["one", "other"] : leaves.length === 2 ? ["yes", "no"] : leaves.map((_, i) => `v${i + 1}`);
      // The selector repeats the ternary with each string replaced by its key.
      const keyOf = new Map(leaves.map((l, i) => [l.node, rule ? null : keys[i]]));
      const selector = (n) => {
        const u = unparen(n);
        if (ts.isConditionalExpression(u)) return `(${code(u.condition)}) ? ${selector(u.whenTrue)} : ${selector(u.whenFalse)}`;
        return JSON.stringify(keyOf.get(u));
      };
      // A value inside a branch is read only when its branch is taken, as before
      // (`x !== null ? "by " + x.name : "none"` must not read x.name when x is null).
      const guard = (path, v) => path.reduceRight((acc, [cond, taken]) => (taken ? `(${code(cond)}) ? ${acc} : ""` : `(${code(cond)}) ? "" : ${acc}`), v);
      ordered.forEach((l, i) => {
        for (const bp of branches[i]) if (bp.t === "arg") bp.guard = (v) => guard(l.path, v);
      });
      p.select = {
        name: name(rule ? "count" : "choice"),
        keys,
        branches,
        code: () => (rule ? code(rule.subject) : selector(c)),
      };
      selects.push(p.select);
    }
    const args = [];
    const elems = [];
    const named = new Map();
    const ref = (p) => {
      if (!named.has(p.e)) {
        const n = name(nameOf(p.e, sf));
        named.set(p.e, n);
        let c = () => code(p.e);
        // A value that is itself built from strings ("{n} isn't scanned yet" inside
        // a branch) is its own message, so no English stays in the code.
        const inner = p.t === "arg" && !isStrLit(unparen(p.e)) && (choiceOf(p.e) || stringy(unparen(p.e))) ? partsOf(p.e) : null;
        const sub = inner && compose(p.e, inner);
        if (sub) c = sub;
        if (p.t === "elem") elems.push([n, c]);
        else args.push([n, () => (p.guard ? p.guard(sub ? c() : `String(${c()})`) : sub ? c() : `String(${c()})`)]);
      }
      return named.get(p.e);
    };
    // A line break inside the text stays one, as a string placeable.
    const flat = (list) => list.map((p) => (p.t === "text" ? p.v.replace(/\r?\n/g, '{ "\\u000A" }') : `{ $${ref(p)} }`)).join("");
    // Edge spaces Fluent would trim from a variant stay as string placeables.
    const keepEdges = (v) => {
      const l = v.match(/^\s*/)[0];
      const t = v.trim() ? v.match(/\s*$/)[0] : "";
      return `${l ? `{ ${fluentString(l)} }` : ""}${v.trim()}${t ? `{ ${fluentString(t)} }` : ""}` || '{ "" }';
    };
    const selectText = (sel, variants, indent) =>
      `{ $${sel.name} ->\n${variants.map((v, i) => `${i === variants.length - 1 ? `${indent.slice(1)}*` : indent}[${sel.keys[i]}] ${v}`).join("\n")}\n${indent.slice(4)}}`;
    let body;
    let plain;
    let lead = "";
    let trail = "";
    if (selects.length === 1) {
      // One choice: each variant is the whole sentence, the way a translator reads it.
      const at = parts.findIndex((p) => p.t === "choice");
      let variants = selects[0].branches.map((b) => flat([...parts.slice(0, at), ...b, ...parts.slice(at + 1)]));
      lead = variants[0].match(/^\s*/)[0];
      trail = variants[0].match(/\s*$/)[0];
      if (variants.every((v) => v.match(/^\s*/)[0] === lead && v.match(/\s*$/)[0] === trail)) variants = variants.map((v) => v.trim() || '{ "" }');
      else {
        lead = trail = "";
        variants = variants.map(keepEdges);
      }
      body = selectText(selects[0], variants, "    ");
      plain = variants.at(-1);
    } else {
      // Several choices: each is a select where it stands in the sentence.
      const out = parts.map((p) => (p.t === "choice" ? selectText(p.select, p.select.branches.map((b) => keepEdges(flat(b))), "        ") : flat([p]))).join("");
      lead = out.match(/^\s*/)[0];
      trail = out.match(/\s*$/)[0];
      body = out.trim();
      plain = parts.map((p) => (p.t === "choice" ? flat(p.select.branches.at(-1)) : p.t === "text" ? p.v : "{}")).join("").trim();
    }
    const words = (v) => v.replace(/\{ \$[A-Za-z0-9_]+ ->[\s\S]*?\n\s*\}/g, "").replace(/\{ \$[A-Za-z0-9_]+ \}/g, "").replace(/\{ "[^"]*" \}/g, "");
    // A variant's value follows its key on the line, so only braces and line breaks matter there.
    const branchTexts = selects.flatMap((sel) => sel.branches.map((b) => b.filter((x) => x.t === "text").map((x) => x.v).join("")));
    const outside = parts.filter((x) => x.t === "text").map((x) => x.v).join("");
    // Braces in the text cannot be said; the value may start with a placeable, never with [ * or .
    if (!body || branchTexts.concat(outside).some((v) => /[{}]/.test(v)) || /^[[*.]/.test(body)) {
      return skip(node, "braces, a line break or a special start"), null;
    }
    const shape = plain.replace(/\{ \$[^}]+ \}/g, "x");
    const fn = message(node, kind ? kind(shape) : kindFor(node, shape, sf), body, plain, !selects.length && !args.length && !elems.length);
    return () => {
      const argList = [...selects.map((sel) => [sel.name, sel.code()]), ...args.map(([k, v]) => [k, v()])];
      if (elems.length) {
        usesMsg = true;
        const a = argList.length ? ` args={${callArgs(argList)}}` : "";
        return `<Msg of={${fn}}${a} elems={{ ${elems.map(([k, v]) => `${k}: ${v()}`).join(", ")} }} />`;
      }
      const call = `${fn}(${callArgs(argList)})`;
      if (jsx) return `{${call}}`; // JSX edges stay in the code as whitespace
      if (!lead && !trail) return call;
      return `(${[lead && JSON.stringify(lead), call, trail && JSON.stringify(trail)].filter(Boolean).join(" + ")})`;
    };
  }

  /** The outermost string expression a literal belongs to. */
  function rootOf(node) {
    let n = node;
    for (;;) {
      const p = n.parent;
      if (ts.isParenthesizedExpression(p)) n = p;
      else if (isPlus(p) && stringy(unparen(leftmost(p)))) n = p;
      else if (ts.isConditionalExpression(p) && choiceOf(p) && p.condition !== n) n = p;
      else if (ts.isTemplateSpan(p)) n = p.parent;
      else return n;
    }
  }

  function literal(node, info) {
    if (info.moduleScope) return moduleScope(node, info);
    if (KEY_NAMES.test(info.text)) return;
    const kind = info.kind;
    if (kind.startsWith("jsx-attr:") && !COPY_ATTR.test(kind.slice(9))) return skip(node, `attribute ${kind.slice(9)}`);
    if (kind.startsWith("prop:") && codeProp(kind.slice(5))) return skip(node, `property ${kind.slice(5)}`);
    if (kind.startsWith("call:") && CODE_CALLEE.test(kind.slice(5))) return;
    if (isStrLit(node) && codeTexts.has(node.text)) return skip(node, "also compared in this file");
    const root = rootOf(node);
    if (done.has(root)) return;
    done.add(root);
    const p = root.parent;
    // A JSX attribute's string literal decodes entities, and needs braces around a call.
    if (isStrLit(root) && ts.isJsxAttribute(p)) {
      const value = decode(root.text);
      if (value === null) return skip(node, "unknown entity");
      const gen = compose(root, [{ t: "text", v: value }]);
      if (gen) addEdit(root.getStart(sf), root.end, () => `{${gen()}}`);
      return;
    }
    const parts = partsOf(root);
    if (!parts) return skip(node, "not a string shape");
    const gen = compose(root, parts);
    if (gen) addEdit(root.getStart(sf), root.end, gen);
  }

  // Module scope runs once, before any language is chosen, so a moved string
  // there is read through a getter: `label: "Text"` -> `get label() { return fn(); }`.
  // Only a property of an object literal; an array element or a bare constant
  // has no getter to become, and stays for a person.
  function moduleScope(node, info) {
    if (!getters) return skip(node, "module scope");
    const root = rootOf(node);
    if (done.has(root)) return;
    done.add(root);
    const p = root.parent;
    if (!ts.isPropertyAssignment(p) || p.initializer !== root || !ts.isObjectLiteralExpression(p.parent)) return skip(node, "module scope, not an object property");
    if (ts.isComputedPropertyName(p.name)) return skip(node, "module scope, computed key");
    const key = p.name.getText(sf);
    if (codeProp(key.replace(/["']/g, ""))) return skip(node, `property ${key}`);
    if (KEY_NAMES.test(info.text)) return;
    if (isStrLit(root) && codeTexts.has(root.text)) return skip(node, "also compared in this file");
    const parts = partsOf(root);
    if (!parts) return skip(node, "module scope, not a string shape");
    const gen = compose(root, parts);
    if (gen) addEdit(p.getStart(sf), p.end, () => `get ${key}() { return ${gen()}; }`);
  }

  (function visit(n) {
    if (ts.isJsxElement(n) || ts.isJsxFragment(n)) children(n);
    ts.forEachChild(n, visit);
  })(sf);
  for (const s of strings) {
    if (s.kind === "jsx-text") {
      if (!handledText.has(s.node)) skip(s.node, "text beside block content");
      continue;
    }
    literal(s.node, s);
  }
  if (!edits.length) return null;

  // Imports: the surface's generated module, and Msg.
  const out = rewrite(0, text.length);
  const fromDir = dirname(join(SRC, rel));
  const spec = (target) => {
    const r = relative(fromDir, join(SRC, target)).split(sep).join("/");
    return r.startsWith(".") ? r : `./${r}`;
  };
  const genSpec = spec(`copy/gen/${surface}`);
  const lines = [];
  const imports = sf.statements.filter(ts.isImportDeclaration);
  const existing = imports.find((d) => d.moduleSpecifier.text === genSpec && d.importClause?.namedBindings && ts.isNamedImports(d.importClause.namedBindings));
  let result = out;
  if (existing) {
    const names = new Set([...existing.importClause.namedBindings.elements.map((e) => e.getText(sf)), ...fns]);
    const before = existing.getText(sf);
    const after = `import {\n${[...names].sort().map((n) => `  ${n},`).join("\n")}\n} from "${genSpec}";`;
    result = result.replace(before, after);
  } else {
    lines.push(`import {\n${[...fns].sort().map((n) => `  ${n},`).join("\n")}\n} from "${genSpec}";`);
  }
  if (usesMsg && !/\bMsg\b/.test(imports.map((d) => d.getText(sf)).join("\n"))) lines.push(`import { Msg } from "${spec("ui/Msg")}";`);
  if (lines.length) {
    const last = imports.at(-1);
    if (last) {
      const marker = last.getText(sf);
      const at = result.indexOf(marker) + marker.length;
      result = `${result.slice(0, at)}\n${lines.join("\n")}${result.slice(at)}`;
    } else {
      result = `${lines.join("\n")}\n${result}`;
    }
  }
  return result;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const args = process.argv.slice(2);
  const dry = args.includes("--dry");
  const getters = args.includes("--getters");
  const exclude = new Set((args[args.indexOf("--exclude") + 1] ?? "").split(",").filter(Boolean));
  const prefixes = args.filter((a, i) => !a.startsWith("--") && args[i - 1] !== "--exclude");
  const catalog = new Catalog();
  const log = [];
  let files = 0;
  for (const abs of sourceFiles(SRC)) {
    const rel = relative(SRC, abs).split(sep).join("/");
    if (!prefixes.some((p) => rel.startsWith(p)) || exclude.has(rel)) continue;
    const before = readFileSync(abs, "utf8");
    const after = transform(rel, before, catalog, (l) => log.push(l), { getters });
    if (after === null || after === before) continue;
    files++;
    if (!dry) writeFileSync(abs, after);
  }
  if (!dry) catalog.write();
  const moved = [...catalog.added.values()].reduce((n, l) => n + l.length, 0);
  for (const l of log) console.log(`skip ${l}`);
  console.log(`codemod: ${files} files, ${moved} messages${dry ? " (dry run)" : ""}; ${log.length} skipped`);
}
