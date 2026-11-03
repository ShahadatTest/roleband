import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { copyCatalog } from "./scripts/copy/vite-plugin.mjs";
import { startupReport } from "./scripts/bundle/plugins.mjs";
import csp from "./csp-policy.json" with { type: "json" };

// Proxy /api to the FastAPI backend so the dashboard uses same-origin requests.
// Target is overridable via VITE_API_TARGET (e.g. to run against a second API on
// another port); it defaults to the standard dev backend on :8010.
const API_TARGET = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8010";

/* The Content-Security-Policy the API serves the dashboard under
   (backend/tracker/api/csp.py renders the same file with the configured
   usage-statistics host). The preview serves it too, with the host the UX
   fixtures' usage state names, so the suite runs the build under the policy. */
const PREVIEW_CSP = Object.entries(csp.directives)
  .map(([name, values]) => [name, ...values.map((v) => (v === "{usage_host}" ? "https://eu.i.posthog.com" : v))].join(" "))
  .join("; ");

/* Where the build goes. The supervisor builds beside the dist the API serves and
   swaps it in once whole (deploy/build_dashboard.sh); scripts/check-bundle-size.mjs
   reads the same variable. */
const OUT_DIR = process.env.ROLEBAND_DIST_OUT || "dist";

export default defineConfig({
  /* startupReport writes dist/.vite/startup-report.json, the startup graph
     scripts/check-bundle-size.mjs gates. */
  plugins: [react(), copyCatalog(), startupReport()],
  build: { outDir: OUT_DIR },
  server: {
    // Defaults to the standard dev port; PORT lets a second instance run alongside it.
    port: Number(process.env.PORT) || 5173,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
  /* `preview` serves the BUILD, and it needs the same proxy for the same
     reason. Without it the two servers disagree about what an unmocked /api
     call does — dev forwards it, preview falls through to the SPA fallback and
     answers index.html, so the client gets HTML where it expected JSON, and a
     spec fails against a build while passing against dev with a failure that
     names a chunk when the cause is an API response. A test harness must not
     change behaviour depending on which server is answering. */
  preview: {
    port: Number(process.env.PORT) || 5173,
    headers: { "Content-Security-Policy": PREVIEW_CSP },
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
});
