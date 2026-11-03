import {
  shellNotifChanged,
  shellNotifClosed,
  shellNotifCoverage,
  shellNotifDigest,
  shellNotifLongOpen,
  shellNotifOther,
  shellNotifPayDown,
  shellNotifPayUp,
  shellNotifReminder,
  shellNotifReposted,
  shellNotifSavedListed,
  shellNotifScanFailed,
  shellNotifScanProblems,
  shellNotifScanStopped,
  shellNotifScanUnfinished,
  shellNotifScanning,
} from "../../copy/gen/shell";
import { Icon } from "../../ui";
import type { IconName } from "../../ui/Icon";

/**
 * Single source of truth for notification category -> icon + accessible label.
 * Labels are getters over the copy catalog, so a language switch reaches them.
 * Shared by the header bell dropdown and the full /notifications route so the
 * two surfaces never drift. Icon *shape* encodes what happened; priority tint
 * (applied via CSS on the row) encodes urgency.
 */
export const NOTIF_ICON: Record<string, { icon: IconName; label: string }> = {
  // Discovery + follow-ups: the two channels that carry the feed.
  daily_digest: { icon: "sparkle", get label() { return shellNotifDigest(); } },
  pursuit_due: { icon: "clock", get label() { return shellNotifReminder(); } },
  // Tracked-role events. Every one of these concerns a saved or pursued role;
  // the backend writes no variant for untracked roles.
  saved_update: { icon: "star", get label() { return shellNotifSavedListed(); } },
  comp_up: { icon: "trendUp", get label() { return shellNotifPayUp(); } },
  comp_down: { icon: "trendDown", get label() { return shellNotifPayDown(); } },
  repost: { icon: "refresh", get label() { return shellNotifReposted(); } },
  long_open_update: { icon: "gem", get label() { return shellNotifLongOpen(); } },
  changed: { icon: "edit", get label() { return shellNotifChanged(); } },
  closed: { icon: "xCircle", get label() { return shellNotifClosed(); } },
  // Operations. `sync_started` is transient -- it carries live progress and is
  // deleted when the run ends -- and a clean run writes nothing at all.
  sync_started: { icon: "activity", get label() { return shellNotifScanning(); } },
  sync_warning: { icon: "alertCircle", get label() { return shellNotifScanProblems(); } },
  // A scan that ran out of RoleBand's own time before some companies, with
  // nothing wrong at any of them: its own category, never a problem.
  sync_unfinished: { icon: "pause", get label() { return shellNotifScanUnfinished(); } },
  sync_failed: { icon: "errorOctagon", get label() { return shellNotifScanFailed(); } },
  // A company you follow that RoleBand can't scan cleanly right now.
  coverage: { icon: "eyeOff", get label() { return shellNotifCoverage(); } },
};

export function notifIconMeta(category: string, meta: Record<string, unknown> = {}): { icon: IconName; label: string } {
  const found = NOTIF_ICON[category] ?? { icon: "bell", label: shellNotifOther() };
  // A scan the person stopped is filed with the unfinished or problem scans
  // (meta.stopped_by_user), but it neither ran out of time nor finished.
  return meta.stopped_by_user === true ? { icon: found.icon, label: shellNotifScanStopped() } : found;
}

export function NotifIcon({ category, meta }: { category: string; meta?: Record<string, unknown> }) {
  const { icon, label } = notifIconMeta(category, meta);
  return (
    <span className="notif-icon" role="img" aria-label={label} title={label}>
      <Icon name={icon} size={15} />
    </span>
  );
}

export function notifStateClass(meta: Record<string, unknown>): string {
  const state = meta.sync_state;
  return typeof state === "string" ? `state-${state}` : "";
}
