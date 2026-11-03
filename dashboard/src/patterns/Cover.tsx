import { ReactNode, RefObject } from "react";
import { useEscapeLayer } from "../ui/escapeLayer";
import { Overlay } from "../ui/Overlay";
import "./cover.css";

/* The Cover (docs/ui.md "Cover"): a full-viewport surface for
 * studying one thing, or a few, over the list it was opened from. Job detail
 * is its first occupant; Compare its second.
 *
 * Two shells, one body — because the two are different things to a keyboard
 * and a screen reader. Opened from a list it covers a page that stays MOUNTED
 * underneath (the list keeps its scroll and filters; Back pops history), so it
 * is a modal dialog: ui/Overlay owns role, aria-modal, focus capture/trap/
 * restore, Escape and the body scroll lock. Reached by URL or refresh it IS
 * the page — its one `main` landmark — and Escape is this component's to own,
 * as a `page` layer (ui/escapeLayer): one layer per cover whichever shell, or
 * onBack runs twice and steps back two entries; and anything opened over the
 * page (the palette) takes the press first.
 *
 * No scrim: the cover is opaque, so a dim layer under it would paint nothing
 * and a click-to-close target would sit over a page you cannot see.
 *
 * `data-design-system="app"` stays on the cover in BOTH shells: the rules in
 * design/surfaces.css and design/dataviz.css are gated on it, so a shell that
 * drops it silently unstyles the panels inside. */
export function Cover({
  label,
  asOverlay,
  onBack,
  bar,
  className,
  scrollRef,
  children,
}: {
  /** Accessible name — the thing being studied ("Role: …", "Comparison"). */
  label: string;
  /** True when this covers a page still mounted underneath. */
  asOverlay: boolean;
  onBack: () => void;
  /** The Bar's contents: Back · frame line · spacer · verbs · one primary. */
  bar: ReactNode;
  /** The occupant's own root class, for its scoped rules. */
  className?: string;
  /** The cover's own scroll box. An occupant scrolls through this, never a
      document-wide lookup: as an overlay, the page underneath has a cover of
      its own (a comparison, a role reached by URL) and comes first in the
      document. */
  scrollRef?: RefObject<HTMLDivElement | null>;
  children: ReactNode;
}) {
  useEscapeLayer(!asOverlay, onBack, "page");

  // By URL the cover IS the page, so it is the page's one `main` landmark; as
  // an overlay the dialog is the landmark and this is its content.
  const Root = asOverlay ? "section" : "main";
  const cover = (
    <Root
      className={`cover${className ? ` ${className}` : ""}`}
      data-design-system="app"
      aria-label={asOverlay ? undefined : label}
    >
      <div className="cover-bar">{bar}</div>
      <div className="cover-scroll" ref={scrollRef}>{children}</div>
    </Root>
  );

  if (!asOverlay) return cover;
  return (
    <Overlay
      isOpen
      onClose={onBack}
      label={label}
      modal
      layer="cover"
      scrim={false}
      closeOnScrim={false}
      className="ui-overlay-full"
    >
      {cover}
    </Overlay>
  );
}
