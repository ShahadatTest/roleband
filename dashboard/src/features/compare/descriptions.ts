import type { Job } from "../../api";
import { blockKey, descriptionBlocks, descriptionSections } from "../../patterns/jobs/descriptionPassages";

/* Three roles, three descriptions, each under its role. Columns cost
 * max(len) of scroll and read every role against every other; one pair per
 * role against a baseline would cost Σ(len) and never compare roles 2 and 3.
 *
 * NOT aligned section by section: employers rarely share section keys, so a
 * row per section would put one populated cell beside empty ones and grow the
 * grid far past the tallest posting. Each column keeps its posting's own
 * order; what lines up is the sticky head.
 *
 * A passage is SHARED when its key appears anywhere in every column and
 * UNIQUE otherwise, across the whole posting, because "Qualifications" in
 * one posting is "Basic Qualifications" in the next. At two columns this is
 * Review's pairwise rule; at three it says "not every posting says this",
 * the one thing the reader came to see. */

export interface ColumnPassage {
  text: string;
  /** Not in every column. */
  unique: boolean;
}

export interface ColumnSection {
  key: string;
  title: string;
  passages: ColumnPassage[];
  /** How many of this section's passages every column has. */
  shared: number;
}

export interface DescriptionColumn {
  /** The posting's sections, in the posting's order. */
  sections: ColumnSection[];
}

export function columnDescriptions(jobs: Job[]): DescriptionColumn[] {
  const perJob = jobs.map((job) =>
    descriptionSections(job).map((section) => ({
      key: section.key,
      title: section.title,
      blocks: descriptionBlocks(section.content),
    })),
  );
  const keysPerColumn = perJob.map(
    (sections) => new Set(sections.flatMap((section) => section.blocks.map(blockKey))),
  );
  const inEvery = (text: string) => keysPerColumn.every((keys) => keys.has(blockKey(text)));

  return perJob.map((sections) => ({
    sections: sections.map((section) => {
      const passages = section.blocks.map((text) => ({ text, unique: !inEvery(text) }));
      return {
        key: section.key,
        title: section.title,
        passages,
        shared: passages.filter((passage) => !passage.unique).length,
      };
    }),
  }));
}

/** True when no passage appears in every column: marking and filtering would
 *  then mark everything, which is the same as marking nothing. */
export function nothingShared(columns: DescriptionColumn[]): boolean {
  return columns.every((column) => column.sections.every((section) => section.shared === 0));
}

/** True when no column has any description at all. */
export function nothingToRead(columns: DescriptionColumn[]): boolean {
  return columns.every((column) => column.sections.every((section) => section.passages.length === 0));
}
