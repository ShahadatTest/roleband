import { ReactNode, useId } from "react";
import "./Card.css";

/* The Card primitive: the reference anatomy as components, so a screen
 * cannot drift row-by-row. It lives in `ui/`, so there is no second primitive
 * tier outside the `ui/` barrel and every lint zone. Consumes --app-* only.
 *
 * The CSS class names read `.settings-*`: they are load-bearing in several
 * stylesheets and gates, so renaming them is a change of its own. */

/** One screen zone as one surface, hairlines inside (never nested cards).
 *  The head is a real heading, so the document outline is never empty. */
export function Card({
  title,
  label,
  meta,
  intro,
  className,
  children,
}: {
  title: ReactNode;
  /** Explicit region name when the title node isn't plain text (defaults to
   *  naming the region by the heading via aria-labelledby). */
  label?: string;
  /** Right-hand head cluster: a mono caption, a help trigger, or one action. */
  meta?: ReactNode;
  /** One-line standing copy under the head — never an InfoTip. */
  intro?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  const headingId = useId();
  return (
    <section
      className={`settings-card${className ? ` ${className}` : ""}`}
      aria-label={label}
      aria-labelledby={label ? undefined : headingId}
    >
      <header className="settings-card-head">
        <h2 id={headingId} className="settings-card-title">{title}</h2>
        {meta && <div className="settings-card-meta">{meta}</div>}
      </header>
      {intro && <p className="settings-card-intro">{intro}</p>}
      <div className="settings-card-body">{children}</div>
    </section>
  );
}

/** What a row hands the Switch in its `toggle` slot. */
export interface CardRowSwitchSlot {
  className: string;
  describedBy?: string;
  children: ReactNode;
}

/** The reference row: control | text stack | trailing meta, hairline-separated.
 *  Title at `name`, description in the body voice, facts in the data voice. */
export function CardRow({
  control,
  toggle,
  title,
  description,
  facts,
  trailing,
  tone,
  className,
  testId,
}: {
  /** Checkbox/radio for the row; when present, control + copy become a label. */
  control?: ReactNode;
  /** Renders a `ui/Switch` (named by its own `label`) from what the row hands
   *  it: `<Switch {...slot} checked=... onChange=... label=... />`. The copy
   *  becomes the switch's visible label, so the whole row is its target. Its
   *  own slot, not `control`: a Switch is a label of its own (a label inside
   *  the row's label is invalid), and `control`'s 15px box is a checkbox's
   *  size, which collapses a Switch put there into a dot. A render function
   *  rather than props or an element, so this primitive imports neither Switch
   *  nor `cloneElement`: either edge costs the shell chunk bytes (Switch would
   *  join the preload list of every route that renders a card; `cloneElement`
   *  would become a new export of the React the shell carries). */
  toggle?: (slot: CardRowSwitchSlot) => ReactNode;
  title: ReactNode;
  description?: ReactNode;
  /** Data line: mono, muted, tabular. Carries counts/timestamps, never prose. */
  facts?: ReactNode;
  trailing?: ReactNode;
  /** "action" = gold selection wash; "info" = live-activity wash. */
  tone?: "action" | "info";
  className?: string;
  /** `data-testid` for a row a test must tell apart from identical siblings. */
  testId?: string;
}) {
  const descriptionId = useId();
  const copy = (
    <span className="settings-row-copy">
      <span className="settings-row-title">{title}</span>
      {description && <span className="settings-row-desc" id={descriptionId}>{description}</span>}
      {facts && <span className="settings-row-facts">{facts}</span>}
    </span>
  );
  return (
    <div
      className={`settings-row${tone ? ` is-${tone}` : ""}${className ? ` ${className}` : ""}`}
      data-testid={testId}
    >
      {toggle ? (
        toggle({
          className: "settings-row-hit",
          describedBy: description ? descriptionId : undefined,
          children: copy,
        })
      ) : control ? (
        <label className="settings-row-hit">
          <span className="settings-row-control">{control}</span>
          {copy}
        </label>
      ) : (
        copy
      )}
      {trailing && <span className="settings-row-trailing">{trailing}</span>}
    </div>
  );
}

export type CardMessageTone = "danger" | "positive" | "info";

/** Banner for errors, confirmations, and notices, so no tab renders its
 *  failure states as bare unstyled text.
 *
 *  An EVENT or a failure, never the card's furniture: standing copy is the
 *  card's `intro` or a row's description, a row's status is one of its
 *  `facts`, and an empty list is `ui/EmptyState`, so one box never means four
 *  things on four tabs. Between
 *  rows it is an aside: the row after it keeps its hairline. */
export function CardMessage({
  tone = "danger",
  role,
  className,
  children,
}: {
  tone?: CardMessageTone;
  role?: "alert" | "status" | "note";
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={`settings-message is-${tone}${className ? ` ${className}` : ""}`}
      role={role}
    >
      {children}
    </div>
  );
}
