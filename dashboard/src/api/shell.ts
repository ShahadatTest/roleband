/* What the app shell (main.tsx, App.tsx, context/, shell/, the bell) imports
   from the typed client: `startupApi` and the types it reads. Never `./index`
   or a domain module; `npm run build` fails one that enters the startup chunk
   (shell-boundary.json "confined"). Kept apart from `./startup` so tests can
   stand the `api` object they already mock in for this one
   (src/test/setup.ts). */
export { startupApi as shellApi } from "./startup";
export type { CompareSelection, JobViewResult } from "./jobs";
export type { CompanyNames } from "./companies";
export type { Notification, NotificationList, NotificationParams } from "./notifications";
export type { SyncCancelResult, SyncResult, SystemStatus } from "./ops";
export type { LocaleSettings, ProfileState } from "./scope";
export type { Stats } from "./statistics";
export type { UsageState } from "./usage";
