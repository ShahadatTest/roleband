/* The Levels tab's rules, pure so each is unit-tested apart from the screen.
 *
 * A search matches whole spellings, never a substring of a label: "L1" must
 * not find "L8–L10", and Amazon's "L8–L10" holds no L9 because the server
 * sends the rungs behind a label, not a range to expand. */

import type { LevelGuideCompany } from "../../api";
import { BAND_ORDER } from "../../labels";
import { resolveCell, type Resolved } from "../../patterns/levels/levelGuide";

/** Levels lowest first, the order the Profile rail draws them. */
export const LEVELS: readonly string[] = [...BAND_ORDER].reverse();

/** A spelling as a search compares it: case and spacing folded, every dash
 *  read as the en dash a range label prints ("63-64" finds "63–64"). */
export function spellingKey(text: string): string {
  return text.normalize("NFKC").toLowerCase().replace(/[-‐‑‒–—−]/g, "–").replace(/\s+/g, " ").trim();
}

/** The company has a level for this track nowhere: every name it shows is an
 *  engineering one. */
export function engineeringOnly(company: LevelGuideCompany, track: string): boolean {
  const resolved = LEVELS.map((level) => resolveCell(company.levels[level], track)).filter((r): r is Resolved => r !== null);
  return resolved.length > 0 && resolved.every((r) => r.engineering);
}

export interface Hit {
  slug: string;
  level: string;
  /** The spelling that matched, which the label may hide ("Distinguished
   *  Engineer" inside "IC7+"). */
  spelling: string;
}

/** Every cell one of whose spellings is the query. */
export function levelHits(companies: readonly LevelGuideCompany[], track: string, query: string): Hit[] {
  const key = spellingKey(query);
  if (!key) return [];
  const hits: Hit[] = [];
  for (const company of companies) {
    for (const level of LEVELS) {
      const resolved = resolveCell(company.levels[level], track);
      if (!resolved) continue;
      const spelling = [resolved.entry.label, ...resolved.entry.spellings].find((s) => spellingKey(s) === key);
      if (spelling) hits.push({ slug: company.slug, level, spelling });
    }
  }
  return hits;
}

/** A spelling worth showing beside the label: the label does not already
 *  show it. */
export function hiddenSpelling(label: string, spelling: string): string | null {
  return spellingKey(label).split("–").map((part) => part.replace(/\+$/, "")).includes(spellingKey(spelling))
    ? null
    : spelling;
}

/** The level a company with no rung at `level` reads it as: the nearest
 *  below, else the nearest above (`ladder.rung_for_band`, which pay uses). */
export function closestLevel(company: LevelGuideCompany, level: string, track: string): string | null {
  const at = LEVELS.indexOf(level);
  for (let i = at - 1; i >= 0; i -= 1) {
    const resolved = resolveCell(company.levels[LEVELS[i]], track);
    if (resolved) return resolved.entry.label;
  }
  for (let i = at + 1; i < LEVELS.length; i += 1) {
    const resolved = resolveCell(company.levels[LEVELS[i]], track);
    if (resolved) return resolved.entry.label;
  }
  return null;
}

/** Where a translation starts: `slug:level`, as the address keeps it. */
export interface From {
  slug: string;
  level: string;
}

export function parseFrom(raw: string | null, companies: readonly LevelGuideCompany[]): From | null {
  if (!raw) return null;
  const [slug, level] = raw.split(":");
  const company = companies.find((c) => c.slug === slug);
  return company && LEVELS.includes(level) && company.levels[level] ? { slug, level } : null;
}

/** The career track the tab opens on: hands-on when the person's Profile
 *  includes it (a fresh install has all four), else their first. */
export function defaultTrack(tracks: readonly string[] | null | undefined, order: readonly string[]): string {
  if (!tracks || tracks.length === 0 || tracks.includes("technical")) return "technical";
  return order.find((track) => tracks.includes(track)) ?? "technical";
}
