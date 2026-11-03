import { uiDismiss } from "../copy/gen/ui";
import { ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useInRouterContext, useScreenKey } from "../routing/screen";
import { Button } from "./Button";
import { ABOVE_COVER } from "./Overlay";
import { Icon } from "./Icon";
import "./Toast.css";

/* THE toast: a transient confirmation of something that just happened, with
 * the one way to take it back. docs/ui.md
 *
 * Without it "remove", "clear" and "unsave" are instant and final. Its
 * physics: the layer
 * is fixed and ignores pointer events so it can never block the page; each
 * toast takes them back because it carries Undo; on phone widths the layer
 * clears the 64px bottom nav so Undo stays clickable; and it is OUT OF FLOW,
 * because confirming an action must never move the thing you just acted on.
 *
 * A toast is `role="status"` and times out; an error toast is `role="alert"`
 * and stays until dismissed or until its `key` is dismissed by the caller.
 * Pass `key` to replace an earlier toast about the same subject instead of
 * stacking a second one.
 *
 * And it belongs to the SCREEN THAT RAISED IT. A toast confirms
 * something that just happened here and carries the way back to it, so once the
 * reader has gone somewhere else it is a report about a page they cannot
 * see, offering to undo an edit to a list that is not on screen. The host is
 * app-level chrome, so without this rule it would ride along: remove a role in
 * Compare, click Radar, and "Removed ... Undo" would arrive on the board.
 *
 * Leaving takes them all — the way back and the plain confirmation both, since
 * "Marked 12 read" is no more true of the next screen than the Undo beside it
 * — and an error is the same rule for the same reason. What counts as leaving
 * is `routing/screen`: the pathname, where a cover counts as its own screen and
 * a query change counts as nothing.
 */
export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  text: ReactNode;
  /** The way back — rendered as a strong ghost beside the text. */
  action?: ToastAction;
  tone?: "status" | "error";
  /** ms before it goes on its own; `null` = stays. Defaults: 6000, 8000 with
      an action, sticky for an error. */
  duration?: number | null;
  /** Replaces a live toast with the same key. */
  key?: string;
}

interface ToastItem extends ToastOptions {
  id: string;
}

export interface ToastApi {
  toast: (options: ToastOptions) => string;
  dismiss: (id: string) => void;
}

/* Without a provider the API is inert: a component test that never asked for
   toasts should not have to mount them, and a screen that toasts still works
   — it just confirms nothing. The app root mounts the provider once. */
const ToastContext = createContext<ToastApi>({ toast: () => "", dismiss: () => {} });

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

const MAX_LIVE = 3;

/* The screen subscription is a child that renders nothing, and it is a child
 * for two reasons. The provider wraps the entire app, so reading the location
 * up there would re-render every screen on every navigation. And a provider
 * mounted without a Router above it — a component test that renders the one
 * screen it is about — has no location to read: the binding is then simply
 * inert, the way the toast API itself is inert without a provider. */
function ScreenWatch({ onScreen }: { onScreen: (screen: string) => void }) {
  const screen = useScreenKey();
  useEffect(() => onScreen(screen), [screen, onScreen]);
  return null;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const timers = useRef(new Map<string, number>());
  /* id -> the screen it was raised on, and the screen the reader is on now.
     Refs, not state: nothing renders from either, and the toast that reads
     `screen` reads it from an event, long after the render that set it. */
  const origin = useRef(new Map<string, string>());
  const screen = useRef<string | null>(null);
  const seq = useRef(0);
  const inRouter = useInRouterContext();

  const dismiss = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer !== undefined) window.clearTimeout(timer);
    timers.current.delete(id);
    origin.current.delete(id);
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const enterScreen = useCallback(
    (next: string) => {
      screen.current = next;
      // A copy, because `dismiss` deletes from the map being read.
      for (const [id, raisedOn] of [...origin.current]) if (raisedOn !== next) dismiss(id);
    },
    [dismiss],
  );

  const toast = useCallback(
    (options: ToastOptions) => {
      const id = options.key ?? `toast-${++seq.current}`;
      const existing = timers.current.get(id);
      if (existing !== undefined) window.clearTimeout(existing);
      if (screen.current !== null) origin.current.set(id, screen.current);
      setItems((current) => [...current.filter((item) => item.id !== id), { ...options, id }].slice(-MAX_LIVE));
      const duration =
        options.duration !== undefined
          ? options.duration
          : options.tone === "error"
            ? null
            : options.action
              ? 8000
              : 6000;
      if (duration !== null) timers.current.set(id, window.setTimeout(() => dismiss(id), duration));
      return id;
    },
    [dismiss],
  );

  useEffect(() => {
    const live = timers.current;
    return () => live.forEach((timer) => window.clearTimeout(timer));
  }, []);

  const api = useMemo(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={api}>
      {/* First, so the screen is known before a child's own effect can toast. */}
      {inRouter && <ScreenWatch onScreen={enterScreen} />}
      {children}
      {/* The live region is the HOST, which is always in the tree and empty
          until something happens. A `role="status"` that arrives WITH its text
          is unreliable — several screen-reader/browser pairs only announce
          changes to a region that was already present. `aria-atomic`
          so a replaced toast is read whole rather than as a diff.
          Deliberately no ROLE here: `role="status"` is used across the app
          for ordinary notices, and a permanently-present one would match
          every `getByRole("status")` in the tree. The items keep theirs.
          It paints above a cover (the layer scale, ui/Overlay.css) and says
          so, which puts its controls on a cover's Tab ring. */}
      <div className="ui-toast-host" aria-live="polite" aria-atomic="true" {...{ [ABOVE_COVER]: "" }}>
        {items.map((item) => {
          const error = item.tone === "error";
          return (
            <div key={item.id} className={`ui-toast${error ? " ui-toast-error" : ""}`} role={error ? "alert" : "status"}>
              <span className="ui-toast-text">{item.text}</span>
              {item.action && (
                <Button
                  size="sm"
                  className="ui-btn-strong"
                  onClick={() => {
                    item.action!.onClick();
                    dismiss(item.id);
                  }}
                >
                  {item.action.label}
                </Button>
              )}
              <Button variant="icon" size="sm" aria-label={uiDismiss()} onClick={() => dismiss(item.id)}>
                <Icon name="close" size={14} />
              </Button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
