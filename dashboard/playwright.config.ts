import { defineConfig, devices } from "@playwright/test";
import { build, write } from "./scripts/gen-copy.mjs";
import { join } from "node:path";
import { uxProfile } from "./tests/ux/runProfile";

// The specs read the catalog through src/test/msg.ts, and src/copy/gen/ is not
// committed: generate it before any spec file loads, however the run was started.
write(build({ twin: false }).files);
const profile = uxProfile();

export default defineConfig({
  testDir: "./tests/ux",
  /* A committed `.only` silently reduces the suite to one test and reports
     green, so CI refuses one outright. Deliberately NOT paired with `retries`:
     this repo's policy is that a flake gets diagnosed, not retried, and retries
     are how a real intermittent failure becomes invisible. */
  forbidOnly: profile.forbidOnly,
  /* Tests inside one file run in parallel too, not just files against each
     other. Not for speed: `--shard` splits by TEST rather than by file once
     this is on, so a CI matrix balances instead of inheriting whatever the
     biggest spec weighs; and a test that only passes because the one before it
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
