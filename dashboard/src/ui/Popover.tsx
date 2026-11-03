import { CSSProperties, ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useInRouterContext, useScreenKey } from "../routing/screen";
import { Overlay } from "./Overlay";
import "./Popover.css";

// Anchor-positioned, non-modal overlay shell: glass panel below (or above) its
// anchor, clear click-catcher behind it, Escape/outside-click to close, focus
// restored to the anchor on close. Filter popovers, hover cards, and menus
// build on this instead of hand-rolling scrims + placement math.

const GAP = 6;
const MARGIN = 8;

/* A popover belongs to the SCREEN it was opened on — the toast's rule,
 * for the same reason. Leaving closes it, and a cover counts as
 * leaving (`routing/screen`); a query change does not. The page under a cover
 * stays MOUNTED, so a popover opened on the list would outlive it: the compare
 * roster, whose own primary is what opens the comparison, would stay open, and
 * since a cover ranks below a popover (ui/Overlay.css) it would float over the
 * comparison.
 * A child for the reason Toast's is: no Router, no screen — inert. */
function LeaveCloses({ onLeave }: { onLeave: () => void }) {
  const screen = useScreenKey();
  const openedOn = useRef(screen);
  useEffect(() => {
    if (screen === openedOn.current) return;
    openedOn.current = screen;
    onLeave();
  }, [screen, onLeave]);
  return null;
}

export interface PopoverProps {
  isOpen: boolean;
  onClose: () => void;
  /** Element the popover attaches to (usually the trigger button). */
  anchor: HTMLElement | null;
  children: ReactNode;
  label: string;
  /** Horizontal alignment against the anchor. Default "start". */
  align?: "start" | "end";
  /** A column the panel spans instead: it takes this element's left and right
      edges, so it lines up with the content around its anchor. `align` is
      then unused. */
  within?: HTMLElement | null;
  className?: string;
  /** See Overlay. A hover-opened popover passes false for both: no focus
      theft, and no click-catcher over the page — the opener owns closing. */
  takeFocus?: boolean;
  closeOnScrim?: boolean;
}

export function Popover({
  isOpen,
  onClose,
  anchor,
  children,
  label,
  align = "start",
  within,
  className,
  takeFocus = true,
  closeOnScrim = true,
}: PopoverProps) {
  const [inner, setInner] = useState<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<CSSProperties>({});
  const inRouter = useInRouterContext();

  // Place below the anchor, clamped to the viewport; flip above when the
  // measured panel would fall off the bottom (CompanyHoverCard convention).
  useLayoutEffect(() => {
    if (!isOpen || !anchor) return;
    const compute = () => {
      const rect = anchor.getBoundingClientRect();
      const h = inner?.offsetHeight ?? 0;
      let top = rect.bottom + GAP;
      if (h && top + h > window.innerHeight - MARGIN) {
        top = Math.max(MARGIN, rect.top - h - GAP);
      }
      if (within) {
        const column = within.getBoundingClientRect();
        setPos({ top, left: column.left, width: column.width });
        return;
      }
      const w = inner?.offsetWidth ?? 0;
      let left = align === "end" ? rect.right - w : rect.left;
      left = Math.max(MARGIN, Math.min(left, window.innerWidth - w - MARGIN));
      setPos({ top, left });
    };
    compute();
    window.addEventListener("resize", compute);
    return () => window.removeEventListener("resize", compute);
  }, [isOpen, anchor, align, within, inner]);

  return (
    <>
      {isOpen && inRouter && <LeaveCloses onLeave={onClose} />}
      <Overlay
        isOpen={isOpen}
        onClose={onClose}
        label={label}
        modal={false}
        scrim={false}
        takeFocus={takeFocus}
        closeOnScrim={closeOnScrim}
        className={`ui-popover${within ? " ui-popover-spans" : ""}${className ? ` ${className}` : ""}`}
        style={{ position: "fixed", ...pos }}
      >
        <div ref={setInner} className="ui-popover-inner">
          {children}
        </div>
      </Overlay>
    </>
  );
}
