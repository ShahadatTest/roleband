import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Notification, NotificationList, api } from "../../api";
import { useJobActions } from "../../context/JobWorkspace";
import { useMissionActions } from "../../context/MissionState";
import { useSyncEpoch } from "../../context/SyncState";
import { useAsyncResource, useRefetchOn } from "../../hooks/useAsyncResource";
import { useSearchParam } from "../../routing/useSearchParam";
import { useSearchParamList } from "../../routing/useSearchParamList";
import { useRememberedParams } from "../../routing/useRememberedParams";
import { useToast } from "../../ui";
import { useCopy } from "./diagnostics/NotifDiagnostics";
import type { MovedPageVerbs } from "./moved-page/MovedPagePanel";
import { isSyncRunning } from "./sync-progress/model";
import { notificationText } from "../../api/notificationText";
import {
  NOTIF_MEMORY_SCOPE,
  PRIORITY_OPTIONS,
  RESET_LENS_PARAMS,
  STATUS_OPTIONS,
  countActiveNotificationFilters,
} from "./filters";
import {
  notificationsUseNotificationsControllerCouldNot,
  notificationsUseNotificationsControllerDismissThatNotification,
  notificationsUseNotificationsControllerMarkItRead,
  notificationsUseNotificationsControllerMarkItUnread,
  notificationsUseNotificationsControllerMarkThemRead,
  notificationsUseNotificationsControllerMarkedNotificationsRead,
  notificationsUseNotificationsControllerRolebandNowReadsSNew,
  notificationsUseNotificationsControllerRemovedFromYourNotifications,
  notificationsUseNotificationsControllerStopFollowing,
  notificationsUseNotificationsControllerStoppedFollowing,
  notificationsUseNotificationsControllerUndo,
  notificationsUseNotificationsControllerUndoThat,
  notificationsUseNotificationsControllerUseThatCareersPage,
} from "../../copy/gen/notifications";

/** Poll cadence while a sync is live. The backend beats progress every 30s. */
const SYNC_POLL_MS = 15_000;

/** One page renders in full in the page flow — the Board's number. */
export const PAGE_SIZE = 20;

/** The Board's search debounce; a keystroke is not a query. */
const SEARCH_DEBOUNCE_MS = 250;

/**
 * The Notifications screen's state: URL lenses, the debounced query, paging,
 * the list resource, the live-sync poll, and every mutation. The screen and
 * its rows render what this returns and call back into it — they hold no
 * request of their own (features/opportunities/useBoardController.ts is the
 * same split).
 */
export function useNotificationsController() {
  const { openJob } = useJobActions();
  const { refreshStats } = useMissionActions();
  const { notificationVersion } = useSyncEpoch();
  const { toast } = useToast();
  // The lenses live in the URL so a filtered view is shareable and survives
  // reload. Search and page stay in memory (Board parity): a query is not a
  // lens, and a deep link to page 3 of a moving feed is not a place.
  /* ...and they are REMEMBERED, which the address alone cannot do: a reload
     keeps the query string, but arriving from the nav rail or the bell does
     not, and every visit would start unfiltered. One mount-time restore into
     a bare address, never over a link that names a lens
     (routing/useRememberedParams). */
  useRememberedParams(NOTIF_MEMORY_SCOPE, RESET_LENS_PARAMS);
  const [status, setStatus] = useSearchParam("status", { options: STATUS_OPTIONS, fallback: "all" });
  const [priority, setPriority] = useSearchParam("priority", { options: PRIORITY_OPTIONS, fallback: "" });
  const [categories, setCategories] = useSearchParamList("category");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const { copied, copy } = useCopy();

  useEffect(() => {
    const id = window.setTimeout(() => setQuery(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [search]);

  // Any edit to a lens or the query starts the list over: a page number
  // belongs to the list it was counted on.
  const categoryKey = categories.join(",");
  useEffect(() => {
    setOffset(0);
  }, [status, priority, categoryKey, query]);

  const params = {
    status,
    priority: priority || null,
    category: categories,
    q: query || null,
    limit: PAGE_SIZE,
    offset,
  };
  const list = useAsyncResource<NotificationList>(
    () => api.notifications(params),
    [status, priority, categoryKey, query, offset],
  );
  const { retry } = list;
  // A finished scan re-reads the page in place: the rows stay on screen.
  useRefetchOn(notificationVersion, list.refresh);

  // Refresh in place: the live-sync poll and the row actions must not flash the
  // boundary's spinner or blank the list. This is the shared resource's own
  // refresh, which also ORDERS the results: the poll and a row action are two
  // starts against identical inputs, and without ordering the slower one would
  // win by finishing last. A failure lands on `refreshError`, not on `error`:
  // quiet, but never swallowed.
  const refresh = list.refresh;

  // Dismissing the only row on the last page leaves an empty page behind a
  // real total: step back to the page that still has rows.
  const data = list.data;
  useEffect(() => {
    if (data && data.items.length === 0 && offset > 0 && data.total > 0) {
      setOffset(Math.floor((data.total - 1) / PAGE_SIZE) * PAGE_SIZE);
    }
  }, [data, offset]);

  // A running sync updates its progress block server-side (heartbeat during
  // collection, per company during persistence). Poll only while one is live,
  // then stop: an idle notifications page must not talk to the API forever.
  const hasLiveSync = (data?.items ?? []).some(isSyncRunning);
  // `refresh` is stable and always re-runs the CURRENT request, so the interval
  // can depend on it directly without restarting every render.
  useEffect(() => {
    if (!hasLiveSync) return;
    const id = window.setInterval(() => void refresh({ preserveData: true }), SYNC_POLL_MS);
    return () => window.clearInterval(id);
  }, [hasLiveSync, refresh]);

  /* A user action that failed must say so: a silent rejection looks like it
     worked until the next refresh quietly puts the row back. The poll stays
     quiet by contrast: its failure lands on the resource's `refreshError`, not
     in the reader's face. */
  const attempt = async (what: string, run: () => Promise<void>) => {
    try {
      await run();
    } catch {
      toast({ key: "notifications", text: notificationsUseNotificationsControllerCouldNot({ what: String(what) }) });
      // Re-read: the optimistic assumption behind the click may be wrong now.
      void refresh({ preserveData: true });
    }
  };

  const markReadOnce = async (n: Notification) => {
    if (n.read_at) return;
    // Reading is incidental to opening, so a failure here must not block the
    // navigation the reader actually asked for: report and carry on.
    await attempt(notificationsUseNotificationsControllerMarkItRead(), async () => {
      await api.markNotificationRead(n.id, true);
      refreshStats();
      await refresh({ preserveData: true });
    });
  };

  const toggleExpanded = (n: Notification) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(n.id)) next.delete(n.id);
      else next.add(n.id);
      return next;
    });
    // Opening the diagnostics is reading it.
    void markReadOnce(n);
  };

  // A job notification navigates; a run/health notification has nowhere to go, so
  // its row click reveals the diagnostics instead of doing nothing. The role
  // opens FIRST: marking read is incidental, so it runs after, in
  // the background, and a write or re-read that never answers can neither
  // hold the click nor navigate late, after the reader has moved on.
  const openNotification = async (n: Notification, hasDetails: boolean) => {
    if (n.job_id) {
      openJob(n.job_id, n.company);
      void markReadOnce(n);
      return;
    }
    if (hasDetails) {
      toggleExpanded(n);
      return;
    }
    await markReadOnce(n);
  };

  /* Opening a role from inside the digest. The digest carries no `job_id` of
   * its own -- it stands for the whole day -- so its entries open through here
   * rather than through `openNotification`. */
  const openJobFromNotification = (jobId: number, company?: string | null) => {
    openJob(jobId, company ?? undefined);
  };

  const markRead = (n: Notification, read: boolean) =>
    attempt(notificationsUseNotificationsControllerMarkItUnread({ choice: (read) ? "yes" : "no" }), async () => {
      await api.markNotificationRead(n.id, read);
      refreshStats();
      await refresh({ preserveData: true });
    });

  /* The row's destructive verb, as careful as the bulk one: "Mark all read"
   * toasts with Undo, and so does this. Dismissal is a timestamp
   * server-side, so the way back is one id, and unlike `markAll` there is no
   * bound to reason about, because one row is one row. The toast names what
   * left: the row it refers to is gone from the list by the time it is read. */
  const dismiss = (n: Notification) =>
    attempt(notificationsUseNotificationsControllerDismissThatNotification(), async () => {
      await api.dismissNotification(n.id);
      refreshStats();
      await refresh({ preserveData: true });
      toast({
        key: "notifications",
        text: notificationsUseNotificationsControllerRemovedFromYourNotifications({ title: notificationText(n).title }),
        action: {
          label: notificationsUseNotificationsControllerUndo(),
          onClick: () => {
            void attempt(notificationsUseNotificationsControllerUndoThat(), async () => {
              await api.restoreNotification(n.id);
              refreshStats();
              await refresh({ preserveData: true });
            });
          },
        },
      });
    });

  /* A careers page gone from its address: the Coverage row's
   * answers. Finding only reads; moving and unfollowing each end the notice,
   * so both re-read the list, and unfollowing offers its way back. */
  const movedPage: MovedPageVerbs = {
    find: async (company, careersUrl) => (await api.findCompanyBoard(company, careersUrl)).candidate,
    move: async (page, board) => {
      let moved = false;
      await attempt(notificationsUseNotificationsControllerUseThatCareersPage(), async () => {
        await api.moveCompanyBoard(page.company, board);
        moved = true;
        refreshStats();
        await refresh({ preserveData: true });
        toast({ key: "notifications", text: notificationsUseNotificationsControllerRolebandNowReadsSNew({ display: String(page.display) }) });
      });
      return moved;
    },
    stopFollowing: (page) =>
      attempt(notificationsUseNotificationsControllerStopFollowing({ display: String(page.display) }), async () => {
        await api.updateCompany(page.company, { enabled: false });
        refreshStats();
        await refresh({ preserveData: true });
        toast({
          key: "notifications",
          text: notificationsUseNotificationsControllerStoppedFollowing({ display: String(page.display) }),
          action: {
            label: notificationsUseNotificationsControllerUndo(),
            onClick: () => {
              void attempt(notificationsUseNotificationsControllerUndoThat(), async () => {
                await api.updateCompany(page.company, { enabled: true });
                refreshStats();
                await refresh({ preserveData: true });
              });
            },
          },
        });
      }),
  };

  // Bulk read is the screen's one verb, a ghost at the toolbar rank, never a
  // gold fill: housekeeping, not a commit. The way back is the toast: the ids
  // come from the server, and Undo posts them to /unread.
  const markAll = () => attempt(notificationsUseNotificationsControllerMarkThemRead(), async () => {
    const { updated, undoable, ids } = await api.markAllNotificationsRead();
    refreshStats();
    await refresh({ preserveData: true });
    toast({
      key: "notifications",
      text: notificationsUseNotificationsControllerMarkedNotificationsRead({ count: updated, updated: updated }),
      // No Undo above the server's bulk bound: it would restore a prefix and
      // report success. Saying nothing is honest; a button that silently does
      // part of the job is not.
      action: !undoable ? undefined : {
        label: notificationsUseNotificationsControllerUndo(),
        onClick: () => {
          void attempt(notificationsUseNotificationsControllerUndoThat(), async () => {
            await api.markNotificationsUnread(ids);
            refreshStats();
            await refresh({ preserveData: true });
          });
        },
      },
    });
  });

  const activeCount = countActiveNotificationFilters({ status, priority, categories });
  // One navigation, not three: each lens setter builds from the URL it read
  // at call time, so three in a row would let the last one restore the first.
  const [, setSearchParams] = useSearchParams();
  const resetAll = () => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const key of RESET_LENS_PARAMS) next.delete(key);
        return next;
      },
      { replace: true },
    );
  };

  return {
    // lenses + query
    status, setStatus, priority, setPriority, categories, setCategories,
    search, setSearch, query, activeCount, resetAll,
    /* The empty state asks a wider question than the register does: "did you
       narrow this list", which a query does even though it is not a filter.
       Reset all and the folded opener's count answer the narrower one. */
    narrowed: activeCount > 0 || query !== "",
    // the list
    list, retry, data,
    total: data?.total ?? 0,
    unread: data?.unread_count ?? 0,
    offset, setOffset,
    // row state + verbs
    expanded, copied, copy,
    openNotification, openJobFromNotification, toggleExpanded, markRead, dismiss, markAll,
    movedPage,
  };
}

export type NotificationsController = ReturnType<typeof useNotificationsController>;
