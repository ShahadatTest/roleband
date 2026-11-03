import { describe, expect, it } from "vitest";
import { RESTING, coast, grab, move, onPlanet, release } from "./globeDrag";
import { MAX_TILT, MIN_TILT, TILT, facingLon, place } from "./globeView";

const at = place(1928, 1056);
const perDegree = (at.r * Math.PI) / 180; // pixels the pointer moves per degree

describe("dragging the planet", () => {
  it("can be grabbed on the planet only", () => {
    expect(onPlanet(at.cx, at.cy, at)).toBe(true);
    expect(onPlanet(at.cx - at.r * 0.99, at.cy, at)).toBe(true);
    expect(onPlanet(at.cx - at.r * 1.01, at.cy, at)).toBe(false);
    expect(onPlanet(100, 100, at)).toBe(false);
  });

  it("turns with the pointer: dragging right brings the west into view", () => {
    const held = grab(RESTING, at.cx, at.cy, 0);
    const dragged = move(held, at.cx + 30 * perDegree, at.cy, 100, at.r);
    expect(dragged.turned).toBeCloseTo(30, 5);
    expect(facingLon(0, dragged.turned)).toBeCloseTo(facingLon(0, 0) - 30, 5);
    expect(dragged.tilt).toBe(TILT);
  });

  it("tilts with the pointer, and stops at its limits instead of turning over", () => {
    const held = grab(RESTING, at.cx, at.cy, 0);
    expect(move(held, at.cx, at.cy + 10 * perDegree, 50, at.r).tilt).toBeCloseTo(TILT + 10, 5);
    expect(move(held, at.cx, at.cy + 1000 * perDegree, 50, at.r).tilt).toBe(MAX_TILT);
    expect(move(held, at.cx, at.cy - 1000 * perDegree, 50, at.r).tilt).toBe(MIN_TILT);
  });

  it("ignores a move with nothing held", () => {
    expect(move(RESTING, 500, 500, 10, at.r)).toBe(RESTING);
  });

  it("coasts after a flick, slows to rest, and keeps where it stopped", () => {
    let state = grab(RESTING, at.cx, at.cy, 0);
    state = move(state, at.cx + 20 * perDegree, at.cy, 100, at.r); // 20 degrees in 0.1 s
    state = release(state, false);
    expect(state.grab).toBeNull();
    expect(state.coast).toBeGreaterThan(100);
    const before = state.turned;
    for (let i = 0; i < 300; i++) state = coast(state, 1 / 60);
    expect(state.coast).toBe(0);
    expect(state.turned).toBeGreaterThan(before);
  });

  it("does not coast with reduced motion", () => {
    let state = grab(RESTING, at.cx, at.cy, 0);
    state = move(state, at.cx + 20 * perDegree, at.cy, 100, at.r);
    expect(release(state, true).coast).toBe(0);
  });
});
