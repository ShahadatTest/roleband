import type { Job } from "../../api";
import { companyName, fmtDate } from "../../format";
import {
  jobsUnfollowedYouDonTFollowSo,
} from "../../copy/gen/jobs";

/** The one sentence for a role at a company the user stopped following.
 * Only Saved and Compare rows, and Job detail, can be at one: the
 *  Board shows followed companies only. The date is the posting's own last
 *  sighting, which is exact; nothing records when the user stopped following. */
export function unfollowedSentence(job: Pick<Job, "company" | "last_seen">): string {
  return jobsUnfollowedYouDonTFollowSo({ company: String(companyName(job.company)), last_seen: String(fmtDate(job.last_seen)) });
}
