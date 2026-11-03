import { describe, expect, it } from "vitest";
import type { DuplicateProposal, LineageLink, LineageReviewItem } from "../../api";
import {
  descriptionDiffFixture,
  duplicateProposalFixture,
  jobDetailRowFixture,
  twinProposalFixture,
} from "../../test/fixtures";
import { type ReviewList, mergeReviewLists } from "./decision";

/* The queue count. The Review queue asks each endpoint for 50, so a count
 * taken from the fetched page would read "100 pairs left" whatever the
 * backlog. These fixtures carry a server total far larger than the page it
 * returns.
 */

type LinkOverrides = Partial<Pick<DuplicateProposal, "status" | "decision" | "reviewed_at" | "score">>;

const item = (id: number, jobId: number, priorJobId: number, over: LinkOverrides = {}): LineageReviewItem => ({
  link: duplicateProposalFixture({ id, job_id: jobId, prior_job_id: priorJobId, gap_days: 12, ...over }),
  prior: jobDetailRowFixture({ id: priorJobId }),
  job: jobDetailRowFixture({ id: jobId }),
  diff: {},
});

const twin = (id: number, jobId: number, priorJobId: number, over: LinkOverrides = {}): LineageReviewItem => ({
  link: twinProposalFixture({ id, job_id: jobId, prior_job_id: priorJobId, score: 0.9, ...over }),
  prior: jobDetailRowFixture({ id: priorJobId }),
  job: jobDetailRowFixture({ id: jobId }),
  diff: {},
  description_diff: descriptionDiffFixture,
});

const list = (total: number, items: LineageReviewItem[], limit = 50): ReviewList => ({
  total,
  limit,
  offset: 0,
  items,
});

describe("mergeReviewLists", () => {
  it("counts the whole backlog, not the page it was handed", () => {
    // A backlog of 275 + 201 pending, with only a few rows of each page in hand.
    const duplicates = list(275, [item(1, 2, 1), item(2, 4, 3)]);
    const twins = list(201, [twin(3, 6, 5)]);

    const merged = mergeReviewLists(duplicates, twins);

    expect(merged.total).toBe(476);
    // The count is not the page length.
    expect(merged.total).not.toBe(merged.items.length);
    expect(merged.items).toHaveLength(3);
  });

  it("counts a pair proposed by both detectors once", () => {
    // History's normal shape: confirming a duplicate proposal AS a twin leaves
    // a reviewed row in each table, so summing the two totals double-counts
    // every conversion.
    const duplicates = list(12, [
      item(1, 2, 1, { status: "rejected", decision: "twin", reviewed_at: "2026-09-01T10:00:00Z" }),
      item(2, 4, 3, { status: "confirmed", decision: "duplicate", reviewed_at: "2026-09-01T09:00:00Z" }),
    ]);
    const twins = list(6, [
      twin(9, 2, 1, { status: "confirmed", decision: "twin", reviewed_at: "2026-09-01T10:00:00Z" }),
    ]);

    const merged = mergeReviewLists(duplicates, twins);

    expect(merged.items).toHaveLength(2);
    expect(merged.total).toBe(17); // 12 + 6, less the one pair held by both
  });

  it("merges a pair whichever order its two rows arrive in", () => {
    const pair = (kind: LineageLink["proposal_kind"], id: number) =>
      kind === "twin" ? twin(id, 9, 8, { score: null }) : item(id, 9, 8, { score: 0.88 });

    const forward = mergeReviewLists(list(1, [pair("duplicate", 1)]), list(1, [pair("twin", 2)]));
    const reverse = mergeReviewLists(list(1, [pair("twin", 2)]), list(1, [pair("duplicate", 1)]));

    expect(forward.items).toHaveLength(1);
    expect(reverse.items).toHaveLength(1);
    expect(forward.total).toBe(1);
    expect(reverse.total).toBe(1);
    // The surviving row keeps the score its twin row does not carry.
    expect(forward.items[0].link.score).toBe(0.88);
    expect(reverse.items[0].link.score).toBe(0.88);
  });

  it("keeps the kept row's own link shape when it borrows its partner's evidence", () => {
    const duplicate = item(1, 9, 8, { status: "rejected", decision: "twin", reviewed_at: "2026-09-01T10:00:00Z" });
    const related = twin(2, 9, 8, { status: "confirmed", decision: "twin", score: null, reviewed_at: "2026-09-01T10:00:00Z" });

    const [kept] = mergeReviewLists(list(1, [duplicate]), list(1, [related])).items;

    expect(kept.link.proposal_kind).toBe("twin");
    expect(kept.link.score).toBe(0.9);
    expect("description_diff" in kept).toBe(true);
  });

  it("never reports fewer pairs than it is holding", () => {
    // A stale or narrower server count must not make the screen claim less
    // than the rows already on it.
    const merged = mergeReviewLists(list(0, [item(1, 2, 1), item(2, 4, 3)]), list(0, []));

    expect(merged.total).toBe(2);
  });

  it("reports an empty queue as empty", () => {
    const merged = mergeReviewLists(list(0, []), list(0, []));

    expect(merged.total).toBe(0);
    expect(merged.items).toEqual([]);
  });
});
