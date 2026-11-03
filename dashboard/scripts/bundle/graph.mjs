// The startup graph of one Vite build: the entry chunk, every chunk it
// imports statically (a browser fetches those before the app can run), their
// CSS, and the modules inside them. Pure: it reads a Rolldown bundle, it writes
// nothing. `plugins.mjs` feeds it from the real build, `check-bundle-size.mjs`
// from the stubbed one.

/** A module id as the gate names it: dashboard-relative, no bundler \0 prefix
 *  and no query, so the same file reads the same in every build and checkout. */
function moduleName(id, root) {
  let name = id.replace(/^\0/, "").replace(/\?.*$/, "");
  const nm = name.lastIndexOf("/node_modules/");
  if (nm >= 0) return name.slice(nm + 1);
  if (root && name.startsWith(root + "/")) name = name.slice(root.length + 1);
  return name;
}

/**
 * `chunks` is a Rolldown bundle's chunk list (`Object.values(bundle)` in a
 * plugin, `output.output` from `build({ write: false })`). Returns the entry's
 * startup files and, per module, its pre-minify bytes and the exports Rolldown
 * kept. Found by `isEntry`, never by file name: a lazy chunk built from an
 * `index.ts` is also called `index-*.js`. `importersOf(id)` (a plugin's
 * `this.getModuleInfo(id).importers`) adds, per startup module, the modules
 * OUTSIDE the startup files that import it, which is who to ask about a
 * lazy-only export.
 */
export function startupOf(chunks, root, importersOf) {
  const byFile = new Map(chunks.filter((c) => c.type === "chunk").map((c) => [c.fileName, c]));
  const entries = [...byFile.values()].filter((c) => c.isEntry);
  if (entries.length !== 1) throw new Error(`bundle graph: expected one entry chunk, found ${entries.length}`);
  const js = [];
  const css = new Set();
  const modules = {};
  const visit = (file) => {
    if (js.includes(file)) return;
    const chunk = byFile.get(file);
    if (!chunk) return;
    js.push(file);
    for (const sheet of chunk.viteMetadata?.importedCss ?? []) css.add(sheet);
    for (const [id, info] of Object.entries(chunk.modules)) {
      modules[moduleName(id, root)] = { bytes: info.renderedLength, exports: [...info.renderedExports].sort() };
    }
    for (const dep of chunk.imports) visit(dep);
  };
  visit(entries[0].fileName);
  if (importersOf) {
    const startupIds = new Set(js.flatMap((file) => Object.keys(byFile.get(file).modules)));
    for (const file of js) {
      for (const id of Object.keys(byFile.get(file).modules)) {
        const outside = (importersOf(id) ?? []).filter((by) => !startupIds.has(by)).map((by) => moduleName(by, root));
        if (outside.length) modules[moduleName(id, root)].lazyImporters = [...new Set(outside)].sort();
      }
    }
  }
  return { entry: entries[0].fileName, js, css: [...css], modules };
}
