// Compiles the copy catalog for Vite and Vitest (docs/copy.md,
// section 2). src/copy/gen/ is generated, never committed: its message ids are
// positions, so a committed copy would turn every parallel addition into a merge
// that could renumber silently. This plugin writes it when a server or build starts and
// again whenever a catalog file changes; the npm hooks cover tsc and eslint, which
// run without Vite.
import { join } from "node:path";
import { Worker } from "node:worker_threads";
import { CopyError, build, write } from "../gen-copy.mjs";

const SOURCES = /src[\\/]copy[\\/](?!gen[\\/]).*\.(ftl|json|yaml)$/;

const DECK_PAGE =
  '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>' +
  '<body><div id="root"></div><script type="module" src="/src/copy/review/main.tsx"></script></body></html>';

/** The dev server's copy review deck: its page, and its data built in a worker.
    Catalog review is CPU work; the worker keeps Vite free to serve the app and
    lazy language imports while the deck checks every pattern. */
function reviewDeck(server) {
  const deckData = () =>
    new Promise((resolve, reject) => {
      const worker = new Worker(new URL("./review-worker.mjs", import.meta.url));
      worker.once("message", resolve);
      worker.once("error", reject);
      worker.once("exit", (code) => {
        if (code !== 0) reject(new Error(`copy review worker exited ${code}`));
      });
    });
  return async (req, res, next) => {
    if (req.url === "/__copy-review/data") {
      try {
        const data = await deckData();
        res.setHeader("Content-Type", "application/json");
        res.end(data);
      } catch (error) {
        res.statusCode = 500;
        res.end(String(error));
      }
      return;
    }
    if (req.url === "/__copy-review/") {
      const html = await server.transformIndexHtml(req.url, DECK_PAGE);
      res.setHeader("Content-Type", "text/html");
      res.end(html);
      return;
    }
    next();
  };
}

export function copyCatalog() {
  const generate = () => write(build({ twin: false }).files);
  return {
    name: "roleband-copy-catalog",
    buildStart() {
      generate(); // a CopyError fails the build with the catalog's own message
    },
    config() {
      // The deck links each message to its source file.
      return { define: { __COPY_SOURCE_ROOT__: JSON.stringify(join(process.cwd(), "src/copy")) } };
    },
    configureServer(server) {
      server.middlewares.use(reviewDeck(server));
      server.watcher.add(join(server.config.root, "src", "copy"));
      const regenerate = (file) => {
        if (!SOURCES.test(file)) return;
        try {
          const written = generate();
          if (written.length) server.config.logger.info(`copy: ${written.length} generated files updated`, { timestamp: true });
        } catch (error) {
          if (!(error instanceof CopyError)) throw error;
          server.config.logger.error(`copy: ${error.message}`, { timestamp: true });
        }
      };
      server.watcher.on("change", regenerate);
      server.watcher.on("add", regenerate);
      server.watcher.on("unlink", regenerate);
    },
  };
}
