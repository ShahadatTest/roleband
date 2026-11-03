import { ReactNode, RefObject, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Job } from "../../api";
import { BAND_LABEL, companyName } from "../../format";
import { Button } from "../../ui/Button";
import { CompanyIcon } from "../../ui/CompanyIcon";
import { Content } from "../../ui/Content";
import { jobsEstShort } from "../../copy/gen/jobs";
import { Popover } from "../../ui/Popover";
import { useMediaQuery } from "../../hooks/useMediaQuery";
import "./margin.css";
import { usePayCoverage } from "../../payCoverage";
import { payShown } from "../../payShown";

/* A consequence's tick in the ledger margin (margin.css). One
 * shape for both verbs the job lists have: the compare beacon (a standing
 * state — `primary`) and the dismiss beacon (a way back — `ghost`). The
 * pill is a `ui/Button` wearing the `ui-beacon` modifier, level with the
 * element it belongs to; its reveal is a `ui/Popover` that opens on hover
 * (no focus theft, no click-catcher), on a keyboard key (ArrowDown, with
 * focus), or on tap where there is no hover. Clicking the pill itself runs
 * the fast path (`onActivate`) — for compare that is going to Compare.
 *
 * Geometry is measured, not assumed: the anchor is found by selector inside
 * the host, and the wrapper is centred on its vertical middle. Below the
 * margin width (1100px) or when the anchor is not on the page, the pill
 * DOCKS to the viewport edge; the reveal still opens.
 */

export const MARGIN_QUERY = "(min-width: 1100px)";

/* One role, as a reveal names it: the title (two lines at most, never cut —
 * it is the thing being decided on) with the row's control on its first line,
 * then ONE muted line of facts — mark, company, band, and the comp LAST with
 * its qualifier, because a bare numeral here reads as a disclosed salary. A
 * role without a number simply has a shorter line: a fact line omits a fact
 * where a column would leave a hole. The register's chip is deliberately not
 * used: a bright plate that reads as a button, for the least decisive fact in
 * the panel.
 *
 * The qualifier names the number it sits beside, and that number is ALWAYS
 * the app's estimate: `comp_low/high/median` is a stored-row or seed lookup by
 * company, level and family (`comp_provenance`), never what an employer
 * printed. `discloses_pay` says the POSTING states pay somewhere, not that
 * this range is it, so it never makes the qualifier read `disclosed`. The
 * posted band is base salary (`disclosed_comp`, detail route
 * only); it does not replace the estimate here, because base and total comp
 * cannot share one slot in a list the reader compares down. */
export function RevealRole({
  job,
  struck = false,
  control,
}: {
  job: Job;
  struck?: boolean;
  /** The row's own control (remove), placed on the title's first line. */
  control?: ReactNode;
}) {
  const name = companyName(job.company);
  const pay = payShown(job, usePayCoverage());
  const comp = pay.text;
  return (
    <span className="job-reveal-role">
      <span className="job-reveal-head">
        <span className={`job-reveal-title${struck ? " is-struck" : ""}`}><Content text={job.title} /></span>
        {control}
      </span>
      <span className="job-reveal-meta">
        <CompanyIcon slug={job.company} display={name} size={12} />
        <Content text={name} />
        <span aria-hidden="true">·</span>
        <span>{BAND_LABEL[job.level_band] ?? job.level_band}</span>
        {comp !== "—" && (
          <>
            <span aria-hidden="true">·</span>
            <span className="job-reveal-comp">
              {!pay.base && !pay.notCovered && <><span className="job-reveal-comp-kind">{jobsEstShort()}</span>{" "}</>}{comp}
            </span>
          </>
        )}
      </span>
    </span>
  );
}

const HOVER_QUERY = "(hover: hover)";
const CLOSE_GRACE_MS = 160;

export interface MarginBeaconProps {
  host: RefObject<HTMLElement | null>;
  /** CSS selector of the element the beacon is level with, inside `host`. */
  anchorSelector: string;
  /** Anything whose change may have moved the anchor (the list data). */
  anchorVersion?: unknown;
  variant: "standing" | "way-back";
  /** Accessible name of the pill. */
  label: string;
  /** What the pill shows: a glyph, and for compare the count. */
  pill: ReactNode;
  /** Runs on click / Enter. Omit when the pill's only job is its reveal. */
  onActivate?: () => void;
  revealLabel: string;
  reveal: ReactNode;
  /** When false the beacon is not rendered at all. */
  present?: boolean;
  /** Docked beacons stack from the bottom edge; 0 is the lowest. */
  dockSlot?: number;
  className?: string;
}

function useMarginAnchor(host: RefObject<HTMLElement | null>, selector: string, version: unknown) {
  const [top, setTop] = useState<number | null>(null);
  useLayoutEffect(() => {
    const root = host.current;
    if (!root) return;
    const compute = () => {
      const el = root.querySelector<HTMLElement>(selector);
      if (!el) {
        setTop(null);
        return;
      }
      const hr = root.getBoundingClientRect();
      const r = el.getBoundingClientRect();
      setTop(r.top - hr.top + r.height / 2);
    };
    compute();
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(compute);
    ro?.observe(root);
    window.addEventListener("resize", compute);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", compute);
    };
  }, [host, selector, version]);
  return top;
}

export function MarginBeacon({
  host,
  anchorSelector,
  anchorVersion,
  variant,
  label,
  pill,
  onActivate,
  revealLabel,
  reveal,
  present = true,
  dockSlot = 0,
  className,
}: MarginBeaconProps) {
  const wide = useMediaQuery(MARGIN_QUERY);
  const canHover = useMediaQuery(HOVER_QUERY);
  const top = useMarginAnchor(host, anchorSelector, anchorVersion);
  const docked = !wide || top === null;

  const [pillEl, setPillEl] = useState<HTMLButtonElement | null>(null);
  const [open, setOpen] = useState(false);
  const [byKeyboard, setByKeyboard] = useState(false);
  const closeTimer = useRef<number | null>(null);

  const cancelClose = useCallback(() => {
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
    closeTimer.current = null;
  }, []);
  const scheduleClose = useCallback(() => {
    cancelClose();
    closeTimer.current = window.setTimeout(() => setOpen(false), CLOSE_GRACE_MS);
  }, [cancelClose]);
  useEffect(() => cancelClose, [cancelClose]);

  // A reveal opened without focus closes on an outside press; one opened by
  // key (focus inside) closes on Escape through the Overlay, and on Tab out.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (pillEl?.contains(t)) return;
      if ((t as Element).closest?.(".ui-popover")) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open, pillEl]);

  if (!present) return null;

  const openReveal = (keyboard: boolean) => {
    cancelClose();
    setByKeyboard(keyboard);
    setOpen(true);
  };

  return (
    <div
      className={`job-beacon${docked ? " is-docked" : ""}${className ? ` ${className}` : ""}`}
      style={docked ? ({ "--dock-slot": dockSlot } as React.CSSProperties) : { top: top ?? 0 }}
      data-docked={docked || undefined}
      onPointerEnter={canHover ? () => openReveal(false) : undefined}
      onPointerLeave={canHover ? scheduleClose : undefined}
    >
      <span className="job-beacon-tether" aria-hidden="true" />
      <Button
        ref={setPillEl}
        variant={variant === "standing" ? "primary" : "ghost"}
        size="sm"
        className="ui-beacon"
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          // No hover to reach the reveal by: the tap opens it, and the reveal
          // carries the fast path as its primary.
          if (!canHover || !onActivate) openReveal(true);
          else onActivate();
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            openReveal(true);
          }
        }}
      >
        {pill}
      </Button>
      <Popover
        isOpen={open}
        onClose={() => setOpen(false)}
        anchor={pillEl}
        label={revealLabel}
        align="end"
        takeFocus={byKeyboard}
        closeOnScrim={false}
      >
        <div
          className="job-reveal"
          onPointerEnter={canHover ? cancelClose : undefined}
          onPointerLeave={canHover ? scheduleClose : undefined}
        >
          {reveal}
        </div>
      </Popover>
    </div>
  );
}
