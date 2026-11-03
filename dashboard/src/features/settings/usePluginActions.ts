import { useCallback, useEffect, useRef, useState } from "react";
import { PluginActionResult, PluginDetail, PluginSchedule, PluginView, api } from "../../api";
import { errorText } from "../../api/errorText";
import { useWriteQueue } from "../../hooks/useWriteQueue";
import { useStatusPoll } from "../../context/SyncState";
import {
  settingsPluginsSectionFailed,
  settingsPluginsSectionRemoved,
  settingsPluginsSectionWaitingWake,
} from "../../copy/gen/settings";
import { leavesGaps } from "./pluginWords";

/* Every write a plugin takes, for both plugin screens. One queue per plugin
   (`useWriteQueue("plugins").keyed(id)`): a row's writes are ordered and never
   wait on another row's. Each write adopts the row the server answers with,
   and the screen refetches after it whether it succeeded or failed, inside the
   queue, so the row stays busy until the refetch lands. A failure is keyed by
   plugin, like the writes, and names the step that failed; it shows in that
   plugin's row.

   Start answers before the detached run exists, so a refetch right after it
   still reads `running: false`. The plugin is held as STARTING until a run
   shows up (it is running, or its last run changed) or `START_WINDOW_MS`
   passes; the screen shows it updating and polls meanwhile. */

export type PluginAction =
  | "review" | "approve" | "on_after_approve" | "on" | "off" | "update" | "pause" | "resume" | "schedule"
  | "uninstall" | "remove" | "robots";

/** An approval the person is looking at: the detail it shows, and whether
 *  approving also turns the plugin on (they reached it through the switch). */
export type Approving = { detail: PluginDetail; andTurnOn: boolean };

/** What a notice says: a message the screen resolves at render, never stored text. */
export type PluginNotice = { kind: "waiting_wake" } | { kind: "removed"; rows: number };

type Failure = { action: PluginAction; caught: unknown };

/** How long a Start waits for its run to appear before the row stops saying so. */
export const START_WINDOW_MS = 30_000;

/** Bookkeeping Remove data clears beside the rows it deletes: not data the
 *  plugin added, so never counted as removed rows. */
const BOOKKEEPING = new Set([
  "plugin_coverage", "plugin_state", "plugin_report",
  // Worked out from its rows, not rows it added: the notice counts
  // what the dialog named.
  "job_comp_estimate", "comp_snapshot",
]);

export function removedRows(deleted: Record<string, number>): number {
  return Object.entries(deleted).reduce((sum, [table, n]) => (BOOKKEEPING.has(table) ? sum : sum + n), 0);
}

export function noticeText(notice: PluginNotice): string {
  return notice.kind === "waiting_wake"
    ? settingsPluginsSectionWaitingWake()
    : settingsPluginsSectionRemoved({ rows: notice.rows });
}

export function usePluginActions({
  refresh,
  adopt,
}: {
  /** Refetch what the screen shows. */
  refresh: () => Promise<unknown>;
  /** Put the row a write answered with on screen before the refetch lands. */
  adopt: (plugin: PluginView) => void;
}) {
  const queue = useWriteQueue("plugins");
  const pollStatus = useStatusPoll();
  const [approving, setApproving] = useState<Approving | null>(null);
  // The plugin whose sites' rules the person is reviewing.
  const [reviewingRobots, setReviewingRobots] = useState<PluginView | null>(null);
  // An approved plugin the person switched on while it leaves companies empty:
  // asked about before it answers app-wide.
  const [turningOn, setTurningOn] = useState<PluginView | null>(null);
  const [notice, setNotice] = useState<PluginNotice | null>(null);
  const [failures, setFailures] = useState<ReadonlyMap<string, Failure>>(new Map());
  // plugin id -> the id of its last run when Start was pressed.
  const [starting, setStarting] = useState<ReadonlyMap<string, number | null>>(new Map());
  const timers = useRef(new Map<string, number>());

  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const id of pending.values()) window.clearTimeout(id);
      pending.clear();
    };
  }, []);

  const fail = useCallback((id: string, failure: Failure | null) => {
    setFailures((current) => {
      if (!failure && !current.has(id)) return current;
      const next = new Map(current);
      if (failure) next.set(id, failure);
      else next.delete(id);
      return next;
    });
  }, []);

  const stopStarting = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer !== undefined) window.clearTimeout(timer);
    timers.current.delete(id);
    setStarting((current) => {
      if (!current.has(id)) return current;
      const next = new Map(current);
      next.delete(id);
      return next;
    });
  }, []);

  /** One write: run `task` in the plugin's queue, adopt the row it answers
   *  with, record which step failed, and always refetch before the row frees. */
  const run = async (id: string, task: (step: (action: PluginAction) => void) => Promise<unknown>, first: PluginAction) => {
    fail(id, null);
    setNotice(null);
    let action = first;
    let ok = true;
    await queue.keyed(id, async () => {
      try {
        await task((next) => { action = next; });
      } catch (caught) {
        ok = false;
        fail(id, { action, caught });
      } finally {
        try { await refresh(); } catch { /* the screen's resource reports its own error */ }
        // A decision that moves the sources says so at once: the status reads
        // "updating" and its fast poll catches the switch landing.
        void pollStatus();
      }
    });
    return ok;
  };

  const adopted = (result: PluginActionResult) => adopt(result.plugin);

  /** Read what approval shows; nothing is written, so nothing is refetched. */
  const review = (plugin: PluginView, andTurnOn = false) => {
    fail(plugin.id, null);
    api.plugin(plugin.id).then(
      (detail) => setApproving({ detail, andTurnOn }),
      (caught) => fail(plugin.id, { action: "review", caught }),
    );
  };

  const turn = (plugin: PluginView, next: boolean) => {
    if (!next) stopStarting(plugin.id);
    void run(plugin.id, async () => {
      adopted(await (next ? api.enablePlugin(plugin.id) : api.disablePlugin(plugin.id)));
    }, next ? "on" : "off");
  };

  /** The switch. Off always works, even while an update lapsed the approval.
   *  On for a plugin that needs approval is reviewed first: on means approve,
   *  then turn on, and nothing happens until the person approves. On for an
   *  approved plugin that would leave companies empty asks first. */
  const toggle = (plugin: PluginView, next: boolean) => {
    if (next && plugin.state === "needs_approval") {
      review(plugin, true);
      return;
    }
    if (next && leavesGaps(plugin)) {
      setTurningOn(plugin);
      return;
    }
    turn(plugin, next);
  };

  /** The person confirmed turning on in the dialog. */
  const confirmTurnOn = () => {
    const plugin = turningOn;
    setTurningOn(null);
    if (plugin) turn(plugin, true);
  };

  /** `robots`: what the person chose about its sites' rules in the same dialog. */
  const approve = (choice: Approving, robots: Record<string, string> | null = null) => {
    setApproving(null);
    const { detail, andTurnOn } = choice;
    void run(detail.id, async (step) => {
      adopted(await api.approvePlugin(detail.id, detail.fingerprint, robots));
      if (andTurnOn && !detail.enabled) {
        step("on_after_approve");
        adopted(await api.enablePlugin(detail.id));
      }
    }, "approve");
  };

  /** Start: update now. The server releases a pause with it. */
  const start = (plugin: PluginView) =>
    run(plugin.id, async () => {
      const result = await api.refreshPlugin(plugin.id);
      if (result.started) {
        const seen = plugin.last_run?.id ?? null;
        setStarting((current) => new Map(current).set(plugin.id, seen));
        const previous = timers.current.get(plugin.id);
        if (previous !== undefined) window.clearTimeout(previous);
        timers.current.set(plugin.id, window.setTimeout(() => stopStarting(plugin.id), START_WINDOW_MS));
      } else if (result.waiting) {
        setNotice({ kind: "waiting_wake" });
      }
    }, "update");

  /** Is this plugin's Start still waiting for its run to show up? */
  const isStarting = (plugin: PluginView) =>
    starting.has(plugin.id) && !plugin.running && (plugin.last_run?.id ?? null) === starting.get(plugin.id);

  const write = (plugin: PluginView, action: PluginAction, call: () => Promise<PluginActionResult>) =>
    run(plugin.id, async () => { adopted(await call()); }, action);

  const pause = (plugin: PluginView) => {
    stopStarting(plugin.id);
    return write(plugin, "pause", () => api.pausePlugin(plugin.id));
  };
  const resume = (plugin: PluginView) => write(plugin, "resume", () => api.resumePlugin(plugin.id));
  const setSchedule = (plugin: PluginView, schedule: PluginSchedule) =>
    write(plugin, "schedule", () => api.setPluginSchedule(plugin.id, schedule));
  const uninstall = (plugin: PluginView) => write(plugin, "uninstall", () => api.uninstallPlugin(plugin.id));
  /** Allow it past its sites' robots rules as shown, or follow them (null). */
  const setRobots = (plugin: PluginView, robots: Record<string, string> | null) => {
    setReviewingRobots(null);
    return write(plugin, "robots", () => api.setPluginRobots(plugin.id, robots));
  };
  const removeData = (plugin: PluginView, typed: string) =>
    run(plugin.id, async () => {
      const result = await api.removePluginData(plugin.id, typed);
      setNotice({ kind: "removed", rows: removedRows(result.deleted) });
    }, "remove");

  /** The failure of this plugin's last write, in the reader's words; null when none. */
  const errorFor = (id: string): string | null => {
    const failure = failures.get(id);
    return failure ? errorText(failure.caught, settingsPluginsSectionFailed({ action: failure.action })) : null;
  };

  return {
    busy: queue.busy,
    approving,
    cancelApproval: () => setApproving(null),
    reviewingRobots,
    reviewRobots: (plugin: PluginView) => setReviewingRobots(plugin),
    cancelRobots: () => setReviewingRobots(null),
    setRobots,
    turningOn,
    confirmTurnOn,
    cancelTurnOn: () => setTurningOn(null),
    notice,
    errorFor,
    isStarting,
    review,
    toggle,
    approve,
    start,
    pause,
    resume,
    setSchedule,
    uninstall,
    removeData,
  };
}
