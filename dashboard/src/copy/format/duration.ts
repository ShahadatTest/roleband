/* Formatting implementation. Public API: ../format.ts. Its own module, apart
   from display.ts, because the app shell loads display.ts: a function living
   there ships in the shell as soon as any lazy screen calls it. */
import {wordsLanguage} from "../runtime";
import {intl, mark} from "./core";

/** A length of time in its two largest units: "2 hr, 5 min", "3 min, 12 sec". */
export function duration(seconds: number): string {
  const parts: [string, number][] = [["hour", Math.floor(seconds / 3600)], ["minute", Math.floor((seconds % 3600) / 60)], ["second", Math.round(seconds % 60)]];
  const shown = parts.filter(([, n]) => n > 0).slice(0, 2);
  if (shown.length === 0) shown.push(["second", 0]);
  const words = shown.map(([unit, n]) => intl(Intl.NumberFormat, wordsLanguage(), { style: "unit", unit, unitDisplay: "short" }).format(n));
  return mark(intl(Intl.ListFormat, wordsLanguage(), { type: "unit", style: "short" }).format(words));
}
