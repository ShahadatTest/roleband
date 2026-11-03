/* Formatting implementation. Public API: ../format.ts. */
import {wordsLanguage} from "../runtime";
import {intl, mark, wordsTag} from "./core";



/** A weekday's short name, Monday = 0 ("Mon" in English), in the words' language. */
export const weekday = (mondayFirst: number): string =>
  mark(intl(Intl.DateTimeFormat, wordsTag(), { weekday: "short", timeZone: "UTC" }).format(Date.UTC(2024, 0, 1 + mondayFirst)));



export const time = (value: string | number | Date): string =>
  mark(intl(Intl.DateTimeFormat, wordsTag(), { hour: "numeric", minute: "2-digit" }).format(new Date(value)));



/** "3 hours ago", "in 2 days", "yesterday": the largest whole unit. */
export function relative(seconds: number): string {
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31_536_000], ["month", 2_592_000], ["week", 604_800], ["day", 86_400], ["hour", 3_600], ["minute", 60],
  ];
  const [unit, size] = units.find(([, s]) => Math.abs(seconds) >= s) ?? ["second", 1];
  return mark(intl(Intl.RelativeTimeFormat, wordsLanguage(), { numeric: "auto" }).format(Math.round(seconds / size), unit));
}






/** "A, B and C" or "A, B or C", in the screen's language and the region's punctuation. */
export const list = (items: string[], joiner: "and" | "or" = "and"): string =>
  intl(Intl.ListFormat, wordsTag(), { type: joiner === "and" ? "conjunction" : "disjunction" }).format(items);



/** Sort the way the screen's language sorts. */
export const compare = (a: string, b: string): number => intl(Intl.Collator, wordsLanguage(), { sensitivity: "base" }).compare(a, b);
