import {
  shellBellAriaCount,
  shellNavNotifications,
  shellBellEmpty,
  shellBellLoadFailed,
  shellBellRowUnread,
  shellBellUnread,
  shellBellViewAll,
  shellNotifMarkReadFailed,
} from "../../copy/gen/shell";
import { Button } from "../../ui/Button";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { shellApi, type Notification } from "../../api/shell";
import { countBadge, fmtDate } from "../../format";
import { useJobActions } from "../../context/JobWorkspace";
import { useMissionActions, useMissionStats } from "../../context/MissionState";
import { useSyncEpoch } from "../../context/SyncState";
import { Icon, Popover, useToast } from "../../ui";
import { NotifIcon, notifStateClass } from "./notifIcons";
// The line anatomy inside the panel is the notification row's, shared with
// the /notifications list; only the popover chrome is this component's own.
import "./notification-row.css";
import "./notification-bell.css";
import { CountBadge } from "../../ui/CountBadge";

type BellTextComponent = (typeof import("./BellText"))["BellText"];

/* The bell button itself is topbar chrome and takes its .icon-btn /
 * .bell-badge styling from shell.css with the rest of the header. The POPOVER
 * is a notifications surface: it rides ui/Popover with the app-overlay doorway
 * class and paints --app-* on every route, the reason the promoted tokens live
 * at :root. */
export function NotificationBell() {
  const stats = useMissionStats();
  const { refreshStats } = useMissionActions();
  const { openJob } = useJobActions();
  const { toast } = useToast();
  const { notificationVersion } = useSyncEpoch();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Notification[]>([]);
  // The last read failed. An empty list that was never read is not "No
  // notifications yet." The panel's own sentence, not `errorText`: that brings
  // the whole error catalog into the startup chunk the bell ships in.
  const [failed, setFailed] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [anchor, setAnchor] = useState<HTMLButtonElement | null>(null);
  // What a notification says in the reader's language is a lazy chunk with its
  // own messages: the shell has no bytes to spare. Until it arrives
  // the panel shows the stored English, the same words for an English reader.
  const [Words, setWords] = useState<BellTextComponent>();
  useEffect(() => {
    if (open) void import("./BellText").then((m) => setWords(() => m.BellText));
  }, [open]);

  /* The rows are read when the panel opens, again while it is open when a
     scan finishes, and after a row is read from it. The newest read wins, as the header counts do: an older answer
     that lands late never replaces a newer one. The bell's own numbers, the
     count and the red state, come from the header counts (`stats`), so they
     follow every read and dismissal on any screen. */
  const loads = useRef(0);
  const load = () => {
    const generation = ++loads.current;
    shellApi.notifications({ limit: 15 }).then((r) => {
      if (generation !== loads.current) return;
      setItems(r.items);
      setFailed(false);
    }).catch(() => {
      if (generation === loads.current) setFailed(true);
    });
  };
  useEffect(() => () => {
    loads.current += 1;
  }, []);

  useEffect(() => {
    if (!open) return;
    load();
  }, [open, notificationVersion]);

  // Escape-to-close belongs to the Popover's Overlay; outside-click stays
  // ours because a non-modal popover has no scrim to catch it. The panel is
  // portaled, so "outside" means outside the wrap AND outside the panel.
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      const target = e.target as Node;
      if (wrapRef.current?.contains(target)) return;
      if (target instanceof Element && target.closest(".notif-popover")) return;
      setOpen(false);
    };
    window.addEventListener("pointerdown", onPointer);
    return () => window.removeEventListener("pointerdown", onPointer);
  }, [open]);

  // The role opens first and the panel closes. Marking read is
  // incidental: it follows in the background, and a failure (a reminder the
  // reconcile deleted while the panel was open answers 404, so does a row
  // another tab dismissed) is said in a toast, never an inert row or an
  // unhandled rejection.
  const openNotification = (n: Notification) => {
    if (n.job_id) {
      openJob(n.job_id, n.company);
      setOpen(false);
    }
    if (!n.read_at) {
      shellApi.markNotificationRead(n.id, true).then(
        () => {
          refreshStats();
          load();
        },
        () => {
          toast({ key: "notifications", text: shellNotifMarkReadFailed() });
          load();
        },
      );
    }
  };

  const unread = stats?.notif_unread ?? 0;
  /* The rail's Notifications badge is this same number, so it follows the same
     cap: two spellings of one count in one viewport is what the rule is for
     (format.ts). The count also goes into the button's name, so a screen
     reader hears how many. */
  const count = unread > 0 ? countBadge(unread, shellBellUnread) : null;
  const bellName = count ? shellBellAriaCount({ badge: count.label }) : shellNavNotifications();
  const badgeClass = count?.dot ? "bell-badge bell-badge-dot" : "bell-badge";

  return (
    <div className="bell-wrap" ref={wrapRef}>
      <button
        ref={setAnchor}
        className={`icon-btn bell-btn ${(stats?.notif_high_unread ?? 0) > 0 ? "has-high" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-label={bellName}
        title={bellName}
        aria-expanded={open}
      >
        <Icon name="bell" />
        {count && <CountBadge className={badgeClass}>{count.text}</CountBadge>}
      </button>
      <Popover
        isOpen={open}
        onClose={() => setOpen(false)}
        anchor={anchor}
        align="end"
        label={shellNavNotifications()}
        className="notif-popover app-overlay"
      >
        <div className="notif-popover-head">
          <strong>{shellNavNotifications()}</strong>
          {unread > 0 && <span>{shellBellUnread({ count: unread })}</span>}
        </div>
        <div className="notif-popover-list">
          {items.length === 0 ? (
            failed ? (
              <div className="notif-empty" role="alert">{shellBellLoadFailed()}</div>
            ) : (
              <div className="notif-empty">{shellBellEmpty()}</div>
            )
          ) : (
            items.map((n) => (
                <button
                  key={n.id}
                  className={`notif-item ${n.priority} ${notifStateClass(n.meta)} ${n.read_at ? "" : "unread"}`}
                  onClick={() => openNotification(n)}
                >
                  <NotifIcon category={n.category} meta={n.meta} />
                  {/* Unread is a colour on screen; said as a word to assistive tech. */}
                  {!n.read_at && <span className="sr-only">{shellBellRowUnread()}</span>}
                  <span className="notif-copy">
                    {Words ? <Words n={n} /> : (
                      <>
                        <strong>{n.title}</strong>
                        {n.body && <span>{n.body}</span>}
                      </>
                    )}
                    <time>{fmtDate(n.created_at)}</time>
                  </span>
                </button>
            ))
          )}
        </div>
        <Button className="notif-view-all" onClick={() => { navigate("/notifications"); setOpen(false); }}>
          {shellBellViewAll()}
        </Button>
      </Popover>
    </div>
  );
}
