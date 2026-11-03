import { describe, expect, it } from "vitest";
import {
  CENTER,
  DAY,
  LABEL_MAX_SHIFT,
  NUMERAL_DY,
  R_NUMERAL,
  SIZE,
  dialPoint,
  placeLabels,
  type DialLabel,
} from "./dial";

/* The dial's label placement, without rendering 998 lines of SVG.
 *
 * These are PROPERTIES of the output, not its current numbers: a label never
 * survives further than `LABEL_MAX_SHIFT` from its mark, survivors never
 * overlap each other, and the fixed hour numerals win every argument.
 */

const label = (minute: number, over: Partial<DialLabel> = {}): DialLabel => ({
  key: `k${minute}-${over.ring ?? "outer"}`,
  minute,
  ring: "outer",
  time: "00:00",
  who: "anthropic",
  text: "00:00 anthropic",
  tone: "muted",
  ...over,
});

/** Two labels collide when their drawn boxes overlap horizontally AND their
 *  baselines are closer than one line. Same test the pass itself applies. */
const collides = (a: { x0: number; x1: number; y: number }, b: { x0: number; x1: number; y: number }) =>
  a.x0 < b.x1 && b.x0 < a.x1 && Math.abs(a.y - b.y) < 12;

describe("the dial's label placement", () => {
  it("never leaves two surviving labels on top of each other", () => {
    // Eight marks inside twenty minutes on one side of the outer orbit: far
    // more than the arc can carry, which is the case the drop rule exists for.
    const placed = placeLabels(
      Array.from({ length: 8 }, (_, i) => label(300 + i * 3, { key: `dense${i}` })),
    );
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        expect(
          collides(placed[i], placed[j]),
          `${placed[i].key} and ${placed[j].key} overlap after placement`,
        ).toBe(false);
      }
    }
    expect(placed.length, "every label was dropped; the pass should keep what fits").toBeGreaterThan(0);
  });

  it("keeps a whole day of marks on both orbits clear of each other", () => {
    /* The in-group pass only deconflicts labels that share a (ring, side)
       group; the final pass is the one that catches a pair from DIFFERENT
       groups — an inner label running inward across an outer one on the far
       side. A single-ring fixture cannot reach it, so the property is stated
       over a full day on both orbits. */
    const placed = placeLabels([
      ...Array.from({ length: 24 }, (_, i) => label(i * 60, { key: `outer${i}` })),
      ...Array.from({ length: 24 }, (_, i) =>
        label(i * 60 + 30, { key: `inner${i}`, ring: "inner", text: "12:30 a-connector" })),
    ]);
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        expect(
          collides(placed[i], placed[j]),
          `${placed[i].key} and ${placed[j].key} overlap after placement`,
        ).toBe(false);
      }
    }
    expect(placed.length, "a 48-mark day should still carry some labels").toBeGreaterThan(8);
  });

  it("drops a label that its own group's pass pushed onto another group's", () => {
    /* The last pass in the function compares every surviving label against
       every other, ACROSS groups — and it is not decoration. The in-group pass
       moves a label down to clear its neighbours, and the box it lands in can
       belong to the other ring, which that pass never looked at. It takes a
       crowd to reach: a two-label pair on different rings cannot, and neither
       can a tidy sweep of the day. This arrangement does.

       The loser is the label further from its own mark, which is the one that
       was already a compromise. */
    const spec: [number, "outer" | "inner", number][] = [
      [1388, "outer", 17], [270, "inner", 8], [65, "outer", 16], [1394, "inner", 20],
      [98, "inner", 17], [140, "inner", 11], [838, "outer", 8],
    ];
    const labels = spec.map(([minute, ring, width], i) => {
      const who = "x".repeat(width);
      return label(minute, { key: `crowd${i}`, ring, who, text: `00:00 ${who}` });
    });
    const placed = placeLabels(labels);

    expect(placed.length, "this crowd should not survive whole").toBeLessThan(labels.length);
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        expect(
          collides(placed[i], placed[j]),
          `${placed[i].key} and ${placed[j].key} overlap after placement`,
        ).toBe(false);
      }
    }
  });

  it("drops a label rather than shifting it past the point where it still reads as its mark's", () => {
    /* Hold the type floor and drop when crowded, never shrink to fit. The agenda beside the dial carries every
       event in full, so a dropped label costs nothing but the dot's caption. */
    const placed = placeLabels(
      Array.from({ length: 10 }, (_, i) => label(300 + i * 2, { key: `stack${i}` })),
    );
    for (const p of placed) {
      expect(
        Math.abs(p.y - p.y0),
        `${p.key} survived ${Math.abs(p.y - p.y0)} units from its mark`,
      ).toBeLessThanOrEqual(LABEL_MAX_SHIFT);
    }
    expect(placed.length, "a ten-deep stack should not fit whole").toBeLessThan(10);
  });

  it("gives way to the fixed hour numerals, which never move", () => {
    // 06:00 exactly: the mark's label wants the numeral's own baseline.
    const numeralY = dialPoint(6 * 60, R_NUMERAL)[1] + NUMERAL_DY;
    const [only] = placeLabels([label(6 * 60, { key: "six", text: "06:00 x", time: "06:00", who: "x" })]);

    expect(only, "a single label should never be dropped").toBeDefined();
    expect(
      Math.abs(only.y - numeralY),
      "the label sits on the 06 numeral. Labels move, numerals are furniture.",
    ).toBeGreaterThanOrEqual(15);
  });

  it("treats midnight's two sides as neighbours, not as 1439 minutes apart", () => {
    /* The wrap is the one place a placement pass can be numerically right and
       visually wrong: 23:59 and 00:00 are a minute apart on the dial and the
       full width of the day apart as numbers. Placement is by ANGLE, so they
       have to deconflict against each other like any other pair. */
    const placed = placeLabels([
      label(DAY - 1, { key: "before", text: "23:59 late", time: "23:59", who: "late" }),
      label(0, { key: "after", text: "00:00 early", time: "00:00", who: "early" }),
    ]);
    expect(placed.map((p) => p.key).sort()).toEqual(["after", "before"]);
    expect(collides(placed[0], placed[1]), "the two sides of midnight overlap").toBe(false);
    // Both are at the top of the dial, which is what makes them neighbours.
    for (const p of placed) expect(p.y).toBeLessThan(CENTER);
  });

  it("keeps a label inside the stage, whichever way it is anchored", () => {
    // A long name at 09:00 anchors left-to-right off the right edge; at 15:00
    // the same string runs off the left. Neither may leave the viewBox.
    for (const minute of [9 * 60, 15 * 60]) {
      const [p] = placeLabels([
        label(minute, { key: `wide${minute}`, text: "09:00 a-very-long-connector-name" }),
      ]);
      expect(p.x0, `label at ${minute} starts off-stage`).toBeGreaterThanOrEqual(0);
      expect(p.x1, `label at ${minute} runs off-stage`).toBeLessThanOrEqual(SIZE);
    }
  });
});
