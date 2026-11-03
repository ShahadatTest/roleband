import { test, expect, mockGet } from "./fixtures";
import { installBoardRoutes } from "./boardHarness";
import { launcherFixture, statusFixture } from "../../src/test/fixtures";
import { msg } from "../../src/test/msg";
import { expectOnTop } from "./paint";

test("the shell keeps held work visible without claiming it is executing", async ({ page, isMobile }) => {
  test.skip(isMobile, "The compact mobile header has no freshness badge.");
  await installBoardRoutes(page);
  await mockGet(page, "/api/status", route => route.fulfill({ json: {
    ...statusFixture,
    reference: { ...statusFixture.reference, target_fp: "pending", pending_jobs: 50 },
    launcher: launcherFixture({ hold: { kind: "attention", reason: "preflight_failed" }, queued: "update" }),
  } }));
  await page.goto("/");
  const badge = page.getByRole("status", { name: msg("shell-freshness-aria", { state: msg("launcher-needs-attention") }) });
  await expectOnTop(badge, "Held work status");
  await expect(badge).toHaveAttribute("title", new RegExp(msg("launcher-reason-checks").replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  await expect(page.getByRole("button", { name: msg("shell-scan-updating-estimates-aria") })).toHaveCount(0);
});
