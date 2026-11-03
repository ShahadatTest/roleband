/* Brace-accurate CSS reader that keeps EXACT SOURCE SPANS.
 *
 * Every node records [start,end) offsets into the original text, so a mover
 * splices source rather than re-rendering it: a re-rendered sheet loses its
 * comments, which are this repo's docs.
 *
 * Handles: nesting, at-rules, comments, strings, url(), and the parent-prelude
 * case a regex mover gets wrong ("min-width:0; flex:1; .stage-band").
 */
export function parse(src) {
  let i = 0;
  const n = src.length;

  function skipTrivia() {
    for (;;) {
      if (i < n && /\s/.test(src[i])) { i++; continue; }
      if (src.startsWith("/*", i)) {
        const end = src.indexOf("*/", i + 2);
        i = end === -1 ? n : end + 2;
        continue;
      }
      return;
    }
  }

  // Advance past one string / comment / url token if we are on one.
  function skipToken() {
    const c = src[i];
    if (c === '"' || c === "'") {
      const q = c; i++;
      while (i < n) {
        if (src[i] === "\\") { i += 2; continue; }
        if (src[i] === q) { i++; return true; }
        i++;
      }
      return true;
    }
    if (src.startsWith("/*", i)) {
      const end = src.indexOf("*/", i + 2);
      i = end === -1 ? n : end + 2;
      return true;
    }
    return false;
  }

  function parseBlock(stop) {
    const nodes = [];
    for (;;) {
      skipTrivia();
      if (i >= n) break;
      if (stop && src[i] === "}") break;

      const start = i;
      // Scan the prelude up to `{` or `;` at depth 0.
      let preludeEnd = -1;
      let kind = null;
      while (i < n) {
        if (skipToken()) continue;
        const c = src[i];
        if (c === "(") { // balanced parens (media queries, :not(), url())
          let d = 0;
          while (i < n) {
            if (skipToken()) continue;
            if (src[i] === "(") d++;
            else if (src[i] === ")") { d--; if (d === 0) { i++; break; } }
            i++;
          }
          continue;
        }
        if (c === "{") { preludeEnd = i; kind = "block"; break; }
        if (c === ";") { preludeEnd = i; kind = "statement"; break; }
        if (c === "}") { preludeEnd = i; kind = "statement"; break; } // unterminated
        i++;
      }
      if (preludeEnd === -1) break;

      const prelude = src.slice(start, preludeEnd).trim();

      if (kind === "statement") {
        // A declaration or an at-statement (@import/@charset). Not a rule.
        if (src[i] === ";") i++;
        nodes.push({ type: "statement", text: prelude, start, end: i });
        continue;
      }

      i = preludeEnd + 1; // past `{`
      const children = parseBlock(true);
      if (src[i] === "}") i++;
      const end = i;

      nodes.push({
        type: prelude.startsWith("@") ? "atrule" : "rule",
        prelude,
        children,
        start,
        end,
        bodyStart: preludeEnd + 1,
        bodyEnd: end - 1,
      });
    }
    return nodes;
  }

  return parseBlock(false);
}

/** Every rule node, with its chain of ancestors (outermost first). */
export function walk(nodes, ancestors = [], out = []) {
  for (const node of nodes) {
    if (node.type === "statement") continue;
    out.push({ node, ancestors });
    walk(node.children, [...ancestors, node], out);
  }
  return out;
}

/** Selector parts, split on top-level commas. */
export function selectorParts(prelude) {
  const parts = [];
  let depth = 0, cur = "";
  for (let k = 0; k < prelude.length; k++) {
    const c = prelude[k];
    if (c === "(" || c === "[") depth++;
    else if (c === ")" || c === "]") depth--;
    else if (c === "," && depth === 0) { parts.push(cur.trim()); cur = ""; continue; }
    cur += c;
  }
  if (cur.trim()) parts.push(cur.trim());
  return parts;
}

/** Leading class tokens of a selector part, e.g. `.stage-band > .x` -> stage-band, x */
export function classesIn(part) {
  return [...part.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)].map((m) => m[1]);
}

/** The class the rule is ABOUT: the first class in the part. */
export function subjectClass(part) {
  const m = part.match(/\.(-?[_a-zA-Z][\w-]*)/);
  return m ? m[1] : null;
}
