import { ReactNode } from "react";
import "../design/settings-shell.css";
import "../design/settings.css";

/* The Settings route's structural root.
 *
 * It sets no marker on the BODY: a surface React renders into a portal,
 * outside this subtree, states its own paint in the sheet that owns it, which
 * is the only place that works on every route (the ScopeGuide drawer opens
 * from Profile too, and Profile is not a Settings route).
 *
 * The wrapper's job: it IS the page's `<main>`, and
 * `data-design-system="settings"` is the route marker the type/geometry
 * contracts read.
 */
export function SettingsDesignSystemRoot({ children }: { children: ReactNode }) {
  return (
    <main
      className="main settings-view settings-design-system"
      data-design-system="settings"
    >
      {children}
    </main>
  );
}
