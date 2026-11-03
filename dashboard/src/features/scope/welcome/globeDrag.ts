import { MAX_TILT, MIN_TILT, TILT, type Placement } from "./globeView";

/* Dragging the welcome planet: sideways turns it, up and down tilts it. The
   surface under the pointer follows the pointer, so a pixel is 1/r radians at
   the facing point. A flick leaves a speed that decays to rest; the planet's
   own slow spin then carries on from where the reader left it. */

export interface Grab {
  x: number;
  y: number;
  turned: number;
  tilt: number;
  lastX: number;
  lastAt: number;
  /** Degrees a second, sideways, over the last moves. */
  speed: number;
}

export interface DragState {
  /** Degrees the reader has turned the planet, east positive. */
  turned: number;
  tilt: number;
  /** Degrees a second left over from a flick. */
  coast: number;
  grab: Grab | null;
}

export const RESTING: DragState = { turned: 0, tilt: TILT, coast: 0, grab: null };
const FASTEST_FLICK = 300;
/** A flick loses this share of its speed each second, roughly. */
const FRICTION = 3;

export function onPlanet(x: number, y: number, at: Placement): boolean {
  return Math.hypot(x - at.cx, y - at.cy) <= at.r;
}

export function grab(state: DragState, x: number, y: number, at: number): DragState {
  return { ...state, coast: 0, grab: { x, y, turned: state.turned, tilt: state.tilt, lastX: x, lastAt: at, speed: 0 } };
}

export function move(state: DragState, x: number, y: number, at: number, r: number): DragState {
  const held = state.grab;
  if (!held) return state;
  const perPixel = 180 / Math.PI / r;
  const seconds = (at - held.lastAt) / 1000;
  const sampled = seconds > 0.008;
  return {
    ...state,
    turned: held.turned + (x - held.x) * perPixel,
    tilt: Math.max(MIN_TILT, Math.min(MAX_TILT, held.tilt + (y - held.y) * perPixel)),
    grab: sampled ? { ...held, lastX: x, lastAt: at, speed: ((x - held.lastX) * perPixel) / seconds } : held,
  };
}

/** Let go. With reduced motion the planet stops where it is. */
export function release(state: DragState, reducedMotion: boolean): DragState {
  if (!state.grab) return state;
  const speed = Math.max(-FASTEST_FLICK, Math.min(FASTEST_FLICK, state.grab.speed));
  return { ...state, grab: null, coast: reducedMotion ? 0 : speed };
}

/** Advance a flick by `seconds`. */
export function coast(state: DragState, seconds: number): DragState {
  if (state.grab || state.coast === 0) return state;
  const left = state.coast * Math.exp(-FRICTION * seconds);
  return { ...state, turned: state.turned + state.coast * seconds, coast: Math.abs(left) < 0.5 ? 0 : left };
}
