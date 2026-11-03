import { geoDistance, geoProjection } from "d3-geo";

/* The welcome planet's geometry and motion, apart from any drawing, so unit
   tests reach them. Angles are degrees unless a name says radians.

   The planet is seen through a camera: a lens of FOV degrees at the distance
   that makes it `r` pixels wide. From there a little less than half the
   sphere shows, so with the tilt the north pole sits on the top edge rather
   than inside the disc, and meridians (the scan line among them) run edge to
   edge. */

/** Below this canvas width the planet sits across the top and the copy below. */
export const STACKED_BELOW = 640;
const FOV = 30;
/** The planet turns west to east, this many degrees a second. */
const SPIN = 4;
/** The longitude facing the viewer at first: the Americas, Europe and Africa. */
export const START_LON = -30;
/** The latitude facing the viewer: the north leans in. */
export const TILT = 20;
export const MIN_TILT = -45;
export const MAX_TILT = 70;
/** One sweep of the scan around the planet, in seconds. */
const PERIOD = 6;
/** Radians behind the scan line over which its trail fades. */
const TRAIL = 0.45;
/** Radians behind the scan line over which a city stays lit. */
const LIT = 0.6;
/** The moment drawn when motion is reduced: the scan crosses the Americas. */
export const STILL_AT = 2.3;

const RAD = Math.PI / 180;

export interface Placement {
  r: number;
  cx: number;
  cy: number;
  stacked: boolean;
}

/** Large on the right and running off the bottom; across the top when narrow. */
export function place(width: number, height: number): Placement {
  if (width < STACKED_BELOW) {
    const r = width * 0.68;
    return { r, cx: width / 2, cy: r * 0.96, stacked: true };
  }
  const r = Math.min(height * 0.56, width * 0.36);
  return { r, cx: width * 0.64, cy: height * 0.57, stacked: false };
}

/** The camera's distance from the planet's centre, in planet radii. */
export function viewDistance(r: number, height: number): number {
  return 1 / Math.sin(Math.atan((r / (height / 2)) * Math.tan((FOV * RAD) / 2)));
}

/** The angle from the facing point to the visible edge, in radians. */
export function horizon(distance: number): number {
  return Math.acos(1 / distance);
}

/** Whether a point is on the side of the planet the camera sees. A d3
    projection clips shapes but not single points, so a city is tested here:
    the far side would otherwise project onto the visible disc. */
export function visible(point: [number, number], facing: [number, number], distance: number, margin = 0): boolean {
  return geoDistance(point, facing) < horizon(distance) - margin;
}

/** How squarely a point faces the camera: 1 at the facing point, 0 at the edge. */
export function facingShare(point: [number, number], facing: [number, number], distance: number): number {
  const edge = 1 / distance;
  return Math.max(0, (Math.cos(geoDistance(point, facing)) - edge) / (1 - edge));
}

/** Vertical perspective from `distance` radii away: a d3 raw projection. */
export function perspective(distance: number) {
  return (lambda: number, phi: number): [number, number] => {
    const k = (distance - 1) / (distance - Math.cos(phi) * Math.cos(lambda));
    return [k * Math.cos(phi) * Math.sin(lambda), k * Math.sin(phi)];
  };
}

/** The projection scale that makes the horizon circle `r` pixels wide. */
export function projectionScale(r: number, distance: number): number {
  return r / Math.sqrt((distance - 1) / (distance + 1));
}

/** The scan line's longitude at `seconds`: it moves east, a turn per PERIOD. */
export function scanLon(seconds: number): number {
  return ((seconds % PERIOD) / PERIOD) * 360 - 197.1;
}

/** How long ago, as an angle in radians, the scan passed longitude `lon`. */
export function sinceScan(scan: number, lon: number): number {
  return ((((scan - lon) % 360) + 360) % 360) * RAD;
}

/** 1 the moment the scan passes a city, fading to 0 behind it. */
export function litness(since: number): number {
  return Math.exp(-since / LIT);
}

/** The trail's strength `degrees` behind the line, 1 at the line. */
export function trailAt(degrees: number): number {
  return Math.exp(-(degrees * RAD) / TRAIL);
}

/** The longitude facing the viewer after `spun` seconds and a `turned` drag. */
export function facingLon(spun: number, turned: number): number {
  return START_LON - spun * SPIN - turned;
}

/** How far down the scan line reaches on screen in one unbroken run from its
    northern end, with the line at `lon` and the planet at rest (START_LON,
    TILT) on a canvas of width x height. The run ends where the line goes
    behind the planet or off the side of the canvas (on a phone the planet is
    wider than the screen). -Infinity when none of it is on screen. */
export function scanReach(lon: number, width: number, height: number): number {
  const at = place(width, height);
  const distance = viewDistance(at.r, height);
  const facing: [number, number] = [facingLon(0, 0), TILT];
  const projection = geoProjection(perspective(distance))
    .rotate([-facing[0], -facing[1]]).translate([at.cx, at.cy]).scale(projectionScale(at.r, distance));
  let lowest = -Infinity;
  for (let lat = 89.5; lat >= -89.5; lat -= 0.5) {
    const point = visible([lon, lat], facing, distance) ? projection([lon, lat]) : null;
    const shown = point !== null && point[0] >= 0 && point[0] <= width;
    if (!shown) {
      if (lowest > -Infinity) break;
      continue;
    }
    lowest = Math.max(lowest, point[1]);
  }
  return lowest;
}

/** The moment the scan is first drawn, in scan seconds: the line has just
    come round the planet's western edge and, on screen, reaches from the top
    of the planet to the bottom of what is shown. Started earlier, the line shows as
    a sliver near the north pole first and reads as appearing out of the top.
    The scan moves east, so the search walks east from the far side. */
export function scanEntry(width: number, height: number): number {
  const at = place(width, height);
  const bottom = Math.min(height, at.cy + at.r) - 1;
  const west = facingLon(0, 0) - 180;
  let lon = west;
  for (let step = 0; step < 360; step += 0.5) {
    lon = west + step;
    if (scanReach(lon, width, height) >= bottom) break;
  }
  return (((((lon + 197.1) % 360) + 360) % 360) / 360) * PERIOD;
}
