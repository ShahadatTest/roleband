/**
 * The product language's KEYS (docs/copy.md).
 *
 * The words live in the catalog (src/copy/en/*.ftl); what stays here
 * is the shape the screens call: counts by noun, stage labels by slug,
 * and the level phrases, each read from the catalog at render so a language
 * switch reaches them. No literal copy lives in this file.
 */
import { sharedCountCompany, sharedCountPosting, sharedCountRole, sharedCuratedList } from "./gen/shared";
import {
  taxonomyLevelNotMapped,
  taxonomyLevelNotPlaced,
  taxonomyLevelNotStated,
  taxonomyLevelUnstatedChoice,
  taxonomyStageApplied,
  taxonomyStageInterviewing,
  taxonomyStageNetworking,
  taxonomyStageOffer,
  taxonomyStageRejected,
  taxonomyStageResearching,
  taxonomyStageSaved,
  taxonomyStageWithdrawn,
} from "./gen/taxonomy";

/** A noun as the message that counts it ("219 roles"). */
export type Noun = (args: { count: number }) => string;

/** The nouns a count names (docs/copy.md). `radar` has no plural on purpose. */
export const NOUN = {
  role: sharedCountRole,
  posting: sharedCountPosting,
  company: sharedCountCompany,
} as const satisfies Record<string, Noun>;

export function count(noun: Noun, n: number): string {
  return noun({ count: n });
}

/** The companies a fresh install follows (docs/copy.md). */
export const CURATED_LIST = sharedCuratedList;

/** A role whose posting names no level (docs/copy.md).
 *  Its stored band is Mid for sorting only, so it is never shown as Mid-level. */
export const LEVEL_NOT_STATED = taxonomyLevelNotStated;
/** A role whose title names a level in the company's own terms that we cannot
 *  place on the shared levels yet. Never "level not stated". */
export const LEVEL_NOT_MAPPED = taxonomyLevelNotMapped;
/** The Level step's choice to include both kinds: we can't place their level. */
export const UNSTATED_LEVEL_CHOICE = taxonomyLevelUnstatedChoice;
/** The Board's Level filter option for both kinds, after the rungs. */
export const LEVEL_NOT_PLACED_OPTION = taxonomyLevelNotPlaced;
/** The level key the server counts those roles under, in scope cells and the
 *  Board's Level facet alike: never "mid", which is their stored sort band.
 *  Kept beside its words rather than in `format.ts` so the app shell does not
 *  carry it. A key, not copy. */
export const UNSTATED_LEVEL = "unstated";

/** Progress stages on a role. The enum values are the API's; the labels are
 *  the user's, read at render. */
export const STAGE_LABEL = {
  get saved() { return taxonomyStageSaved(); },
  get researching() { return taxonomyStageResearching(); },
  get networking() { return taxonomyStageNetworking(); },
  get applied() { return taxonomyStageApplied(); },
  get interviewing() { return taxonomyStageInterviewing(); },
  get offer() { return taxonomyStageOffer(); },
  get rejected() { return taxonomyStageRejected(); },
  get withdrawn() { return taxonomyStageWithdrawn(); },
};

export type StageSlug = keyof typeof STAGE_LABEL;
export const STAGES = Object.keys(STAGE_LABEL) as StageSlug[];
