/* A context provider's value must be stable between renders. An inline object
   or function is a new value every render, so every consumer under the
   provider re-renders on any change above it; `isolation.test.tsx` proves the
   app's own providers do not, but only the ones `AppProviders` mounts. This
   scan covers every provider in src: its value is an identifier declared by
   `useMemo`, `useCallback`, `useRef` or `useState`, or by a custom hook that
   returns `useMemo`/`useCallback`. */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

function sourceFiles(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) sourceFiles(path, acc);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) acc.push(path);
  }
  return acc;
}

const FILES = sourceFiles(SRC).map((path) => ({ path, source: readFileSync(path, "utf8") }));
const STABLE_HOOK = /^(?:useMemo|useCallback|useRef)\s*[<(]/;

/** Whether a custom hook, defined somewhere in src, returns a memoized value. */
function hookIsStable(name: string): boolean {
  for (const { source } of FILES) {
    const at = source.search(new RegExp(`function ${name}\\s*[<(]`));
    if (at < 0) continue;
    const body = source.slice(at, at + 4000);
    return /return\s+(?:useMemo|useCallback)\s*[<(]/.test(body);
  }
  return false;
}

/** Why a provider's value is unstable, or null when it is stable. `source` is
 *  the file up to the provider: the declaration nearest before it is the one
 *  in scope (a file can name `value` in several components). */
export function unstableValue(expression: string, source: string): string | null {
  const value = expression.trim();
  if (/^[{[(]|^function\b|^async\b|=>/.test(value)) return `an inline value (${value.slice(0, 30)})`;
  if (!/^\w+$/.test(value)) return null;
  const declarations = [...source.matchAll(new RegExp(`const\\s+${value}\\s*(?::[^=]+)?=\\s*([^;\\n]+)`, "g"))];
  const declared = declarations[declarations.length - 1];
  const fromState = new RegExp(`const\\s*\\[\\s*${value}\\s*,[^\\]]*\\]\\s*=\\s*useState`).test(source);
  if (fromState) return null;
  if (!declared) return null; // a prop or a module constant: not built in this render
  const rhs = declared[1].trim();
  if (STABLE_HOOK.test(rhs)) return null;
  const hook = rhs.match(/^(use[A-Z]\w*)\s*[<(]/)?.[1];
  if (hook) return hookIsStable(hook) ? null : `${value} comes from ${hook}, which returns no memoized value`;
  return `${value} is built in the render (${rhs.slice(0, 30)})`;
}

/** Every `X.Provider value={...}` and React 19 `<Ctx value={...}>` of a context. */
function providers(source: string): { expression: string; at: number }[] {
  const contexts = [...source.matchAll(/const\s+(\w+)\s*=\s*(?:\/\*[^*]*\*\/\s*)?createContext/g)].map((m) => m[1]);
  const out: { expression: string; at: number }[] = [];
  for (const m of source.matchAll(/<(\w+)\.Provider\s+value=\{([^}]*(?:\{[^}]*\}[^}]*)*)\}/g)) {
    out.push({ expression: m[2], at: m.index ?? 0 });
  }
  for (const name of contexts) {
    for (const m of source.matchAll(new RegExp(`<${name}\\s+value=\\{([^}]*(?:\\{[^}]*\\}[^}]*)*)\\}`, "g"))) {
      out.push({ expression: m[1], at: m.index ?? 0 });
    }
  }
  return out;
}

describe("context provider values are stable", () => {
  it("every provider in src passes a memoized or stable value", () => {
    const offenders: string[] = [];
    let seen = 0;
    for (const { path, source } of FILES) {
      for (const { expression, at } of providers(source)) {
        seen++;
        const why = unstableValue(expression, source.slice(0, at));
        if (why) offenders.push(`${relative(SRC, path)}: ${why}`);
      }
    }
    expect(seen, "the scan found no provider at all").toBeGreaterThan(3);
    expect(offenders).toEqual([]);
  });

  it.each([
    ["{{ toast, dismiss }}".slice(1, -1), "", true],
    ["() => setOpen(true)", "", true],
    ["value", "const value = { search };", true],
    ["value", "const value = useMemo(() => ({ search }), [search]);", false],
    ["api", "const [api, setApi] = useState(null);", false],
  ])("the scan judges value={%s} (negative controls included)", (expression, source, unstable) => {
    expect(unstableValue(expression, source) !== null).toBe(unstable);
  });
});
