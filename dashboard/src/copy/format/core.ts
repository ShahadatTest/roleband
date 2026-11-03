/* Private formatting cache and locale policy. Public API: ../format.ts. */
import {locale, regionTag, wordsLanguage} from "../runtime";


type Ctor<T> = new (tag: string, options: never) => T;

const made = new Map<string, unknown>();

export function intl<T>(C: Ctor<T>, tag: string, options: object = {}): T {
  const key = `${C.name}|${tag}|${JSON.stringify(options)}`;
  let value = made.get(key) as T | undefined;
  if (!value) made.set(key, (value = new C(tag, options as never)));
  return value;
}


export const mark = (text: string): string => (locale() === "en-XA" ? `⟦${text}⟧` : text);


/** The language's words with the region's conventions: Spanish month names in
 *  the region's day-month order; English lists with the serial comma in the
 *  US ("A, B, and C") and without it in Britain. Falls back to the language. */
export function wordsTag(): string {
  try {
    const country = new Intl.Locale(regionTag()).region;
    return country ? new Intl.Locale(wordsLanguage(), { region: country }).toString() : wordsLanguage();
  } catch {
    return wordsLanguage();
  }
}


export const DATE_STYLES = {
  day: { day: "numeric", month: "short" },
  full: { day: "numeric", month: "short", year: "numeric" },
  weekday: { weekday: "short", day: "numeric", month: "short" },
} as const satisfies Record<string, Intl.DateTimeFormatOptions>;
