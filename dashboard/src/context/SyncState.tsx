import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { shellApi, type SystemStatus } from "../api/shell";
import type { AsyncResource } from "../hooks/useAsyncResource";
import { useVisibleInterval } from "../hooks/useVisibleInterval";
import { useMissionActions } from "./MissionState";

// Status poll cadences: relaxed while idle, tight while a scrape is in flight so
// the Sync button reflects progress and completion within a few seconds.
const STATUS_IDLE_MS = 60_000;
const STATUS_ACTIVE_MS = 3_000;

/**
 * The system's own state: freshness, the supervised run, and the epoch that
 * says a run finished.
 *
 * This is the context that TICKS — every 3 seconds while a sync is live — and
 * it stands apart for that reason: in one object with the compare selection and
 * the board query, a poll would re-render every job row, the compare grid and
 * the register on screen. Nothing dense subscribes here:
 * the freshness badge, the sync button and the scope popover do.
 *
 * It reads `refreshStats` from MissionState, so its provider nests inside that
 * one — the running -> idle edge is when the header counts change.
 *
 * THREE contexts, split by cadence. The status object is replaced on
 * every poll; the epoch advances once per completed run; the verbs never change.
 * One object would re-render the notifications controller and the header bell
 * every 3 seconds for an epoch that had not moved, and the sync-scope popover
 * for a verb.
 */
export interface SyncStatusValue {
  /** System freshness/supervision status, polled centrally so the freshness
   *  badge and the Sync button share one source of truth (and one poller). */
  status: SystemStatus | null;
  statusFailed: boolean;
  /** True from the moment the user triggers a sync until a poll shows the run
   *  has finished. Distinct from status.running so the button reacts instantly
   *  on click (before the backend has written the "running" marker). */
  syncing: boolean;
  /** Companies the in-flight sync covers. Empty = the full roster. */
  syncingCompanies: string[];
}

/** Advances after a confirmed running -> terminal transition. Notification
 *  surfaces use it to refetch durable sync-result rows without a reload — and
 *  nothing else, which is why it is not in the object that polls. */
export interface SyncEpochValue {
  notificationVersion: number;
  /** Advances at the same confirmed running -> terminal edge: a screen that
   *  lists roles reads what the scan changed (the Board offers it, rather than
   *  moving rows under the reader). */
  runVersion: number;
  /** Advances when the stored estimates moved together (`/api/status`
   *  `reference.last_change_id` changed: a plugin turned on or off, a clean
   *  plugin update, a new edition of RoleBand's data). It is also the one moment
   *  pay, benefits and company size change source, so every surface
   *  showing any of them re-reads on it (`useSourceSwitch`), not only when a
   *  scan ends. */
  referenceVersion: number;
  /** A plugin answers pay (`/api/status` `capabilities`): only then does a
   *  screen read which companies it has read. */
  payByPlugin: boolean;
  /** Advances when the prices job's run ends: an open Stock prices card and an
   *  open profile re-read the prices it stored. */
  pricesVersion: number;
}

type JobView = NonNullable<SystemStatus["jobs"]>[number];
const live = (job: JobView | undefined) => job?.state === "running" || job?.state === "starting";

/** What a trigger did. `started`: work is queued, or the live run already
 *  covers it. `joined`: the companies it named join the live run, which reads
 *  them next. `false`: it did not land. */
export type SyncTrigger = "started" | "joined" | false;

export interface SyncActions {
  /** No argument = the whole roster; a subset runs as a targeted scan, or
   *  joins the run that is live. A caller that ignores the answer is telling
   *  the reader a scan started that did not. */
  triggerSync: (companies?: string[]) => Promise<SyncTrigger>;
  /** Resolves TRUE when the stop landed, FALSE when it did not: the run, or
   *  the queue, goes on. */
  cancelSync: () => Promise<boolean>;
  /** Read `/api/status` now: a decision that moved the sources (a plugin
   *  turned on or off) is seen at once, and the fast poll that catches the
   *  switch landing starts with it, not at the next idle tick. */
  pollStatus: () => Promise<void>;
}

/** The stored estimates are being recomputed: the re-estimate after a scan, a
 *  plugin turned on or off, or a new edition of RoleBand's data. */
export function estimatesMoving(status: SystemStatus | null): boolean {
  // A held engine applies nothing, whatever the reference still counts as pending.
  if (status?.launcher?.status.hold) return false;
  const reference = status?.reference;
  return Boolean(reference && reference.target_fp !== null && reference.pending_jobs > 0);
}

const StatusCtx = createContext<SyncStatusValue | null>(null);
const EpochCtx = createContext<SyncEpochValue | null>(null);
const ActionsCtx = createContext<SyncActions | null>(null);

export function SyncStateProvider({ children }: { children: React.ReactNode }) {
  const { refreshStats } = useMissionActions();
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncingCompanies, setSyncingCompanies] = useState<string[]>([]);
  // Mirrors of the live run and its scope, for a trigger to read at click time.
  const scope = useRef<string[]>([]);
  const runLive = useRef(false);
  const setScope = useCallback((companies: string[]) => {
    scope.current = companies;
    setSyncingCompanies(companies);
  }, []);
  const [notificationVersion, setNotificationVersion] = useState(0);
  const [runVersion, setRunVersion] = useState(0);
  const [referenceVersion, setReferenceVersion] = useState(0);
  const [pricesVersion, setPricesVersion] = useState(0);
  const pricesWereLive = useRef(false);
  // The reference change the last poll saw; `undefined` until the first one,
  // so loading the app is never itself a change.
  const lastChange = useRef<number | null | undefined>(undefined);

  // Centralized /api/status poll. It self-adjusts its cadence: fast while a run
  // is in flight (optimistic syncing or a fresh "running" marker), relaxed
  // otherwise. On the running -> idle edge we refresh the header stats so the new
  // counts land. `wasRunning` tracks only the *confirmed* marker (not the
  // optimistic bridge) so completion is detected from a real true -> false edge.
  const wasRunning = useRef(false);
  const optimisticTimer = useRef<number | null>(null);
  const clearOptimistic = useCallback(() => {
    if (optimisticTimer.current !== null) {
      window.clearTimeout(optimisticTimer.current);
      optimisticTimer.current = null;
    }
    setSyncing(false);
  }, []);

  // The newest read wins. The interval, a cadence change and the
  // trigger/cancel verbs each start a read, and clearing an interval does not
  // recall one already sent. Only the newest start may write — the status, the
  // failure flag and the completion edge alike — so an older "running" answer
  // cannot revive a finished run or fire its completion twice. Unmounting
  // retires every read in flight.
  const statusGeneration = useRef(0);
  const refreshStatus = useCallback(async () => {
    const generation = ++statusGeneration.current;
    try {
      const s = await shellApi.status();
      if (generation !== statusGeneration.current) return null;
      setStatus(s);
      setStatusFailed(false);
      runLive.current = s.running;
      // Optional on the wire: a status from an older API without the reference
      // set must not fail the poll.
      const change = s.reference?.last_change_id ?? null;
      if (lastChange.current !== undefined && change !== lastChange.current) {
        setReferenceVersion((version) => version + 1);
      }
      lastChange.current = change;
      const pricesLive = live(s.jobs?.find((job) => job.key === "prices"));
      if (pricesWereLive.current && !pricesLive) setPricesVersion((version) => version + 1);
      pricesWereLive.current = pricesLive;
      // A confirmed marker has taken over — retire the optimistic bridge. The
      // queue counts: a manual request may sit queued for a whole scheduler
      // tick before any pipeline starts, and `running` alone would leave the
      // bridge to expire on its 15s timer and flicker the button back to idle.
      const confirmed = s.running || s.manual_queued.length > 0;
      if (confirmed) clearOptimistic();
      // Confirmed work just finished: pull fresh header stats and tell durable
      // notification views to fetch the terminal sync row.
      if (wasRunning.current && !confirmed) {
        refreshStats();
        setNotificationVersion((version) => version + 1);
        setRunVersion((version) => version + 1);
        // The subset belongs to the run that just ended; the next trigger sets
        // its own, and a stale list would mislabel a scheduled run as targeted.
        setScope([]);
      }
      wasRunning.current = confirmed;
      return s;
    } catch {
      if (generation === statusGeneration.current) setStatusFailed(true);
      return null;
    }
  }, [refreshStats, clearOptimistic, setScope]);

  // Poll fast while a pipeline is live, or while the stored estimates are
  // being recomputed after it (a sync is done when they are).
  // A queue that is merely waiting does not earn the fast cadence — it can sit
  // for hours behind a provider backoff, and polling every couple of seconds
  // for that whole time buys nothing.
  // So is any supervised job that is starting or running: its state, and the
  // reason it waits once it stops, reach the screen within one poll.
  const active = syncing || (status?.running ?? false) || estimatesMoving(status) || !!status?.jobs?.some(live);
  useVisibleInterval(refreshStatus, active ? STATUS_ACTIVE_MS : STATUS_IDLE_MS);

  // Clean up the optimistic-bridge timer if the provider unmounts mid-sync, and
  // retire the reads still out.
  useEffect(() => () => {
    statusGeneration.current += 1;
    if (optimisticTimer.current !== null) window.clearTimeout(optimisticTimer.current);
  }, []);

  /* Reported rather than rethrown, for two reasons (so is a stop's). This verb has to retire
     its own optimistic bridge on the way out whatever the caller does; and the
     three callers ask three different questions of the same failure — the
     header owns the RUN, the register only ever asked whether its ask landed,
     and the scope picker hands straight off to the header. Rethrowing would
     make each of them write a catch to answer a question it does not have. */
  const triggerSync = useCallback(async (companies: string[] = []): Promise<SyncTrigger> => {
    // Companies that join a live run widen a targeted run's scope; a run
    // whose scope is the whole roster, or unknown, stays that.
    const before = scope.current;
    const widen = (names: string[]) => (before.length > 0 ? [...new Set([...before, ...names])] : []);
    setSyncing(true); // optimistic: react on click, before the marker is written
    setScope(runLive.current ? widen(companies) : companies);
    // Safety net: if the marker never shows (fast run seen between polls, or a
    // spawn that never materialized), don't spin forever.
    if (optimisticTimer.current !== null) window.clearTimeout(optimisticTimer.current);
    optimisticTimer.current = window.setTimeout(() => setSyncing(false), 15_000);
    let outcome: SyncTrigger;
    try {
      // `started` echoes the covered subset. An `already_running` keeps the live
      // run's scope plus what it queued, never our picks alone.
      const result = await shellApi.sync(companies);
      const running = result.status === "already_running";
      setScope(running ? widen(result.queued) : result.companies ?? []);
      outcome = running && result.queued.length > 0 ? "joined" : "started";
    } catch {
      clearOptimistic(); // trigger failed (offline/error): return the button to idle
      setScope(before);
      outcome = false;
    }
    // Poll immediately so a running state (or already_running) surfaces at once.
    await refreshStatus();
    return outcome;
  }, [refreshStatus, clearOptimistic, setScope]);

  const cancelSync = useCallback(async (): Promise<boolean> => {
    let stopped = true;
    try {
      await shellApi.cancelSync();
    } catch {
      stopped = false;
    }
    clearOptimistic();
    await refreshStatus();
    return stopped;
  }, [refreshStatus, clearOptimistic]);

  const statusValue = useMemo<SyncStatusValue>(
    () => ({ status, statusFailed, syncing, syncingCompanies }),
    [status, statusFailed, syncing, syncingCompanies],
  );
  const payByPlugin = !!status?.capabilities?.some((c) => c.slot === "pay.levels" && c.providers.length > 0);
  const epoch = useMemo<SyncEpochValue>(
    () => ({ notificationVersion, runVersion, referenceVersion, payByPlugin, pricesVersion }),
    [notificationVersion, runVersion, referenceVersion, payByPlugin, pricesVersion],
  );
  const pollStatus = useCallback(async () => {
    await refreshStatus();
  }, [refreshStatus]);
  const actions = useMemo<SyncActions>(
    () => ({ triggerSync, cancelSync, pollStatus }),
    [triggerSync, cancelSync, pollStatus],
  );

  return (
    <ActionsCtx.Provider value={actions}>
      <EpochCtx.Provider value={epoch}>
        <StatusCtx.Provider value={statusValue}>{children}</StatusCtx.Provider>
      </EpochCtx.Provider>
    </ActionsCtx.Provider>
  );
}

export function useSyncStatus(): SyncStatusValue {
  const v = useContext(StatusCtx);
  if (!v) throw new Error("useSyncStatus must be used within SyncStateProvider");
  return v;
}

export function useSyncEpoch(): SyncEpochValue {
  const v = useContext(EpochCtx);
  if (!v) throw new Error("useSyncEpoch must be used within SyncStateProvider");
  return v;
}

/** Re-read a resource in place when the sources answering pay, benefits and
 *  company size change: a switch the re-estimate just applied. Every
 *  surface showing data a plugin can answer takes it, so none keeps the old
 *  source's figures after the switch. Outside a `SyncStateProvider` (a
 *  component test) there is no switch to follow and it never fires. */
export function useSourceSwitch(refresh: AsyncResource<unknown>["refresh"]): void {
  // `useRefetchOn`'s rule, restated: importing it would pull the resource hook
  // into the shell chunk this provider ships in (its bundle gate is at the
  // ceiling). Only a change after mount re-reads; `refresh` is read at the change.
  const version = useReferenceVersion();
  const seen = useRef(version);
  const latest = useRef(refresh);
  useEffect(() => {
    latest.current = refresh;
  });
  useEffect(() => {
    if (seen.current === version) return;
    seen.current = version;
    void latest.current({ preserveData: true });
  }, [version]);
}

/** `SyncEpochValue.referenceVersion`, 0 outside a `SyncStateProvider`: for a
 *  cache that outlives its component and must drop what an older source said. */
export function useReferenceVersion(): number {
  return useContext(EpochCtx)?.referenceVersion ?? 0;
}

/** `SyncEpochValue.pricesVersion`, 0 outside a `SyncStateProvider`. */
export function usePricesVersion(): number {
  return useContext(EpochCtx)?.pricesVersion ?? 0;
}

/** One supervised job as the last poll saw it; null outside a `SyncStateProvider`
 *  or before the first poll. */
export function useJob(key: string): JobView | null {
  return useContext(StatusCtx)?.status?.jobs?.find((job) => job.key === key) ?? null;
}

/** `SyncEpochValue.payByPlugin`, false outside a `SyncStateProvider`. */
export function usePayByPlugin(): boolean {
  return useContext(EpochCtx)?.payByPlugin ?? false;
}

/** `SyncActions.pollStatus`, or nothing outside a `SyncStateProvider`. */
export function useStatusPoll(): () => Promise<void> {
  const actions = useContext(ActionsCtx);
  return actions?.pollStatus ?? noPoll;
}

const noPoll = async () => {};

export function useSyncActions(): SyncActions {
  const v = useContext(ActionsCtx);
  if (!v) throw new Error("useSyncActions must be used within SyncStateProvider");
  return v;
}
