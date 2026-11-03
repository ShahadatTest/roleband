import type { Job, JobDescriptionSection } from "../../api";
import {
  jobsDescriptionPassagesDescription,
} from "../../copy/gen/jobs";

/* What a posting's description IS to a comparison: sections, each a list of
 * passages, and one definition of "the same passage". Review's pairwise diff
 * and Compare's aligned columns both read through this, so a
 * change to what counts as sameness reaches both screens at once. */

/** A posting's sections; a bare description is one section. */
export function descriptionSections(job: Job): JobDescriptionSection[] {
  if (job.description_sections && job.description_sections.length > 0) return job.description_sections;
  if (job.description_text?.trim()) return [{ key: "job_description", title: jobsDescriptionPassagesDescription(), content: job.description_text }];
  return [];
}

/** A section's passages: one per non-empty line. */
export function descriptionBlocks(text: string | undefined): string[] {
  return (text ?? "")
    .split(/\n+/)
    .map((block) => block.trim())
    .filter(Boolean);
}

/** What makes two passages "the same": case, bullets and spacing do not. */
export function blockKey(text: string): string {
  return text
    .toLowerCase()
    .replace(/^(?:[-*•·‣▪◦]+|\d+[.)])\s*/, "")
    .replace(/\s+/g, " ")
    .trim();
}
