import { Button } from "../../../ui/Button";
import { useCallback, useState } from "react";
import { Notification } from "../../../api";
import { Badge, Icon } from "../../../ui";
import "./diagnostics.css";
import {
  notificationsNotifDiagnosticsClosed,
  notificationsNotifDiagnosticsCopyBlocked,
  notificationsNotifDiagnosticsDrift,
  notificationsNotifDiagnosticsDriftAlerts,
  notificationsNotifDiagnosticsDriftAlerts2,
  notificationsNotifDiagnosticsDriftRecorded,
  notificationsNotifDiagnosticsDuration,
  notificationsNotifDiagnosticsError,
  notificationsNotifDiagnosticsErrors,
  notificationsNotifDiagnosticsErrors2,
  notificationsNotifDiagnosticsKept,
  notificationsNotifDiagnosticsNew,
  notificationsNotifDiagnosticsNotes,
  notificationsNotifDiagnosticsOk,
  notificationsNotifDiagnosticsPerSource,
  notificationsNotifDiagnosticsPerSource2,
  notificationsNotifDiagnosticsRun,
  notificationsNotifDiagnosticsRunStartedTook,
  notificationsNotifDiagnosticsScanned,
  notificationsNotifDiagnosticsSource,
  notificationsNotifDiagnosticsSourceScannedKeptNewClosed,
  notificationsNotifDiagnosticsSourcesOk,
  notificationsNotifDiagnosticsStatus,
  notificationsNotifDiagnosticsText,
  notificationsNotifDiagnosticsTook,
  notificationsNotifDiagnosticsUnknownError,
  notificationsNotifDiagnosticsYourBrowserBlockedClipboardAccess,
} from "../../../copy/gen/notifications";
import { Msg } from "../../../ui/Msg";
import { notificationText } from "../../../api/notificationText";

/**
 * Notification diagnostics: the expanded, copy-pasteable view of a problem event.
 *
 * The backend records *where* a run hurt (per-source counters, drift alerts
 * with their status codes / req ids, source errors) in `notification.meta.diagnostics`.
 * This module is the read model for it: parse defensively (meta is untyped JSONB and
 * a row may lack the block), render it, and serialize it to text a user can paste
 * into a bug report.
 */

export interface DriftRow {
  source: string;
  message: string;
  context: Record<string, unknown>;
}

export interface SourceRow {
  source: string;
  scanned: number;
  kept: number;
  new: number;
  closed: number;
  errors: string[];
  drift_count: number;
  duration_seconds: number | null;
}

export interface Diagnostics {
  run_id: number | null;
  run_status: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  totals: Record<string, number>;
  sources: SourceRow[];
  drift: DriftRow[];
  errors: { source: string; error: string }[];
  notes: string | null;
}

const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : 0);
const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);

/** Parse `meta.diagnostics`. Returns null when absent (healthy runs, rows without the block). */
export function parseDiagnostics(meta: Record<string, unknown> | null | undefined): Diagnostics | null {
  const raw = meta?.diagnostics;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const d = raw as Record<string, unknown>;

  const sources: SourceRow[] = (Array.isArray(d.sources) ? d.sources : [])
    .filter((s): s is Record<string, unknown> => !!s && typeof s === "object")
    .map((s) => ({
      source: str(s.source) ?? "unknown",
      scanned: num(s.scanned),
      kept: num(s.kept),
      new: num(s.new),
      closed: num(s.closed),
      errors: (Array.isArray(s.errors) ? s.errors : []).map(String),
      drift_count: num(s.drift_count),
      duration_seconds: typeof s.duration_seconds === "number" ? s.duration_seconds : null,
    }));

  const drift: DriftRow[] = (Array.isArray(d.drift) ? d.drift : [])
    .filter((x): x is Record<string, unknown> => !!x && typeof x === "object")
    .map((x) => ({
      source: str(x.source) ?? "unknown",
      message: str(x.message) ?? notificationsNotifDiagnosticsDriftRecorded(),
      context: x.context && typeof x.context === "object" ? (x.context as Record<string, unknown>) : {},
    }));

  const errors = (Array.isArray(d.errors) ? d.errors : [])
    .filter((x): x is Record<string, unknown> => !!x && typeof x === "object")
    .map((x) => ({ source: str(x.source) ?? "unknown", error: str(x.error) ?? notificationsNotifDiagnosticsUnknownError() }));

  const totals: Record<string, number> = {};
  if (d.totals && typeof d.totals === "object") {
    for (const [k, v] of Object.entries(d.totals as Record<string, unknown>)) {
      if (typeof v === "number") totals[k] = v;
    }
  }

  return {
    run_id: typeof d.run_id === "number" ? d.run_id : null,
    run_status: str(d.run_status),
    started_at: str(d.started_at),
    finished_at: str(d.finished_at),
    duration_seconds: typeof d.duration_seconds === "number" ? d.duration_seconds : null,
    totals,
    sources,
    drift,
    errors,
    notes: str(d.notes),
  };
}

function fmtDuration(seconds: number | null): string {
  if (seconds === null) return "-";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

function fmtContext(context: Record<string, unknown>): string {
  return Object.entries(context)
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" ");
}

/** The short text: exactly what the collapsed row shows. */
export function notifSummaryText(n: Notification): string {
  const text = notificationText(n);
  const lines = [text.title];
  if (text.body) lines.push(text.body);
  lines.push(`${n.category} · ${n.priority} · ${n.created_at}`);
  return lines.join("\n");
}

/** The long text: summary plus the full diagnostics, ready to paste into an issue. */
export function notifDetailText(n: Notification): string {
  const d = parseDiagnostics(n.meta);
  const lines = [notifSummaryText(n)];
  if (!d) return lines.join("\n");

  lines.push("");
  lines.push(
    notificationsNotifDiagnosticsRunStartedTook({ value: String(d.run_id ?? "?"), value2: String(d.run_status ?? "?"), value3: String(d.started_at ?? "?"), duration_seconds: String(fmtDuration(
      d.duration_seconds,
    )) }),
  );
  const totals = Object.entries(d.totals);
  if (totals.length) lines.push(totals.map(([k, v]) => `${k}=${v}`).join(" "));

  if (d.errors.length) {
    lines.push("", notificationsNotifDiagnosticsErrors2({ length: d.errors.length }));
    for (const e of d.errors) lines.push(`  [${e.source}] ${e.error}`);
  }
  if (d.drift.length) {
    lines.push("", notificationsNotifDiagnosticsDriftAlerts2({ length: d.drift.length }));
    for (const row of d.drift) {
      const ctx = fmtContext(row.context);
      lines.push(`  [${row.source}] ${row.message}${ctx ? ` (${ctx})` : ""}`);
    }
  }
  if (d.sources.length) {
    lines.push("", notificationsNotifDiagnosticsPerSource2());
    lines.push(("  " + notificationsNotifDiagnosticsSourceScannedKeptNewClosed()));
    for (const s of d.sources) {
      const status = s.errors.length ? `ERROR: ${s.errors[0]}` : s.drift_count ? /* not copy: diagnostics, English by design */ `${s.drift_count} drift` : "ok";
      lines.push(
        `  ${s.source} | ${s.scanned} | ${s.kept} | ${s.new} | ${s.closed} | ${fmtDuration(
          s.duration_seconds,
        )} | ${status}`,
      );
    }
  }
  if (d.notes) lines.push("", notificationsNotifDiagnosticsNotes({ notes: String(d.notes) }));
  return lines.join("\n");
}

/** `execCommand` fallback for non-secure origins, where navigator.clipboard is unavailable. */
function execCommandCopy(text: string): boolean {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  document.body.removeChild(ta);
  return ok;
}

export type CopyState = { key: string; ok: boolean } | null;

/**
 * Clipboard write with a transient confirmation.
 *
 * Reports failure rather than swallowing it: when the browser denies clipboard
 * access (permission blocked, non-secure origin, both paths dead) the button must
 * not claim "Copied" over a clipboard that never received the text.
 */
export function useCopy(): { copied: CopyState; copy: (key: string, text: string) => Promise<void> } {
  const [copied, setCopied] = useState<CopyState>(null);
  const copy = useCallback(async (key: string, text: string) => {
    let ok = true;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      ok = execCommandCopy(text);
    }
    setCopied({ key, ok });
    window.setTimeout(() => setCopied((c) => (c?.key === key ? null : c)), 1600);
  }, []);
  return { copied, copy };
}

export function CopyButton({
  label,
  text,
  copyKey,
  copied,
  onCopy,
}: {
  label: string;
  text: string;
  copyKey: string;
  copied: CopyState;
  onCopy: (key: string, text: string) => Promise<void>;
}) {
  const state = copied?.key === copyKey ? copied : null;
  const caption = state ? notificationsNotifDiagnosticsCopyBlocked({ choice: (state.ok) ? "yes" : "no" }) : label;
  return (
    <Button
      size="sm"
      className={`notif-clip-btn${state && !state.ok ? " failed" : ""}`}
      aria-label={label}
      title={state && !state.ok ? notificationsNotifDiagnosticsYourBrowserBlockedClipboardAccess() : label}
      onClick={(e) => {
        e.stopPropagation();
        void onCopy(copyKey, text);
      }}
    >
      <Icon name={state ? (state.ok ? "check" : "alertCircle") : "copy"} size={13} />
      <span>{caption}</span>
      {/* Announce the outcome; the icon swap alone is invisible to a screen reader. */}
      <span role="status" aria-live="polite" className="sr-only">
        {notificationsNotifDiagnosticsText({ choice: (state) ? (state.ok) ? "v1" : "v2" : "v3" })}
      </span>
    </Button>
  );
}

/** The expanded panel body: errors first, then drift, then the per-source table. */
export function NotifDiagnostics({ diag }: { diag: Diagnostics }) {
  return (
    <div className="notif-diag">
      <dl className="notif-diag-meta">
        <div>
          <dt>{notificationsNotifDiagnosticsRun()}</dt>
          <dd className="mono">#{diag.run_id ?? "?"}</dd>
        </div>
        <div>
          <dt>{notificationsNotifDiagnosticsStatus()}</dt>
          <dd className="mono">{diag.run_status ?? "?"}</dd>
        </div>
        <div>
          <dt>{notificationsNotifDiagnosticsDuration()}</dt>
          <dd className="mono">{fmtDuration(diag.duration_seconds)}</dd>
        </div>
        <div>
          <dt>{notificationsNotifDiagnosticsSourcesOk()}</dt>
          <dd className="mono">
            {diag.totals.sources_ok ?? 0}/{diag.totals.sources_total ?? diag.sources.length}
          </dd>
        </div>
      </dl>

      {diag.errors.length > 0 && (
        <section className="notif-diag-block">
          <h4><Msg of={notificationsNotifDiagnosticsErrors} elems={{ length: diag.errors.length }} /></h4>
          <ul className="notif-diag-list">
            {diag.errors.map((e, i) => (
              <li key={`${e.source}-${i}`} className="bad">
                <span className="notif-diag-source mono">{e.source}</span>
                <span className="notif-diag-msg">{e.error}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {diag.drift.length > 0 && (
        <section className="notif-diag-block">
          <h4><Msg of={notificationsNotifDiagnosticsDriftAlerts} elems={{ length: diag.drift.length }} /></h4>
          <ul className="notif-diag-list">
            {diag.drift.map((row, i) => {
              const ctx = fmtContext(row.context);
              return (
                <li key={`${row.source}-${i}`} className="warn">
                  <span className="notif-diag-source mono">{row.source}</span>
                  <span className="notif-diag-msg">
                    {row.message}
                    {ctx && <code className="notif-diag-ctx mono">{ctx}</code>}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {diag.sources.length > 0 && (
        <section className="notif-diag-block">
          <h4>{notificationsNotifDiagnosticsPerSource()}</h4>
          <div className="notif-diag-scroll">
            <table className="notif-diag-table">
              <thead>
                <tr>
                  <th scope="col">{notificationsNotifDiagnosticsSource()}</th>
                  <th scope="col">{notificationsNotifDiagnosticsScanned()}</th>
                  <th scope="col">{notificationsNotifDiagnosticsKept()}</th>
                  <th scope="col">{notificationsNotifDiagnosticsNew()}</th>
                  <th scope="col">{notificationsNotifDiagnosticsClosed()}</th>
                  <th scope="col">{notificationsNotifDiagnosticsTook()}</th>
                  <th scope="col">{notificationsNotifDiagnosticsStatus()}</th>
                </tr>
              </thead>
              <tbody>
                {diag.sources.map((s) => (
                  <tr key={s.source} className={s.errors.length ? "bad" : s.drift_count ? "warn" : ""}>
                    <th scope="row" className="mono">
                      {s.source}
                    </th>
                    <td className="mono">{s.scanned}</td>
                    <td className="mono">{s.kept}</td>
                    <td className="mono">{s.new}</td>
                    <td className="mono">{s.closed}</td>
                    <td className="mono">{fmtDuration(s.duration_seconds)}</td>
                    <td>
                      {s.errors.length ? (
                        <Badge tone="danger" size="sm">{notificationsNotifDiagnosticsError()}</Badge>
                      ) : s.drift_count ? (
                        <Badge tone="warning" size="sm"><Msg of={notificationsNotifDiagnosticsDrift} elems={{ drift_count: s.drift_count }} /></Badge>
                      ) : (
                        <Badge tone="success" size="sm">{notificationsNotifDiagnosticsOk()}</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {diag.notes && <p className="notif-diag-notes">{diag.notes}</p>}
    </div>
  );
}
