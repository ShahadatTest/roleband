import type { PayFloor } from "../../api";
import type { ScopeSelection } from "./scopeDraftModel";
import type { AnswerRoles } from "./walk/walkModel";

/* First-run setup's answers, kept for the tab until Start saves them. Setup
   writes nothing to the server before Start, so a reload, or a phone browser
   discarding a background tab, would otherwise put the person back at step 1
   with every answer gone. In sessionStorage: it lives as long as the tab, a
   new launch starts blank, and nothing reaches the server before Start. A save
   forgets it; "Set up later" keeps it, so "Finish setting up" returns to the
   answers.

   What comes back is untrusted: a stored blob outlives the code that wrote it,
   so a part of another shape reads as nothing kept. Storage can always fail:
   a failed read is nothing kept, a failed write is dropped.

   Its own module, with no imports but types, so the test setup can clear it
   without loading the provider. */

const KEY = "roleband.setup.v1";

export interface SetupStash {
  draft?: ScopeSelection;
  /** The Summary's pay floor: null is "no floor", left out is untouched. */
  floor?: PayFloor | null;
  /** The companies step's choice. */
  companies?: string;
}

function storage(): Storage | null {
  try {
    // Reading the property itself throws when site data is blocked.
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

const strings = (value: unknown): string[] | null =>
  Array.isArray(value) && value.every((item) => typeof item === "string") ? value : null;
const stageOf = (value: unknown): string | null | undefined =>
  value === null ? null : typeof value === "string" ? value : undefined;

const SET_KEYS = ["roles", "bands", "tracks", "locations", "domains", "excluded", "excepted"] as const;

function encodeDraft(draft: ScopeSelection) {
  return {
    ...Object.fromEntries(SET_KEYS.map((key) => [key, [...draft[key]]])),
    answers: draft.answers === null
      ? null
      : [...draft.answers].map(([track, roles]) => [track, roles === "any" ? "any" : [...roles]]),
    includeUnstatedLevel: draft.includeUnstatedLevel,
    experienceStage: draft.experienceStage,
    targetStage: draft.targetStage,
  };
}

function decodeAnswers(value: unknown): Map<string, AnswerRoles> | null | undefined {
  if (value === null) return null;
  if (!Array.isArray(value)) return undefined;
  const answers = new Map<string, AnswerRoles>();
  for (const entry of value) {
    if (!Array.isArray(entry) || entry.length !== 2 || typeof entry[0] !== "string") return undefined;
    const roles = entry[1] === "any" ? "any" : strings(entry[1]);
    if (roles === null) return undefined;
    answers.set(entry[0], roles === "any" ? "any" : new Set(roles));
  }
  return answers;
}

function decodeDraft(value: unknown): ScopeSelection | undefined {
  if (!value || typeof value !== "object") return undefined;
  const stored = value as Record<string, unknown>;
  const sets: Partial<Record<(typeof SET_KEYS)[number], Set<string>>> = {};
  for (const key of SET_KEYS) {
    const list = strings(stored[key]);
    if (!list) return undefined;
    sets[key] = new Set(list);
  }
  const answers = decodeAnswers(stored.answers);
  const experienceStage = stageOf(stored.experienceStage);
  const targetStage = stageOf(stored.targetStage);
  if (answers === undefined || experienceStage === undefined || targetStage === undefined) return undefined;
  if (typeof stored.includeUnstatedLevel !== "boolean") return undefined;
  return {
    ...(sets as Record<(typeof SET_KEYS)[number], Set<string>>),
    answers,
    includeUnstatedLevel: stored.includeUnstatedLevel,
    experienceStage,
    targetStage,
  };
}

function decodeFloor(value: unknown): PayFloor | null | undefined {
  if (value === null) return null;
  if (!value || typeof value !== "object") return undefined;
  const { amount, currency } = value as Record<string, unknown>;
  return typeof amount === "number" && Number.isFinite(amount) && typeof currency === "string" ? { amount, currency } : undefined;
}

function readRaw(): Record<string, unknown> {
  try {
    const raw = storage()?.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

export function readSetupStash(): SetupStash {
  const raw = readRaw();
  const stash: SetupStash = {};
  const draft = decodeDraft(raw.draft);
  if (draft) stash.draft = draft;
  const floor = "floor" in raw ? decodeFloor(raw.floor) : undefined;
  if (floor !== undefined) stash.floor = floor;
  if (typeof raw.companies === "string") stash.companies = raw.companies;
  return stash;
}

/** Keeps the parts given, beside the ones already kept. */
export function keepSetupStash(part: SetupStash): void {
  try {
    const next = { ...readRaw() };
    if (part.draft) next.draft = encodeDraft(part.draft);
    if (part.floor !== undefined) next.floor = part.floor;
    if (part.companies !== undefined) next.companies = part.companies;
    storage()?.setItem(KEY, JSON.stringify(next));
  } catch {
    /* Not kept: a reload starts setup over, as it did before. */
  }
}

export function forgetSetupStash(): void {
  try {
    storage()?.removeItem(KEY);
  } catch {
    /* Nothing to forget where nothing could be kept. */
  }
}
