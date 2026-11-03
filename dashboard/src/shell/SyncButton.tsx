import { time } from "../copy/format";
import {
  shellScanAddTitle,
  shellScanChooseAria,
  shellScanCompanyCount,
  shellScanCouldNotStart,
  shellScanCouldNotStop,
  shellScanFound,
  shellScanIdleTitle,
  shellScanInProgressAria,
  shellScanNow,
  shellScanQueued,
  shellScanQueuedAria,
  shellScanQueuedBlocked,
  shellScanQueuedLabel,
  shellScanQueuedUntil,
  shellScanWaiting,
  shellScanRequestedTitle,
  shellScanResultNew,
  shellScanResultNone,
  shellScanRunningTitle,
  shellScanScanning,
  shellScanUpdatingEstimates,
  shellScanUpdatingEstimatesAria,
  shellScanSomeTitle,
  shellScanStop,
  shellScanStopQueuedAria,
  shellScanStopTitle,
  shellScanStopped,
  shellScanStopping,
} from "../copy/gen/shell";
import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { estimatesMoving, useSyncActions, useSyncStatus } from "../context/SyncState";
import { Icon } from "../ui/Icon";

// How long the "+N new" result lingers after a run completes before the button
// settles back to its idle "Sync" label.
const RESULT_LINGER_MS = 6_000;

function elapsedLabel(startedAt: string | null | undefined, nowMs: number): string {
  if (!startedAt) return "";
  const secs = Math.max(0, Math.floor((nowMs - new Date(startedAt).getTime()) / 1000));
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

// Header control that triggers an on-demand market-data sync and reflects its
// live progress. Idle -> "Sync"; while a run is in flight -> a spinning icon +
// "Syncing…" + elapsed; just after it finishes -> a transient "+N new" result.
//
// Split, not two buttons: the left segment is the whole roster and the caret
// opens the company picker. The run's live state
// stays on the one control that owns it, so a targeted sync and a scheduled one
// are the same thing on screen — only their label differs.
//
// **Queued is its own state, not a shade of running.** A manual sync waits for
// the scheduler's next tick, and can wait hours behind a provider backoff.
// Rendered as "Syncing…", it would show an elapsed clock counting from the
// LAST run's start, reporting live work that finished long ago. So the spinner, the clock and the "N found" readout belong to `running`
// alone; queued work says it is queued, and says what it is waiting for.
/* Lazy: the scope picker opens on demand, so its list and search stay out of
   the startup chunk. Only this loader and the open branch below are shell. */
const SyncScopePopover = lazy(() =>
  import("../features/sync/SyncScopePopover").then((m) => ({ default: m.SyncScopePopover })),
);

export function SyncButton() {
  const { status, syncing, syncingCompanies } = useSyncStatus();
  const { triggerSync, cancelSync } = useSyncActions();
  const [stopping, setStopping] = useState(false);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [caret, setCaret] = useState<HTMLButtonElement | null>(null);
  const running = status?.running ?? false;
  const queuedCount = status?.manual_queued?.length ?? 0;
  // The scan has ended and the estimates it moved are being written: the work
  // is not done until they are, so the "+N new" result
  // waits for it. Never stoppable: the recompute is quick and resumes anyway.
  const updating = !running && estimatesMoving(status);
  // Everything that means "the user asked for work and it has not finished":
  // the optimistic bridge, a live pipeline, a queue waiting for a tick, and
  // the estimates that pipeline moved.
  const pending = syncing || running || queuedCount > 0 || updating;
  // Busy = work is happening now: a live pipeline, or the optimistic gap right
  // after a click. A queue that is only waiting for a tick is not busy.
  const busy = syncing || running || updating;
  const canStop = pending && !updating && (syncing || (status?.manual_sync_running ?? false) || queuedCount > 0);
  // The picker is offered when nothing is pending, and while a run is live:
  // the companies it names then join that run.
  const canPick = !pending || running;

  // Transient completion result, shown on the pending -> idle edge. Keyed to
  // `pending` rather than `running` so a multi-batch queue reports "+N new"
  // once at the end, not after every batch the scheduler happens to run.
  const wasRunning = useRef(pending);
  const [result, setResult] = useState<string | null>(null);
  const resultTimer = useRef<number | null>(null);

  /* One transient readout, whatever put it there. A trigger that never landed
     is as much a result as "+3 new": `triggerSync` swallows its own error to
     retire the optimistic bridge, so without this the button would return to
     "Scan now" and tell the reader nothing at all. A stop that did not land
     reads on the stop control itself, since the run it could not stop goes on. */
  const showResult = useCallback((text: string) => {
    setResult(text);
    if (resultTimer.current !== null) window.clearTimeout(resultTimer.current);
    resultTimer.current = window.setTimeout(() => setResult(null), RESULT_LINGER_MS);
  }, []);

  /* A click that ended the work, a start that failed or a stop, makes a
     pending -> idle edge too, and that edge must not report "Up to date" or
     "+3 new" over "Couldn't start" or "Stopped". Whether the edge's effect or
     the click's continuation runs first is React's scheduling, and a stopped
     run can stay reported for another poll, so the click leaves its readout
     here only when the edge is still to come, and the edge shows it instead. */
  const clickOutcome = useRef<string | null>(null);
  const settle = useCallback((text: string) => {
    if (wasRunning.current) clickOutcome.current = text;
    showResult(text);
  }, [showResult]);

  useEffect(() => {
    if (wasRunning.current && !pending) {
      const outcome = clickOutcome.current;
      clickOutcome.current = null;
      const n = status?.last_run_new ?? 0;
      showResult(outcome ?? (n > 0 ? shellScanResultNew({ count: n }) : shellScanResultNone()));
    } else if (!wasRunning.current && pending) {
      // New work: the last one's readout is not about it.
      setResult(null);
    }
    wasRunning.current = pending;
  }, [pending, status?.last_run_new, showResult]);

  useEffect(() => () => {
    if (resultTimer.current !== null) window.clearTimeout(resultTimer.current);
  }, []);

  // Tick once a second while running so the elapsed readout advances smoothly
  // between the (slower) status polls. Only while RUNNING: a queued sync has no
  // start time to count from, and counting from the previous run's is wrong.
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(t);
  }, [running]);

  const elapsed = running ? elapsedLabel(status?.last_run_started_at, nowMs) : "";
  // While running, the backend publishes a climbing `last_run_seen` after each
  // company, so a long (~50-min) full scrape reads as live progress rather than
  // a frozen "Syncing…". Only shown once the first company has landed (>0).
  const seen = running ? status?.last_run_seen ?? 0 : 0;
  // How much the live run covers, as its own readout rather than in the label:
  // a manual run's label is "Stop sync" (its action), and the scope is a fact
  // about the run that must survive that. "Syncing…" on a 3-company run and on
  // a 40-company one are very different waits.
  const scopeCount = busy ? syncingCompanies.length : 0;
  // What a queue is waiting on. The earliest end wins: that is when the next
  // queued company can actually start, and an open-ended block (a paused or
  // policy-denied provider) has no end to promise.
  const blocked = status?.manual_blocked ?? [];
  const blockedUntil = blocked.length > 0 && blocked.every((b) => b.until)
    ? blocked.map((b) => b.until as string).sort()[0]
    : null;
  // The background service holding the scan comes first: until it lets the
  // scan start, no provider's state matters.
  const scanJob = status?.jobs?.find((job) => job.key === "scan");
  const scanHeld = !running && scanJob?.state !== "running" ? scanJob?.reason ?? null : null;
  const queuedNote = queuedCount > 0 && !running
    ? scanHeld
      ? shellScanWaiting({ count: queuedCount, reason: scanHeld })
      : blockedUntil
      ? shellScanQueuedUntil({ count: queuedCount, time: time(blockedUntil) })
      : blocked.length > 0
        ? shellScanQueuedBlocked({ count: queuedCount, reason: blocked[0].reason })
        : shellScanQueued({ count: queuedCount })
    : "";
  // The label is the control's *action* once it is stoppable — an established
  // rule here — so the queued STATE rides in `queuedNote` beside it rather than
  // fighting for the label. The accessible name still separates the two: only a
  // live run can be stopped mid-flight; a queue is cancelled before it starts.
  const queuedOnly = queuedCount > 0 && !running;
  const label = canStop
    ? (stopping ? shellScanStopping() : result ?? shellScanStop())
    : running
      ? shellScanScanning()
      : updating
        ? shellScanUpdatingEstimates()
        : queuedCount > 0
          ? shellScanQueuedLabel()
          : result ?? shellScanNow();
  const aria = canStop
    ? (queuedOnly && !syncing ? shellScanStopQueuedAria() : shellScanStop())
    : running
      ? shellScanInProgressAria()
      : updating
        ? shellScanUpdatingEstimatesAria()
        : queuedCount > 0
          ? shellScanQueuedAria()
          : shellScanNow();
  const act = async () => {
    if (canStop) {
      setStopping(true);
      const stopped = await cancelSync();
      setStopping(false);
      if (stopped) settle(shellScanStopped());
      else showResult(shellScanCouldNotStop());
    } else if (!pending) {
      if (!(await triggerSync())) settle(shellScanCouldNotStart());
    }
  };

  return (
    <div className={`sync-split${pending ? " is-syncing" : ""}`}>
      <button
        type="button"
        className={`sync-button${pending ? " is-syncing" : ""}${canStop ? " can-stop" : ""}${result && !pending ? " is-done" : ""}`}
        onClick={() => { void act(); }}
        disabled={(pending && !canStop) || stopping}
        aria-busy={busy}
        aria-label={aria}
        title={
          canStop
            ? shellScanStopTitle()
            : running || updating
              ? shellScanRunningTitle()
              : queuedCount > 0
                ? shellScanRequestedTitle()
                : shellScanIdleTitle()
        }
      >
        {/* The spinner is a claim that work is happening. Only a live pipeline
            gets to make it — a queue is waiting, not working. */}
        <span className={`sync-icon${(running || updating) && !canStop ? " icon-spin" : ""}`} aria-hidden="true">
          <Icon name={canStop ? "xCircle" : "refresh"} />
        </span>
        <span className="sync-label">{label}</span>
        {scopeCount > 0 && (
          <span className="sync-scope-count">
            {shellScanCompanyCount({ count: scopeCount })}
          </span>
        )}
        {running && seen > 0 && <span className="sync-progress">{shellScanFound({ count: seen })}</span>}
        {running && elapsed && <span className="sync-elapsed">{elapsed}</span>}
        {queuedNote && <span className="sync-queued">{queuedNote}</span>}
      </button>
      {/* Hidden while work waits or estimates update: there is nothing for a
          pick to join until a run is live. */}
      {canPick && (
        <button
          ref={setCaret}
          type="button"
          className="sync-caret"
          aria-label={shellScanChooseAria()}
          aria-expanded={scopeOpen}
          aria-haspopup="dialog"
          title={running ? shellScanAddTitle() : shellScanSomeTitle()}
          onClick={() => setScopeOpen((open) => !open)}
        >
          <Icon name="chevronDown" size={13} />
        </button>
      )}
      {/* The picker chooses the scope and hands the run straight to this
          control, so its trigger reports where every other run state does
          rather than inside a popover that has already closed. */}
      {scopeOpen && canPick && (
        <Suspense fallback={null}>
          <SyncScopePopover
            isOpen
            joining={running}
            anchor={caret}
            onClose={() => setScopeOpen(false)}
            onFailed={() => showResult(shellScanCouldNotStart())}
          />
        </Suspense>
      )}
    </div>
  );
}
