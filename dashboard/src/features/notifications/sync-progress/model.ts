import { useEffect, useState } from "react";
import { Notification, type SourceOutcome } from "../../../api";
import {
  notificationsModelFinishingUp,
  notificationsModelRecordingRoles,
  notificationsModelScannedFound,
  notificationsModelScanningCompanies,
  notificationsModelSources,
} from "../../../copy/gen/notifications";

/**
 * The read model behind live sync progress: parse, clock, predicates.
 *
 * The pipeline collects every source concurrently *before* it writes anything,
 * so `ScrapeRun.jobs_seen` stays at zero for the longest phase of a run: a run
 * minutes deep into hydration looks identical to a stalled one. The backend
 * publishes counters into `notification.meta.progress` (heartbeat during
 * collect, inline per company during persist); this module turns them into a
 * typed snapshot and answers the questions the views ask of it.
 *
 * Parse defensively: meta is untyped JSONB, a row may have no `progress` block
 * at all, and a `progress` block may have no `companies` array, which is why
 * the panel keeps a complete aggregate-only rendering path.
 *
 * It lives apart from `SyncProgressPanel` because the panel's own children
 * (`SyncStream`, `SyncContribution`) need these types and predicates, and
 * importing them from the panel module would import the composition root that
 * renders them: an import cycle `import/no-cycle` refuses.
 */
export type SyncPhase = "collecting" | "persisting" | "finishing";

/** Lifecycle position. Orthogonal to `outcome` — where a company is, not how it went. */
export type SyncCompanyState =
  | "queued"
  | "scraping"
  | "collected"
  | "persisting"
  | "recorded";

/** Verbatim `SourceOutcome` from the backend, as the generated schema names it. */
export type SyncOutcome = SourceOutcome;

/**
 * Whether each outcome produced usable observations: the backend's `_USABLE`
 * (`connectors/recipes/outcome.py`). `bounded`/`truncated` are listings cut by
 * OUR time or page ceiling, `suspended` one this computer cut by sleeping or
 * going offline: the pages already collected landed, and styling them as
 * failures would blame the source for our bound. `lossy` enumerated the board
 * minus a handful of unreadable rows. `empty` answered in full and listed
 * nothing. A Record, so a value the backend adds fails `tsc` here until it is
 * classified, instead of vanishing from the sync view.
 */
export const LANDED: Record<SyncOutcome, boolean> = {
  ok: true,
  capped: true,
  bounded: true,
  truncated: true,
  suspended: true,
  lossy: true,
  empty: true,
  degraded: true,
  failed: false,
  blocked: false,
  unattempted: false,
};

export interface SyncCompany {
  slug: string;
  state: SyncCompanyState;
  /** Null until collection ends. */
  outcome: SyncOutcome | null;
  /** Epoch ms this company entered `state`; null while queued. */
  sinceMs: number | null;
  /** In-scope keeps. */
  detected: number;
  /** Everything the listing returned — `detected` 0 with `scanned` high is a success. */
  scanned: number;
  recorded: number;
}

export interface SyncProgress {
  phase: SyncPhase;
  percent: number;
  companiesTotal: number;
  companiesCollected: number;
  companiesRecorded: number;
  companiesScraping: number;
  companiesQueued: number;
  companiesFailed: number;
  companiesDegraded: number;
  opportunitiesDetected: number;
  opportunitiesRecorded: number;
  opportunitiesPending: number;
  companies: SyncCompany[];
  concurrencyLimit: number;
  snapshotAtMs: number | null;
}

const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? Math.max(0, v) : 0);

const PHASES: SyncPhase[] = ["collecting", "persisting", "finishing"];

const COMPANY_STATES: SyncCompanyState[] = [
  "queued",
  "scraping",
  "collected",
  "persisting",
  "recorded",
];

const OUTCOMES = Object.keys(LANDED) as SyncOutcome[];

/** Collection has finished, whatever the outcome. */
export const FINISHED_STATES: SyncCompanyState[] = ["collected", "persisting", "recorded"];

export const PHASE_LABEL: Record<SyncPhase, string> = {
  get collecting() { return notificationsModelScanningCompanies(); },
  get persisting() { return notificationsModelRecordingRoles(); },
  get finishing() { return notificationsModelFinishingUp(); },
};

/** A snapshot older than three missed heartbeats is not describing "now" any more. */
const STALE_AFTER_MS = 90_000;
/** Beyond a day of apparent skew the server clock is nonsense; trust ours instead. */
const ABSURD_SKEW_MS = 86_400_000;

function parseCompany(raw: unknown): SyncCompany | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const c = raw as Record<string, unknown>;
  const slug = c.slug;
  if (typeof slug !== "string" || !slug) return null;
  const since = c.since_ms;
  return {
    slug,
    state: COMPANY_STATES.includes(c.state as SyncCompanyState)
      ? (c.state as SyncCompanyState)
      : "queued",
    outcome: OUTCOMES.includes(c.outcome as SyncOutcome) ? (c.outcome as SyncOutcome) : null,
    sinceMs: typeof since === "number" && Number.isFinite(since) ? since : null,
    detected: num(c.detected),
    scanned: num(c.scanned),
    recorded: num(c.recorded),
  };
}

/** Parse `meta.progress`. Returns null when absent (non-sync rows, rows without the block). */
export function parseSyncProgress(
  meta: Record<string, unknown> | null | undefined,
): SyncProgress | null {
  const raw = meta?.progress;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const p = raw as Record<string, unknown>;

  const phase = PHASES.includes(p.phase as SyncPhase) ? (p.phase as SyncPhase) : "collecting";
  const companies = Array.isArray(p.companies)
    ? (p.companies.map(parseCompany).filter(Boolean) as SyncCompany[])
    : [];
  const limit = num(p.concurrency_limit);
  const snapshotAt = p.snapshot_at_ms;
  return {
    phase,
    percent: Math.min(100, num(p.percent)),
    companiesTotal: num(p.companies_total),
    companiesCollected: num(p.companies_collected),
    companiesRecorded: num(p.companies_recorded),
    companiesScraping: num(p.companies_scraping),
    companiesQueued: num(p.companies_queued),
    companiesFailed: num(p.companies_failed),
    companiesDegraded: num(p.companies_degraded),
    opportunitiesDetected: num(p.opportunities_detected),
    opportunitiesRecorded: num(p.opportunities_recorded),
    opportunitiesPending: num(p.opportunities_pending),
    companies,
    concurrencyLimit: limit >= 1 ? Math.min(10, Math.round(limit)) : 5,
    snapshotAtMs:
      typeof snapshotAt === "number" && Number.isFinite(snapshotAt) ? snapshotAt : null,
  };
}

/** True when this notification represents a run that is still going. */
export function isSyncRunning(n: Notification): boolean {
  return n.category === "sync_started" && n.meta?.sync_state === "running";
}

/** One-line summary for the collapsed row. */
export function syncProgressSummary(p: SyncProgress): string {
  const companies = notificationsModelSources({ companiesCollected: p.companiesCollected, companiesTotal: p.companiesTotal });
  return notificationsModelScannedFound({ companies: String(companies), opportunitiesDetected: p.opportunitiesDetected });
}

const pad = (n: number) => String(n).padStart(2, "0");

/** Elapsed as a clock. Sub-minute reads in seconds so short sources feel live. */
export function fmtElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m ${pad(total % 60)}s`;
  return `${Math.floor(minutes / 60)}h ${pad(minutes % 60)}m`;
}

export interface SyncClock {
  nowMs: number;
  skewMs: number;
  staleMs: number;
}

/**
 * A clock that ticks smoothly between snapshots.
 *
 * The backend republishes progress once a heartbeat (30s) and the UI polls every
 * 15s, so anything the server measured for us would advance in visible jumps.
 * Timestamps therefore cross the wire as absolute server epochs, and the offset
 * between the two clocks is estimated here.
 *
 * Each sample is `snapshot_at - now`, which equals `trueSkew - staleness` with
 * `staleness >= 0` — so every sample is a *lower bound* on the true skew, and a
 * running maximum converges upward without ever overshooting. That choice is
 * what guarantees a rendered clock can never run backwards when a fresher
 * snapshot lands: the estimate only ever grows, so elapsed only ever grows.
 */
export function useSyncClock(snapshotAtMs: number | null, live: boolean): SyncClock {
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [skewMs, setSkewMs] = useState<number | null>(null);

  useEffect(() => {
    if (snapshotAtMs == null) return;
    const sample = snapshotAtMs - Date.now();
    if (Math.abs(sample) > ABSURD_SKEW_MS) return;
    setSkewMs((prev) => (prev === null ? sample : Math.max(prev, sample)));
    setNowMs(Date.now());
  }, [snapshotAtMs]);

  useEffect(() => {
    if (!live) return;
    // One timer for the whole panel, not one per source.
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [live]);

  const skew = skewMs ?? 0;
  return {
    nowMs,
    skewMs: skew,
    staleMs: snapshotAtMs == null ? 0 : Math.max(0, nowMs + skew - snapshotAtMs),
  };
}

/**
 * Every source has been committed, so there is no outstanding work.
 *
 * Needed because the `sync_started` row is never flipped out of `running` — a
 * finished run gets a separate terminal notification — so "the row says running"
 * is not evidence that anything is still happening.
 */
export function isRunComplete(p: SyncProgress): boolean {
  return p.companiesTotal > 0 && p.companiesRecorded >= p.companiesTotal;
}

/**
 * The run has gone quiet mid-flight.
 *
 * Gated on outstanding work: publishing stops when a run ends, so without this a
 * perfectly successful run would sit there accusing itself of having crashed 90
 * seconds later.
 */
export function isSyncStale(clock: SyncClock, complete = false): boolean {
  return !complete && clock.staleMs > STALE_AFTER_MS;
}
