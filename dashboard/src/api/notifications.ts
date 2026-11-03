/* Notifications: the feed and its read, unread, dismiss and restore actions.
   One domain of the typed client; `index.ts` composes `api`. */

import type { Schemas } from "./schemas";
import { postJSON } from "./transport";

/* Notification wire types are aliases of the generated schemas
   (`tracker/api/schemas/notifications.py`). */

/** One notification, as the feed lists it and every single-row action answers.
 *  `priority`, `category` and `source_type` are plain strings on the wire: no
 *  database constraint backs them, and retired categories are still served.
 *  `company` is the linked job's slug, null with no job. `meta` is the stored
 *  JSON object, whose keys depend on the category that wrote it. */
export type Notification = Schemas["NotificationRow"];

/** One page of the feed. `total` and `category_counts` follow the filters (the
 *  facet counts ignore the category filter itself, so an unselected category
 *  still says how many rows it would show); the two unread counts are global. */
export type NotificationList = Schemas["NotificationListResponse"];

export interface NotificationParams {
  status?: "all" | "unread";
  priority?: string | null;
  // Repeated `?category=` narrows with IN.
  category?: string[] | null;
  q?: string | null;
  limit?: number;
  offset?: number;
}

export const notificationsApi = {
  // The ids are the way back: Undo posts them to markNotificationsUnread — but
  // ONLY when `undoable`. A clear larger than the server's bulk-unread bound
  // returns no ids at all rather than a partial set, so the caller must offer
  // Undo on the flag, never on `ids.length`.
  markAllNotificationsRead: () =>
    postJSON<Schemas["NotificationReadAllResponse"]>("/api/notifications/read_all"),
  markNotificationsUnread: (ids: number[]) =>
    postJSON<Schemas["NotificationUnreadResponse"]>(
      "/api/notifications/unread",
      { ids } satisfies Schemas["UnreadPayload"],
    ),
  dismissNotification: (id: number) => postJSON<Notification>(`/api/notifications/${id}/dismiss`),
  /** The way back from a row dismiss. Dismissal is a timestamp, so one id is the
   *  whole undo — no captured payload, and no bound like the bulk pair above. */
  restoreNotification: (id: number) => postJSON<Notification>(`/api/notifications/${id}/restore`),
};
