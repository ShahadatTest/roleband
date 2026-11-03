import { AnchorHTMLAttributes, MouseEvent, ReactNode } from "react";
import { positionPath } from "../../routing/paths";
import "./JobLinkRow.css";

/* A compact row that OPENS A JOB (F3 pattern). A `<div onClick>` row is
 * invisible to the keyboard, announced as nothing, and unable to offer the one
 * thing a destination should — open in a new tab. Hand-rolling half the
 * contract back with role/tabIndex/onKeyDown is the copy this pattern exists
 * to stop.
 *
 * It is an ANCHOR, not a button, because a job HAS a URL: the same
 * `/company/:slug/job/:id` the board's rows navigate to. That buys Enter,
 * the status-bar destination, and cmd/ctrl/shift/middle-click straight from
 * the platform. A plain left click is intercepted so the app still opens the
 * detail as an overlay over the current page (`openJob` stashes
 * `backgroundLocation`), which a raw navigation would lose.
 *
 * The row's LOOK stays with its screen: pass the class the screen already
 * uses (`mini-job`, `cmp-head-title`). This file owns only the link reset
 * and the focus ring.
 */
export interface JobLinkRowProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href" | "onClick"> {
  jobId: number;
  /** Company slug when the caller knows it: it makes the URL canonical. */
  company?: string | null;
  /** The app's job opener — `useAppState().openJob`, or a screen's prop of it. */
  onOpen: (id: number, companySlug?: string | null) => void;
  children: ReactNode;
}

export function JobLinkRow({ jobId, company, onOpen, className, children, ...rest }: JobLinkRowProps) {
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    // Anything that means "somewhere else, please" belongs to the browser:
    // a modifier, a middle click, or a handler that already acted.
    if (event.defaultPrevented) return;
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onOpen(jobId, company);
  };
  return (
    <a
      /* A whole-row target: the row IS the control, so its title and meta are
         its label rather than prose (docs/ui.md). */
      data-selection="chrome"
      className={`job-link${className ? ` ${className}` : ""}`}
      href={company ? positionPath(company, jobId) : `/job/${jobId}`}
      onClick={onClick}
      {...rest}
    >
      {children}
    </a>
  );
}
