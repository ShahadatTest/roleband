import "./ExternalLink.css";
import type { ReactNode } from "react";
import { Icon } from "./Icon";

/** A link out of RoleBand, inside running text: the `link` control's accented
 *  rank (`docs/ui.md`, Controls), opening a new tab, with the external
 *  glyph so the reader knows before clicking that it leaves the app. An anchor
 *  takes the link vocabulary without the button component (`docs/ui.md`). */
export function ExternalLink({ href, label, children }: {
  href: string;
  /** The accessible name, when the words shown are the same for several
   *  links on one screen. It starts with those words (WCAG 2.5.3). */
  label?: string;
  children: ReactNode;
}) {
  return (
    <a className="ui-btn ui-btn-link ui-external-link" href={href} target="_blank" rel="noreferrer" aria-label={label}>
      {children}
      <Icon name="external" size={12} />
    </a>
  );
}
