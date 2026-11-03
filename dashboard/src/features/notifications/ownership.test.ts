import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const src = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (path: string) => readFileSync(join(src, path), "utf8");

/* Notifications ownership. The screen renders what
 * the controller returns; the controller holds every request, effect and
 * mutation; the row decides how a notification LOOKS and nothing about what
 * happens to it. Nothing of this domain lives in `components/`. */
describe("Notifications ownership", () => {
  it("the screen renders and the controller owns the requests", () => {
    const screen = read("features/notifications/NotificationScreen.tsx");
    expect(screen).toContain('from "./useNotificationsController"');
    expect(screen).toContain("<NotificationRow");
    // No api call, no promise, no timer, no URL write: those are the controller's.
    expect(screen).not.toMatch(/api\.|\.then\(|setTimeout|setInterval|useSearchParam/);
    const controller = read("features/notifications/useNotificationsController.ts");
    for (const owned of ["api.notifications", "useSearchParam", "setInterval", "useAsyncResource"]) {
      expect(controller, owned).toContain(owned);
    }
  });

  it("the row presents and never mutates", () => {
    const row = read("features/notifications/NotificationRow.tsx");
    expect(row).not.toMatch(/api\.|\.then\(|useState|useEffect/);
    expect(row).toContain('import "./notification-row.css"');
  });

  it("the bell is the domain's second surface, sharing the line and not the chrome", () => {
    const bell = read("features/notifications/NotificationBell.tsx");
    // The shared line anatomy (icon + copy stack) is declared as a dependency,
    // the way JobDetail declares patterns/jobs/job-row.css.
    expect(bell).toContain('import "./notification-row.css"');
    expect(bell).toContain('import "./notification-bell.css"');
    expect(bell).toContain('from "./notifIcons"');
    // The screen's shell sheet is not the bell's business.
    expect(bell).not.toContain("notification-screen.css");
    expect(read("features/notifications/NotificationScreen.tsx")).not.toContain("notification-bell.css");
  });

  it("nothing of this domain is left in legacy components/", () => {
    for (const legacy of [
      "NotificationCenter.tsx",
      "NotificationBell.tsx",
      "notifIcons.tsx",
      "notifDiagnostics.tsx",
      "notifSyncProgress.tsx",
      "notifSyncStream.tsx",
      "notifSyncContribution.tsx",
      "notifications.css",
    ]) {
      expect(existsSync(join(src, "components", legacy)), legacy).toBe(false);
    }
    // The shell mounts the feature root directly, with no hop through `components/`.
    expect(read("routeRegistry.tsx")).toContain("./features/notifications/NotificationScreen");
    expect(read("App.tsx")).toContain('from "./features/notifications/NotificationBell"');
  });

  it("both list screens put the undo in the same place, with the same scope", () => {
    // The register carries no head row on either screen, and ui/FilterRail
    // offers no primitive that draws one, so a third screen cannot add it quietly.
    expect(read("features/notifications/NotificationFilters.tsx")).not.toMatch(/Reset all|ResetAll\(/);
    // "Reset all" or its copy-catalog message call.
    expect(read("features/opportunities/BoardFilters.tsx")).not.toMatch(/Reset all|radarReset\(/);
    expect(read("ui/FilterRail.tsx")).not.toContain("FilterRailHead");
    // The Board measures itself, so its undo is the count's own `reset`
    // slot rather than a sibling of the bar.
    const board = read("features/opportunities/BoardToolbar.tsx");
    const at = board.indexOf("<ResultsSummary");
    expect(at).toBeGreaterThan(-1);
    const resetProp = board.indexOf("reset={", at);
    expect(resetProp).toBeGreaterThan(at);
    expect(board.slice(resetProp, resetProp + 400)).toMatch(/Reset all|radarReset\(\)/);
    // Notifications shows no count at all, so its undo stands in the toolbar
    // band directly: still the bar, never the register.
    const notif = read("features/notifications/NotificationScreen.tsx");
    expect(notif).not.toContain("ResultsSummary");
    const bar = notif.indexOf('className="notif-toolbar');
    expect(bar).toBeGreaterThan(-1);
    expect(notif.slice(bar).search(/Reset all|ResetAll\(\)/)).toBeGreaterThan(-1);
  });
});
