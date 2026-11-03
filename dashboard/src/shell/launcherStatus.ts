import type { SystemStatus } from "../api";
import * as copy from "../copy/gen/launcher-status";

type Hold = NonNullable<NonNullable<SystemStatus["launcher"]>["status"]["hold"]>;
export function launcherHoldText(hold: Hold): string {
  switch (hold.reason) {
    case "supervisor_absent": case "supervisor_stale": return copy.launcherReasonSupervisor();
    case "schema_pending": case "dependencies_pending": return copy.launcherReasonSetup();
    case "build_failed": return copy.launcherReasonBuild();
    case "preflight_failed": return copy.launcherReasonChecks();
    case "model_missing": return copy.launcherReasonModel();
    case "model_preparing": return copy.launcherReasonPreparing();
    case "waiting_for_mains": return copy.launcherReasonPower();
    case "waiting_for_wake": return copy.launcherReasonWake();
    case "preflight_running": return copy.launcherReasonPreflight();
    case "busy_external": return copy.launcherReasonBusy();
    case "maintenance": return copy.launcherReasonMaintenance();
    case "update_queued": return copy.launcherReasonQueued();
    case "provider_paused": case "provider_backoff": case "provider_policy_denied": return copy.launcherReasonProvider();
    default: return copy.launcherReasonOther();
  }
}
