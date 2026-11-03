import { list } from "../copy/format";
import {
  shellFreshnessAria,
  shellFreshnessLabel,
  shellFreshnessLoadingAria,
  shellFreshnessNever,
  shellFreshnessOffline,
  shellFreshnessOfflineAria,
  shellFreshnessOfflineTitle,
  shellFreshnessOldest,
  shellFreshnessWaiting,
} from "../copy/gen/shell";
import { useSyncStatus } from "../context/SyncState";
import { companyName, formatWhen, freshnessLabel } from "../format";
import { launcherNeedsAttention, launcherWaiting } from "../copy/gen/launcher-status";
import { launcherHoldText } from "./launcherStatus";

export function FreshnessBadge() {
  const { status, statusFailed } = useSyncStatus();

  if (statusFailed && !status) {
    return (
      <span className="freshness-badge unknown" role="status" aria-label={shellFreshnessOfflineAria()} title={shellFreshnessOfflineTitle()}>
        <span className="dot" aria-hidden="true" />
        <span className="freshness-label">{shellFreshnessLabel()}</span>
        <strong>{shellFreshnessOffline()}</strong>
      </span>
    );
  }

  const freshness = freshnessLabel(status);
  const hold = status?.launcher?.status.hold;
  const text = hold ? (hold.kind === "attention" ? launcherNeedsAttention() : launcherWaiting()) : freshness.text;
  const tone = hold ? (hold.kind === "attention" ? "stale" : "unknown") : freshness.tone;
  // Closure eligibility (`overdue`) does not determine whether a board was
  // recently read. The tooltip lists only boards waiting for a full read.
  const behind = (status?.scheduler.unread ?? []).map((row) => companyName(row.company));
  const title = [
    hold ? launcherHoldText(hold) : null,
    status?.last_success_at
      ? shellFreshnessOldest({ when: formatWhen(status.last_success_at) })
      : shellFreshnessNever(),
    behind.length > 0 ? shellFreshnessWaiting({ companies: list(behind) }) : null,
  ].filter(Boolean).join(". ");

  return (
    <span className={`freshness-badge ${tone}`} role="status" aria-label={status ? shellFreshnessAria({ state: text }) : shellFreshnessLoadingAria()} title={status ? title : undefined}>
      <span className="dot" aria-hidden="true" />
      <span className="freshness-label">{shellFreshnessLabel()}</span>
      <strong>{text}</strong>
    </span>
  );
}
