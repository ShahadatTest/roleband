/* Profile: suggestions, the pay floor and pursuits.
   One domain of the typed client; `index.ts` composes `api`. */

import type { Schemas } from "./schemas";
import { getJSON, putJSON, postJSON, deleteJSON } from "./transport";

export type PursuitStage = Schemas["JobPursuit"]["stage"];

/** Pursuit state, as job detail and a pursuit write send it. */
export type PursuitInfo = Schemas["JobPursuit"];

/** A listed pursuit: the row plus the opportunity it tracks. */
export type PursuitListItem = Schemas["PursuitListItem"];

/* Profile suggestion wire types are aliases of the generated schemas
   (`tracker/api/schemas/profile_suggestions.py`). */

/** Why inference raised a suggestion. Stored as JSONB and served as stored, so
 *  keys beyond these may arrive; every named key always does. */
export type ProfileSuggestionBasis = Schemas["ProfileSuggestionBasis"];

/** The optional pay floor: lowest yearly base, one currency. */
export type PayFloor = Schemas["PayFloor"];

/** One inferred adjustment, as the list and both verdicts answer with it.
 *  `kind` and `status` are what the table's CHECK constraints admit; `world`
 *  is a plain string, served with its slug as `display` once retired. */
export type ProfileSuggestion = Schemas["ProfileSuggestionRow"];

export const profileApi = {
  /** The optional pay floor: a yearly base in one currency, kept
   *  apart from the scope; every write answers with the stored floor. */
  payFloor: () => getJSON<Schemas["PayFloorResponse"]>("/api/profile/pay-floor"),
  savePayFloor: (floor: Schemas["PayFloorInput"]) => putJSON<Schemas["PayFloorResponse"]>("/api/profile/pay-floor", floor),
  clearPayFloor: () => deleteJSON<Schemas["PayFloorResponse"]>("/api/profile/pay-floor"),
  /** Inferred profile adjustments (pending only). The inference pass proposes;
   *  accept/dismiss below are the only resolution paths, and accept is the
   *  only way a suggestion touches scope. */
  profileSuggestions: () =>
    getJSON<Schemas["ProfileSuggestionListResponse"]>("/api/profile/suggestions"),
  acceptProfileSuggestion: (id: number) =>
    postJSON<Schemas["ProfileSuggestionAcceptResponse"]>(`/api/profile/suggestions/${id}/accept`, {}),
  dismissProfileSuggestion: (id: number) =>
    postJSON<Schemas["ProfileSuggestionDismissResponse"]>(`/api/profile/suggestions/${id}/dismiss`, {}),
  /** Pursuits over HTTP — same helper the MCP write tool uses. No DELETE:
   *  `withdrawn` is a stage, and history is the point. */
  pursuits: (stage?: PursuitStage) =>
    getJSON<Schemas["PursuitListResponse"]>(
      `/api/pursuits${stage ? `?stage=${stage}` : ""}`,
    ),
  setPursuit: (jobId: number, update: Schemas["PursuitUpdate"]) =>
    putJSON<Schemas["PursuitWriteResponse"]>(`/api/jobs/${jobId}/pursuit`, update),
};
