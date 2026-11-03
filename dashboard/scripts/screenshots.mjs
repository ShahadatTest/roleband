#!/usr/bin/env node
/* The README's role page screenshots, made from the synthetic dataset on a
   throwaway database. The Radar picture is a capture of a real install, so this
   script never writes it.

   npm run screenshots                 # build, seed, shoot, write docs/images/job-detail*.webp
   npm run screenshots -- --no-build   # reuse the current dashboard/dist
   npm run screenshots -- --keep       # leave the scratch database for a look afterwards

   Nothing here reads or writes the live database: the API runs with
   ROLEBAND_PGDATA pointed at a fresh temporary cluster and ROLEBAND_DATABASE_URL
   empty, the synthetic seed refuses any database holding rows it did not write,
   and usage sharing is switched off. Plugins stay off, as a first install has them.
   The seed records no company as read, on purpose (fabricated rows are never
   evidence), so the header would say "Not scanned yet"; the browser alone gets a
   status answer patched to a check two hours ago. The data is synthetic either
   way, and the README says so.
   Chromium encodes WebP from its own screenshot, so no image library is needed.
   Each file must stay under the cap that backend/tests/test_docs_closed_set.py
   enforces; quality steps down until it does. */

import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const DASHBOARD = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = resolve(DASHBOARD, "..");
const BACKEND = join(ROOT, "backend");
const PYTHON = join(BACKEND, ".venv", "bin", "python");
const OUT = join(ROOT, "docs", "images");
const MAX_BYTES = 300 * 1024;
const PORT = Number(process.env.SCREENSHOT_PORT ?? 8031);
const BASE = `http://127.0.0.1:${PORT}`;
const VIEWPORT = { width: 1440, height: 900 };

const args = new Set(process.argv.slice(2));
const scratch = mkdtempSync(join(tmpdir(), "roleband-shots-"));
const pgdata = join(scratch, "db");
const env = {
  ...process.env,
  ROLEBAND_PGDATA: pgdata,
  ROLEBAND_DATABASE_URL: "",
  ROLEBAND_PLUGINS: "false",
  ROLEBAND_NO_USAGE_STATS: "1",
};

function run(cmd, argv, cwd) {
  console.log(`$ ${cmd} ${argv.join(" ")}`);
  const result = spawnSync(cmd, argv, { cwd, env, stdio: "inherit" });
  if (result.status !== 0) throw new Error(`${cmd} ${argv.join(" ")} exited ${result.status}`);
}

async function waitForApi(api) {
  for (let i = 0; i < 180; i += 1) {
    if (api.exitCode !== null) throw new Error(`the API exited ${api.exitCode} before answering`);
    try {
      const res = await fetch(`${BASE}/api/status`);
      if (res.ok) return;
    } catch {
      /* not listening yet */
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error("the API did not answer within 3 minutes");
}

async function firstJob() {
  const res = await fetch(`${BASE}/api/jobs?limit=20`);
  const body = await res.json();
  const withPay = body.items.find((job) => job.comp_median != null) ?? body.items[0];
  if (!withPay) throw new Error("the seeded database has no jobs");
  return withPay;
}

/** Chromium re-encodes its own PNG as WebP, stepping quality down until the file fits. */
async function toWebp(encoder, png) {
  for (const quality of [0.86, 0.8, 0.72, 0.64, 0.56]) {
    const dataUrl = await encoder.evaluate(
      async ({ b64, q }) => {
        const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        const bitmap = await createImageBitmap(new Blob([bytes], { type: "image/png" }));
        const canvas = document.createElement("canvas");
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        canvas.getContext("2d").drawImage(bitmap, 0, 0);
        return canvas.toDataURL("image/webp", q);
      },
      { b64: png.toString("base64"), q: quality },
    );
    const webp = Buffer.from(dataUrl.split(",")[1], "base64");
    if (webp.length <= MAX_BYTES) return { webp, quality };
  }
  throw new Error(`cannot fit a screenshot under ${MAX_BYTES} bytes`);
}

async function shoot(browser, encoder, { name, path, theme }) {
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 2,
    colorScheme: theme,
    reducedMotion: "reduce",
    locale: "en-US",
  });
  await context.addInitScript((t) => window.localStorage.setItem("theme", t), theme);
  const page = await context.newPage();
  await page.route(`${BASE}/api/status`, async (route) => {
    const response = await route.fetch();
    const status = await response.json();
    status.last_success_age_hours = 2;
    status.last_success_at = new Date(Date.now() - 2 * 3600_000).toISOString();
    status.stale = false;
    await route.fulfill({ response, json: status });
  });
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(800);
  const png = await page.screenshot({ type: "png" });
  await context.close();
  const { webp, quality } = await toWebp(encoder, png);
  writeFileSync(join(OUT, `${name}.webp`), webp);
  console.log(`  ${name}.webp  ${Math.round(webp.length / 1024)} KiB  (quality ${quality})`);
}

let api;
try {
  if (!existsSync(PYTHON)) throw new Error(`no backend virtualenv at ${PYTHON}; run ./setup.sh first`);
  if (!args.has("--no-build")) run("npm", ["run", "build"], DASHBOARD);
  run(join(BACKEND, ".venv", "bin", "alembic"), ["upgrade", "head"], BACKEND);
  run(PYTHON, ["-m", "scripts.seed_synthetic", "--count", "120"], BACKEND);

  api = spawn(PYTHON, ["-m", "uvicorn", "tracker.api.app:app", "--host", "127.0.0.1", "--port", String(PORT)], {
    cwd: BACKEND,
    env,
    stdio: ["ignore", "ignore", "inherit"],
  });
  await waitForApi(api);
  const job = await firstJob();

  const browser = await chromium.launch();
  const encoder = await browser.newPage();
  const shots = [
    { name: "job-detail", path: `/company/${job.company}/job/${job.id}`, theme: "light" },
    { name: "job-detail-dark", path: `/company/${job.company}/job/${job.id}`, theme: "dark" },
  ];
  console.log(`writing ${shots.length} screenshots to ${OUT}`);
  for (const shot of shots) await shoot(browser, encoder, shot);
  await browser.close();
} finally {
  if (api && api.exitCode === null) api.kill("SIGTERM");
  spawnSync(PYTHON, ["-c", "import sys; from pathlib import Path; from tracker.platform.embedded_db import stop_server; stop_server(Path(sys.argv[1]))", pgdata], {
    cwd: BACKEND,
    env,
    stdio: "ignore",
  });
  if (args.has("--keep")) console.log(`scratch database kept at ${pgdata}`);
  else rmSync(scratch, { recursive: true, force: true });
}
