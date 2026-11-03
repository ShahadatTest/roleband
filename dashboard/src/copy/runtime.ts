/* The locale runtime (docs/copy.md, sections 2 and 6).
 *
 * English messages are compiled inline (`copy/gen/*.ts`) and each is wrapped by
 * `m(id, en)`: the active locale's table wins, English is the fallback, per
 * message. Every other locale is ONE lazy table, loaded by `activate`. A switch
 * sets the table and notifies; `CopyBoundary` remounts the UI so every render,
 * model and label helper re-reads it. Nothing here keeps text: it keeps the
 * table and the region, and callers resolve text at render. */

/** Selector parameters are data, never rich element slots. Type-only contract. */
export type Message<A, S extends keyof A> = ((a: A) => string) & { readonly __copySelectors?: S };

export type Table = (((a: any) => string) | undefined)[];

export interface Locale {
  code: string;
  name: string;
  dir: "ltr" | "rtl";
  status: "complete" | "beta" | "pseudo";
  fallback: string[];
}

/** What the reader chose: a language, and a region or null for the system's. */
export interface Choice {
  language: string;
  region: string | null;
}

export const STORAGE_KEY = "roleband.locale";
/** A per-device flag that lists the pseudo locales in Settings, for checking copy. */
const COPY_CHECK_KEY = "roleband.copy-check";

const systemRegion = (): string => (typeof navigator !== "undefined" && navigator.language) || "en-US";

let table: Table | null = null;
let language = "en";
/** The language the active table is written in (English for pseudo locales). */
let tableLanguage = "en";
let requested: Choice = { language: "en", region: null };
let revision = 0;
export const intentRevision = (): number => revision;
export const beginIntent = (): number => ++revision;

/** Intl validates and canonicalizes tags before they can reach any formatter. */
export function canonicalTag(value: string): string {
  if (value.length > 35) throw new RangeError("language tag too long");
  return Intl.getCanonicalLocales(value)[0] ?? (() => { throw new RangeError("empty language tag"); })();
}
let region = systemRegion();
const listeners = new Set<() => void>();
const intl = new Map<string, Intl.PluralRules | Intl.NumberFormat>();

function cached<T extends Intl.PluralRules | Intl.NumberFormat>(kind: string, tag: string, make: (t: string) => T): T {
  const key = `${kind}:${tag}`;
  let value = intl.get(key) as T | undefined;
  if (!value) intl.set(key, (value = make(tag)));
  return value;
}

/** Plural rules belong to the language a message is WRITTEN in; number formats
 *  to the reader's region. An English message shown as the fallback inside a
 *  Spanish screen still says "1000000 roles" (Spanish rules would pick `many`),
 *  while its digits follow the region (compiler.test.ts holds this). */
const pluralIn = (tag: string, n: number): Intl.LDMLPluralRule =>
  cached("p", tag, (t) => new Intl.PluralRules(t)).select(n);

/** A placeable: numbers by the active region, everything else as given. */
export const F = (v: unknown): string =>
  typeof v === "number" ? cached("n", region, (r) => new Intl.NumberFormat(r)).format(v) : String(v ?? "");

/** A select variant matches like Fluent's: equal strings, equal numbers, or a
 *  number whose plural category is the key. */
const select = (tag: string, v: unknown, key: string | number): boolean =>
  typeof key === "number" ? v === key : v === key || (typeof v === "number" && pluralIn(tag, v) === key);
/** In a locale table: the table's own language. */
export const S = (v: unknown, key: string | number): boolean => select(tableLanguage, v, key);
/** A compiled fallback retains the grammar of the language it was written in.
 *  scripts/gen-copy.mjs emits it only into a table that falls back across
 *  languages, so no checked-in source imports it.
 *  @public */
export const SL = (tag: string, v: unknown, key: string | number): boolean => select(tag, v, key);
/** In the compiled English messages, active or fallback alike. */
export const SE = (v: unknown, key: string | number): boolean => select("en", v, key);

/** Wrap one compiled English message: the active table wins, English is the
 *  fallback. A message with no arguments arrives as its text. */
export function m(id: number, en: string): () => string;
export function m<Fn extends (...args: never[]) => string>(id: number, en: Fn): Fn;
export function m(id: number, en: string | ((...args: unknown[]) => string)) {
  return (...args: unknown[]) => {
    const own = table && table[id];
    return own ? own(...(args as [never])) : typeof en === "string" ? en : en(...args);
  };
}

export const locale = (): string => language;
/** The region numbers and dates are written for: the chosen one, else the system's. */
export const regionTag = (): string => region;
/** The language words are written in: the active table's (English for pseudo locales). */
export const wordsLanguage = (): string => tableLanguage;
export const choice = (): Choice => requested;
/** One string that changes whenever what a render says or how it formats does:
 *  the boundary's key. A region-only change must remount too. */
export const activeKey = (): string => `${language}|${region}`;
export const subscribe = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

/** Is the copy-check flag on for this device (pseudo locales listed)? */
export function copyCheckOn(): boolean {
  try {
    return localStorage.getItem(COPY_CHECK_KEY) === "1";
  } catch {
    return false;
  }
}

/** The choice this browser last made, read before the first render. */
export function storedChoice(): Choice | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object" || typeof (value as Choice).language !== "string") return null;
    const stored = value as Choice;
    return { language: stored.language === "keys" ? "keys" : canonicalTag(stored.language), region: typeof stored.region === "string" ? canonicalTag(stored.region) : null };
  } catch {
    return null;
  }
}

/** Called only by `activate`, which owns loading and persistence. */
export function setActive(next: { table: Table | null; language: string; tableLanguage: string; region: string | null }): void {
  table = next.table;
  language = next.language;
  tableLanguage = next.tableLanguage;
  requested = { language: next.language, region: next.region };
  region = next.region ?? systemRegion();
  intl.clear();
  listeners.forEach((listener) => listener());
}
