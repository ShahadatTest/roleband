/* The endpoints the app shell calls at startup and on every route: system
   status and the scan, header stats, the compare selection and viewed marks,
   the bell, the profile, usage consent, company names and the locale.

   Their own module because every module the shell loads ships whole in the
   startup chunk, and a domain object is never tree-shaken by method: a shell
   that called `api` would carry every domain and every method any screen
   adds. `index.ts` spreads `startupApi` into the one `api` object, so screens
   still call `api.status()`; the shell reaches these through `./shell` only, which `npm run build` holds
   it to (shell-boundary.json "confined"). An endpoint joins here only when the
   shell itself calls it. */
import type { CompareSelection, JobViewResult } from "./jobs";
import type { CompanyNames } from "./companies";
import type { Notification, NotificationList, NotificationParams } from "./notifications";
import type { SyncCancelResult, SyncResult, SystemStatus } from "./ops";
import type { LocaleSettings, ProfileState } from "./scope";
import type { Stats } from "./statistics";
import type { UsageState } from "./usage";
import { getJSON, postJSON, postMarkJSON, putJSON, qs } from "./transport";

export const startupApi = {
  status: () => getJSON<SystemStatus>("/api/status"),
  // No companies = the full roster. A subset runs as
  // `scope=targeted`, so it refreshes those companies without claiming the
  // whole radar is fresh.
  sync: (companies: string[] = []) => postJSON<SyncResult>("/api/sync", { companies }),
  cancelSync: () => postJSON<SyncCancelResult>("/api/sync/cancel"),
  stats: () => getJSON<Stats>("/api/stats"),
  markJobViewed: (id: number) => postMarkJSON<JobViewResult>(`/api/jobs/${id}/view`),
  compareSelection: (signal?: AbortSignal) =>
    getJSON<CompareSelection>("/api/compare-selection", signal),
  /** Replace-all, and the response is authoritative: ids past the cap and ids
   *  whose job is gone come back absent, so the caller reconciles its
   *  optimistic set against what was really stored. */
  setCompareSelection: (jobIds: number[]) =>
    putJSON<CompareSelection>("/api/compare-selection", { job_ids: jobIds }),
  notifications: (params: NotificationParams = {}) =>
    getJSON<NotificationList>(`/api/notifications?${qs(params)}`),
  markNotificationRead: (id: number, read: boolean) =>
    postJSON<Notification>(`/api/notifications/${id}/${read ? "read" : "unread"}`),
  profile: () => getJSON<ProfileState>("/api/profile"),
  usage: (signal?: AbortSignal) => getJSON<UsageState>("/api/usage", signal),
  companyNames: () => getJSON<CompanyNames>("/api/companies/names"),
  locale: () => getJSON<LocaleSettings>("/api/settings/locale"),
};
