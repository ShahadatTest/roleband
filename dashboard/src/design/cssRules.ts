/* The design gates' CSS reader, shared so every gate reads a stylesheet the
 * same way. Brace-accurate, string- and comment-aware, nesting resolved by
 * joining parent and child selectors. */

export type Rule = { selectors: string[]; scope: string; decls: Map<string, string>; line: number };

/** Brace-accurate, string- and comment-aware. A regex over `{}` pairs reads a
 *  nested rule that follows declarations as a selector of
 *  "min-width: 0; flex: 1; .stage-band" and skips it. */
export function rules(css: string): Rule[] {
  const out: Rule[] = [];
  let i = 0;

  const parseBlock = (scope: string, parentSel: string, stop: boolean) => {
    for (;;) {
      while (i < css.length && /\s/.test(css[i])) i++;
      if (css.startsWith("/*", i)) { i = css.indexOf("*/", i + 2) + 2 || css.length; continue; }
      if (i >= css.length || (stop && css[i] === "}")) return;

      const start = i;
      let kind: "block" | "statement" | null = null;
      while (i < css.length) {
        const c = css[i];
        if (c === '"' || c === "'") {
          const q = c; i++;
          while (i < css.length && css[i] !== q) i += css[i] === "\\" ? 2 : 1;
          i++; continue;
        }
        if (css.startsWith("/*", i)) { i = css.indexOf("*/", i + 2) + 2 || css.length; continue; }
        if (c === "(") { let d = 0; while (i < css.length) { if (css[i] === "(") d++; else if (css[i] === ")" && --d === 0) { i++; break; } i++; } continue; }
        if (c === "{" || c === ";" || c === "}") { kind = c === "{" ? "block" : "statement"; break; }
        i++;
      }
      if (kind === null) return;

      const prelude = css.slice(start, i).trim();
      if (kind === "statement") { if (css[i] === ";") i++; continue; }
      i++; // past `{`

      const isAt = prelude.startsWith("@");
      const bodyStart = i;
      const nested: Rule[] = [];
      const before = out.length;
      parseBlock(
        isAt ? [scope, prelude].filter(Boolean).join(" && ") : scope,
        isAt ? parentSel : [parentSel, prelude].filter(Boolean).join(" "),
        true,
      );
      const bodyEnd = i;
      if (css[i] === "}") i++;
      void nested; void before;

      if (!isAt && !prelude.startsWith("@")) {
        const decls = new Map<string, string>();
        // Only this rule's own declarations: children were consumed above, and
        // a declaration never contains a brace outside a string or paren.
        // Comments go first: a declaration written after one (`/* why */ outline: none;`)
        // has no `;` before it, and would silently not be read.
        const body = css.slice(bodyStart, bodyEnd).replace(/\/\*[\s\S]*?\*\//g, "").replace(/\{[^{}]*\}/g, "");
        for (const m of body.matchAll(/(?:^|;)\s*([-\w]+)\s*:\s*([^;{}]+)/g)) {
          decls.set(m[1], m[2].replace(/\s+/g, " ").trim());
        }
        const full = [parentSel, prelude].filter(Boolean).join(" ");
        out.push({
          selectors: splitSelectors(full),
          scope: isAt ? [scope, prelude].filter(Boolean).join(" && ") : scope,
          decls,
          line: css.slice(0, start).split("\n").length,
        });
      }
    }
  };
  parseBlock("", "", false);
  return out;
}

function splitSelectors(prelude: string): string[] {
  const parts: string[] = [];
  let depth = 0, cur = "";
  for (const c of prelude) {
    if (c === "(" || c === "[") depth++;
    else if (c === ")" || c === "]") depth--;
    else if (c === "," && depth === 0) { parts.push(cur); cur = ""; continue; }
    cur += c;
  }
  parts.push(cur);
  // settings.css nests under `.settings-design-system`; that marker is SCOPE,
  // not identity, so it is stripped before the two sheets are compared.
  return parts
    .map((p) => p.replace(/^\s*&\s*/, "").replace(/\s+/g, " ").trim())
    // Strip the marker only when it SCOPES something. `.settings-design-system`
    // on its own is the scope root's own rule, not a scoped copy of anything.
    .map((p) =>
      p
        .replace(/^body\[data-settings-design-system="active"\]\s+/, "")
        .replace(/^body\.settings-design-system\s+/, "")
        .replace(/^\.settings-design-system\s+/, ""),
    )
    .filter(Boolean);
}
