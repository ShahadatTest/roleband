/* The startup gate's decisions (scripts/check-bundle-size.mjs). The
   boundary half runs REAL Rolldown, the bundler Vite builds with,
   over a small in-memory app, built twice exactly as the gate builds it, so
   what is asserted is Rolldown's chunking and tree-shaking, not a hand-written
   stand-in for them. Each failure case has its negative control beside it. */
import { describe, expect, it } from "vitest";
import { rolldown, type Plugin } from "rolldown";
import { boundaryProblems, confinementProblems, driftProblems, lazyOnly, snapshotOf, type Boundary } from "../../scripts/bundle/gate.mjs";
import { startupOf } from "../../scripts/bundle/graph.mjs";
import { stubLazy } from "../../scripts/bundle/plugins.mjs";

const ROOT = "/app";
const APP: Record<string, string> = {
  // The shell uses `shellFn` and the context hook `useCtx`; it opens a screen lazily.
  "src/entry.js": `import { shellFn } from "./util.js"; import { useCtx } from "./ctx.js";
    console.log(shellFn(), useCtx()); export const open = () => import("./screen.js");`,
  // A utility module the shell loads for one function, with two more only the screen calls.
  "src/util.js": `import { TABLE } from "./table.js";
    export function shellFn() { return "shell"; }
    export function lazyFn() { return "lazy"; }
    export function label(key) { return TABLE[key]; }`,
  // Reached only through `label`: in the shell only because the screen calls `label`.
  "src/table.js": `export const TABLE = { a: "Alpha", b: "Beta" };`,
  // A context the shell provides; screens read it through a hook of their own.
  "src/ctx.js": `const value = { n: 1 }; export function useCtx() { return value.n; } export function useScreenCtx() { return value; }`,
  "src/screen.js": `import { lazyFn, label, shellFn } from "./util.js"; import { useScreenCtx } from "./ctx.js";
    export default function Screen() { return [lazyFn(), label("a"), shellFn(), useScreenCtx()]; }`,
};

function app(files: Record<string, string>): Plugin {
  return {
    name: "in-memory-app",
    resolveId(source, importer) {
      if (!importer) return `${ROOT}/${source}`;
      const dir = importer.slice(0, importer.lastIndexOf("/"));
      return `${dir}/${source.replace(/^\.\//, "")}`;
    },
    load(id) {
      const key = id.slice(ROOT.length + 1);
      if (key in files) return files[key];
      return null;
    },
  };
}

async function startup(files: Record<string, string>, stub: boolean) {
  const plugins = stub ? [stubLazy() as unknown as Plugin, app(files)] : [app(files)];
  const bundle = await rolldown({ input: "src/entry.js", plugins, logLevel: "silent" });
  const { output } = await bundle.generate({ format: "es" });
  return startupOf(output, ROOT).modules;
}

const empty: Boundary = { infrastructure: [], debt: [] };

describe("shell boundary, through real Rolldown", () => {
  it("names the exports and the module that only a lazy screen put in the shell, and nothing the shell uses", async () => {
    const found = lazyOnly(await startup(APP, false), await startup(APP, true));
    const names = found.map((p) => (p.export ? `${p.module}#${p.export}` : p.module)).sort();
    expect(names).toEqual(["src/ctx.js#useScreenCtx", "src/table.js", "src/util.js#label", "src/util.js#lazyFn"]);
    // Negative controls: what the shell itself uses is never flagged.
    expect(names).not.toContain("src/util.js#shellFn");
    expect(names).not.toContain("src/ctx.js#useCtx");
  });

  it("finds nothing once the screen-only code lives in a module the shell does not import", async () => {
    const fixed = {
      ...APP,
      "src/util.js": `export function shellFn() { return "shell"; }`,
      "src/screenUtil.js": `import { TABLE } from "./table.js"; export function lazyFn() { return "lazy"; } export function label(key) { return TABLE[key]; }`,
      "src/screen.js": `import { shellFn } from "./util.js"; import { lazyFn, label } from "./screenUtil.js"; import { useScreenCtx } from "./ctx.js";
        export default function Screen() { return [lazyFn(), label("a"), shellFn(), useScreenCtx()]; }`,
    };
    const found = lazyOnly(await startup(fixed, false), await startup(fixed, true));
    expect(found.map((p) => `${p.module}#${p.export ?? ""}`)).toEqual(["src/ctx.js#useScreenCtx"]);
  });

  it("fails a new leak, passes infrastructure and debt, and names paid-off debt", async () => {
    const full = await startup(APP, false);
    const found = lazyOnly(full, await startup(APP, true));
    const fresh = boundaryProblems(found, empty, {});
    expect(fresh.failures.join("\n")).toMatch(/src\/util\.js \{label, lazyFn\}/);
    expect(fresh.failures.join("\n")).toMatch(/src\/table\.js is in the startup chunk/);

    const declared: Boundary = {
      infrastructure: [{ module: "src/ctx.js", exports: ["useScreenCtx"], why: "a context hook screens read" }],
      debt: [{ module: "src/util.js", export: "lazyFn" }, { module: "src/util.js", export: "label" }, { module: "src/table.js" }],
    };
    const clean = boundaryProblems(found, declared, {});
    expect(clean.failures).toEqual([]);
    expect(clean.stale).toEqual([]);

    // Infrastructure names exports: a different export of the same module still fails.
    const narrow = boundaryProblems(found, { ...declared, infrastructure: [{ module: "src/ctx.js", exports: ["other"], why: "x" }] }, {});
    expect(narrow.failures.join("\n")).toMatch(/src\/ctx\.js \{useScreenCtx\}/);

    const paid = boundaryProblems(found, { ...declared, debt: [...declared.debt, { module: "src/gone.js" }] }, {});
    expect(paid.stale).toEqual([expect.stringMatching(/src\/gone\.js is no longer a leak/)]);
  });

  it("warns, and files as debt, only what the shell itself stopped using; recording never launders a leak", async () => {
    const full = await startup(APP, false);
    const stubbed = await startup(APP, true);
    const found = lazyOnly(full, stubbed);
    // A snapshot recorded WHILE the leak existed: its `shell` field never holds a lazy-only export.
    const recordedWithLeak = snapshotOf(full, stubbed);
    expect(boundaryProblems(found, empty, recordedWithLeak).failures).toHaveLength(3);
    // A snapshot from when the shell still called lazyFn itself.
    const before = { ...recordedWithLeak, "src/util.js": { ...recordedWithLeak["src/util.js"]!, shell: ["shellFn", "lazyFn"] } };
    const result = boundaryProblems(found, empty, before);
    expect(result.warnings.join("\n")).toMatch(/src\/util\.js \{lazyFn\}/);
    expect(result.failures.join("\n")).toMatch(/src\/util\.js \{label\}/);
    expect(result.shed).toEqual([{ module: "src/util.js", export: "lazyFn" }]);
  });
});

describe("confined directories", () => {
  const rule = { dir: "src/api/", allow: ["src/api/shell.ts", "src/api/transport.ts"], why: "the shell's door" };
  const info = (bytes: number) => ({ bytes, exports: [] });
  it("fails a module of the directory the rule does not allow, naming every one in one line", () => {
    const problems = confinementProblems(
      { "src/api/shell.ts": info(10), "src/api/jobs.ts": info(900), "src/api/index.ts": info(40), "src/App.tsx": info(5) },
      [rule],
    );
    expect(problems).toEqual([expect.stringMatching(/^src\/api\/index\.ts, src\/api\/jobs\.ts entered the startup chunk/)]);
  });
  it("passes the allowed modules, code outside the directory, and a module tree-shaken to nothing", () => {
    expect(confinementProblems({ "src/api/shell.ts": info(10), "src/api/transport.ts": info(10), "src/App.tsx": info(5), "src/api/jobs.ts": info(0) }, [rule])).toEqual([]);
  });
});

describe("startup size against the recorded measure", () => {
  const recorded = { js: 300_000, css: 60_000, slack: 512, cap: 320_000 };
  it("passes inside the slack in both directions", () => {
    expect(driftProblems({ js: 300_512, css: 59_488 }, recorded)).toEqual([]);
  });
  it("fails beyond the slack in either direction, naming the kind and the delta", () => {
    expect(driftProblems({ js: 300_513, css: 60_000 }, recorded)).toEqual([expect.stringMatching(/startup js .*\+513 B/)]);
    expect(driftProblems({ js: 300_000, css: 59_487 }, recorded)).toEqual([expect.stringMatching(/startup css .*-513 B/)]);
  });
  it("fails over the cap even when recorded there", () => {
    expect(driftProblems({ js: 320_001, css: 60_000 }, { ...recorded, js: 320_001 })).toEqual([expect.stringMatching(/over the cap/)]);
  });
});
