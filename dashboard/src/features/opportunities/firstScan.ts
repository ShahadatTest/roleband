import type { SystemStatus } from "../../api";

/* Where the first pass over the followed companies stands: every company read
   once. Until then an empty or short board says the scan is still reading,
   never that the person's choices emptied it. Read from `/api/status` alone,
   so the board and its line agree on every poll.

   The pass is `ever_read` of `required`, not `last_success_at`: that dates
   the oldest read, and is set as soon as ONE company has been read. */

/** A hold the person can be told about: the scan job's own reason code, or a
    provider's state when queued work waits behind it. */
export type FirstScanHold = { reason: string; until: string | null };

/** When to look again. `soon` before the pace is known (too few companies
    read, or too little time); `minutes` from the pace; `hour` past sixty
    minutes; `almost` under a minute. */
export type FirstScanWhen =
  | { when: "soon" }
  | { when: "minutes"; minutes: number }
  | { when: "hour" }
  | { when: "almost" };

export type FirstScanCount = { read: number; total: number };

export type FirstScan =
  | { phase: "done" }
  /** Nothing to scan: no followed company the scheduler reads on its own. */
  | { phase: "none" }
  | { phase: "starting" }
  /** `count` is null before the scheduler has seeded its roster. */
  | { phase: "running"; count: FirstScanCount | null; back: FirstScanWhen }
  | { phase: "held"; count: FirstScanCount; hold: FirstScanHold }
  /** Not running, not held, not about to start: stopped by the person or by an
      error. Scan now continues it from the companies not yet read. */
  | { phase: "stopped"; count: FirstScanCount };

/** The pace is a guess until this many companies are read and this long has
    passed: the first companies of a scan say little about the rest. */
const PACE_MIN_READ = 5;
const PACE_MIN_MS = 30_000;

/** The scan job states that mean a scan is lined up and will start by itself. */
const LINED_UP = new Set(["queued", "starting", "waiting"]);

export function firstScan(status: SystemStatus, syncing: boolean, nowMs: number): FirstScan {
  const scheduler = status.scheduler;
  const running = syncing || status.running;
  if (!scheduler.seeded) {
    // Before the roster is seeded there is no count to give; a full run that
    // finished is the only evidence of a first pass.
    if (status.last_success_at !== null) return { phase: "done" };
    return running ? { phase: "running", count: null, back: { when: "soon" } } : { phase: "starting" };
  }
  if (scheduler.required === 0) return { phase: "none" };
  const count = { read: Math.min(scheduler.ever_read, scheduler.required), total: scheduler.required };
  if (count.read >= count.total) return { phase: "done" };
  if (running) return { phase: "running", count, back: backIn(count, status.last_run_started_at, nowMs) };

  const job = status.jobs?.find((row) => row.key === "scan");
  if (job?.reason) return { phase: "held", count, hold: { reason: job.reason, until: null } };
  const blocked = status.manual_blocked[0];
  if (blocked) return { phase: "held", count, hold: { reason: blocked.reason, until: blocked.until ?? null } };
  if ((job && LINED_UP.has(job.state)) || status.manual_queued.length > 0) return { phase: "starting" };
  if (status.last_run_started_at === null) return { phase: "starting" };
  return { phase: "stopped", count };
}

/* The pace is the companies read over the time since this run started. A
   run that continues an earlier one starts with some already read, which
   makes it look faster than it is: the estimate errs short, and the count
   beside it still says how far there is to go. */
function backIn(count: FirstScanCount, startedAt: string | null, nowMs: number): FirstScanWhen {
  const elapsed = startedAt ? nowMs - Date.parse(startedAt) : NaN;
  if (!(elapsed >= PACE_MIN_MS) || count.read < PACE_MIN_READ) return { when: "soon" };
  const minutes = Math.ceil(((count.total - count.read) * elapsed) / count.read / 60_000);
  if (minutes <= 1) return { when: "almost" };
  if (minutes > 60) return { when: "hour" };
  return { when: "minutes", minutes };
}

/** A third of the roster read with nothing on the board is the point where
    "keep waiting" stops being the whole answer. */
export function nothingFitsYet(count: FirstScanCount | null): boolean {
  return count !== null && count.read * 3 >= count.total;
}
