/* Jobs: the board, a posting's detail, facets, similar postings, saving, the comparison and "not for me".
   One domain of the typed client; `index.ts` composes `api`. */

import type { operations } from "../api.gen";
import type { Schemas } from "./schemas";
import { qs, requestJSON, getJSON, putJSON, postJSON } from "./transport";

/** A job row as every surface lists it, plus the keys only some responses
 *  carry: the ranked list paths add `relevance`/`why_world` or
 *  `matched_via`/`match_class`, and the detail route adds everything in
 *  `JobDetailResponse`. Optional here means "absent from some responses". */
export type Job = Omit<Schemas["JobListItem"], "posting_reality"> &
  // Every `GET /api/jobs` row sends it, but Review and Compare
  // build rows from payloads that do not, so a row may lack it.
  Partial<Pick<Schemas["JobListItem"], "posting_reality">> &
  Partial<Omit<Schemas["JobDetailResponse"], keyof Schemas["JobListItem"]>>;

/** The full detail payload: every key present. */
export type JobDetail = Schemas["JobDetailResponse"];

/** A posting as the lineage and twin surfaces pair it: the row plus its own
 *  text and stated pay, without what the detail route adds. */
export type JobDetailRow = Schemas["JobDetailRow"];

/** Advisory model verdict on which world a role serves. Display material only. */
export type RelevanceReview = Schemas["JobRelevanceReview"];

// --- Skill requirements -------------------------------------------------------

// UI vocabularies. The server sends these columns as plain strings (no database
// constraint backs them), so a consumer that switches on one keeps a fallback.
export type RequirementModality = "required" | "preferred" | "used_in_role" | "context";
export type ImportanceBand = "core" | "important" | "supporting" | "context";

export type JobSkillEvidence = Schemas["RequirementEvidence"];
export type JobSkill = Schemas["RequirementSkill"];
export type JobQualification = Schemas["RequirementQualification"];
export type JobRequirements = Schemas["JobRequirements"];
export type JobDescriptionSection = Schemas["DescriptionSection"];
export type CompSource = Schemas["CompSource"];

/** The posted pay band. Null on the detail route until the pay pass has run;
 *  `disclosed: false` means it ran and the posting stated none. */
export type DisclosedComp = Schemas["DisclosedComp"];

// The comp package shown on a job: what kind of money, and how sure we are of it.
// Built by backend/tracker/analytics/comp_package.py — see that module for the rules.
export type JobCompPackage = Schemas["JobCompPackage"];
export type CompProvenance = Schemas["CompComponent"]["provenance"];
export type CompComponent = Schemas["CompComponent"];
export type JobCompReconciliation = Schemas["CompReconciliation"];
export type JobCompPolicy = Schemas["OfferPolicy"];

export type LifecycleEvent = Schemas["JobLifecycleEntry"];

/** Structured filters a search query was read as, echoed on search responses. */
export type ParsedQuery = Schemas["ParsedQueryEcho"];

/** `GET /api/jobs`. Search-only and intent-only keys are absent otherwise;
 *  the field descriptions live on the Pydantic model. */
export type JobList = Schemas["JobListResponse"];

/** `GET /api/facets`: the board's filter options and open-role counts. A location's
 *  `parent` can name a group that is not offered, so an orphan renders at the top
 *  level; a value counting `total` roles narrows nothing. */
export type Facets = Schemas["FacetsResponse"];

export type JobViewResult = Schemas["JobViewResponse"];
export type PostingPageResult = Schemas["PostingPageResponse"];

/** `GET /api/jobs/{id}/history`: the headline age with its basis,
 *  role age when earlier postings of the same role count, every dated event,
 *  and the unconfirmed possible matches that count for nothing. */
export type ListingHistory = Schemas["ListingHistoryResponse"];
export type ListingEvent = Schemas["ListingEvent"];

/** The roles held side by side, in the order they were picked. Durable, so
 *  the rail count survives a reload the way the star beside the same row
 *  does. */
export type CompareSelection = Schemas["CompareSelectionOut"];

/** A neighbour: a list row with its similarity to the posting asked about. */
export type SimilarJob = Schemas["SimilarJob"];

export type SimilarJobs = Schemas["SimilarJobsResponse"];

/** The query `GET /api/jobs` parses, as generated from the route. */
export type JobsQuery = NonNullable<operations["list_jobs_api_jobs_get"]["parameters"]["query"]>;

/** A key the job list sorts by: a column, or "relevance" (Best fit). The
 *  route publishes the set, so a key it does not know fails `tsc`. */
export type JobSort = NonNullable<JobsQuery["sort"]>;
export type SortOrder = NonNullable<JobsQuery["order"]>;

export interface Filters {
  company: string[];
  level_band: string[];
  family: string[];
  track: string[];
  location_group: string[];
  domain: string[];
  workplace_type: string[];
  status: string;
  q: string;
  base_min: number | null;
  base_max: number | null;
  posted_within_days: number | null;
  // Exact counterpart to the Mission header's "new signals" count: jobs with
  // an `opened` lifecycle event since the current UTC day began.
  new_today_only: boolean;
  // Counterpart chip to new_today_only: roles re-listed today (repost successors).
  repost_today_only: boolean;
  favorites_only: boolean;
  // The Not-for-me lens (Show › Not for me): ONLY rows the user marked
  // "not for me", newest mark first (default browsing always excludes them
  // server-side).
  dismissed_only: boolean;
  // Only roles whose posting states a pay band (the AI pass found one).
  discloses_pay: boolean;
  // The Show lens: the reader's own mark. "unread" = never opened, "read" =
  // opened at least once, "" = both. Rows the reader has already dealt with
  // leave the list while they hunt for the one they have not.
  viewed: "" | "unread" | "read";
  ids?: number[];
  sort: JobSort;
  order: SortOrder;
  /** Expand the related section of an exact-title Best-match response.
   *  Reset to false whenever the query or any explicit filter changes. */
  include_related?: boolean;
  limit: number;
  offset: number;
}

// Shared default filter state, used by the board and (with overrides) by the
// Saved and Compare tabs.
export const DEFAULT_FILTERS: Filters = {
  company: [],
  level_band: [],
  family: [],
  track: [],
  location_group: [],
  domain: [],
  workplace_type: [],
  status: "open",
  q: "",
  base_min: null,
  base_max: null,
  posted_within_days: null,
  new_today_only: false,
  repost_today_only: false,
  favorites_only: false,
  dismissed_only: false,
  discloses_pay: false,
  viewed: "",
  // Relevance is the DEFAULT order: with any intent signal the
  // backend ranks by direction and stamps ranked_by:"intent"; with none it
  // falls back to first_seen server-side. One click back to Newest always.
  sort: "relevance",
  order: "desc",
  // Related expansion is per-query state: any query or explicit filter change
  // resets it — the board owns those resets.
  include_related: false,
  // One-scroll board: a page of roles is rendered IN FULL in the
  // page flow — no inner scroll window — so the page size is what a reader
  // scrolls before the pager, not a buffer size.
  limit: 20,
  offset: 0,
};

/** Keys whose empty string is a CHOICE the caller made, not an absence.
 *
 *  `qs` drops `""` because for nearly every param an empty box means "the user
 *  typed nothing" and the server's own default is the right answer. `status` is
 *  the exception: `/api/jobs` declares `status: str | None = "open"`, so an
 *  ABSENT param means open-only, while an explicit `status=` means no status
 *  condition at all. Saved ("closed roles are still saved") and the Board's
 *  "All" both ask for the second and, without it, silently get the first.
 *
 *  Opt in per key, never in bulk. `viewed` is typed `Literal["read","unread"] |
 *  None` on the wire, so `viewed=` is a 422 — and DEFAULT_FILTERS
 *  carries `viewed: ""`, so a blanket allowance would break every board request.
 */
const JOBS_MEANINGFUL_EMPTY: ReadonlySet<string> = new Set(["status"]);

export type DismissResult = Schemas["DismissResponse"];

export const jobsApi = {
  jobs: (f: Filters, signal?: AbortSignal) =>
    getJSON<JobList>(`/api/jobs?${qs(f, JOBS_MEANINGFUL_EMPTY)}`, signal),
  job: (id: number, signal?: AbortSignal) => getJSON<JobDetail>(`/api/jobs/${id}`, signal),
  /** Read the posting's own page because it was opened; called
   *  after Job detail renders, never as part of loading it. */
  readPostingPage: (id: number) => postJSON<PostingPageResult>(`/api/jobs/${id}/posting-page`),
  jobHistory: (id: number, signal?: AbortSignal) => getJSON<ListingHistory>(`/api/jobs/${id}/history`, signal),
  facets: (signal?: AbortSignal) => getJSON<Facets>("/api/facets", signal),
  similar: (id: number, scope: "within" | "cross" | "all" = "cross", limit = 8, signal?: AbortSignal) =>
    getJSON<SimilarJobs>(`/api/jobs/${id}/similar?scope=${scope}&limit=${limit}`, signal),
  setFavorite: (id: number, on: boolean) =>
    requestJSON<Schemas["FavoriteResponse"]>(
      `/api/jobs/${id}/favorite`,
      on ? "PUT" : "DELETE",
    ),
  /** "Not for me". The response echoes the employer's verbatim team/department
   *  so the flow can OFFER an exclusion rule — writing one is a separate,
   *  explicitly-confirmed call (`createScopeRule`). */
  dismissJob: (id: number, reason?: string | null) =>
    putJSON<DismissResult>(`/api/jobs/${id}/feedback`, { verdict: "dismissed", reason: reason ?? null }),
  undismissJob: (id: number) =>
    requestJSON<Schemas["UndismissResponse"]>(`/api/jobs/${id}/feedback`, "DELETE"),
};
