/* `package.json` "sideEffects" declares every module of ours side-effect-free
   except stylesheets. That is what keeps a module-level call (`new Set(...)`,
   `forwardRef(...)`, `createContext(...)`) from pinning a module the shell
   does not use into the startup chunk.

   Its one failure mode is silent and production-only: a module imported for
   its EFFECT alone (`import "./register"`) is dropped from the build, and the
   dev server, which does not tree-shake, never shows it. So such an import
   must be declared, and this test names an undeclared one. */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, normalize, relative } from "node:path";
import { describe, expect, it } from "vitest";

const DASHBOARD = process.cwd();
const SRC = join(DASHBOARD, "src");
const pkg = JSON.parse(readFileSync(join(DASHBOARD, "package.json"), "utf8")) as { sideEffects?: string[] };

/** Relative specifiers a file imports for effect only, CSS aside. */
function bareImports(source: string): string[] {
  return [...source.matchAll(/^\s*import\s+["']([^"']+)["']\s*;?\s*$/gm)]
    .map((m) => m[1]!)
    .filter((spec) => spec.startsWith(".") && !spec.endsWith(".css"));
}

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return path === join(SRC, "test") ? [] : sources(path);
    // Zone probes import a module on purpose to break a lint boundary; no build includes them.
    return /\.(ts|tsx)$/.test(name) && !/\.test\.|\.fixture\./.test(name) ? [path] : [];
  });
}

describe("side-effect declaration", () => {
  it("declares our modules side-effect-free except stylesheets", () => {
    expect(pkg.sideEffects).toContain("**/*.css");
  });

  it("finds a bare import, and leaves a binding import and a stylesheet alone", () => {
    const sample = `import "./register";\nimport { x } from "./x";\nimport "./a.css";\nimport "@fontsource/x";\n`;
    expect(bareImports(sample)).toEqual(["./register"]);
  });

  it("every module of ours imported for effect alone is declared in sideEffects", () => {
    const declared = new Set((pkg.sideEffects ?? []).map((p) => normalize(p)));
    const undeclared = sources(SRC).flatMap((file) =>
      bareImports(readFileSync(file, "utf8"))
        .map((spec) => relative(DASHBOARD, join(dirname(file), spec)))
        .filter((target) => ![".ts", ".tsx", ""].some((ext) => declared.has(normalize(`${target}${ext}`))))
        .map((target) => `${relative(DASHBOARD, file)} imports ${target} for its effect; add "./${target}.ts(x)" to package.json "sideEffects", or the production build drops it`),
    );
    expect(undeclared).toEqual([]);
  });
});
