import type { DecidedReviewItem, DuplicateReviewList, LineageLink, LineageReviewItem } from "../../api";
import { percent } from "../../copy/format";
import {
  duplicatesComparisonLedgerDifferent,
  duplicatesDecisionCloseButNotTheSame,
  duplicatesDecisionDifferentRoles,
  duplicatesDecisionDuplicate,
  duplicatesDecisionOneRoleTwoPostingsListed,
  duplicatesDecisionRelated,
  duplicatesDecisionRelatedRoles,
  duplicatesDecisionSameRole,
  duplicatesDecisionTwoDifferentRolesKeepBoth,
} from "../../copy/gen/duplicates";

/* The review domain's shared vocabulary: what a decision is, how it is named
 * to the reviewer, and how the queue and history lists reconcile the same
 * pair surfacing through both the duplicate and twin detectors. */

export type RelationshipDecision = "duplicate" | "twin" | "different";

/** A review item of either kind and either form: what the decision helpers read. */
export type ReviewPair = { link: LineageLink };

/** The queue or the history as the screen holds it: both review routes merged
 *  into one pair-deduplicated list of either kind. A client view, not a wire
 *  shape — each route sends only its own kind. */
export type ReviewList<Item extends ReviewPair = LineageReviewItem> = Omit<DuplicateReviewList, "items"> & {
  items: Item[];
};
/** The Decided list: both routes' summary forms, merged the same way. */
export type DecidedList = ReviewList<DecidedReviewItem>;

export const DECISION_COPY: Record<
  RelationshipDecision,
  { label: string; short: string; note: string }
> = {
  different: {
    get label() { return duplicatesDecisionDifferentRoles(); },
    get short() { return duplicatesComparisonLedgerDifferent(); },
    get note() { return duplicatesDecisionTwoDifferentRolesKeepBoth(); },
  },
  twin: {
    get label() { return duplicatesDecisionRelatedRoles(); },
    get short() { return duplicatesDecisionRelated(); },
    get note() { return duplicatesDecisionCloseButNotTheSame(); },
  },
  duplicate: {
    get label() { return duplicatesDecisionSameRole(); },
    get short() { return duplicatesDecisionDuplicate(); },
    get note() { return duplicatesDecisionOneRoleTwoPostingsListed(); },
  },
};

/** A detector's score, said one way on every list: a percentage. Null when
 *  the detector gave none. */
export const similarityText = (score: number | null | undefined): string | null =>
  score == null ? null : percent(score);

/** One proposal's key, `${proposal_kind}-${id}`: a duplicate and a twin
 *  proposal can share an id, never a key. */
export function proposalKey(item: ReviewPair): string {
  return `${item.link.proposal_kind}-${item.link.id}`;
}

export function decisionOf(item: ReviewPair): RelationshipDecision {
  if (
    item.link.decision === "duplicate" ||
    item.link.decision === "twin" ||
    item.link.decision === "different"
  ) {
    return item.link.decision;
  }
  if (item.link.status === "confirmed") {
    return item.link.proposal_kind === "twin" ? "twin" : "duplicate";
  }
  return "different";
}

function preferHistoryItem(candidate: ReviewPair, current: ReviewPair): boolean {
  const candidateTime = candidate.link.reviewed_at ? Date.parse(candidate.link.reviewed_at) : 0;
  const currentTime = current.link.reviewed_at ? Date.parse(current.link.reviewed_at) : 0;
  if (candidateTime !== currentTime) return candidateTime > currentTime;
  const decision = decisionOf(candidate);
  return (
    (decision === "twin" && candidate.link.proposal_kind === "twin") ||
    (decision === "duplicate" && candidate.link.proposal_kind === "duplicate")
  );
}

/* The same item with the score and reasons its partner row supplied. Each
 * item keeps its own type, and so its kind's link shape. */
function withEvidence<Item extends ReviewPair>(item: Item, score: number | null, reasons: string[]): Item {
  return { ...item, link: withLinkEvidence(item.link, score, reasons) };
}

function withLinkEvidence<Link extends LineageLink>(link: Link, score: number | null, reasons: string[]): Link {
  return { ...link, score, reasons };
}

/* Merge the duplicate and twin lists into one pair-deduped list.
 *
 * `total` is the size of the SET, not `items.length` (the size of the PAGE):
 * the queue asks each endpoint for 50, so a page-length count would sit at
 * 100 whatever the backlog, and a verdict would take it to 99 only for the
 * reload to put it back.
 *
 * Both endpoints count their own list in full (`func.count()` over the same
 * filter, unpaged), so the set is |L| + |T| minus the pairs that are in BOTH,
 * and that last term is exactly the merges performed below. Exact whenever
 * every shared pair is inside the fetched window, which holds for two
 * different reasons:
 *
 * - the QUEUE has no shared pairs to miss. `fetch_twin_candidates` refuses to
 *   propose a twin for a pair that already carries a pending or confirmed
 *   duplicate link, because that pair's duplicate proposal already offers
 *   "Mark as twin" on this very screen.
 * - HISTORY is mostly shared pairs (confirming a duplicate proposal AS a twin
 *   leaves a reviewed row in each table), and it fetches the newest 200 + 200
 *   verdicts; both rows of a converted pair carry the same moment.
 *
 * Past that window this over-counts a converted pair by one row, a bounded
 * error the count accepts rather than freezing at the page size.
 */
export function mergeReviewLists<Left extends ReviewPair, Right extends ReviewPair>(
  left: ReviewList<Left>,
  right: ReviewList<Right>,
): ReviewList<Left | Right> {
  const byPair = new Map<string, Left | Right>();
  let shared = 0;
  for (const item of [...left.items, ...right.items]) {
    const pair = [item.link.job_id, item.link.prior_job_id].sort((a, b) => a - b).join(":");
    const previous = byPair.get(pair);
    if (!previous) {
      byPair.set(pair, item);
      continue;
    }
    shared += 1;
    const preferred = preferHistoryItem(item, previous) ? item : previous;
    const fallback = preferred === item ? previous : item;
    byPair.set(
      pair,
      withEvidence(
        preferred,
        preferred.link.score ?? fallback.link.score,
        preferred.link.reasons.length > 0 ? preferred.link.reasons : fallback.link.reasons,
      ),
    );
  }
  const items = [...byPair.values()];
  return {
    // The floor is the rows in hand: a stale or narrower server count must
    // never make the screen claim fewer pairs than it is holding.
    total: Math.max(items.length, left.total + right.total - shared),
    limit: left.limit + right.limit,
    offset: 0,
    items: items.sort((a, b) => {
      const aDate = a.link.reviewed_at ? Date.parse(a.link.reviewed_at) : 0;
      const bDate = b.link.reviewed_at ? Date.parse(b.link.reviewed_at) : 0;
      return bDate - aDate || (b.link.score ?? 0) - (a.link.score ?? 0);
    }),
  };
}
