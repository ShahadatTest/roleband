/* Operations: status, the manual sync and its picker, the connector schedule.
   One domain of the typed client; `index.ts` composes `api`. */

import type { Schemas } from "./schemas";
import { getJSON, patchJSON, putJSON } from "./transport";

// `GET /api/status`. `running` is "a pipeline is executing right now" and
// nothing else: queued-but-not-started work is `manual_queued`, and the part of
// it that cannot start yet is `manual_blocked`. Merging the two would render a
// stalled sync as a live one with a ticking clock. `manual_sync_running`
// is true only for a run started by the header Sync control.
export type SystemStatus = Schemas["SystemStatusResponse"];

// `POST /api/sync`: `started` (work queued; `companies` echoes the subset, empty
// = the roster) or `already_running` (attached to a live run it did not scope;
// `queued` names the companies asked for, which that run reads next).
export type SyncResult = Schemas["SyncResponse"];

// One selectable company in the sync scope picker. The roster is exactly what
// the pipeline would accept, so anything listed here can really be synced.
// `last_sync_at` is the last attempt, not the last success.
export type SyncTarget = Schemas["SyncTarget"];
export type SyncTargets = Schemas["SyncTargetsResponse"];
/** How one company's last scan went (`connectors/recipes/outcome.py`). */
export type SourceOutcome = Schemas["SourceOutcome"];

// `POST /api/sync/cancel`: `cancelled` (names the run it ended, if any) or
// `not_running` / `error` with nothing dequeued.
export type SyncCancelResult = Schemas["SyncCancelResponse"];

/* Settings > Schedule wire types are aliases of the generated schemas.
   `GET /api/schedule` and `PATCH /api/schedule/{binding_id}` both
   answer the whole schedule, a binding's `status` is one of the six the
   serializer names, and the PATCH body is the anchor the route parses. */
export type ScheduleProvider = Schemas["ScheduleProviderPayload"];
export type ScheduleBinding = Schemas["ScheduleBindingPayload"];
export type SyncSchedule = Schemas["SchedulePayload"];
export type ScheduleTimeUpdate = Schemas["ScheduleTimeUpdate"];
/* The schedule plan: a full scan when the computer comes on, a quick
   scan every `repeat_hours` while it is on, and the usual on-hours it learned.
   Every schedule route takes `tz`, the zone those hours are told in. */
export type SchedulePlan = Schemas["SchedulePlanPayload"];
export type ScheduleUpcomingRun = Schemas["ScheduleUpcomingRun"];
export type ScheduleWindow = Schemas["ScheduleWindow"];
export type SchedulePlanUpdate = Schemas["SchedulePlanUpdate"];

const localZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const zoned = (path: string) => `${path}?tz=${encodeURIComponent(localZone())}`;

export const opsApi = {
  schedule: () => getJSON<SyncSchedule>(zoned("/api/schedule")),
  updateSchedule: (bindingId: number, update: ScheduleTimeUpdate) =>
    patchJSON<SyncSchedule>(zoned(`/api/schedule/${bindingId}`), update),
  // Only the keys sent change; `ready_by_minute: null` clears the user's time.
  updateSchedulePlan: (update: SchedulePlanUpdate) =>
    putJSON<SyncSchedule>(zoned("/api/schedule/plan"), update),
  syncTargets: () => getJSON<SyncTargets>("/api/sync/targets"),
};
