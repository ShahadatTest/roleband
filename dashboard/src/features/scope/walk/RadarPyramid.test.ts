import { describe, expect, it } from "vitest";
import { layerPoints, pyramidLayers } from "./RadarPyramid";
import { NO_PROGRESS, type WalkProgress } from "./walkProgress";

/* The radar pyramid explains; it does not measure. Its
   model says what each layer decides and keeps, and its geometry is one
   triangle cut into even layers whatever the counts. */

const counted = (kept: WalkProgress["kept"], pendingFrom: WalkProgress["pendingFrom"] = null): WalkProgress => ({
  ready: true, total: 1000, kept, pendingFrom, pendingPlaces: pendingFrom ? ["Stockholm"] : [], counting: false,
});
const ALL = { accountable: true, level: true, where: true, roles: true, subjects: true };
const KEPT = { accountable: 500, level: 250, where: 100, roles: 50, subjects: 1 };

describe("pyramidLayers", () => {
  it("is five layers from Career track at the wide top to World at the point, each saying what it decides and keeps", () => {
    const layers = pyramidLayers(counted(KEPT), ALL, { roles: true, subjects: true }, true);
    expect(layers.map((layer) => layer.id)).toEqual(["accountable", "level", "where", "roles", "subjects"]);
    expect(layers.map((layer) => layer.state)).toEqual(["built", "built", "built", "built", "built"]);
    expect(layers[1]).toMatchObject({ label: "Level", gist: "Where you are today, up to where you're aiming", detail: "Keeps 25%, 250 roles" });
    expect(layers[4].detail).toBe("Keeps <1%, 1 role");
    // Visible labels carry shares; the accessible detail retains exact counts,
    // including a reduction smaller than one percent.
    expect(layers.map((layer) => layer.metric)).toEqual(["50%", "25%", "10%", "5%", "<1%"]);
  });

  it("says what an unanswered, unused, locked or unsaved layer is waiting for", () => {
    expect(pyramidLayers(counted(KEPT), { ...ALL, where: false }, { roles: true, subjects: true }, false).map((layer) => [layer.id, layer.state, layer.detail]).slice(2)).toEqual([
      ["where", "open", "Not answered yet"],
      ["roles", "locked", "After the first three answers"],
      ["subjects", "locked", "After the first three answers"],
    ]);
    expect(pyramidLayers(counted(KEPT), ALL, { roles: false, subjects: true }, true)[3]).toMatchObject({ state: "open", detail: "Any, nothing narrowed" });
    expect(pyramidLayers(counted(KEPT, "where"), ALL, { roles: true, subjects: true }, true)[2]).toMatchObject({ state: "pending", detail: "Counted after you save" });
  });

  it("with nothing read yet, an answered layer says its answer and the rest still say what they wait for", () => {
    const named = { accountable: "Leading a team", level: "At Staff", where: "In Silicon Valley", roles: "Any role that fits", subjects: "Any world" };
    const layers = pyramidLayers(NO_PROGRESS, { ...ALL, where: false }, { roles: false, subjects: false }, false, named);
    expect(layers.map((layer) => [layer.metric, layer.detail])).toEqual([
      ["Leading a team", "Leading a team"],
      ["At Staff", "At Staff"],
      ["Choose", "Not answered yet"],
      ["Locked", "After the first three answers"],
      ["Locked", "After the first three answers"],
    ]);
    expect(layers.every((layer) => !/No count|%/.test(layer.metric))).toBe(true);
  });

  it("before any count names no share and no number", () => {
    const layers = pyramidLayers(NO_PROGRESS, ALL, { roles: false, subjects: true }, true);
    expect(layers.every((layer) => !/\d/.test(layer.detail))).toBe(true);
    expect(layers[0]).toMatchObject({ state: "uncounted", detail: "Answered, no count yet" });
  });
});

describe("layerPoints", () => {
  const points = (index: number) => layerPoints(index, 5).split(" ").map((pair) => pair.split(",").map(Number));
  it("cuts one point-down triangle into even layers: equal heights, straight sides, the point at the bottom", () => {
    const heights = [0, 1, 2, 3].map((index) => points(index)[3][1] - points(index)[0][1]);
    // Even to the 0.1px the coordinates are written at.
    for (const height of heights) expect(Math.abs(height - heights[0])).toBeLessThanOrEqual(0.15);
    // Every corner on the left lies on one line, so the layers stack into one shape.
    const left = [0, 1, 2, 3, 4].flatMap((index) => [points(index)[0], points(index)[3]]);
    const slope = (a: number[], b: number[]) => (b[0] - a[0]) / (b[1] - a[1]);
    for (const corner of left.slice(1)) expect(slope(left[0], corner)).toBeCloseTo(slope(left[0], left[left.length - 1]), 1);
    // Upside down: Role, the first layer, is the widest and on top; the
    // last layer's lower corners meet in the point.
    expect(points(0)[0][1]).toBeLessThan(points(4)[0][1]);
    expect(points(0)[1][0] - points(0)[0][0]).toBeGreaterThan(points(1)[1][0] - points(1)[0][0]);
    const tip = points(4);
    expect(tip[2][0]).toBeCloseTo(tip[3][0], 5);
  });
});
