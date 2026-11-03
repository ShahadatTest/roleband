import { sharedFilters, sharedFiltersCount } from "../copy/gen/shared";
import { CSSProperties, ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button, Icon, Overlay } from "../ui";
import { useMediaQuery } from "../hooks/useMediaQuery";

/* THE modal home of a filter register (F3 pattern). Above rail widths the register stands beside the list and this
 * renders nothing; below them it is the toolbar's "Filters · N" opener and,
 * on demand, the panel — anchored under the opener, or a bottom sheet under
 * SHEET_QUERY. The panel is `ui/Overlay`, so the lifecycle every floating
 * surface shares is not restated here: Escape, scrim click, focus capture
 * into the panel and back to the opener, the Tab trap, body scroll lock,
 * aria-modal, so the control behaves the same on every screen. The panel
 * closes itself when the viewport grows into rail mode, so shrinking again
 * never reopens a panel nobody asked for.
 *
 * What the screen still owns: the register's contents, and where in its
 * toolbar the opener sits.
 */

/** Below this the panel is a bottom sheet (FilterRail.css names the same arm). */
export const SHEET_QUERY = "(max-width: 860px)";

/** Open state that cannot survive the rail: the moment the register has its
 * own column, the folded home closes, and stays closed until asked again. */
function useFilterSurface(railMode: boolean) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (railMode) setOpen(false);
  }, [railMode]);
  return { open, toggle: () => setOpen((v) => !v), close: () => setOpen(false) };
}

export interface FilterSurfaceProps {
  /** True while the register renders as its own rail; nothing renders then. */
  railMode: boolean;
  /** Active filter count, worn on the opener as "Filters · N". */
  activeCount: number;
  children: ReactNode;
}

export function FilterSurface({ railMode, activeCount, children }: FilterSurfaceProps) {
  const { open, toggle, close } = useFilterSurface(railMode);
  const sheet = useMediaQuery(SHEET_QUERY);
  const openerRef = useRef<HTMLButtonElement>(null);
  const [anchored, setAnchored] = useState<CSSProperties>({});

  // Hung from the opener's bottom-right, re-placed on resize. The sheet arm
  // positions itself from the sheet (FilterRail.css), so no inline style
  // there — an inline top/right would beat the sheet's bottom-docking.
  useLayoutEffect(() => {
    if (!open || sheet) return;
    const place = () => {
      const rect = openerRef.current?.getBoundingClientRect();
      if (!rect) return;
      setAnchored({ top: rect.bottom + 8, right: Math.max(16, window.innerWidth - rect.right) });
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open, sheet]);

  if (railMode) return null;
  return (
    <>
      <Button ref={openerRef} aria-expanded={open} onClick={toggle}>
        <Icon name="sliders" size={14} /> {activeCount > 0 ? sharedFiltersCount({ count: activeCount }) : sharedFilters()}
      </Button>
      <Overlay
        isOpen={open}
        onClose={close}
        label={sharedFilters()}
        modal
        scrim={sheet}
        closeOnScrim
        className="filter-pop"
        style={sheet ? undefined : anchored}
      >
        {children}
      </Overlay>
    </>
  );
}
