// Every user-visible string literal in dashboard/src, found with the TypeScript
// compiler. Includes array elements that read as prose, and whether a string is
// evaluated at module scope: a live language switch cannot reach those
// (docs/copy.md).
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join, relative, sep } from "node:path";

const ts = createRequire(import.meta.url)("typescript");

const hasLetters = (s) => /\p{L}{2,}/u.test(s);
const looksCode = (s) => (/^[a-z0-9_\-./:#?=&%]+$/.test(s) && !/\s/.test(s)) || /^[A-Z_]+$/.test(s) || /^(true|false|null|undefined)$/.test(s);

/** The source files whose strings a reader can see. */
export function sourceFiles(src) {
  const files = [];
  (function walk(d) {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      const p = join(d, e.name);
      if (e.isDirectory()) {
        if (!["test", "__tests__", "gen", "__golden__"].includes(e.name)) walk(p);
        continue;
      }
      if (/\.tsx?$/.test(e.name) && !/\.test\.|\.d\.ts$|\.gen\.ts$|\.fixture\.ts$/.test(e.name)) files.push(p);
    }
  })(src);
  return files.sort();
}

/** [{ file, line, kind, text, parts, moduleScope }] */
export function extractStrings(src) {
  return extractSource(src).strings;
}

/** Every file's strings, and the habits only the syntax tree shows
 *  (`habits`: [{ file, line, habit, text }]). */
export function extractSource(src) {
  const strings = [];
  const habits = [];
  for (const f of sourceFiles(src)) {
    const rel = relative(src, f).split(sep).join("/");
    const found = extractFile(rel, readFileSync(f, "utf8"));
    for (const { node: _node, ...s } of found.strings) strings.push(s);
    habits.push(...found.habits);
  }
  return { strings, habits };
}

/** One file's strings, with their AST nodes and the source file they belong to
 *  (the codemod, scripts/copy/codemod.mjs, rewrites exactly these), and its
 *  AST habits. */
export function extractFile(rel, text) {
  const out = [];
  const habits = [];
  {
    const f = rel;
    const sf = ts.createSourceFile(f, text, ts.ScriptTarget.Latest, true, f.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const inFunction = (node) => {
      for (let p = node.parent; p; p = p.parent) if (ts.isFunctionLike(p)) return true;
      return false;
    };
    const emit = (node, kind, str, parts = 0, words = false) => {
      str = str.replace(/\s+/g, " ").trim();
      if (!str || !hasLetters(str) || (!words && looksCode(str))) return;
      const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
      out.push({ node, file: rel, line: line + 1, kind, text: str, parts, moduleScope: !inFunction(node) });
    };
    const tmpl = (n) => {
      if (ts.isNoSubstitutionTemplateLiteral(n) || ts.isStringLiteral(n)) return { s: n.text, parts: 0 };
      if (ts.isTemplateExpression(n)) {
        let s = n.head.text;
        for (const sp of n.templateSpans) s += "{" + sp.expression.getText(sf).slice(0, 40) + "}" + sp.literal.text;
        return { s, parts: n.templateSpans.length };
      }
      return null;
    };
    // Attributes and call targets whose strings are code, not copy.
    const CODE_ATTRS = /^(className|id|key|href|to|role|type|name|htmlFor|rel|target|src|d|viewBox|fill|stroke|path|mode|variant|size|tone|icon|as|lang|dir|inputMode|autoComplete|method|encType|transform|in|in2|result|operator|data-.*|aria-(controls|labelledby|describedby|owns|activedescendant|current|haspopup|live|sort|orientation|autocomplete|keyshortcuts))$/;
    // Object properties whose VALUE is an identifier the code or the API reads.
    const CODE_VALUE_PROPS = /^(type|model|provider|base_url|baseUrl|endpoint|url)$/;
    const CODE_CALLS = /^(querySelector|querySelectorAll|getElementById|closest|matches|getItem|setItem|removeItem|addEventListener|removeEventListener|dispatchEvent|getPropertyValue|setProperty|setAttribute|getAttribute|hasAttribute|removeAttribute|test|match|replace|split|join|startsWith|endsWith|includes|indexOf|padStart|padEnd|log|warn|error|info|debug|getJSON|putJSON|postJSON|patchJSON|deleteJSON|requestJSON|fetch|qs|RegExp|useBodyAttribute|navigate|createElement|toggle|add|remove|has|get|set|delete|startTransition|import|require|css)$/;
    const codeContext = (n) => {
      const p = n.parent;
      if (!p) return true;
      if (ts.isImportDeclaration(p) || ts.isExportDeclaration(p) || ts.isExternalModuleReference(p) || ts.isLiteralTypeNode(p)) return true;
      if (ts.isPropertyAssignment(p) && p.name === n) return true; // an object KEY
      // A class's own name (`this.name = "ApiError"`) is for developers.
      if (ts.isBinaryExpression(p) && p.operatorToken.kind === ts.SyntaxKind.EqualsToken && p.right === n && /\.name$/.test(p.left.getText(sf))) return true;
      // A Set's members are what a lookup compares against, not words shown.
      if (ts.isArrayLiteralExpression(p) && ts.isNewExpression(p.parent) && p.parent.expression.getText(sf) === "Set") return true;
      // Navigation keys a handler compares against (`["ArrowLeft", "Home"].includes(e.key)`).
      if (ts.isArrayLiteralExpression(p) && p.elements.every((e) => ts.isStringLiteral(e) && /^(Arrow(Left|Right|Up|Down)|Home|End|PageUp|PageDown)$/.test(e.text))) return true;
      if (ts.isPropertyAssignment(p) && p.initializer === n && CODE_VALUE_PROPS.test(p.name.getText(sf).replace(/["']/g, ""))) return true;
      if (ts.isElementAccessExpression(p) || ts.isCaseClause(p)) return true;
      if (ts.isBinaryExpression(p) && /^(===|!==|==|!=|in|instanceof)$/.test(p.operatorToken.getText(sf))) return true;
      if (ts.isJsxAttribute(p) || (ts.isJsxExpression(p) && p.parent && ts.isJsxAttribute(p.parent))) {
        const attr = ts.isJsxAttribute(p) ? p : p.parent;
        if (CODE_ATTRS.test(attr.name.getText(sf))) return true;
      }
      if ((ts.isCallExpression(p) || ts.isNewExpression(p)) && p.expression !== n) {
        const callee = p.expression.getText(sf).split(".").pop();
        if (CODE_CALLS.test(callee)) return true;
      }
      if (ts.isTaggedTemplateExpression(p)) return true;
      // A thrown Error's text is for developers and logs: a screen says a
      // failure through errorText (api/errorText.ts), never its message.
      if (ts.isNewExpression(p) && /^(Error|TypeError|RangeError|ApiError)$/.test(p.expression.getText(sf))) return true;
      return false;
    };
    const kindOf = (n) => {
      const p = n.parent;
      if (ts.isJsxAttribute(p)) return "jsx-attr:" + p.name.getText(sf);
      if (ts.isJsxExpression(p) && ts.isJsxAttribute(p.parent)) return "jsx-attr:" + p.parent.name.getText(sf);
      if (ts.isJsxExpression(p)) return "jsx-expr";
      if (ts.isPropertyAssignment(p)) return "prop:" + p.name.getText(sf).replace(/["']/g, "");
      if (ts.isCallExpression(p) || ts.isNewExpression(p)) return "call:" + p.expression.getText(sf).split(".").pop();
      if (ts.isConditionalExpression(p)) return "ternary";
      if (ts.isArrayLiteralExpression(p)) return "array";
      if (ts.isReturnStatement(p) || ts.isArrowFunction(p)) return "return";
      if (ts.isVariableDeclaration(p)) return "const";
      return "expr";
    };
    // Reads as words: a letter run outside placeholders, and a space or a
    // capitalised word ("Radar", "Saved"); not a slug, a path or a constant.
    const readsAsCopy = (s) => {
      const words = s.replace(/\{[^}]*\}/g, " ").trim();
      if (!/\p{L}{2,}/u.test(words) || looksCode(words)) return false;
      if (/^[a-z][\w-]*$/.test(words) || /^[\w-]+(\/[\w-]+)+$/.test(words) || /^\/[^\s]*$/.test(s.replace(/\{[^}]*\}/g, "x")) || /^#|^\.|^--|^\(|https?:|\/api\/|^[\w-]+:\s|var\(|px\b|^[\w.-]+\.(ts|tsx|css|json|svg|png)$|:not\(|\[[a-z-]+\]/.test(words)) return false;
      // A class list ("rail-badge rail-badge-dot", "stat-chip good"): lowercase
      // tokens, at least one hyphenated, nothing else.
      if (/^[a-z][a-z0-9-]*( [a-z][a-z0-9-]*)*$/.test(words) && /-/.test(words)) return false;
      return / /.test(words) || /^\p{Lu}\p{Ll}/u.test(words);
    };
    // A hand-built plural (`n === 1 ? "role" : "roles"`) is words whatever their
    // shape, and so is a template that holds one: single lowercase words
    // otherwise read as code, which would hide every such plural from the count.
    const pluralTest = (c) => {
      while (ts.isParenthesizedExpression(c)) c = c.expression;
      return ts.isBinaryExpression(c) && /^(===|!==)$/.test(c.operatorToken.getText(sf)) && [c.left, c.right].some((x) => ts.isNumericLiteral(x) && x.text === "1");
    };
    const pluralBranch = (n) => {
      let p = n.parent;
      while (ts.isParenthesizedExpression(p)) p = p.parent;
      return ts.isConditionalExpression(p) && p.condition !== n && pluralTest(p.condition);
    };
    const holdsPlural = (n) => ts.isTemplateExpression(n) && n.templateSpans.some((sp) => {
      let e = sp.expression;
      while (ts.isParenthesizedExpression(e)) e = e.expression;
      return ts.isConditionalExpression(e) && pluralTest(e.condition);
    });
    // `${n} companies`, `saved ${when}`, `${a} or ${b}`: words written beside a value
    // are a sentence even when each is one lowercase word. Not a class list
    // (`chip ${on}`), a CSS value (`${x}px`) or a string a code-named variable holds,
    // and never one marked /* not copy */.
    const CODE_NAME = /(class|cls|style|key|id|url|path|href|selector|transform|query|param|slug|token|cache|storage|testid|origin)$/i;
    const holderName = (n) => {
      let p = n.parent;
      while (p && (ts.isParenthesizedExpression(p) || ts.isConditionalExpression(p) || ts.isBinaryExpression(p) || ts.isTemplateSpan(p) || ts.isTemplateExpression(p))) p = p.parent;
      if (p && (ts.isVariableDeclaration(p) || ts.isPropertyAssignment(p) || ts.isJsxAttribute(p) || ts.isPropertyDeclaration(p))) return p.name.getText(sf);
      if (p && ts.isJsxExpression(p) && ts.isJsxAttribute(p.parent)) return p.parent.name.getText(sf);
      return "";
    };
    const marked = (n) => {
      for (let p = n; p && !ts.isSourceFile(p); p = p.parent) {
        // A comment on the same line before the node is the previous token's "trailing" one.
        const ranges = [...(ts.getLeadingCommentRanges(sf.text, p.pos) ?? []), ...(ts.getTrailingCommentRanges(sf.text, p.pos) ?? [])];
        if (ranges.some((r) => /not copy/.test(sf.text.slice(r.pos, r.end)))) return true;
        if (ts.isStatement(p)) break;
      }
      return false;
    };
    const wordsBesideValues = (n) => {
      if (!ts.isTemplateExpression(n) || marked(n) || CODE_NAME.test(holderName(n))) return false;
      const texts = [n.head.text, ...n.templateSpans.map((sp) => sp.literal.text)];
      const words = texts.join(" ").match(/\p{L}{2,}/gu) ?? [];
      if (!words.length) return false;
      if (texts.some((t) => /^(px|em|rem|vh|vw|deg|%|fr)\b/.test(t))) return false; // ${x}px
      if (words.every((w) => /^[a-z][a-z0-9]*$/.test(w)) && texts.join(" ").split(/\s+/).filter(Boolean).every((t) => /^[a-z][a-z0-9-]*$/.test(t)) && texts.some((t) => /-/.test(t))) return false; // a class list
      // A word stands apart from a value: "{} companies", "saved {}", "{} or {}".
      return texts.some((t, i) => (i > 0 && /^\s+\p{L}{2,}/u.test(t)) || (i < texts.length - 1 && /\p{L}{2,}\s+$/u.test(t)) || /\p{L}{2,}\s+\p{L}{2,}/u.test(t));
    };
    // One word handed to a prop a screen shows is a word, though alone it reads
    // like a slug: a KPI's `sub: "today"`, `label="clusters"`, the pair an
    // ECharts visualMap writes at its ends (`text: ["more alike", "less"]`).
    const DISPLAY_PROPS = /^(sub|label|text|title)$/;
    const displayWord = (n) => {
      if (!(ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n))) return false;
      if (!/^\S+$/.test(n.text.trim()) || !/\p{L}{2,}/u.test(n.text)) return false;
      let p = n.parent;
      while (p && (ts.isParenthesizedExpression(p) || (ts.isConditionalExpression(p) && p.condition !== n) || (ts.isBinaryExpression(p) && /^(\?\?|\|\|)$/.test(p.operatorToken.getText(sf))))) p = p.parent;
      if (p && ts.isArrayLiteralExpression(p) && ts.isPropertyAssignment(p.parent) && p.parent.initializer === p) return p.parent.name.getText(sf) === "text";
      if (p && ts.isJsxExpression(p)) p = p.parent;
      if (p && ts.isPropertyAssignment(p) && p.name !== n) return DISPLAY_PROPS.test(p.name.getText(sf).replace(/["']/g, ""));
      if (p && ts.isJsxAttribute(p)) return DISPLAY_PROPS.test(p.name.getText(sf));
      return false;
    };
    // The functions this file imports from the generated catalog: a call to one
    // returns catalog text, and `<Msg>` renders one.
    const messages = new Set();
    for (const st of sf.statements) {
      if (!ts.isImportDeclaration(st) || !/(^|\/)copy\/gen\//.test(st.moduleSpecifier.text)) continue;
      const bound = st.importClause?.namedBindings;
      if (bound && ts.isNamedImports(bound)) for (const el of bound.elements) messages.add(el.name.text);
    }
    const unwrap = (e) => {
      while (e && (ts.isParenthesizedExpression(e) || ts.isAsExpression(e) || ts.isNonNullExpression(e))) e = e.expression;
      return e;
    };
    const messageCall = (e) => {
      e = unwrap(e);
      return !!e && ts.isCallExpression(e) && ts.isIdentifier(e.expression) && messages.has(e.expression.text);
    };
    const tagOf = (e) => (ts.isJsxElement(e) ? e.openingElement.tagName.getText(sf) : ts.isJsxSelfClosingElement(e) ? e.tagName.getText(sf) : null);
    const isMessageChild = (k) => {
      if (tagOf(k) === "Msg") return true;
      if (!ts.isJsxExpression(k) || !k.expression) return false;
      const e = unwrap(k.expression);
      if (ts.isConditionalExpression(e)) return messageCall(e.whenTrue) || messageCall(e.whenFalse);
      return messageCall(e);
    };
    // Where a value lands once the ternaries, parentheses and fallbacks that
    // choose it are passed: `{on ? "on" : "off"}` lands in the JSX child.
    const landing = (n) => {
      let c = n;
      let p = n.parent;
      while (p && (ts.isParenthesizedExpression(p) || (ts.isConditionalExpression(p) && p.condition !== c)
        || (ts.isBinaryExpression(p) && (/^(\?\?|\|\|)$/.test(p.operatorToken.getText(sf)) || (p.operatorToken.getText(sf) === "&&" && p.right === c))))) {
        c = p;
        p = p.parent;
      }
      return p;
    };
    // Rendered text that is code shown as code: a key cap, a code sample.
    const CODE_TAGS = /^(Kbd|kbd|code|pre|samp)$/;
    const inCodeTag = (n) => {
      for (let p = n.parent; p && !ts.isSourceFile(p); p = p.parent) if (CODE_TAGS.test(tagOf(p) ?? "")) return true;
      return false;
    };
    // A word, not a token: letters, with no path, flag, dotted name or query in it.
    const wordish = (s) => /\p{L}{2,}/u.test(s) && !/^[-./#]|[_=&%{}<>]|\.\w|\/\w|^\w+:/.test(s.trim());
    // A string written as a JSX child is rendered, whatever its shape: the
    // `{stated ? "stated" : "estimated"}` a ternary hands to the screen.
    const jsxChildWord = (n) => {
      if (!(ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) || !wordish(n.text)) return false;
      const p = landing(n);
      return !!p && ts.isJsxExpression(p) && (ts.isJsxElement(p.parent) || ts.isJsxFragment(p.parent)) && !inCodeTag(p);
    };
    // A lowercase phrase with a hyphenated word ("employee-selected mix") is
    // shaped like a class list; held as an object's value under a name that is
    // not a class holder, or handed to a display prop, it is a phrase.
    const CLASS_HOLDER = /class|cls|style/i;
    const phraseValue = (n) => {
      if (!(ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n))) return false;
      const s = n.text.trim();
      if (!/^[a-z][a-z0-9-]*( [a-z][a-z0-9-]*)+$/.test(s) || !/-/.test(s)) return false;
      let p = landing(n);
      if (p && ts.isJsxExpression(p)) p = p.parent;
      if (p && ts.isPropertyAssignment(p) && p.name !== n) return !CLASS_HOLDER.test(p.name.getText(sf)) && !CODE_NAME.test(p.name.getText(sf).replace(/["']/g, ""));
      if (p && ts.isJsxAttribute(p)) return DISPLAY_PROPS.test(p.name.getText(sf));
      return false;
    };
    // A plural built by hand from two word arguments: `count(n, "question", "questions")`.
    const pluralOf = (one, many) => many === one + "s" || many === one + "es" || (one.endsWith("y") && many === one.slice(0, -1) + "ies");
    const pluralPair = (n) => {
      if (!ts.isStringLiteral(n) || !/^\p{Ll}{2,}$/u.test(n.text) || !ts.isCallExpression(n.parent) || n.parent.expression === n) return false;
      // A call building a class name or a test id is code, whatever its arguments say.
      const p = landing(n.parent);
      if (p && ts.isJsxExpression(p) && ts.isJsxAttribute(p.parent) && CODE_ATTRS.test(p.parent.name.getText(sf))) return false;
      const words = n.parent.arguments.filter((a) => ts.isStringLiteral(a) && a !== n).map((a) => a.text);
      return words.some((w) => pluralOf(n.text, w) || pluralOf(w, n.text));
    };
    // The object a `<Msg elems={{ ... }}>` places into its message's slots.
    const elemsObject = (o) => {
      const attr = o && ts.isObjectLiteralExpression(o) && o.parent && ts.isJsxExpression(o.parent) ? o.parent.parent : null;
      return !!attr && ts.isJsxAttribute(attr) && attr.name.getText(sf) === "elems" && tagOf(attr.parent.parent) === "Msg";
    };
    // The object of values a message call or a `<Msg>` fills its placeholders from.
    const messageValues = (o) => elemsObject(o) || (!!o && ts.isObjectLiteralExpression(o) && messageCall(o.parent) && o.parent.arguments[0] === o);
    // A word placed into a message's slot is part of its sentence, out of the translator's reach.
    const elemsWord = (n) => {
      if (!(ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) || !/\p{L}{2,}/u.test(n.text)) return false;
      const p = landing(n);
      return !!p && ts.isPropertyAssignment(p) && p.name !== n && elemsObject(p.parent);
    };
    const habit = (node, name, str) => {
      const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
      habits.push({ file: rel, line: line + 1, habit: name, text: str });
    };
    // Catalog text by its shape in code: a message call, `msg(...)`, or a name
    // that holds a label (`bandLabel`, `fact.label`, `BAND_LABEL[x]`, `modalityLabel(x)`).
    const LABEL_NAME = /^(label|title|heading)$|Labels?$|_LABELS?$|^LABELS?$|_COPY$/;
    const copyish = (e) => {
      e = unwrap(e);
      if (!e) return false;
      if (ts.isBinaryExpression(e) && /^(\?\?|\|\|)$/.test(e.operatorToken.getText(sf))) return copyish(e.left) || copyish(e.right);
      if (ts.isConditionalExpression(e)) return copyish(e.whenTrue) || copyish(e.whenFalse);
      if (ts.isCallExpression(e)) {
        if (messageCall(e)) return true;
        const callee = unwrap(e.expression);
        // `String(label)` hands its argument on unchanged.
        if (ts.isIdentifier(callee) && callee.text === "String") return e.arguments.length === 1 && copyish(e.arguments[0]);
        return ts.isIdentifier(callee) && LABEL_NAME.test(callee.text);
      }
      if (ts.isElementAccessExpression(e)) return copyish(e.expression);
      if (ts.isPropertyAccessExpression(e)) return LABEL_NAME.test(e.name.text) || (ts.isElementAccessExpression(unwrap(e.expression)) && copyish(e.expression));
      if (ts.isIdentifier(e)) return LABEL_NAME.test(e.text);
      return false;
    };
    // Recasing that serves a comparison or a search, not a reader.
    const MATCHING = /^(includes|startsWith|endsWith|indexOf|lastIndexOf|localeCompare|match|matchAll|search|test|has|get|split|replace|replaceAll)$/;
    const forMatching = (call) => {
      let p = call.parent;
      while (p && ts.isParenthesizedExpression(p)) p = p.parent;
      if (!p) return false;
      if (ts.isPropertyAccessExpression(p) && MATCHING.test(p.name.text)) return true;
      if (ts.isBinaryExpression(p) && /^(===|!==|==|!=|<|>|<=|>=)$/.test(p.operatorToken.getText(sf))) return true;
      if (ts.isCallExpression(p) && p.expression !== call) {
        const callee = unwrap(p.expression);
        const name = ts.isPropertyAccessExpression(callee) ? callee.name.text : ts.isIdentifier(callee) ? callee.text : "";
        if (MATCHING.test(name)) return true;
      }
      return false;
    };
    const habitsAt = (n) => {
      // Punctuation written beside a message closes or opens its sentence in
      // code: "All shown (", message, ")" cannot be repunctuated by a translation.
      if (ts.isJsxElement(n) || ts.isJsxFragment(n)) {
        const kids = n.children.filter((k) => !(ts.isJsxText(k) && !k.text.trim()));
        kids.forEach((k, i) => {
          if (!ts.isJsxText(k)) return;
          const t = k.text.trim();
          if (/[\p{L}\p{N}]/u.test(t) || !/[()[\].,:;!?（）。，：；！？]/u.test(t)) return;
          if ((i > 0 && isMessageChild(kids[i - 1])) || (i < kids.length - 1 && isMessageChild(kids[i + 1]))) habit(k, "split-sentence", t);
        });
      }
      // A bare space handed to a message's placeholder is spacing the translation cannot move.
      if ((ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) && /^\s+$/.test(n.text)) {
        const p = landing(n);
        if (p && ts.isPropertyAssignment(p) && p.name !== n && messageValues(p.parent)) habit(n, "message-spacer", JSON.stringify(n.text));
      }
      // Case belongs to the language: `bandLabel.toLowerCase()` writes English rules into every locale.
      if (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) && /^to(Locale)?(Lower|Upper)Case$/.test(n.expression.name.text)
        && copyish(n.expression.expression) && !forMatching(n) && !marked(n)) habit(n, "recased-copy", n.getText(sf).slice(0, 80));
    };
    const visit = (n) => {
      habitsAt(n);
      // JSX text is rendered, never code: "found", "open" are words here.
      // A key cap (<Kbd>esc</Kbd>) is a glyph, as ⌘ K is.
      if (ts.isJsxText(n) && ts.isJsxElement(n.parent) && n.parent.openingElement.tagName.getText(sf) === "Kbd") { /* a glyph */ }
      else if (ts.isJsxText(n)) emit(n, "jsx-text", n.getText(sf), 0, true);
      else if ((ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n) || ts.isTemplateExpression(n)) && !codeContext(n)) {
        const v = tmpl(n);
        const forced = pluralBranch(n) || holdsPlural(n) || wordsBesideValues(n) || displayWord(n)
          || jsxChildWord(n) || phraseValue(n) || pluralPair(n) || elemsWord(n);
        if (marked(n)) { /* the author says this string is code */ }
        else if (v && forced && /\p{L}{2,}/u.test(v.s.replace(/\{[^}]*\}/g, " "))) emit(n, kindOf(n), v.s, v.parts, true);
        else if (v && readsAsCopy(v.s) && !/className|^\s*[.#[]/.test(v.s)) emit(n, kindOf(n), v.s, v.parts);
        if (ts.isTemplateExpression(n)) {
          // Strings nested in a template's placeholders are their own literals.
          for (const sp of n.templateSpans) ts.forEachChild(sp.expression, visit), visit(sp.expression);
          return;
        }
      }
      ts.forEachChild(n, visit);
    };
    visit(sf);
    return { sf, strings: out, habits };
  }
}

/** The habits the copy system retires, counted per file: [[relative path, { habit: count }]]. */
export function fileHabits(src) {
  const out = [];
  for (const f of sourceFiles(src)) {
    const rel = relative(src, f).split(sep).join("/");
    if (rel === "copy/format.ts" || rel.startsWith("copy/format/") || rel === "copy/runtime.ts") continue;
    const text = readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    out.push([rel, {
      "locale-call": (text.match(/\.toLocale\w*String\(|new Intl\.\w+\(/g) ?? []).length,
      "plural-ternary": (text.match(/(===|!==)\s*1\s*\?/g) ?? []).length,
      "locale-compare": (text.match(/\.localeCompare\(|Intl\.Collator/g) ?? []).length,
      "error-message-shown": (text.match(/\b(err|error|caught|e|reason|exc)\.message\b/g) ?? []).length,
    }]);
  }
  return out;
}
