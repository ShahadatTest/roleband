/* How a company names a level, read from the level guide
 * (`GET /api/statistics/levels`). The Levels tab and the company page read a
 * cell the same way, so a code never differs between the two. */

import type { LevelGuide, LevelGuideCell, LevelGuideCompany, LevelGuideEntry } from "../../api";

export interface Resolved {
  entry: LevelGuideEntry;
  /** The company grades engineers only, and the track is not engineering:
   *  the engineering name is shown, marked as such. */
  engineering: boolean;
}

/** One cell as the chosen career track reads it. */
export function resolveCell(cell: LevelGuideCell | undefined, track: string): Resolved | null {
  if (!cell) return null;
  if (cell.company_wide) return { entry: cell.company_wide, engineering: false };
  const own = cell.per_track?.[track];
  if (own) return { entry: own, engineering: false };
  const technical = cell.per_track?.technical;
  return technical ? { entry: technical, engineering: true } : null;
}

/** The company's own code for a level on one career track, or none: a flat
 *  ladder's titles state no level, a skipped level has no code, and an
 *  engineering code is not another track's. */
export function levelCode(company: LevelGuideCompany | undefined, level: string, track: string): string | null {
  if (!company || company.flat) return null;
  const resolved = resolveCell(company.levels[level], track);
  return resolved && !resolved.engineering ? resolved.entry.label : null;
}

/** A row of one company's codes with the role words every code repeats cut
 *  off the end: "Senior Software Engineer", "Staff Software Engineer" read
 *  "Senior", "Staff". A code that is only those words ("Software Engineer")
 *  stays whole, since cutting it would leave nothing. Fewer than two codes
 *  share nothing, so they stay whole too. */
export function rungWords(labels: readonly string[]): string[] {
  if (labels.length < 2) return [...labels];
  const words = labels.map((label) => label.trim().split(/\s+/));
  let shared = 0;
  for (;;) {
    const at = shared + 1;
    const tail = words[0][words[0].length - at];
    if (!tail || !words.every((w) => w.length >= at && w[w.length - at].toLowerCase() === tail.toLowerCase())) break;
    shared = at;
  }
  return words.map((w, i) => (shared > 0 && w.length > shared ? w.slice(0, -shared).join(" ") : labels[i]));
}

/** A company's ladder: its own, or the one it shares ("Google DeepMind"
 *  levels as Google). */
export function ladderOf(guide: LevelGuide | null | undefined, slug: string): LevelGuideCompany | undefined {
  if (!guide) return undefined;
  const own = guide.companies.find((company) => company.slug === slug);
  if (own) return own;
  const sameAs = guide.unguided.find((row) => row.slug === slug)?.same_as;
  return sameAs ? guide.companies.find((company) => company.slug === sameAs) : undefined;
}
