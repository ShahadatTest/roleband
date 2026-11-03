import { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";

/* The top bar's count chip: a number and the noun it counts, in one of three
 * shapes — a fact, a lens toggle, or a link to the list it counts. One recipe
 * spelled once, so no caller writes `.stat-chip` by hand. */
type Base = {
  n: ReactNode;
  label: string;
  /** The live-market hue for a count that is market data (new roles). */
  good?: boolean;
  ariaLabel: string;
  title?: string;
};

type Shape =
  | { kind?: "fact" }
  | { kind: "lens"; onClick: () => void; pressed: boolean }
  | {
      kind: "link";
      to: string;
      state?: unknown;
      /** Match the path exactly. `to="/"` is a PREFIX of every route, so
       *  without this the Radar chip paints "active" on every screen in the
       *  app. */
      end?: boolean;
      /** Whether this chip is the view on screen, when the path alone cannot
       *  say. A router match ignores everything but the path, so `/` wearing
       *  the new-today lens would still match "open roles" and both chips
       *  would light. */
      active?: boolean;
      onClick?: () => void;
    };

export function StatChip(props: Base & Shape) {
  const base = props.good ? "stat-chip good" : "stat-chip";
  const body = (
    <>
      {/* The space is for the accessible name, not the layout (flex drops it):
          without it the visible text reads "1open", which the name "1 open
          role" does not contain. */}
      <span className="n">{props.n}</span>{" "}
      <span className="l">{props.label}</span>
    </>
  );
  if (props.kind === "lens") {
    return (
      <button
        className={`${base} clickable`}
        onClick={props.onClick}
        aria-label={props.ariaLabel}
        aria-pressed={props.pressed}
        title={props.title}
      >
        {body}
      </button>
    );
  }
  if (props.kind === "link") {
    const lit = /* not copy: class names */ `${base} clickable`;
    const shared = {
      to: props.to,
      state: props.state,
      onClick: props.onClick,
      "aria-label": props.ariaLabel,
      title: props.title,
    };
    // A plain Link when the caller knows better than the path: NavLink writes
    // `aria-current` from its own match, so a chip painted dark would still
    // announce itself as the current page.
    if (props.active !== undefined) {
      return (
        <Link {...shared} className={lit} aria-current={props.active ? "page" : undefined}>
          {body}
        </Link>
      );
    }
    return (
      <NavLink {...shared} end={props.end} className={lit}>
        {body}
      </NavLink>
    );
  }
  return (
    <div className={base} role="group" aria-label={props.ariaLabel}>
      {body}
    </div>
  );
}
