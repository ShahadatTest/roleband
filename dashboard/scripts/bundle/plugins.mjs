// The two Vite plugins the startup gate reads its builds through
// (scripts/check-bundle-size.mjs).
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { startupOf } from "./graph.mjs";

export const REPORT_PATH = ".vite/startup-report.json";

/** Writes the real build's startup graph to `dist/.vite/startup-report.json`.
 *  `writeBundle`, not `generateBundle`: a `write: false` build (the stubbed one
 *  below) must never overwrite the report of the build that shipped. */
export function startupReport() {
  let root = "";
  let outDir = "";
  let report = null;
  return {
    name: "roleband-startup-report",
    apply: "build",
    configResolved(config) {
      root = config.root;
      outDir = resolve(config.root, config.build.outDir);
    },
    generateBundle(_options, bundle) {
      report = startupOf(Object.values(bundle), root, (id) => this.getModuleInfo(id)?.importers);
    },
    writeBundle() {
      const path = join(outDir, REPORT_PATH);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, JSON.stringify(report, null, 1));
    },
  };
}

const EMPTY = "\0roleband-empty-lazy";

/** Every dynamic `import()` resolves to one empty module, so the build is the
 *  app as if no lazy screen existed. What the real shell carries beyond this
 *  build's shell is there only because a lazy screen uses it. */
export function stubLazy() {
  return {
    name: "roleband-stub-lazy",
    enforce: "pre",
    resolveDynamicImport(specifier) {
      return typeof specifier === "string" ? EMPTY : null;
    },
    resolveId(id) {
      return id === EMPTY ? id : null;
    },
    load(id) {
      return id === EMPTY ? "export default function Empty() { return null; }" : null;
    },
  };
}
