import { Notification } from "../../api";
import { fmtDate } from "../../format";
import { Badge, Button, Icon } from "../../ui";
import type { BadgeTone } from "../../ui";
import { NotifIcon, notifStateClass } from "./notifIcons";
import {
  CopyButton,
  NotifDiagnostics,
  notifDetailText,
  notifSummaryText,
  parseDiagnostics,
  type CopyState,
} from "./diagnostics/NotifDiagnostics";
import { SyncProgressPanel } from "./sync-progress/SyncProgressPanel";
import { parseSyncProgress, syncProgressSummary } from "./sync-progress/model";
import { DigestPanel, parseDigest } from "./DigestPanel";
import { categoryLabel } from "./filters";
import { notificationText } from "../../api/notificationText";
import { MovedPagePanel, type MovedPageVerbs } from "./moved-page/MovedPagePanel";
import { movedPageOf } from "./moved-page/model";
import "./notification-row.css";
import {
  notificationsNotificationRowCopyFullDetails,
  notificationsNotificationRowCopyNotificationText,
  notificationsNotificationRowCopyNotificationText2,
  notificationsNotificationRowCopySummary,
  notificationsNotificationRowDetailsFor,
  notificationsNotificationRowDismiss,
  notificationsNotificationRowDismiss2,
  notificationsNotificationRowMarkRead,
  notificationsNotificationRowShowDetails,
  notificationsNotificationRowUnread,
  notificationsPriorityHigh,
  notificationsPriorityLow,
  notificationsPriorityNormal,
} from "../../copy/gen/notifications";
import { Content } from "../../ui/Content";

/** A priority code on its badge, said; an unknown one as the code. */
const PRIORITY: Record<string, () => string> = {
  high: notificationsPriorityHigh,
  normal: notificationsPriorityNormal,
  low: notificationsPriorityLow,
};

/* The priority chip's tone follows the sync state while one is attached: the
 * state outranks the priority. */
function priorityTone(n: Notification): BadgeTone {
  switch (notifStateClass(n.meta)) {
    case "state-running":
      return "info";
    case "state-success":
      return "success";
    case "state-warning":
      return "warning";
    case "state-failed":
      return "danger";
    // Ran out of RoleBand's own time: nothing went wrong, so no
    // warning hue, and no accent either, which would read as news to act on.
    case "state-partial":
      return "neutral";
    default:
      return n.priority === "high" ? "danger" : "accent";
  }
}

/** One notification: the reading (icon, title, body, live progress, time), the
 *  row's verbs, and the disclosure that reveals its diagnostics or its live
 *  sync block. Every verb is the screen controller's — this file decides how a
 *  notification LOOKS and nothing about what happens to it. */
export function NotificationRow({
  n,
  isOpen,
  copied,
  onCopy,
  onOpen,
  onToggle,
  onMarkRead,
  onDismiss,
  onOpenJob,
  movedPage,
}: {
  n: Notification;
  isOpen: boolean;
  copied: CopyState;
  onCopy: (key: string, text: string) => Promise<void>;
  onOpen: (n: Notification, hasDetails: boolean) => void;
  onToggle: (n: Notification) => void;
  onMarkRead: (n: Notification, read: boolean) => void;
  onDismiss: (n: Notification) => void;
  onOpenJob: (jobId: number, company?: string | null) => void;
  /** The answers a gone careers page offers; absent where a
   *  surface shows the notice without them. */
  movedPage?: MovedPageVerbs;
}) {
  const moved = movedPage ? movedPageOf(n.category, n.meta) : null;
  const diag = parseDiagnostics(n.meta);
  const progress = parseSyncProgress(n.meta);
  // The digest names the day's roles behind the disclosure. It has no job_id of
  // its own, so without this its row would be a count that goes nowhere.
  const digest = n.category === "daily_digest" ? parseDigest(n.meta) : null;
  // A running sync is expandable on its progress block alone — it has no
  // diagnostics until it finishes.
  const canExpand = !!diag || !!progress || !!digest;
  const panelId = `notif-details-${n.id}`;
  const text = notificationText(n);
  return (
    <article
      className={`notif-row ${n.priority} ${notifStateClass(n.meta)} ${n.read_at ? "" : "unread"} ${
        isOpen ? "open" : ""
      }`}
    >
      <div className="notif-row-head">
        <button className="notif-row-main" onClick={() => onOpen(n, canExpand)}>
          <NotifIcon category={n.category} meta={n.meta} />
          <span className="notif-copy">
            <span className="notif-row-title">
              <strong>{text.title}</strong>
              {/* Unread is a tint plus a bar whose HUE also carries priority, so
                  colour alone would carry it, on a channel two meanings share.
                  The word is for assistive tech only, as the Board's "viewed"
                  is. `aria-current` would be
                  wrong here: this is a read state, not the current item in a
                  set. */}
              {!n.read_at && <span className="sr-only">{notificationsNotificationRowUnread()}</span>}
              <Badge tone={priorityTone(n)} size="sm">{PRIORITY[n.priority]?.() ?? n.priority}</Badge>
              <Badge size="sm">{categoryLabel(n.category)}</Badge>
            </span>
            {text.body && <span>{text.bodyIsContent ? <Content text={text.body} /> : text.body}</span>}
            {progress && <span className="notif-progress-line">{syncProgressSummary(progress)}</span>}
            <time>{fmtDate(n.created_at)}</time>
          </span>
        </button>
        <div className="notif-actions">
          {canExpand && (
            <Button
              variant="icon"
              size="sm"
              className="notif-disclose"
              onClick={() => onToggle(n)}
              aria-expanded={isOpen}
              aria-controls={panelId}
              aria-label={notificationsNotificationRowShowDetails({ choice: (isOpen) ? "yes" : "no" })}
              title={notificationsNotificationRowShowDetails({ choice: (isOpen) ? "yes" : "no" })}
            >
              <Icon name="chevronDown" />
            </Button>
          )}
          <Button
            variant="icon"
            size="sm"
            className={copied?.key === `sum-${n.id}` && !copied.ok ? "failed" : ""}
            onClick={() => void onCopy(`sum-${n.id}`, notifSummaryText(n))}
            aria-label={notificationsNotificationRowCopyNotificationText()}
            title={
              notificationsNotificationRowCopyNotificationText2({ choice: (copied?.key === `sum-${n.id}` && !copied.ok) ? "yes" : "no" })
            }
          >
            <Icon name={copied?.key === `sum-${n.id}` ? (copied.ok ? "check" : "alertCircle") : "copy"} />
          </Button>
          <Button
            variant="icon"
            size="sm"
            onClick={() => onMarkRead(n, !n.read_at)}
            aria-label={notificationsNotificationRowMarkRead({ choice: (n.read_at) ? "yes" : "no" })}
            title={notificationsNotificationRowMarkRead({ choice: (n.read_at) ? "yes" : "no" })}
          >
            <Icon name={n.read_at ? "bell" : "check"} />
          </Button>
          <Button variant="icon" size="sm" onClick={() => onDismiss(n)} aria-label={notificationsNotificationRowDismiss()} title={notificationsNotificationRowDismiss2()}>
            <Icon name="trash" />
          </Button>
        </div>
      </div>

      {moved && movedPage && <MovedPagePanel page={moved} verbs={movedPage} />}

      {canExpand && isOpen && (
        <div className="notif-details" id={panelId} role="region" aria-label={notificationsNotificationRowDetailsFor({ title: text.title })}>
          {progress && <SyncProgressPanel progress={progress} />}
          {digest && <DigestPanel digest={digest} onOpenJob={onOpenJob} />}
          {diag && (
            <>
              <div className="notif-details-bar">
                <CopyButton
                  label={notificationsNotificationRowCopySummary()}
                  copyKey={`panel-sum-${n.id}`}
                  text={notifSummaryText(n)}
                  copied={copied}
                  onCopy={onCopy}
                />
                <CopyButton
                  label={notificationsNotificationRowCopyFullDetails()}
                  copyKey={`panel-full-${n.id}`}
                  text={notifDetailText(n)}
                  copied={copied}
                  onCopy={onCopy}
                />
              </div>
              <NotifDiagnostics diag={diag} />
            </>
          )}
        </div>
      )}
    </article>
  );
}
