/* Settings > Plugins and the reference set.
   One domain of the typed client; `index.ts` composes `api`. */

import type { Schemas } from "./schemas";
import { deleteJSON, getJSON, postJSON, putJSON } from "./transport";

/* Wire types are aliases of the generated schemas
   (`tracker/api/schemas/plugins.py`). A plugin's name, attribution and licence
   are third-party text: render them through `ui/Content`. */

/** `GET /api/plugins`: every install, the reference set, who answers each slot. */
export type PluginsResponse = Schemas["PluginsResponse"];
export type PluginView = Schemas["PluginView"];
export type PluginRunView = Schemas["PluginRunView"];
/** `GET /api/plugins/{id}`: the row plus recent runs and what approval shows. */
export type PluginDetail = Schemas["PluginDetail"];
export type PluginApproval = Schemas["PluginApproval"];
export type ReferenceView = Schemas["ReferenceView"];
export type CapabilityView = Schemas["CapabilityView"];
/** Approve, enable, disable, pause, resume, schedule, uninstall: the row after,
 *  and whether estimates are moving. */
export type PluginActionResult = Schemas["PluginActionResponse"];
export type PluginRefreshResult = Schemas["PluginRefreshResponse"];
export type PluginRemoveDataResult = Schemas["PluginRemoveDataResponse"];
/** How often a plugin updates; `null` returns to the plugin's own schedule. */
export type PluginSchedule = Schemas["PluginScheduleSet"]["schedule"];
/** What a plugin can bring (`PluginSlot` on the wire): the slots it declares,
 *  answers and adopts, and the capability rows. */
export type PluginSlot = Schemas["PluginView"]["slots"][number];
/** `GET /api/pay-coverage`: who answers pay and the companies it has read. */
export type PayCoverage = Schemas["PayCoverage"];
/** `GET /api/plugins/{id}/robots`: each declared site's rules, read now, and the consent. */
export type PluginRobots = Schemas["PluginRobots"];
export type PluginRobotsSite = Schemas["PluginRobotsSite"];
/** How a run ended (`PluginRunView.outcome`). */
export type PluginRunOutcome = Schemas["PluginRunView"]["outcome"];

const path = (id: string) => `/api/plugins/${encodeURIComponent(id)}`;

export const pluginsApi = {
  plugins: () => getJSON<PluginsResponse>("/api/plugins"),
  payCoverage: () => getJSON<PayCoverage>("/api/pay-coverage"),
  plugin: (id: string) => getJSON<PluginDetail>(path(id)),
  /** `fingerprint`: the install the dialog showed; a changed one is refused.
   *  `robots`: the robots files the person allowed it past, {host: sha256}, or
   *  null: it follows them. */
  approvePlugin: (id: string, fingerprint: string, robots: Record<string, string> | null = null) =>
    postJSON<PluginActionResult>(`${path(id)}/approve`, { fingerprint, robots }),
  pluginRobots: (id: string) => getJSON<PluginRobots>(`${path(id)}/robots`),
  setPluginRobots: (id: string, robots: Record<string, string> | null) =>
    putJSON<PluginActionResult>(`${path(id)}/robots`, { robots }),
  enablePlugin: (id: string) => postJSON<PluginActionResult>(`${path(id)}/enable`),
  disablePlugin: (id: string) => postJSON<PluginActionResult>(`${path(id)}/disable`),
  refreshPlugin: (id: string, job?: string) =>
    postJSON<PluginRefreshResult>(`${path(id)}/refresh`, job ? { job } : {}),
  /** `confirm`: the plugin's id, typed by the person. */
  removePluginData: (id: string, confirm: string) =>
    postJSON<PluginRemoveDataResult>(`${path(id)}/remove-data`, { confirm }),
  /** Stops an update and holds every scheduled one; the plugin stays on. */
  pausePlugin: (id: string) => postJSON<PluginActionResult>(`${path(id)}/pause`),
  /** Scheduled updates again; starts nothing now (`refreshPlugin` does). */
  resumePlugin: (id: string) => postJSON<PluginActionResult>(`${path(id)}/resume`),
  setPluginSchedule: (id: string, schedule: PluginSchedule) =>
    putJSON<PluginActionResult>(`${path(id)}/schedule`, { schedule }),
  /** Turns it off and removes its code; its data stays, unread. */
  uninstallPlugin: (id: string) => deleteJSON<PluginActionResult>(path(id)),
};
