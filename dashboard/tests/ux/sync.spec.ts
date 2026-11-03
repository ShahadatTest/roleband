import { msg } from "../../src/test/msg";
import { expect, test } from "./fixtures";
import {
  facetsFixture,
  jobFixture,
  jobListFixture,
  notificationsFixture,
  statsFixture,
  statusFixture,
  syncStartedFixture,
} from "../../src/test/fixtures";

// Drives the on-demand Sync control end to end: idle -> triggering (POST /api/sync)
// -> live "Syncing…" (status.running) -> completion result ("+N new"). The status
// route is stateful so we can walk the run through its lifecycle deterministically.
test.beforeEach(async ({ page }) => {
  await page.route("/api/profile", (route) => route.fulfill({ json: {
    profile: null, scope_configured: true,
  } }));
  await page.route("/api/stats", (route) => route.fulfill({ json: statsFixture }));
  await page.route("/api/facets", (route) => route.fulfill({ json: facetsFixture }));
  await page.route("/api/notifications**", (route) => route.fulfill({ json: notificationsFixture }));
  await page.route("/api/jobs/*/similar**", (route) => route.fulfill({ json: { scope: "cross", items: [] } }));
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: jobListFixture }));
  await page.route("/api/jobs/101", (route) => route.fulfill({ json: jobFixture }));
});

test("the Sync button triggers a scrape and shows live progress then the result", async ({ page }) => {
  let synced = false;
  let pollsSinceSync = 0;
  const COMPLETED_NEW = 7;

  await page.route("/api/sync", async (route) => {
    synced = true;
    await route.fulfill({ json: syncStartedFixture });
  });

  await page.route("/api/status", async (route) => {
    let running = false;
    let last_run_new = statusFixture.last_run_new;
    if (synced) {
      pollsSinceSync += 1;
      // Report the run in flight for the first couple of polls, then finished
      // with a fresh new-count so the button surfaces "+N new".
      if (pollsSinceSync <= 2) running = true;
      else last_run_new = COMPLETED_NEW;
    }
    await route.fulfill({ json: { ...statusFixture, running, last_run_new } });
  });

  await page.clock.install();
  await page.goto("/");

  // Idle: an enabled "Sync" control lives in the mission header.
  const idle = page.getByRole("button", { name: "Scan now" });
  await expect(idle).toBeVisible();
  await expect(idle).toBeEnabled();
  await expect(idle).toHaveText(/Scan/);

  // Clicking fires the trigger and immediately reflects in-progress.
  const [request] = await Promise.all([
    page.waitForRequest("/api/sync"),
    idle.click(),
  ]);
  expect(request.method()).toBe("POST");

  const busy = page.getByRole("button", { name: "Scan in progress" });
  await expect(busy).toBeVisible();
  await expect(busy).toBeDisabled();
  await expect(busy).toHaveText(/Scanning/);

  // While a run is in flight the status is read every 3 s, counted from the
  // last read: the switch to that cadence asks nothing twice, so the next read
  // still finds the run going and the one after it finds it done.
  await page.clock.runFor(3_100);
  await expect(busy).toHaveText(/Scanning/);
  await page.clock.runFor(3_100);
  await expect(page.getByRole("button", { name: /Scan/ })).toContainText(`+${COMPLETED_NEW} new`);
});

test("a queued scan the background service holds says why, and says it again once the hold changes", async ({ page }) => {
  const scan = (reason: string) => ({
    key: "scan", job: "scan", state: "waiting", reason, since: "2026-10-19T09:00:00Z",
    next_at: null, run_id: null, progress: null, waiting: null, queued: 1,
  });
  let reason = "preflight_running";
  await page.route("/api/status", (route) => route.fulfill({ json: {
    ...statusFixture, running: false, manual_sync_running: true, manual_queued: ["meta"], jobs: [scan(reason)],
    supervisor: reason === "supervisor_stale"
      ? { state: "stale", since: "2026-10-19T09:00:00Z", reason: null }
      : statusFixture.supervisor,
  } }));
  await page.clock.install();
  await page.goto("/");

  const control = page.getByRole("button", { name: "Stop queued scan" });
  await expect(control).toContainText(msg("shell-scan-waiting", { count: 1, reason: "preflight_running" }));
  reason = "supervisor_stale";
  await page.clock.fastForward(61_000); // the next idle poll
  await expect(control).toContainText(msg("shell-scan-waiting", { count: 1, reason: "supervisor_stale" }));
});
