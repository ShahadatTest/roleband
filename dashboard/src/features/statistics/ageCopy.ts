import { relDays } from "../../format";
import {
  insightsAgeCopyCountedFromWhenEachRole,
  insightsAgeCopyDatedByTheEmployer,
  insightsAgeCopyListedFor,
  insightsAgeCopyListedToday,
} from "../../copy/gen/insights";

/* Age captions for Insights. Here rather than in format.ts:
   format.ts is in the app shell's chunk, and only these screens say them. */

/* One posting's age as a caption: the row's own `listed_days`.
 * Never `days_open`, our first-sighting clock, which only aggregates read
 * (docs/copy.md: "days open" is never said). */
export function listedFor(days: number | null | undefined): string | null {
  if (days == null) return null;
  if (days === 0) return insightsAgeCopyListedToday();
  return insightsAgeCopyListedFor({ days: String(relDays(days)) });
}

/* Beside an age aggregate (a median, age bands, how long postings stay up):
 * how much of its sample the employer dated. The aggregate itself keeps the
 * first-sighting clock; this says how much of it an employer date could move. */
export function employerDated(share: number | null | undefined): string | null {
  if (share == null) return null;
  return insightsAgeCopyDatedByTheEmployer({ percent: Math.round(share * 100) });
}

/* The quiet line under an age aggregate whose clock the panel does not already
 * explain: which clock, and how much of the sample the employer dated. A role
 * RoleBand watched open counts from that sighting; one its company's FIRST scan
 * found was already listed, so it counts from its listed date. */
export function ageAggregateNote(share: number | null | undefined): string | null {
  const dated = employerDated(share);
  return dated && insightsAgeCopyCountedFromWhenEachRole({ dated: String(dated) });
}
