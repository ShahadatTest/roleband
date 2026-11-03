import type { ReactNode } from "react";
import "./CountBadge.css";

/** A count on a navigation item (`CountBadge.css` holds the one recipe).
 *  `className` names the placement, which owns position and colour only.
 *  `spoken` keeps the count in the accessible name (a tab's "Queue 9");
 *  otherwise the item's own name carries it and the badge is hidden. */
export function CountBadge({ className, spoken = false, children }: {
  className: string;
  spoken?: boolean;
  children?: ReactNode;
}) {
  return (
    <span className={`ui-count ${className}`} aria-hidden={spoken ? undefined : true}>
      {children}
    </span>
  );
}
