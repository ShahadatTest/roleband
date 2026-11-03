import type { PluginRunOutcome, PluginRunView, PluginSlot, PluginView } from "../../api";
import { date, duration, list, relative } from "../../copy/format";
import { sharedResultsOfCompany } from "../../copy/gen/shared";
import {
  settingsPluginSettingsNever,
  settingsPluginSettingsRun,
  settingsPluginSettingsRunProgress,
  settingsPluginsSectionAnswers,
  settingsPluginsSectionBrings,
  settingsPluginsSectionNextUpdate,
  settingsPluginsSectionPaused,
  settingsPluginsSectionRead,
  settingsPluginsSectionSlot,
  settingsPluginsSectionWaiting,
} from "../../copy/gen/settings";

/* The words both plugin screens build a plugin's state from (Settings >
   Plugins and one plugin's settings). Functions, never module-level text: copy
   resolves at render. */

/** Every slot the wire can name, each once: `Record` makes a new `PluginSlot`
 *  a type error here until it has a word (`pluginWords.test.ts` holds each
 *  value to its own catalog branch). */
export const PLUGIN_SLOTS = Object.keys({
  "pay.levels": true,
  "pay.observations": true,
  "company.facts": true,
  "company.benefits": true,
} satisfies Record<PluginSlot, true>) as PluginSlot[];

/** The catalog keys a slot by underscores; the wire by dots. */
export const slotWord = (slot: PluginSlot) => settingsPluginsSectionSlot({ slot: slot.replaceAll(".", "_") });
export const slotList = (slots: readonly PluginSlot[]) => list(slots.map(slotWord));
export const ago = (iso: string) => relative((new Date(iso).getTime() - Date.now()) / 1000);

/** The one state a row ends on: what the person most needs to know first. */
export type RowState = "needs_approval" | "updating" | "paused" | "enabled" | "disabled" | "removed";

/** `starting`: Start was pressed and the update has not shown up yet. */
export function rowState(plugin: PluginView, starting = false): RowState {
  if (plugin.state === "removed") return "removed";
  if (plugin.state === "needs_approval") return "needs_approval";
  if (plugin.running || (starting && plugin.state === "enabled")) return "updating";
  if (plugin.state === "enabled" && plugin.paused) return "paused";
  return plugin.state;
}

/** A plugin that may run now: approved as it is and switched on. A plugin
 *  whose approval lapsed keeps its switch on (`enabled`) but is not runnable. */
export const runnable = (plugin: PluginView) => plugin.state === "enabled";

/** What it answers now: the kinds its own updates answer. */
const answeringSlots = (plugin: PluginView) => [...plugin.active_slots].sort();

/** What it brings: what it answers now, else that it waits, else what it would bring. */
export function bringsLine(plugin: PluginView): string {
  const answering = answeringSlots(plugin);
  if (answering.length > 0) return settingsPluginsSectionAnswers({ slots: slotList(answering) });
  if (plugin.state === "enabled") return settingsPluginsSectionWaiting();
  return settingsPluginsSectionBrings({ slots: slotList(plugin.slots) });
}

/** Companies one slot answers for from the plugin's own updates: each read
 *  whole at least once. Zero while it cannot answer: `coverage`
 *  counts what it published, and a plugin that is off or waits for approval
 *  answers with none of it. */
const freshFor = (plugin: PluginView, slot: PluginSlot) =>
  runnable(plugin) && plugin.active_slots.includes(slot) ? plugin.coverage[slot] ?? 0 : 0;

/** Companies one slot has read whole, whether or not it answers now: what a
 *  plugin that is off or waits for approval would answer for once it is on. */
export const readFor = (plugin: PluginView, slot: PluginSlot) => plugin.coverage[slot] ?? 0;

/** What a read count is out of: the followed companies a plugin is given,
 *  never fewer than it read (a company read and unfollowed since still counts). */
export const outOf = (plugin: PluginView, read: number) => Math.max(plugin.companies, read);

/** What Remove data deletes for it: the kinds of data it added
 *  (`removable_slots`), else only what was worked out from it, its own kinds
 *  staying as history (the observations it read). */
export function removeWords(plugin: PluginView): { what: "rows" | "history"; kinds: string } {
  return plugin.removable_slots.length > 0
    ? { what: "rows", kinds: slotList(plugin.removable_slots) }
    : { what: "history", kinds: slotList(plugin.slots) };
}

/** Turning it on would leave something empty: a kind it brings has read fewer
 *  than all followed companies, so they show none of it, and none of ours.
 * The switch asks first then. */
export const leavesGaps = (plugin: PluginView) =>
  plugin.companies > 0 && plugin.slots.some((slot) => readFor(plugin, slot) < plugin.companies);

/** A time left the way a person says it: whole hours from three hours, five
 *  minutes from ten, else whole minutes; never under a minute. */
export function aboutTime(seconds: number): string {
  const step = seconds >= 3 * 3600 ? 3600 : seconds >= 600 ? 300 : 60;
  return duration(Math.max(Math.round(seconds / step) * step, 60));
}

/** One company's time: whole minutes from a minute, else five seconds. */
export function paceTime(seconds: number): string {
  const step = seconds >= 60 ? 60 : 5;
  return duration(Math.max(Math.round(seconds / step) * step, 5));
}

/** How long the rest takes, at the pace its own updates kept; null
 *  while no pass is under way or none has measured a pace. */
export function leftToRead(plugin: PluginView): { duration: string; pace: string } | null {
  const left = plugin.reading_left;
  if (!left || left.units <= 0) return null;
  return { duration: aboutTime(left.seconds), pace: paceTime(left.seconds_per_unit) };
}

/** The list row's one coverage figure: the most companies any one slot is
 *  fresh for. Never the sum, which counts a company once per kind of data (pay
 *  and benefits for 96 companies is not 192); the largest slot's count is a
 *  number of companies that is true as said, and the plugin's settings give
 *  each kind its own. */
export const freshest = (plugin: PluginView) => Math.max(0, ...plugin.slots.map((slot) => freshFor(plugin, slot)));

/** How a run ended, as the catalog keys it: a clean run that left its pass
 *  unfinished reads as one in progress, never as a finished update. */
export const runOutcome = (run: PluginRunView): PluginRunOutcome | "continues" =>
  run.outcome === "clean" && run.continues ? "continues" : run.outcome;

const runWhen = (run: PluginRunView) => ago(run.ended_at ?? run.started_at);

/** How many companies a run read, "4 of 1,180 companies"; null when it never
 *  said how many it had to read. */
export function companiesRead(run: PluginRunView): string | null {
  if (!run.progress_total) return null;
  return sharedResultsOfCompany({ n: run.progress_done ?? 0, t: run.progress_total, total: run.progress_total });
}

/** How far a run got, when that is news: every run but a finished one (a
 *  clean run read what it set out to), and only when it counted companies.
 *  A run the plugin summarized itself (`ownSummary`) says it in those words. */
const progressOf = (run: PluginRunView): string | null =>
  (runOutcome(run) === "clean" || run.summary ? null : companiesRead(run));

/** What a run did in the plugin's own words (`ctx.summary`), said after how
 *  it ended; null while Start waits for its run to show up, or when the
 *  plugin said nothing. */
export const ownSummary = (run: PluginRunView | null, starting = false): string | null =>
  (starting ? null : run?.summary ?? null);

/** The last update as the first fact of the row's sub-line: the same words
 *  the plugin's own page says it in (`runLine`), so the list and the page
 *  never disagree on casing or wording. */
export function lastUpdate(plugin: PluginView, starting = false): string {
  return runLine(plugin.last_run, starting && !plugin.running);
}

/** One update standing alone (the Last update value): its own sentence, with
 *  how far it got. `starting`: Start was pressed and its run has not shown up yet. */
export function runLine(run: PluginRunView | null, starting = false): string {
  if (starting) return settingsPluginSettingsRun({ outcome: "running", when: "" });
  if (!run) return settingsPluginSettingsNever();
  const read = progressOf(run);
  if (read) return settingsPluginSettingsRunProgress({ outcome: runOutcome(run), when: runWhen(run), read });
  return settingsPluginSettingsRun({ outcome: runOutcome(run), when: runWhen(run) });
}

/** The row's sub-line after what it brings: the last update, what it answers
 *  for, then what comes next. */
export function timingLine(plugin: PluginView, starting = false): string {
  return [lastUpdate(plugin, starting), ...timingRest(plugin, starting)].join(FACTS_JOIN);
}

/** Between the facts of a row's sub-line. */
export const FACTS_JOIN = " · ";

/** The sub-line's facts after the last update: what it answers for, then what comes next. */
export function timingRest(plugin: PluginView, starting = false): string[] {
  const parts: string[] = [];
  const fresh = freshest(plugin);
  if (fresh > 0) parts.push(settingsPluginsSectionRead({ read: fresh, companies: outOf(plugin, fresh) }));
  if (runnable(plugin) && plugin.paused) parts.push(settingsPluginsSectionPaused());
  else if (plugin.next_update_at && !plugin.running && !starting && !plugin.last_run?.continues) {
    parts.push(settingsPluginsSectionNextUpdate({ when: date(plugin.next_update_at, "day") }));
  }
  return parts;
}
