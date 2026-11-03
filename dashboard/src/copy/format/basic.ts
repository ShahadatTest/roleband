/* Formatting used by the shell; extra formats stay route-lazy. */
import {regionTag} from "../runtime";
import {intl,mark,wordsTag,DATE_STYLES} from "./core";


export const number = (n: number, options: Intl.NumberFormatOptions = {}): string =>
  mark(intl(Intl.NumberFormat, regionTag(), options).format(n));


/** A share, 0..1. */
export const percent = (share: number, digits = 0): string =>
  mark(intl(Intl.NumberFormat, regionTag(), { style: "percent", maximumFractionDigits: digits }).format(share));


/** Money in its own currency; `compact` writes "$132K". */
export const money = (amount: number, currency = "USD", { compact = false } = {}): string =>
  mark(
    intl(Intl.NumberFormat, regionTag(), {
      style: "currency",
      currency,
      notation: compact ? "compact" : "standard",
      maximumFractionDigits: compact ? 1 : 0,
    }).format(amount),
  );


export const date = (value: string | number | Date, style: keyof typeof DATE_STYLES = "full"): string =>
  mark(intl(Intl.DateTimeFormat, wordsTag(), DATE_STYLES[style]).format(new Date(value)));


/** A calendar day sent as "YYYY-MM-DD" ("28 Sep" or "Sep 28"). It names a day,
 *  not an instant: built at the reader's own midnight, so no zone shifts it. */
export const calendarDay = (iso: string): string =>
  mark(intl(Intl.DateTimeFormat, wordsTag(), DATE_STYLES.day).format(new Date(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10))));


/** Caller-selected date fields, with the active words and region. */
export const timestamp = (value: string | number | Date, options: Intl.DateTimeFormatOptions = {}): string =>
  mark(intl(Intl.DateTimeFormat, wordsTag(), options).format(new Date(value)));
