import { list } from "../../../copy/format";
import type { SchedulePlan, ScheduleUpcomingRun, ScheduleWindow } from "../../../api";
import { DAY, minuteOf } from "./dial";
import { formatMinute } from "./schedule";
import {
  settingsPlanAbout,
  settingsPlanAllDay,
  settingsPlanCompanies,
  settingsPlanHours,
  settingsPlanHoursMinutes,
  settingsPlanLearned,
  settingsPlanLearnedEveryDay,
  settingsPlanLearnedUnseen,
  settingsPlanLearnedWeekdaysWeekends,
  settingsPlanMin,
  settingsPlanScanKind,
  settingsPlanStillLearningWhenYourComputer,
  settingsPlanTo,
  settingsPlanUsuallyOff,
} from "../../../copy/gen/settings";

/* The schedule plan on the dial, with no React in it.

   The plan reads every company on one clock: a full scan when the computer
   comes on, a quick scan each repeat while it is on. On the dial a full scan
   rides the outer orbit and a quick scan the inner one, as reconciliation and
   discovery do under the timers, and each is drawn as long as it takes. The usual
   on-hours replace the fixed night tint once they are learned. */

export type PlanKind = ScheduleUpcomingRun["kind"];

export interface PlanSegment {
  key: string;
  kind: PlanKind;
  at: string;
  startMinute: number;
  endMinute: number;
  seconds: number;
  estimated: boolean;
  onWake: boolean;
  running: boolean;
  /** While dragged: the time it would land on (the grid), which its label
   *  says while the arc itself follows the pointer. */
  landing?: number;
}

/** Arcs shorter than this would read as a dot, not a stretch of time. */
export const MIN_SEGMENT_MINUTES = 8;

/** The plan's runs that start within one turn of the dial from `now`. A
    running one is kept although it began before now: it is the run in hand.
    A run is keyed by its kind and its place among runs of that kind, never by
    its place in the list: a save that moves the full scan ahead of the quick
    ones reorders the list, and an inspector open on the full scan must stay
    on it. */
export function planSegments(plan: SchedulePlan, now: string): PlanSegment[] {
  const nowMs = Date.parse(now);
  const seen = new Map<string, number>();
  return plan.upcoming
    .filter((run) => run.running || Date.parse(run.at) - nowMs < DAY * 60_000)
    .map((run) => {
      const ordinal = seen.get(run.kind) ?? 0;
      seen.set(run.kind, ordinal + 1);
      const startMinute = minuteOf(run.at);
      const minutes = Math.max(MIN_SEGMENT_MINUTES, Math.round(run.seconds / 60));
      return {
        key: `${run.kind}-${ordinal}`,
        kind: run.kind,
        at: run.at,
        startMinute,
        endMinute: (startMinute + minutes) % DAY,
        seconds: run.seconds,
        estimated: run.estimated,
        onWake: run.on_wake,
        running: run.running,
      };
    });
}

/** The minutes of the day outside the usual on-hours, as (start, end) pairs
    for the off-hours tint. Null while the hours are still being learned. */
export function offHours(windows: ScheduleWindow[] | null | undefined): Array<[number, number]> | null {
  if (!windows) return null;
  if (windows.length === 0) return [[0, DAY]];
  const sorted = [...windows].sort((a, b) => a.start_minute - b.start_minute);
  const gaps: Array<[number, number]> = [];
  for (let index = 0; index < sorted.length; index++) {
    const end = sorted[index].end_minute;
    const next = sorted[(index + 1) % sorted.length].start_minute + (index + 1 === sorted.length ? DAY : 0);
    if (next > end) gaps.push([end % DAY, next % DAY]);
  }
  return gaps;
}

export const kindLabel = (kind: PlanKind) => settingsPlanScanKind({ kind });

/** "41 min", "1 h 5 min": how long a run takes, rounded to the minute. */
export function formatDuration(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return settingsPlanMin({ minutes });
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? settingsPlanHoursMinutes({ hours, minutes: rest }) : settingsPlanHours({ hours });
}

/** "about 41 min" until a run of the kind has been measured. */
export const durationText = (run: { seconds: number; estimated: boolean }) =>
  run.estimated ? settingsPlanAbout({ duration: formatDuration(run.seconds) }) : formatDuration(run.seconds);

/** Which of the three things the usual hours say: on all day, usually off, or
    on at the hours listed. */
const usualOf = (windows: ScheduleWindow[]): "all" | "off" | "set" => {
  if (windows.length === 0) return "off";
  if (windows.length === 1 && windows[0].start_minute === 0 && windows[0].end_minute === DAY) return "all";
  return "set";
};

/** The usual on-hours in words: "09:00 to 18:00", several as one list. */
export function windowsText(windows: ScheduleWindow[]): string {
  const usual = usualOf(windows);
  if (usual === "off") return settingsPlanUsuallyOff();
  if (usual === "all") return settingsPlanAllDay();
  return list(windows
    .map((window) => settingsPlanTo({ start: formatMinute(window.start_minute), end: formatMinute(window.end_minute % DAY) })));
}

/** The learned hours as one plain sentence, for the note under the plan's
    settings: a fact the app learned, never a setting, so it is said once and
    quietly rather than given a row of its own. */
export function learnedSentence(plan: SchedulePlan): string {
  const usual = plan.usual;
  if (usual.learning) {
    return settingsPlanStillLearningWhenYourComputer({ observed_days: usual.observed_days, needed_days: usual.needed_days });
  }
  const days = usual.observed_days;
  const { weekdays, weekends } = usual;
  if (weekdays && weekends) {
    const weekdayTimes = windowsText(weekdays);
    const weekendTimes = windowsText(weekends);
    // Weekends are said apart only when they read differently from weekdays.
    if (usualOf(weekdays) === usualOf(weekends) && weekdayTimes === weekendTimes) {
      return settingsPlanLearnedEveryDay({ days, usual: usualOf(weekdays), times: weekdayTimes });
    }
    return settingsPlanLearnedWeekdaysWeekends({
      days,
      weekdays: usualOf(weekdays),
      weekdayTimes,
      weekends: usualOf(weekends),
      weekendTimes,
    });
  }
  const seen = weekdays ?? weekends;
  if (!seen) return settingsPlanLearnedUnseen({ days });
  return settingsPlanLearned({ days, usual: usualOf(seen), times: windowsText(seen) });
}

/** Whether the plan learned a usual start it can fall back to. */
export const hasUsualStart = (plan: SchedulePlan) => !plan.usual.learning
  && [plan.usual.weekdays, plan.usual.weekends].some((windows) => windows?.length && windows[0].start_minute > 0);

/** The hub's line under the time: what runs and over how many companies. */
export function runSubject(run: { kind: PlanKind }, plan: SchedulePlan): string {
  const companies = run.kind === "full" ? plan.roster : plan.quick_roster;
  return settingsPlanCompanies({ kind: run.kind, companies });
}
