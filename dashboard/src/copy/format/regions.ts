/* Formatting implementation. Public API: ../format.ts. */
import {wordsLanguage} from "../runtime";
import {intl, mark, DATE_STYLES} from "./core";



/** A country's name in the screen's language, from its ISO code. */
export const country = (alpha2: string): string =>
  intl(Intl.DisplayNames, wordsLanguage(), { type: "region" }).of(alpha2.toUpperCase()) ?? alpha2;




/** How a region writes a number and a date, for the region picker: shown in
 *  that region's own conventions, whatever the active one is. */
export function regionSample(tag: string): { number: string; date: string } {
  const country = new Intl.Locale(tag).region;
  const words = country ? new Intl.Locale(wordsLanguage(), { region: country }).toString() : wordsLanguage();
  return {
    number: mark(intl(Intl.NumberFormat, tag).format(1234.5)),
    date: mark(intl(Intl.DateTimeFormat, words, DATE_STYLES.day).format(new Date(SAMPLE_DATE))),
  };
}


const SAMPLE_DATE = "2026-04-12T12:00:00Z";



/** A region tag's ISO country, for the picker without constructing Intl in UI. */
export const regionCountry = (tag: string): string => new Intl.Locale(tag).region ?? tag;



/** Browser negotiation retains script distinctions (zh-Hans versus zh-Hant). */
export function matchLanguage(tags: readonly string[], codes: readonly string[]): string {
  for (const raw of tags) {
    try {
      const tag = new Intl.Locale(raw);
      if (codes.includes(tag.baseName)) return tag.baseName;
      const match = codes.find(code => {
        const candidate = new Intl.Locale(code);
        return candidate.language === tag.language && candidate.maximize().script === tag.maximize().script;
      });
      if (match) return match;
    } catch { /* malformed browser preference: try the next */ }
  }
  return "en";
}
