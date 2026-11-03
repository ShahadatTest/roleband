import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { shellApi } from "../api/shell";
import { COMPARE_ROUTE, coverBackground, positionPath } from "../routing/paths";

/* Three roles, not four (docs/ui.md "Cover"). The screen is a grid plus one
 * full description diff per role past the first: at four there are six
 * job-description columns below the fold, none of them comparable to each
 * other, and the attribute grid runs out of horizontal room. Named once here
 * and READ from the context value (`compareCap`) rather than imported —
 * naming this constant from a lazy chunk promotes it to a live export of the
 * shell chunk. */
const COMPARE_CAP = 3;

const sameOrder = (a: readonly number[], b: readonly number[]) =>
  a.length === b.length && a.every((id, i) => id === b[i]);

/**
 * What the reader is DOING with jobs: the compare selection, what they have
 * opened, and the verbs that change either.
 *
 * TWO contexts, because a context re-renders everyone who reads it whenever its
 * VALUE identity changes, and the verbs never change while the selection
 * changes constantly. `StatisticsRoute` wants only `openJob`; joined, it
 * would re-render on every compare toggle on any screen.
 */
export interface JobWorkspaceValue {
  /** The compare selection: pick on any tab, view on Compare. Server-backed,
   *  so a reload keeps the roles and the rail count the way it keeps the star
   *  beside the same row. */
  compareIds: Set<number>;
  compareFull: boolean;
  /** How many roles the comparison holds. A value, not an import: every
   *  surface that states the cap ("Compare is full (max 3)", "2 of 3") reads
   *  it from here. */
  compareCap: number;
  /** False until the stored selection has been read once. An empty selection
   *  and an unread one look identical and mean opposite things — Compare would
   *  otherwise flash "pick at least 2 roles" at someone arriving with four. */
  compareHydrated: boolean;
  /** The last write did not reach the store, so what is on screen is not what
   *  would come back on a reload. Stated here; this is F2 and cannot reach a
   *  toast itself, so the shell's `CompareSaveAlert` raises one at any
   *  selection size and the beacon's reveal repeats it. Clears on
   *  the next write that lands, which replace-all makes automatic. */
  compareSyncFailed: boolean;
  viewedIds: Set<number>;
  /** Bumped by every save the server confirmed, so lists of saved state
   *  re-read (the Board's, Saved's). Written only through `savedChanged`. */
  favVersion: number;
  /** The newest confirmed save: which posting, and whether it is now saved.
   *  For a screen that draws roles and patches one in place rather than
   *  re-reading (Compare). Null until a save lands. */
  lastSaved: SavedChange | null;
}

/** A save the server confirmed, as `useSaveCommand` announces it. */
export interface SavedChange {
  jobId: number;
  saved: boolean;
}

export interface JobActions {
  toggleCompare: (id: number) => void;
  setCompare: (ids: number[]) => void;
  clearCompare: () => void;
  /** Forget roles whose job is gone. The store cascades on job deletion, so
   *  this covers only the window where a job closed while the tab was open —
   *  the roster fetch is what discovers it, and a silent drop there would
   *  leave the count claiming a role it never drew. */
  dropCompare: (ids: number[]) => void;
  /** Send the selection on screen again after a write that did not land
   *  (`compareSyncFailed`). The shell's alert offers it. */
  retryCompare: () => void;
  /** Open an opportunity's full-screen detail route. Any tab's cards can call
   *  this; it navigates and preserves the current page as the return target so
   *  browser back/forward and direct links behave correctly. When the caller
   *  knows the company slug (list rows, notifications) it builds the canonical
   *  company-scoped position URL (/company/:slug/job/:id); otherwise it falls
   *  back to /job/:id, which self-canonicalizes once the job loads. */
  /** Open the comparison as a cover over the current page (or over a role
   *  cover's background). No-op when already on it. */
  openCompare: () => void;
  openJob: (id: number, companySlug?: string | null) => void;
  markJobViewed: (id: number) => void;
  /** Announce a confirmed save. Called by `useSaveCommand`, never by a screen:
   *  the command decides which writes count. */
  savedChanged: (change: SavedChange) => void;
}

const ValueCtx = createContext<JobWorkspaceValue | null>(null);
const ActionsCtx = createContext<JobActions | null>(null);

export function JobWorkspaceProvider({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  // Both through refs, and for the same reason: neither identity is stable.
  // `location` changes on every navigation, and react-router v7's `navigate` is
  // NOT stable either (App.tsx's first-run guard depends on the same fact).
  // A verb that closes over them directly would churn this context's value on
  // every navigation, which is the thing the split exists to prevent.
  const locationRef = useRef(location);
  locationRef.current = location;
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  const [compareIds, setCompareIds] = useState<Set<number>>(new Set());
  const [compareHydrated, setCompareHydrated] = useState(false);
  const [compareSyncFailed, setCompareSyncFailed] = useState(false);
  const [viewedIds, setViewedIds] = useState<Set<number>>(new Set());
  const viewedIdsRef = useRef<Set<number>>(new Set());
  // One state, so a save re-renders readers once: the version the lists key
  // on and the change a patching screen reads move together.
  const [saves, setSaves] = useState<{ version: number; last: SavedChange | null }>({ version: 0, last: null });

  // The selection as an ORDERED list, mirrored in a ref. Order is contract —
  // the beacon docks level with the role picked last — and the verbs need to
  // read the current set without depending on it, or the actions object would
  // change identity on every toggle and undo the value/verb split.
  const compareRef = useRef<number[]>([]);
  // The set we want stored, and whether a write is already in flight. Writes
  // are serialized rather than fired per toggle: two PUTs racing can land out
  // of order, and the loser would be the newer one.
  const desiredRef = useRef<number[] | null>(null);
  const writingRef = useRef(false);
  // Set by the first local change. A hydrate that arrives after the user has
  // already picked something must not overwrite them with the older stored set.
  const touchedRef = useRef(false);

  const flush = useCallback(async () => {
    if (writingRef.current) return;
    writingRef.current = true;
    try {
      while (desiredRef.current !== null) {
        const send = desiredRef.current;
        desiredRef.current = null;
        try {
          const stored = await shellApi.setCompareSelection(send);
          setCompareSyncFailed(false);
          // The response is authoritative — it has dropped ids past the cap and
          // ids whose job is gone. Adopt it only when nothing newer is queued;
          // an echo for a superseded write would walk the selection backwards.
          if (desiredRef.current === null && !sameOrder(compareRef.current, stored.job_ids)) {
            compareRef.current = stored.job_ids;
            setCompareIds(new Set(stored.job_ids));
          }
        } catch {
          // The selection stays on screen: it is the user's work, and discarding
          // it would make picks vanish, which this store exists to prevent. The
          // fact is recorded here and SHOWN by the beacon — a context is F2 and
          // may not reach the presentation tier to raise a toast of its own.
          // Replace-all is what makes recovery free: the next successful write
          // carries the whole set, so a restored connection self-heals with no
          // retry queue.
          setCompareSyncFailed(true);
        }
      }
    } finally {
      writingRef.current = false;
    }
  }, []);

  /** Move the selection locally NOW and persist behind it. The gesture is
   *  hover-speed and must not wait on a round trip. */
  const applyCompare = useCallback(
    (next: number[]) => {
      touchedRef.current = true;
      compareRef.current = next;
      setCompareIds(new Set(next));
      desiredRef.current = next;
      void flush();
    },
    [flush],
  );

  // Read the stored selection once, on mount.
  useEffect(() => {
    let live = true;
    shellApi
      .compareSelection()
      .then((stored) => {
        if (!live || touchedRef.current) return;
        // Clamped: a selection stored under an older, larger cap must not come
        // back over it. The store clamps too — this is the client refusing to
        // render more columns than the screen has.
        const held = stored.job_ids.slice(0, COMPARE_CAP);
        compareRef.current = held;
        setCompareIds(new Set(held));
      })
      .catch(() => {
        // Nothing to show but the empty set, which is what is already on screen.
        // A background read that fails stays quiet; the
        // first write will surface any real outage.
      })
      .finally(() => {
        if (live) setCompareHydrated(true);
      });
    return () => {
      live = false;
    };
  }, []);

  const toggleCompare = useCallback(
    (id: number) => {
      const current = compareRef.current;
      if (current.includes(id)) {
        applyCompare(current.filter((existing) => existing !== id));
      } else if (current.length < COMPARE_CAP) {
        applyCompare([...current, id]);
      }
      // At the cap an unselected row changes nothing, so it writes nothing.
    },
    [applyCompare],
  );

  const setCompare = useCallback(
    (ids: number[]) => applyCompare(ids.slice(0, COMPARE_CAP)),
    [applyCompare],
  );

  const clearCompare = useCallback(() => applyCompare([]), [applyCompare]);

  const dropCompare = useCallback(
    (ids: number[]) => {
      if (ids.length === 0) return;
      const gone = new Set(ids);
      const next = compareRef.current.filter((id) => !gone.has(id));
      if (next.length !== compareRef.current.length) applyCompare(next);
    },
    [applyCompare],
  );

  const retryCompare = useCallback(() => {
    setCompareSyncFailed(false);
    desiredRef.current = compareRef.current;
    void flush();
  }, [flush]);

  const markJobViewed = useCallback((id: number) => {
    if (viewedIdsRef.current.has(id)) return;
    viewedIdsRef.current.add(id);
    setViewedIds(new Set(viewedIdsRef.current));
    void shellApi.markJobViewed(id).catch(() => {
      viewedIdsRef.current.delete(id);
      setViewedIds(new Set(viewedIdsRef.current));
    });
  }, []);

  const openJob = useCallback(
    (id: number, companySlug?: string | null) => {
      markJobViewed(id);
      const current = locationRef.current;
      // When already viewing a job overlay, keep the original page underneath as
      // the background so back/forward walks job→job→list rather than nesting.
      // A comparison is the one cover a role stacks ON (one level,
      // docs/ui.md "Cover"): Back from a column's role
      // returns to the comparison, and from there to the list.
      const background = current.pathname === COMPARE_ROUTE ? current : coverBackground(current);
      const to = companySlug ? positionPath(companySlug, id) : `/job/${id}`;
      navigateRef.current(to, { state: { backgroundLocation: background } });
    },
    [markJobViewed],
  );

  /** Open the comparison as a cover over the page the reader is on. From a
   *  role cover it covers that cover's background — the list — so Back lands
   *  where the picking happened. */
  const openCompare = useCallback(() => {
    const current = locationRef.current;
    if (current.pathname === COMPARE_ROUTE) return;
    navigateRef.current(COMPARE_ROUTE, { state: { backgroundLocation: coverBackground(current) } });
  }, []);

  const savedChanged = useCallback(
    (change: SavedChange) => setSaves((prev) => ({ version: prev.version + 1, last: change })),
    [],
  );

  const value = useMemo<JobWorkspaceValue>(
    () => ({
      compareIds,
      compareFull: compareIds.size >= COMPARE_CAP,
      compareCap: COMPARE_CAP,
      compareHydrated,
      compareSyncFailed,
      viewedIds,
      favVersion: saves.version,
      lastSaved: saves.last,
    }),
    [compareIds, compareHydrated, compareSyncFailed, viewedIds, saves],
  );

  // Every dep is stable, so this object is created once and no consumer of the
  // verbs alone ever re-renders because of this provider.
  const actions = useMemo<JobActions>(
    () => ({
      toggleCompare,
      setCompare,
      clearCompare,
      dropCompare,
      retryCompare,
      openJob,
      openCompare,
      markJobViewed,
      savedChanged,
    }),
    [toggleCompare, setCompare, clearCompare, dropCompare, retryCompare, openJob, openCompare, markJobViewed, savedChanged],
  );

  return (
    <ActionsCtx.Provider value={actions}>
      <ValueCtx.Provider value={value}>{children}</ValueCtx.Provider>
    </ActionsCtx.Provider>
  );
}

export function useJobWorkspace(): JobWorkspaceValue {
  const v = useContext(ValueCtx);
  if (!v) throw new Error("useJobWorkspace must be used within JobWorkspaceProvider");
  return v;
}

export function useJobActions(): JobActions {
  const v = useContext(ActionsCtx);
  if (!v) throw new Error("useJobActions must be used within JobWorkspaceProvider");
  return v;
}

export { COMPARE_CAP };
