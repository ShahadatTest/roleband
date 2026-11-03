import type { ScheduleEvent, ScheduleMode } from "./schedule";

/* The chronograph's geometry, with no React in it.

   `ScheduleChronograph.tsx` draws the dial; this decides WHERE. The label
   placement pass is the part worth reading on its own: it clamps each label
   into the stage, clears the fixed hour numerals, resolves label-on-label
   collisions within each (ring, side) group, and DROPS a label that has been
   pushed so far it stops reading as its mark's: hold the type
   floor and drop when crowded rather than shrink to fit. */

export const SIZE = 620;
export const CENTER = SIZE / 2;
export const R_REC = 216;
export const R_DISC = 164;
export const R_HUB = 108;
export const R_TICKS = 260;
export const R_NUMERAL = 238;
export const DAY = 24 * 60;
/** Half-thickness of the cycle's lit track and of the halo under it. The
 *  track is deliberately near the orbit's own line weight: as thick as the
 *  24px marks, the pair would read as one painted slab. */
export const WINDOW_BAND = 2.75;
export const WINDOW_HALO = 8;

const rad = (minute: number) => (minute / DAY) * Math.PI * 2;

export const dialPoint = (minute: number, r: number): [number, number] => [
  CENTER + r * Math.sin(rad(minute)),
  CENTER - r * Math.cos(rad(minute)),
];

export const arcPath = (m1: number, m2: number, r: number) => {
  const [x1, y1] = dialPoint(m1, r);
  const [x2, y2] = dialPoint(m2, r);
  const span = (m2 - m1 + DAY) % DAY;
  const large = span > DAY / 2 ? 1 : 0;
  return `M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`;
};

export const annulusPath = (m1: number, m2: number, r1: number, r2: number) => {
  const [ax, ay] = dialPoint(m1, r2);
  const [bx, by] = dialPoint(m2, r2);
  const [cx, cy] = dialPoint(m2, r1);
  const [dx, dy] = dialPoint(m1, r1);
  const span = (m2 - m1 + DAY) % DAY;
  const large = span > DAY / 2 ? 1 : 0;
  return [
    `M ${ax.toFixed(1)} ${ay.toFixed(1)}`,
    `A ${r2} ${r2} 0 ${large} 1 ${bx.toFixed(1)} ${by.toFixed(1)}`,
    `L ${cx.toFixed(1)} ${cy.toFixed(1)}`,
    `A ${r1} ${r1} 0 ${large} 0 ${dx.toFixed(1)} ${dy.toFixed(1)}`,
    "Z",
  ].join(" ");
};

/** The same segment, closed by a half-round at each end instead of a radial
 *  cut. A stroked arc would get this from `stroke-linecap: round`, but the
 *  band stays a filled annulus so it keeps the dial's curvature however few
 *  minutes it covers — so the caps have to be drawn. Each is a semicircle of
 *  the band's own half-thickness, which is exactly what a round-capped stroke
 *  of that width would add: the shape gains no thickness, only its ends stop
 *  being edges. */
export const cappedArcPath = (m1: number, m2: number, r1: number, r2: number) => {
  const [ax, ay] = dialPoint(m1, r2);
  const [bx, by] = dialPoint(m2, r2);
  const [cx, cy] = dialPoint(m2, r1);
  const [dx, dy] = dialPoint(m1, r1);
  const span = (m2 - m1 + DAY) % DAY;
  const large = span > DAY / 2 ? 1 : 0;
  const cap = ((r2 - r1) / 2).toFixed(2);
  return [
    `M ${ax.toFixed(1)} ${ay.toFixed(1)}`,
    `A ${r2} ${r2} 0 ${large} 1 ${bx.toFixed(1)} ${by.toFixed(1)}`,
    `A ${cap} ${cap} 0 0 1 ${cx.toFixed(1)} ${cy.toFixed(1)}`,
    `A ${r1} ${r1} 0 ${large} 0 ${dx.toFixed(1)} ${dy.toFixed(1)}`,
    `A ${cap} ${cap} 0 0 1 ${ax.toFixed(1)} ${ay.toFixed(1)}`,
    "Z",
  ].join(" ");
};


/** A stamp's local wall-clock minute. The dial is a day, not a timeline: an
    event's date is the agenda's business, its time of day is the dial's. */
export const minuteOf = (iso: string) => {
  const date = new Date(iso);
  return date.getHours() * 60 + date.getMinutes();
};

// cluster is being dragged apart — the members left parked behind.
export interface DialMark {
  key: string;
  clusterId: string;
  mode: ScheduleMode;
  at: string;
  overdue: boolean;
  events: ScheduleEvent[];
  radius: number;
  parked?: boolean;
}


export interface DialLabel {
  key: string;
  minute: number;
  ring: "outer" | "inner";
  /** Drawn as two tspans; `text` is the combined form the collision pass
   *  measures, so the two must stay in step. */
  time: string;
  who: string;
  text: string;
  tone: "warn" | "muted" | "cyan";
}

export interface PlacedLabel extends DialLabel {
  x: number;
  y: number;
  /** Where the label wanted to sit, before collision resolution moved it.
   *  The distance between y and y0 is what decides whether it still reads as
   *  this mark's label or gets dropped. */
  y0: number;
  anchor: "start" | "middle" | "end";
  x0: number;
  x1: number;
  /** Which collision group the label belongs to: labels outside the orbits
   *  stack by side, the cramped inner annulus resolves as one. */
  side: "left" | "right";
  stacked: boolean;
  dropped?: boolean;
}

// Place mark labels beside their orbit, clamp them into the stage, then
// resolve vertical collisions within each (ring, side) group so crowded
// arcs stay readable.
//
// One mono character at the dial's `viz` size advances 6.97 user units; the
// constant must follow the label's type size, or the collision pass believes
// labels are narrower than they draw and lets neighbours overlap. Round up:
// over-measuring costs a little spacing, under-measuring costs legibility.
const LABEL_CHAR_W = 7;

/** How far a label may be pushed from its mark before it stops being that
 *  mark's label. Past this it is dropped: the agenda list beside the dial
 *  carries every event in full, and each mark's own button names its time and
 *  connector, so nothing is only available from the dial's text. Hold the
 *  11px floor and drop when crowded, rather than shrink text to fit. */
export const LABEL_MAX_SHIFT = 26;

// The 00/06/12/18 numerals sit at the same radius as the side labels, so a
// mark near a cardinal hour lands right on top of one. They are fixed
// furniture: labels move, numerals never do.
export const NUMERAL_DY = 4;
const NUMERAL_KEEPOUT = [0, 6, 12, 18].map((hour) => {
  const [x, y] = dialPoint(hour * 60, R_NUMERAL);
  return {
    x0: x - 10,
    x1: x + 10,
    // Compare baselines: the numeral is drawn NUMERAL_DY below its anchor.
    y: y + NUMERAL_DY,
    side: hour === 6 ? "right" : hour === 18 ? "left" : "mid",
  };
});

export function placeLabels(labels: DialLabel[]): PlacedLabel[] {
  const placed: PlacedLabel[] = labels.map((label): PlacedLabel => {
    const a = rad(label.minute);
    const s = Math.sin(a);
    const cos = Math.cos(a);
    const outer = label.ring === "outer";
    const side: "left" | "right" = s > 0 ? "right" : "left";
    const middle = Math.abs(s) <= 0.12;
    const vy = outer
      ? cos > 0.6 ? -8 : cos < -0.6 ? 14 : 4
      : cos > 0.6 ? 13 : cos < -0.6 ? -7 : 4;

    // An inner label runs toward the centre, so a mark inside the hub's
    // vertical band would write straight across the hub. Those flip outward
    // and join the outer stack, where the collision pass deconflicts them.
    const crossesHub = !outer && !middle
      && Math.abs(dialPoint(label.minute, 142)[1] + vy - CENTER) < R_HUB + 6;
    const anchor: PlacedLabel["anchor"] = middle
      ? "middle"
      : outer || crossesHub
        ? (side === "right" ? "start" : "end")
        : (side === "right" ? "end" : "start");
    const r = outer
      ? (middle ? 274 : 236)
      : crossesHub ? 178 : (middle ? 136 : 142);

    const dx = anchor === "start" ? 5 : anchor === "end" ? -5 : 0;
    const [px, py] = dialPoint(label.minute, r);
    const width = label.text.length * LABEL_CHAR_W;
    let x = px + dx;
    if (anchor === "end") x = Math.max(x, width + 2);
    else if (anchor === "start") x = Math.min(x, SIZE - width - 2);
    else x = Math.min(Math.max(x, width / 2 + 2), SIZE - width / 2 - 2);
    const x0 = anchor === "end" ? x - width : anchor === "middle" ? x - width / 2 : x;
    return {
      ...label,
      x,
      y: py + vy,
      y0: py + vy,
      anchor,
      side,
      stacked: outer || crossesHub,
      x0,
      x1: x0 + width,
    };
  });

  const groups = new Map<string, typeof placed>();
  for (const label of placed) {
    // The inner band is one cramped annulus, so its labels share a collision
    // group; anything sitting outside the orbits stacks by side instead.
    const key = label.stacked
      ? `outer:${label.anchor === "middle" ? "mid" : label.side}`
      : "inner:all";
    const group = groups.get(key) ?? [];
    group.push(label);
    groups.set(key, group);
  }
  for (const [key, group] of groups) {
    // Clear the fixed hour numerals first, then re-resolve label-on-label.
    if (key.startsWith("outer:")) {
      const side = key.slice("outer:".length);
      for (const label of group) {
        for (const numeral of NUMERAL_KEEPOUT) {
          if (numeral.side !== side) continue;
          const overlapsX = label.x0 < numeral.x1 && numeral.x0 < label.x1;
          if (overlapsX && Math.abs(label.y - numeral.y) < 15) label.y = numeral.y + 15;
        }
      }
    }
    group.sort((a, b) => a.y - b.y);
    for (let i = 1; i < group.length; i++) {
      for (let j = 0; j < i; j++) {
        const overlapsX = group[i].x0 < group[j].x1 && group[j].x0 < group[i].x1;
        if (overlapsX && group[i].y - group[j].y < 12) {
          group[i].y = group[j].y + 13;
        }
      }
    }
  }

  // Drop rather than shrink. Two ways a label stops earning its place: it has
  // been pushed so far to clear its neighbours that it stops reading as its
  // mark's, or the arc is so crowded that even after the pass
  // it still overlaps one. Either way the label goes and the mark keeps its
  // dot — the agenda beside the dial lists every event in full.
  for (const label of placed) {
    if (Math.abs(label.y - label.y0) > LABEL_MAX_SHIFT) label.dropped = true;
  }
  const live = placed.filter((label) => !label.dropped);
  for (let i = 0; i < live.length; i++) {
    for (let j = i + 1; j < live.length; j++) {
      if (live[i].dropped || live[j].dropped) continue;
      const overlapsX = live[i].x0 < live[j].x1 && live[j].x0 < live[i].x1;
      if (overlapsX && Math.abs(live[i].y - live[j].y) < 12) {
        // Keep the one closer to its own mark; the other was the compromise.
        const loser =
          Math.abs(live[i].y - live[i].y0) >= Math.abs(live[j].y - live[j].y0) ? live[i] : live[j];
        loser.dropped = true;
      }
    }
  }
  return placed.filter((label) => !label.dropped);
}
