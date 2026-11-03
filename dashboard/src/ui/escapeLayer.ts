import { useEffect, useLayoutEffect, useRef } from "react";

/* ONE press of Escape, ONE surface: the one on top.
 *
 * A surface holds a LAYER while it is open, and one window listener hands the
 * press to the topmost layer alone, so one press never closes the palette AND
 * steps the cover under it back, or takes a dialog with the popover opened in
 * it. Window-level still, so it works when focus has escaped the surface.
 *
 * Topmost means painted on top: the rank on the layer scale (ui/Overlay.css)
 * first, so a cover opened under a dialog never outranks it, then the order the
 * surfaces opened in, which is how a popover sits over the dialog it was opened
 * from. `page` is a screen whose own Escape is a step (a cover reached by URL,
 * the welcome scene): anything opened over it comes first.
 *
 * A layer that declines Escape still holds its place — what it covers is not
 * what the reader is looking at. And a press a control inside has already
 * handled (`preventDefault`) is not a surface's to act on. */

export type EscapeRank = "page" | "cover" | "dialog";

const RANK: Record<EscapeRank, number> = { page: 0, cover: 1, dialog: 2 };

interface Layer {
  rank: number;
  /** Runs the surface's Escape; false when it declines. */
  escape: () => boolean;
}

/** Bottom to top. */
const layers: Layer[] = [];

function onKeyDown(e: KeyboardEvent) {
  if (e.key !== "Escape" || e.defaultPrevented) return;
  if (layers[layers.length - 1]?.escape()) e.preventDefault();
}

/**
 * Hold an Escape layer while `active`. `onEscape` undefined declines the press
 * without giving it to the layer beneath. Registration is keyed on `active` and
 * `rank` only: the handler is read through a ref, because a re-render is not a
 * re-open, and re-registering on a new handler identity would lift a layer over
 * the ones opened after it.
 */
export function useEscapeLayer(active: boolean, onEscape: (() => void) | undefined, rank: EscapeRank = "dialog") {
  const latest = useRef(onEscape);
  useLayoutEffect(() => {
    latest.current = onEscape;
  });

  useEffect(() => {
    if (!active) return;
    const layer: Layer = {
      rank: RANK[rank],
      escape: () => {
        const run = latest.current;
        run?.();
        return run !== undefined;
      },
    };
    // Over everything of its rank and below, under anything that outranks it.
    const above = layers.findIndex((other) => other.rank > layer.rank);
    layers.splice(above === -1 ? layers.length : above, 0, layer);
    if (layers.length === 1) window.addEventListener("keydown", onKeyDown);
    return () => {
      layers.splice(layers.indexOf(layer), 1);
      if (layers.length === 0) window.removeEventListener("keydown", onKeyDown);
    };
  }, [active, rank]);
}
