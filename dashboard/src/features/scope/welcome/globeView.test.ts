import { geoOrthographic, geoProjection } from "d3-geo";
import { describe, expect, it } from "vitest";
import {
  START_LON, STACKED_BELOW, TILT, facingLon, horizon, litness, perspective, place, projectionScale,
  scanEntry, scanLon, scanReach, sinceScan, trailAt, viewDistance, visible,
} from "./globeView";

/** The planet as the intro draws it, on a canvas of width x height. */
function planet(width: number, height: number) {
  const at = place(width, height);
  const distance = viewDistance(at.r, height);
  const projection = geoProjection(perspective(distance))
    .clipAngle((horizon(distance) * 180) / Math.PI)
    .rotate([-facingLon(0, 0), -TILT])
    .translate([at.cx, at.cy])
    .scale(projectionScale(at.r, distance));
  return { at, projection };
}

describe("where the planet sits", () => {
  it("is large on the right of a wide screen, and across the top of a narrow one", () => {
    const wide = place(1928, 1056);
    expect(wide.stacked).toBe(false);
    expect(wide.cx).toBeGreaterThan(1928 / 2);
    expect(wide.cy + wide.r).toBeGreaterThan(1056); // runs off the bottom
    const narrow = place(STACKED_BELOW - 1, 760);
    expect(narrow.stacked).toBe(true);
    expect(narrow.cx).toBe((STACKED_BELOW - 1) / 2);
  });

  /* What the camera is for: tilted toward the viewer, the north pole sits on
     the planet's top edge, so the scan line runs edge to edge. A flat
     (orthographic) view of the same tilt shows the pole inside the disc. */
  it.each([[1928, 1056], [1368, 856]])("puts the north pole on the top edge at %ix%i", (width, height) => {
    const { at, projection } = planet(width, height);
    const pole = projection([0, 90]);
    expect(pole).not.toBeNull();
    expect(Math.abs(pole![1] - (at.cy - at.r))).toBeLessThan(at.r * 0.03);
    const flat = geoOrthographic().rotate([-START_LON, -TILT]).translate([at.cx, at.cy]).scale(at.r)([0, 90])!;
    expect(flat[1] - (at.cy - at.r)).toBeGreaterThan(at.r * 0.05);
  });

  it("shows the facing point at the centre and hides the far side", () => {
    const { at, projection } = planet(1928, 1056);
    const centre = projection([START_LON, TILT])!;
    expect(Math.abs(centre[0] - at.cx)).toBeLessThan(1);
    expect(Math.abs(centre[1] - at.cy)).toBeLessThan(1);
    const distance = viewDistance(at.r, 1056);
    const facing: [number, number] = [START_LON, TILT];
    expect(visible(facing, facing, distance)).toBe(true);
    expect(visible([START_LON + 60, TILT], facing, distance)).toBe(true);
    // The camera sees a little less than half the planet: 80 degrees away is hidden.
    expect(visible([START_LON + 80, TILT], facing, distance)).toBe(false);
    // A projection maps the far side onto the disc (the antipode lands at the
    // centre), which is why cities are tested with `visible`.
    expect(visible([START_LON + 180, -TILT], facing, distance)).toBe(false);
    expect(projection([START_LON + 180, -TILT])).not.toBeNull();
  });
});

describe("the scan", () => {
  it("moves east, a full turn per sweep", () => {
    const step = ((scanLon(1) - scanLon(0)) + 360) % 360;
    expect(step).toBeGreaterThan(0);
    expect(step).toBeLessThan(180);
  });

  it("lights a city just after passing it, not just before", () => {
    const scan = scanLon(2.3);
    expect(litness(sinceScan(scan, scan - 1))).toBeGreaterThan(0.9);
    expect(litness(sinceScan(scan, scan + 1))).toBeLessThan(0.01);
  });

  it("leaves a trail that is strongest at the line and fades behind it", () => {
    expect(trailAt(0)).toBe(1);
    expect(trailAt(10)).toBeLessThan(trailAt(5));
    expect(trailAt(90)).toBeLessThan(0.05);
  });
});

describe("where the scan starts", () => {
  /* The line enters from the west. Started too early it shows as a sliver
     near the north pole; it starts once it reaches from the top of the planet
     to the bottom of what is shown, on the planet's western side. */
  it.each([[2000, 1100], [1440, 900], [375, 394]])("on a %ix%i canvas it starts reaching the bottom, on the western side", (width, height) => {
    const at = place(width, height);
    const bottom = Math.min(height, at.cy + at.r) - 1;
    const lon = scanLon(scanEntry(width, height));
    expect(scanReach(lon, width, height)).toBeGreaterThanOrEqual(bottom);
    expect(scanReach(lon - 0.5, width, height)).toBeLessThan(bottom);
    const west = ((facingLon(0, 0) - lon) % 360 + 360) % 360;
    expect(west).toBeGreaterThan(0);
    expect(west).toBeLessThan(90);
  });
});
