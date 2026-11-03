import { defineConfig, devices } from "@playwright/test";
import { build, write } from "./scripts/gen-copy.mjs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { uxProfile } from "./tests/ux/runProfile";
import { shardTestMatch, uxShard } from "./tests/ux/shards";

// The specs read the catalog through src/test/msg.ts, and src/copy/gen/ is not
// committed: generate it before any spec file loads, however the run was started.
write(build({ twin: false }).files);
const profile = uxProfile();
const testDir = fileURLToPath(new URL("./tests/ux", import.meta.url));
const shard = uxShard();

export default defineConfig({
  testDir,
  /* ROLEBAND_UX_SHARD runs one of the CI shards: whole spec files balanced by
     recorded time (tests/ux/shards.ts). */
  ...(shard && { testMatch: shardTestMatch(testDir, shard) }),
  /* A committed `.only` silently reduces the suite to one test and reports
     green, so CI refuses one outright. Deliberately NOT paired with `retries`:
     this repo's policy is that a flake gets diagnosed, not retried, and retries
     are how a real intermittent failure becomes invisible. */
  forbidOnly: profile.forbidOnly,
  /* Tests inside one file run in parallel too, not just files against each
     other: a shard's two workers share its biggest spec instead of one worker
     carrying it alone, and a test that only passes because the one before it
     ran first is a defect this surfaces. */
  fullyParallel: true,
  outputDir: profile.outputDir,
  reporter: [["list"], ["json", { outputFile: join(profile.outputDir, "results.json") }]],
  workers: profile.workers,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL: profile.baseURL,
    serviceWorkers: "block",
    trace: "retain-on-failure",
  },
  webServer: {
    command: profile.command,
    env: { VITE_API_TARGET: profile.apiTarget },
    url: profile.baseURL,
    // An existing server may belong to a different checkout.
    reuseExistingServer: false,
    timeout: 120_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["iPhone 14"] } },
  ],
});
