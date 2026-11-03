import type { MouseEvent } from "react";

/* The half of the selection system that CSS cannot state.
 *
 * `user-select: none` keeps an element's own text out of a selection. It does
 * not stop a drag that BEGINS on the element from starting one — which then
 * sweeps up whatever is selectable around it. This is the fix, once, for
 * every drag surface.
 *
 * Two things it must be:
 *
 * - `mousedown`, not `pointerdown`. Cancelling pointerdown also cancels the
 *   click that opens the chronograph's inspector; cancelling mousedown leaves
 *   it intact.
 * - `preventDefault` on mousedown also suppresses focus. A drag surface that is
 *   itself focusable must focus itself in its own handler — spread this first,
 *   then add `onMouseDown`, and call both.
 *
 * `data-selection="chrome"` rather than a role selector because a drag surface
 * is not always a control: the stage rail is a `role="group"`, and the dial's
 * stage is a plain div.
 */
export const dragSurface = {
  "data-selection": "chrome",
  onMouseDown: (event: MouseEvent) => event.preventDefault(),
} as const;
