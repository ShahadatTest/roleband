import { afterEach, describe, expect, it } from "vitest";
import { activate } from "../../../copy/activate";
import { list } from "../../../copy/format";
import { schedulePlanFixture } from "../../../test/fixtures";
import { msg } from "../../../test/msg";
import { DAY, minuteOf } from "./dial";
import {
  MIN_SEGMENT_MINUTES,
  durationText,
  formatDuration,
  offHours,
  planSegments,
  hasUsualStart,
  kindLabel,
  learnedSentence,
  runSubject,
  windowsText,
} from "./plan";

const NOW = "2026-07-28T14:30:00Z";
const run = (at: string, overrides = {}) => ({
  at, kind: "quick" as const, seconds: 600, estimated: false, on_wake: false, running: false, ready_by: false, ...overrides,
});

describe("planSegments", () => {
  it("keeps the runs of one turn of the dial and a run already in progress", () => {
    const plan = schedulePlanFixture({
      upcoming: [
        run("2026-07-28T14:00:00Z", { running: true, kind: "full", seconds: 2460 }),
        run("2026-07-28T20:30:00Z"),
        run("2026-07-29T14:29:00Z"),
        run("2026-07-29T14:31:00Z"), // a turn and a minute away: drawn on top of now
      ],
    });
    const segments = planSegments(plan, NOW);
    expect(segments.map((segment) => segment.at)).toEqual([
      "2026-07-28T14:00:00Z", "2026-07-28T20:30:00Z", "2026-07-29T14:29:00Z",
    ]);
    expect(segments[0]).toMatchObject({ kind: "full", running: true });
    expect((segments[0].endMinute - segments[0].startMinute + DAY) % DAY).toBe(41);
  });

  it("draws a very short run long enough to read as a stretch, wrapping midnight", () => {
    const [segment] = planSegments(schedulePlanFixture({
      upcoming: [run("2026-07-28T23:57:00Z", { seconds: 30 })],
    }), NOW);
    const start = minuteOf("2026-07-28T23:57:00Z");
    expect(segment.startMinute).toBe(start);
    expect(segment.endMinute).toBe((start + MIN_SEGMENT_MINUTES) % DAY);
  });
});

describe("offHours", () => {
  it("is the complement of the usual hours, wrapping midnight", () => {
    expect(offHours([{ start_minute: 540, end_minute: 1080 }])).toEqual([[1080, 540]]);
    expect(offHours([
      { start_minute: 1200, end_minute: 1440 },
      { start_minute: 0, end_minute: 120 },
    ])).toEqual([[120, 1200]]);
    expect(offHours([
      { start_minute: 480, end_minute: 720 },
      { start_minute: 780, end_minute: 1080 },
    ])).toEqual([[720, 780], [1080, 480]]);
  });

  it("is the whole day when the computer is never on, and nothing while learning", () => {
    expect(offHours([])).toEqual([[0, DAY]]);
    expect(offHours(null)).toBeNull();
    expect(offHours([{ start_minute: 0, end_minute: 1440 }])).toEqual([]);
  });
});

describe("words", () => {
  it("rounds run lengths to minutes and marks a guess", () => {
    expect(formatDuration(2460)).toBe("41 min");
    expect(formatDuration(3900)).toBe("1 h 5 min");
    expect(formatDuration(7200)).toBe("2 h");
    expect(formatDuration(5)).toBe("1 min");
    expect(durationText({ seconds: 2700, estimated: true })).toBe("about 45 min");
  });

  it("says the usual hours plainly", () => {
    expect(windowsText([{ start_minute: 510, end_minute: 1080 }])).toBe("08:30 to 18:00");
    expect(windowsText([{ start_minute: 0, end_minute: 1440 }])).toBe("All day");
    expect(windowsText([])).toBe("Usually off");
  });

  it("says what it learned in one sentence, weekends apart only when they differ", () => {
    const office = schedulePlanFixture();
    expect(learnedSentence(office)).toBe(
      "Learned from the last 14 days: your computer is on 09:00 to 18:00 on weekdays and usually off at weekends.",
    );
    const allDay = [{ start_minute: 0, end_minute: 1440 }];
    const always = schedulePlanFixture({ usual: { ...office.usual, weekdays: allDay, weekends: allDay } });
    expect(learnedSentence(always)).toBe("Learned from the last 14 days: your computer is on all day every day.");
    const learning = schedulePlanFixture({
      usual: { ...office.usual, learning: true, observed_days: 3, weekdays: null, weekends: null },
    });
    expect(learnedSentence(learning)).toBe("Still learning when your computer is on: 3 of 5 days seen.");
  });

  it("says the learned hours for each part of the week it saw", () => {
    const office = schedulePlanFixture();
    const usual = (weekdays: typeof office.usual.weekdays, weekends: typeof office.usual.weekends) =>
      learnedSentence(schedulePlanFixture({ usual: { ...office.usual, weekdays, weekends } }));
    const hours = [{ start_minute: 9 * 60, end_minute: 18 * 60 }];
    expect(usual(hours, null)).toBe(msg("settings-plan-learned", { days: 14, usual: "set", times: windowsText(hours) }));
    expect(usual(null, [])).toBe(msg("settings-plan-learned", { days: 14, usual: "off", times: windowsText([]) }));
    expect(usual(null, null)).toBe(msg("settings-plan-learned-unseen", { days: 14 }));
    expect(usual([], [])).toBe(msg("settings-plan-learned-every-day", { days: 14, usual: "off", times: windowsText([]) }));
    expect(usual(hours, [])).toBe(msg("settings-plan-learned-weekdays-weekends", {
      days: 14, weekdays: "set", weekdayTimes: windowsText(hours), weekends: "off", weekendTimes: windowsText([]),
    }));
    // Both on at set hours, but not the same hours: said apart.
    const late = [{ start_minute: 10 * 60, end_minute: 15 * 60 }];
    expect(usual(hours, late)).toBe(msg("settings-plan-learned-weekdays-weekends", {
      days: 14, weekdays: "set", weekdayTimes: windowsText(hours), weekends: "set", weekendTimes: windowsText(late),
    }));
    expect(usual(hours, hours)).toBe(msg("settings-plan-learned-every-day", { days: 14, usual: "set", times: windowsText(hours) }));
  });

  it("names a run by its kind and counts the companies that kind reads", () => {
    const plan = schedulePlanFixture();
    expect(kindLabel("full")).toBe(msg("settings-plan-scan-kind", { kind: "full" }));
    expect(kindLabel("quick")).toBe(msg("settings-plan-scan-kind", { kind: "quick" }));
    expect(kindLabel("full")).not.toBe(kindLabel("quick"));
    expect(runSubject({ kind: "full" }, plan)).toBe(msg("settings-plan-companies", { kind: "full", companies: 1112 }));
    expect(runSubject({ kind: "quick" }, plan)).toBe(msg("settings-plan-companies", { kind: "quick", companies: 944 }));
  });

  it("knows a usual start only when one was learned and does not begin at midnight", () => {
    const office = schedulePlanFixture();
    expect(hasUsualStart(office)).toBe(true);
    const allDay = [{ start_minute: 0, end_minute: 1440 }];
    expect(hasUsualStart(schedulePlanFixture({ usual: { ...office.usual, weekdays: allDay, weekends: allDay } })))
      .toBe(false);
    expect(hasUsualStart(schedulePlanFixture({ usual: { ...office.usual, learning: true } }))).toBe(false);
  });
});

/* The words are the reader's: a guessed length and several usual hours carry
   no English joiner or qualifier into another language. */
describe("words in another language", () => {
  afterEach(() => activate("en"));

  it("says a guessed length in the reader's words", async () => {
    await activate("es");
    const guess = durationText({ seconds: 2460, estimated: true });
    expect(guess).toBe(msg("settings-plan-about", { duration: msg("settings-plan-min", { minutes: 41 }) }));
    expect(guess).not.toMatch(/about/);
    expect(durationText({ seconds: 2460, estimated: false })).toBe(msg("settings-plan-min", { minutes: 41 }));
  });

  it("joins several usual hours as the reader's language lists them", async () => {
    await activate("es");
    const hours = [{ start_minute: 510, end_minute: 720 }, { start_minute: 780, end_minute: 1080 }];
    expect(windowsText(hours)).toBe(list([
      msg("settings-plan-to", { start: "08:30", end: "12:00" }),
      msg("settings-plan-to", { start: "13:00", end: "18:00" }),
    ]));
    expect(windowsText(hours)).not.toContain(", ");
  });
});
