import { ReactNode } from "react";
import { sharedFilters } from "../copy/gen/shared";
import "./rail-shell.css";

/* THE two-column shell for a screen whose filter register stands beside its
 * content. The companion to
 * FilterSurface: that pattern owns the register's FOLDED home below rail
 * widths, this one owns its home beside the content above them, and both read
 * the same `railMode` from `useMediaQuery(RAIL_QUERY)`.
 *
 * What a screen still owns
 * is its measure (its own max-width arm on `.rail-shell`) and the height the
 * rail pins under, passed as the `--rail-shell-top` custom property — kept as
 * a property rather than a prop because the value is a measured CSS variable
 * (`useMeasuredCssSize`), so it must stay in the cascade rather than round-trip
 * through React on every resize.
 */
export function RailShell({
  railMode,
  register,
  className,
  children,
}: {
  /** Above rail widths the register has its own column; below, this renders
   *  only `children` and FilterSurface serves the register from the toolbar. */
  railMode: boolean;
  register: ReactNode;
  /** The screen's own arm on the shell — its measure, and `--rail-shell-top`. */
  className: string;
  children: ReactNode;
}) {
  /* Returned bare, never as `<>{railMode && rail}{children}</>`: that spelling
     would make React reconcile an ARRAY where it had one child, remounting the
     content column on every render rather than only when the rail boundary is
     actually crossed. */
  if (!railMode) return <>{children}</>;
  return (
    <div className={`rail-shell ${className}`}>
      <aside className="rail-shell-rail" aria-label={sharedFilters()}>
        {register}
      </aside>
      {children}
    </div>
  );
}
