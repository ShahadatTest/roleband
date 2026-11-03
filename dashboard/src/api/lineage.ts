/* Lineage and twins: stacks, both review queues, verdicts and the model's advice.
   One domain of the typed client; `index.ts` composes `api`. */

import type { Schemas } from "./schemas";
import { qs, getJSON, postJSON } from "./transport";

/** `POST /api/{lineage,twins}/links/{id}/analyze`: the local model's advice on a
 *  proposal. Advisory only; the human verdict is untouched. */
export type DuplicateLLMAssessment = Schemas["RelationshipAssessment"];

// --- Repost lineage (the "stack deck") and twins ---
// Aliases of the generated responses. A duplicate proposal and a
// twin proposal differ by key set, so a link is their union: narrow a link on
// `proposal_kind`, and a whole review item on `description_diff`.
export type DuplicateProposal = Schemas["DuplicateProposal"];
export type TwinProposal = Schemas["TwinProposal"];
export type LineageLink = DuplicateProposal | TwinProposal;

/** What moved between a posting and the one before it: a key per changed field, absent otherwise. */
export type LineageDiff = Schemas["PostingDiff"];

export type LineageMember = Schemas["LineageMember"];

/** `GET /api/jobs/{id}/lineage`: the whole stack, or `lineage_id: null` with no members. */
export type LineageDetail = Schemas["JobLineageResponse"];

export type DuplicateReviewItem = Schemas["DuplicateReviewItem"];
export type TwinReviewItem = Schemas["TwinReviewItem"];
/** An item of either review queue. */
export type LineageReviewItem = DuplicateReviewItem | TwinReviewItem;
export type DescriptionDiffEvidence = Schemas["DescriptionDiff"];

export type DuplicateReviewList = Schemas["DuplicateReviewList"];
export type TwinReviewList = Schemas["TwinReviewList"];

/** The summary form a review route answers with `detail=false`: each posting a
 *  list row, without its description or stated pay, and a twin item without
 *  its description diff. The Decided list reads it. */
export type DuplicateReviewSummaryList = Schemas["DuplicateReviewSummaryList"];
export type TwinReviewSummaryList = Schemas["TwinReviewSummaryList"];
/** An item of either Decided list. */
export type DecidedReviewItem = Schemas["DuplicateReviewSummaryItem"] | Schemas["TwinReviewSummaryItem"];

/* Both Decided reads ask for every verdict of every confidence (a verdict keeps
   the link's confidence, and `qs` keeps the empty `confidence=` only because it
   is named here), in the summary form. */
const DECIDED = { status: "reviewed", confidence: "", detail: false } as const;
const KEEP_CONFIDENCE: ReadonlySet<string> = new Set(["confidence"]);
export type DecidedQuery = typeof DECIDED & { limit: number };
const decidedQuery = (limit: number) => qs({ ...DECIDED, limit } satisfies DecidedQuery, KEEP_CONFIDENCE);

export type DuplicateVerdictResult = Schemas["DuplicateVerdictResult"];
export type TwinVerdictResult = Schemas["TwinVerdictResult"];

/** `pending` withdraws the last verdict: the pair returns to the queue and
    whatever the verdict changed beyond the link is put back. */
export type LineageVerdict = Schemas["LineageReviewPayload"]["verdict"];
export type TwinVerdict = Schemas["TwinReviewPayload"]["verdict"];

export type TwinMember = Schemas["TwinMember"];
/** `GET /api/jobs/{id}/twins`: the posting first, then its confirmed twin component. */
export type TwinDetail = Schemas["JobTwinsResponse"];

/** `GET /api/jobs/{id}/place-set`: the role's postings, one per place, when its
 *  employer lists it once per place. Decided by rule, never queued. */
export type PlaceSetDetail = Schemas["JobPlaceSetResponse"];
export type PlaceSetMember = Schemas["PlaceSetMember"];
/** `different` splits a posting out of its set; `pending` takes that back. */
export type PlaceSetDecision = Schemas["PlaceSetReviewPayload"]["decision"];

export const lineageApi = {
  lineage: (id: number) => getJSON<LineageDetail>(`/api/jobs/${id}/lineage`),
  lineageReview: (params: { status?: string; confidence?: string; order?: "strongest" | "weakest"; limit?: number; offset?: number } = {}) =>
    getJSON<DuplicateReviewList>(`/api/lineage/review?${qs(params)}`),
  lineageReviewHistory: (limit = 20) =>
    getJSON<DuplicateReviewSummaryList>(`/api/lineage/review?${decidedQuery(limit)}`),
  reviewLineageLink: (id: number, verdict: LineageVerdict) =>
    postJSON<DuplicateVerdictResult>(
      `/api/lineage/links/${id}/review`,
      { verdict },
    ),
  twinReview: (params: { status?: string; confidence?: string; limit?: number; offset?: number } = {}) =>
    getJSON<TwinReviewList>(`/api/twins/review?${qs(params)}`),
  twinReviewHistory: (limit = 20) =>
    getJSON<TwinReviewSummaryList>(`/api/twins/review?${decidedQuery(limit)}`),
  reviewTwinLink: (id: number, verdict: TwinVerdict) =>
    postJSON<TwinVerdictResult>(`/api/twins/links/${id}/review`, { verdict }),
  twins: (id: number) => getJSON<TwinDetail>(`/api/jobs/${id}/twins`),
  placeSet: (id: number) => getJSON<PlaceSetDetail>(`/api/jobs/${id}/place-set`),
  reviewPlaceSet: (id: number, decision: PlaceSetDecision) =>
    postJSON<PlaceSetDetail>(`/api/jobs/${id}/place-set/review`, { decision }),
  analyzeLineageLink: (id: number) =>
    postJSON<DuplicateLLMAssessment>(`/api/lineage/links/${id}/analyze`),
  analyzeTwinLink: (id: number) =>
    postJSON<DuplicateLLMAssessment>(`/api/twins/links/${id}/analyze`),
};
