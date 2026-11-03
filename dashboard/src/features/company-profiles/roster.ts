import type { CompanyProfileSummary } from "../../api";
import { compare } from "../../copy/format";

/* The roster's shape: two sections, the first split into folding groups.
 *
 * 1. The dataset: companies the level atlas researched (`in_dataset`), grouped
 *    by the sectors Settings lists them under, in Settings' order (FAANG
 *    first). A company in two sectors is a row in each, as in Settings. One the
 *    atlas researched outside every sector closes the section under
 *    `NO_SECTOR`.
 * 2. Other companies: everything else the user follows, one folding group.
 *
 * Rows within a group run A to Z by name: this list is for finding a company,
 * and the API's slug order puts "10xteam" before "Airbnb" and "openai" apart
 * from "OpenAI Foundry". Empty groups and sections are dropped, so a narrowed
 * list never draws a heading over nothing.
 */

export const DATASET_SECTION = "dataset";
export const OTHER_SECTION = "other";
/** The dataset group for a company the atlas researched outside every sector. */
export const NO_SECTOR = "no-sector";

export type RosterGroup = {
  /** Unique across the roster: `sector:<slug>`, `no-sector` or `other`. */
  key: string;
  /** The sector slug, or null for the two groups that are not sectors. */
  sector: string | null;
  members: CompanyProfileSummary[];
};

export type RosterSection = {
  key: typeof DATASET_SECTION | typeof OTHER_SECTION;
  /** Distinct companies: a company in two sectors counts once. */
  count: number;
  groups: RosterGroup[];
};

// In the reader's language, case-blind (`copy/format`); the slug breaks a tie
// between two companies of one name, so the order never depends on arrival.
const byName = (a: CompanyProfileSummary, b: CompanyProfileSummary) =>
  compare(a.display_name, b.display_name) || (a.slug < b.slug ? -1 : a.slug > b.slug ? 1 : 0);

export function rosterSections(
  companies: readonly CompanyProfileSummary[],
  sectorOrder: readonly string[],
): RosterSection[] {
  const dataset = companies.filter((c) => c.in_dataset);
  const other = companies.filter((c) => !c.in_dataset);

  // A sector the server lists that this build does not order still gets a
  // group, after the known ones, rather than its companies vanishing.
  const extra = [...new Set(dataset.flatMap((c) => c.sectors))].filter((s) => !sectorOrder.includes(s)).sort();
  const groups: RosterGroup[] = [...sectorOrder, ...extra].map((sector) => ({
    key: `sector:${sector}`,
    sector,
    members: dataset.filter((c) => c.sectors.includes(sector)).sort(byName),
  }));
  groups.push({ key: NO_SECTOR, sector: null, members: dataset.filter((c) => c.sectors.length === 0).sort(byName) });

  const sections: RosterSection[] = [
    { key: DATASET_SECTION, count: dataset.length, groups: groups.filter((g) => g.members.length > 0) },
    { key: OTHER_SECTION, count: other.length, groups: [{ key: OTHER_SECTION, sector: null, members: [...other].sort(byName) }] },
  ];
  return sections.filter((section) => section.count > 0);
}

/** Rows in the order the list draws them, folded groups included. */
export function renderOrder(sections: readonly RosterSection[]): CompanyProfileSummary[] {
  return sections.flatMap((section) => section.groups.flatMap((group) => group.members));
}

/** The first group that holds the company: the one to unfold so it is seen. */
export function groupOf(sections: readonly RosterSection[], slug: string): string | null {
  for (const section of sections) {
    for (const group of section.groups) {
      if (group.members.some((c) => c.slug === slug)) return group.key;
    }
  }
  return null;
}
