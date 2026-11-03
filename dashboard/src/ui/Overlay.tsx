import { uiCloseLabel } from "../copy/gen/ui";
import { CSSProperties, ReactNode, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useEscapeLayer } from "./escapeLayer";
import "./Overlay.css";

// Overlay core (F1 primitive, docs/architecture.md). One place for
// the open/close contract every floating surface shares: portal rendering,
// Escape-to-close, scrim click-to-close, focus capture + restore, focus trap,
// aria-modal/role handling, and body scroll lock. Popover/Dialog/Sheet are thin
// shells over this component — new floating UI must not hand-roll these
// behaviors (ratchet-enforced, src/test/ratchet.test.ts).

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/* A layer that paints ABOVE a cover and carries controls says so with this
 * attribute — ui/Toast's host does, because it carries the way back from the
 * cover's own gestures. A cover-layer overlay runs its Tab ring on into it:
 * painted but out of the ring is still no way back. A dialog does
 * not, because a dialog outranks that layer (the scale is in Overlay.css). */
export const ABOVE_COVER = "data-above-cover";
/** Marks the page a cover is laid over (the app's rail, top bar and screen).
 *  While a modal cover is open it is inert: out of the accessibility tree and
 *  the tab order, which `aria-modal` alone does not achieve. */
export const BEHIND_COVER = "data-behind-cover";

const focusablesIn = (root: ParentNode) => Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE));

/* The modal Tab ring. The browser walks the middle of each run in DOM order;
 * this steers only the seams: it wraps the two ends, and for a cover it crosses
 * between the cover and the layer above it. Those need steering because the
 * toast host sits in the app root, BEFORE the cover's portal — DOM order runs
 * from the cover's last control off the end of the document, and from the
 * toast back into the list mounted underneath. */
function steerTab(
  e: { key: string; shiftKey: boolean; preventDefault: () => void },
  content: HTMLElement,
  above: HTMLElement[],
) {
  if (e.key !== "Tab") return;
  const own = focusablesIn(content);
  const up = above.flatMap(focusablesIn);
  const ring = [...own, ...up];
  if (ring.length === 0) {
    e.preventDefault();
    return;
  }
  const go = (el: HTMLElement) => {
    e.preventDefault();
    el.focus();
  };
  const active = document.activeElement;
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (e.shiftKey) {
    if (active === first || active === content) go(last);
    else if (up.length > 0 && active === up[0]) go(own[own.length - 1]);
  } else if (active === last) go(first);
  else if (up.length > 0 && active === own[own.length - 1]) go(up[0]);
}

const aboveCover = () => Array.from(document.querySelectorAll<HTMLElement>(`[${ABOVE_COVER}]`));

export interface OverlayProps {
  isOpen: boolean;
  onClose: () => void;
  children: ReactNode;
  /** Accessible name for the overlay content. */
  label: string;
  /** Modal overlays trap focus, lock body scroll, and set aria-modal. Default true. */
  modal?: boolean;
  /** Dim the backdrop. Default true. Non-modal shells (Popover) keep it clear. */
  scrim?: boolean;
  /** Clicking the backdrop closes the overlay. Default true. */
  closeOnScrim?: boolean;
  /** Escape closes the overlay when it is the topmost layer. Default true.
      False still holds the layer: the press never reaches what is beneath. */
  closeOnEscape?: boolean;
  role?: "dialog" | "alertdialog";
  /** Extra class for the positioned content element. */
  className?: string;
  /** Inline style for the content element (Popover uses this for anchoring). */
  style?: CSSProperties;
  /** Extra class for the fixed full-viewport wrapper (Dialog centers with it). */
  wrapperClassName?: string;
  /** Take focus on open and hand it back on close. Default true. A shell that
      opens on HOVER passes false: moving the pointer must never move the
      keyboard's focus — the opener opens it again by key with focus. */
  takeFocus?: boolean;
  /** Which rank of the layer scale (Overlay.css). `dialog` (default) is a
      question put over the screen; `cover` IS a screen, laid over the list it
      was opened from — ranked below the toast host that reports on it. */
  layer?: "dialog" | "cover";
}

export function Overlay({
  isOpen,
  onClose,
  children,
  label,
  modal = true,
  scrim = true,
  closeOnScrim = true,
  closeOnEscape = true,
  role = "dialog",
  className,
  style,
  wrapperClassName,
  takeFocus = true,
  layer = "dialog",
}: OverlayProps) {
  const contentRef = useRef<HTMLDivElement | null>(null);
  const restoreRef = useRef<HTMLElement | null>(null);

  // Capture focus on open; restore it to the opener on close/unmount. A modal
  // cover also makes the page behind it inert, in this one effect because the
  // order is the point: the opener is noted and focus moved in before the page
  // goes inert (inerting a focused element drops its focus), and the page is
  // released before focus goes back to it (an inert element refuses focus).
  useEffect(() => {
    if (!isOpen) return;
    if (takeFocus) {
      restoreRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      const content = contentRef.current;
      // Children that autofocus (callback refs run before effects) win; otherwise
      // the container itself takes focus so keyboard users land inside.
      if (content && !content.contains(document.activeElement)) content.focus();
    }
    const behind = modal && layer === "cover"
      ? Array.from(document.querySelectorAll<HTMLElement>(`[${BEHIND_COVER}]`))
      : [];
    behind.forEach((el) => el.setAttribute("inert", ""));
    return () => {
      behind.forEach((el) => el.removeAttribute("inert"));
      if (!takeFocus) return;
      const restore = restoreRef.current;
      if (!restore || !document.contains(restore)) return;
      // WebKit judges focusability from the last layout it computed, in which
      // the page is still inert, and drops the call without a word. Reading a
      // layout value brings it up to date first.
      if (behind.length > 0) void restore.offsetWidth;
      restore.focus();
    };
  }, [isOpen, takeFocus, modal, layer]);

  // Escape closes — when this is the topmost layer, and only then (ui/
  // escapeLayer). A layer that declines Escape still holds its place.
  useEscapeLayer(isOpen, closeOnEscape ? onClose : undefined, layer);

  // Modal overlays freeze the page behind them.
  useEffect(() => {
    if (!isOpen || !modal) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [isOpen, modal]);

  // Tab cycles inside modal content instead of escaping into the page — and,
  // for a cover, through whatever paints above it on the way round.
  const trapFocus = (e: React.KeyboardEvent) => {
    const content = contentRef.current;
    if (!modal || !content) return;
    steerTab(e, content, layer === "cover" ? aboveCover() : []);
  };

  // A cover's Tab from OUTSIDE its content, which the handler above never
  // hears. Two cases. Focus in the layer above the cover steers round the
  // same ring. Focus DROPPED on the page — its control is gone, as a
  // toast's Undo is by pressing it — would walk on from wherever that was,
  // and backwards from the toast host is the list under this cover; so it
  // comes back into the ring. Another modal surface over the cover (the
  // palette, a nested overlay) keeps its own focus. The toast host is always
  // mounted (it is the live region), so the regions present at open are the
  // ones there are.
  useEffect(() => {
    if (!isOpen || !modal || layer !== "cover") return;
    const regions = aboveCover();
    const onKey = (e: KeyboardEvent) => {
      const content = contentRef.current;
      const active = document.activeElement;
      if (e.key !== "Tab" || e.defaultPrevented || !content || content.contains(active)) return;
      if (regions.some((region) => region.contains(active))) return steerTab(e, content, regions);
      if (active?.closest('[aria-modal="true"], .ui-overlay')) return;
      const ring = [...focusablesIn(content), ...regions.flatMap(focusablesIn)];
      e.preventDefault();
      (ring[e.shiftKey ? ring.length - 1 : 0] ?? content).focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen, modal, layer]);

  // A modal dialog holds focus in every engine. `steerTab` steers only the
  // ring's two seams and leaves the middle to the browser, which is right where
  // the browser tabs to buttons — and WebKit, by default, does not: from a text
  // field it skips every button in the dialog and walks out into the page.
  // So once the browser has moved focus, anything that landed outside comes
  // back to the next control in the ring, in the direction the key asked for.
  // A cover needs it as much: a button after its last field or link (the
  // listing history's) walks focus out under WebKit. Its ring runs on into the layer above it, as `steerTab`'s does.
  useEffect(() => {
    if (!isOpen || !modal) return;
    const onKey = (e: KeyboardEvent) => {
      const content = contentRef.current;
      if (e.key !== "Tab" || e.defaultPrevented || !content) return;
      const from = document.activeElement;
      if (!(from instanceof HTMLElement) || !content.contains(from)) return;
      const backwards = e.shiftKey;
      // After the default action: a microtask would run before the browser moves focus.
      window.setTimeout(() => {
        const now = document.activeElement;
        if (!document.contains(content) || (now && content.contains(now))) return;
        // A surface opened by the key itself (a nested dialog) keeps its focus,
        // and so does the layer above a cover, which is in its ring.
        if (now instanceof Element && now !== document.body && now.closest(".ui-overlay")) return;
        const above = layer === "cover" ? aboveCover() : [];
        if (now && above.some((region) => region.contains(now))) return;
        const ring = [...focusablesIn(content), ...above.flatMap(focusablesIn)];
        if (ring.length === 0) return content.focus();
        const at = ring.indexOf(from);
        const next =
          at === -1
            ? ring[backwards ? ring.length - 1 : 0]
            : ring[(at + (backwards ? -1 : 1) + ring.length) % ring.length];
        next.focus();
      }, 0);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen, modal, layer]);

  if (!isOpen) return null;

  return createPortal(
    <div
      className={`ui-overlay${layer === "cover" ? " ui-overlay-cover" : ""}${wrapperClassName ? ` ${wrapperClassName}` : ""}`}
    >
      {closeOnScrim ? (
        <button
          type="button"
          className={`ui-overlay-scrim${scrim ? " ui-overlay-scrim-dim" : ""}`}
          aria-label={uiCloseLabel({ label })}
          onClick={onClose}
        />
      ) : (
        scrim && <div className="ui-overlay-scrim ui-overlay-scrim-dim" aria-hidden="true" />
      )}
      <div
        ref={contentRef}
        className={`ui-overlay-content${className ? ` ${className}` : ""}`}
        role={role}
        aria-modal={modal || undefined}
        aria-label={label}
        tabIndex={-1}
        style={style}
        onKeyDown={trapFocus}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
