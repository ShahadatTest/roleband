import type { ScopeAxes, ScopeCatalog, ScopeSettingsPayload, ScopeSettingsSaveResult } from "../../api";
import { INCLUDE_UNSTATED_LEVEL_DEFAULT } from "./scopeCells";
import { answersFrom, answersWire, projectAnswers, sameAnswers, type Answers } from "./walk/walkModel";

/* The tracking scope's state machine, with no React in it.
   `useScopeDraft` owns the requests, the transient flags and the context; every
   rule about what the state BECOMES lives here, where it can be read and tested
   without a provider, a mocked client and a rendered tree.

   Two sides, not one: `saved` is what the server holds, `draft` is what the user
   has. Everything the screens ask — is there anything to save, what would it
   cost, which endpoint does it go to — is a comparison between them. */

/** The five axes, plus the two persona markers that ride with them. One of
    these is the draft; the other is what was last saved. The aim sentence is
    not here: it ranks and never scopes, so Settings > Intelligence owns it and
    a scope save leaves it untouched. */
export interface ScopeSelection {
  roles: Set<string>;
  bands: Set<string>;
  tracks: Set<string>;
  locations: Set<string>;
  domains: Set<string>;
  /** Subjects the person is not interested in: a veto on the worlds axis,
      kept apart from it because "not interested" must drop a role whatever
      else it is about. */
  excluded: Set<string>;
  /** Places excepted inside the included ones ("the US except New York").
      Saved as `excluded_location_groups`. */
  excepted: Set<string>;
  /** Which roles of each kind: the walk's per-answer choice. The
      flat `roles` and `tracks` above are its projection while it is set.
      Null: the draft has no answers (Welcome writes the flat lists and the
      server reads answers off them). */
  answers: Answers | null;
  /** Whether roles whose level isn't stated pass the level axis.
      Saved as `include_unstated_level`. */
  includeUnstatedLevel: boolean;
  experienceStage: string | null;
  targetStage: string | null;
}

export interface ScopeDraftState {
  saved: ScopeSelection;
  draft: ScopeSelection;
  /** `in_scope_changed` from the last save: ground truth for how many known
      jobs entered or left scope. Null until a save happens. */
  lastInScopeChanged: number | null;
  /** What the Board holds after the last save (`on_board`): the
      number the confirmation says. Null until a save. */
  lastOnBoard: number | null;
  /** Roles the last save put on the Board from earlier scans (`promoted`),
      and whether more wait for the scan that is running. Null until
      a save. */
  lastPromotion: SavePromotion | null;
  /** The draft was carried over from an earlier visit to Profile:
      the loads refresh `saved` only and leave the person's unsaved picks be. */
  keepDraft?: boolean;
}

export type SavePromotion = { promoted: number; pending: boolean };

export type ScopeAxis = "roles" | "bands" | "tracks" | "locations" | "domains" | "excluded" | "excepted";

/** The five axes in one list, so a rule that must hold for all of them cannot
    quietly skip one. */
const SCOPE_AXES: ScopeAxis[] = ["roles", "bands", "tracks", "locations", "domains", "excluded", "excepted"];

/** One save path: the scope and the two level markers together. */
export type ScopeSaveRequest = { endpoint: "settings"; body: ScopeSettingsPayload };

export interface ScopeSaveOutcome {
  /** What was sent. The response echoes the axes but never the passengers, so
      the request is the only record of which markers the server now holds. */
  request: ScopeSaveRequest;
  /** The draft as it stood when the write was SUBMITTED. A response can only be
      adopted into the draft where the draft has not moved since — see
      `applySaveResult`. */
  submitted: ScopeSelection;
  /** The server's answer: the axes as saved, the counts the confirmation
      says, and what the save promoted. */
  result: ScopeSettingsSaveResult;
}

export type ScopeDraftAction =
  | {
    type: "catalog_loaded";
    settings: ScopeAxes;
    domains: string[];
    initialSelection: "saved" | "empty";
  }
  | {
    type: "persona_loaded";
    stages: { experience: string; target: string } | null;
  }
  | { type: "toggled"; axis: ScopeAxis; slug: string }
  | { type: "role_category_toggled"; slugs: string[] }
  | { type: "locations_replaced"; slugs: string[] }
  | { type: "places_replaced"; locations: string[]; excepted: string[] }
  | { type: "roles_replaced"; slugs: string[] }
  | { type: "domains_replaced"; slugs: string[] }
  | { type: "excluded_replaced"; slugs: string[] }
  | { type: "answers_replaced"; answers: Answers; allFamilies: readonly string[] }
  | { type: "server_domains_adopted"; slugs: string[]; excluded: string[] }
  | { type: "stage_placed"; handle: "experience" | "target"; slug: string }
  | { type: "bands_derived"; stageOrder: string[] }
  | { type: "unstated_level_set"; include: boolean }
  | { type: "save_confirmed"; outcome: ScopeSaveOutcome };

function emptySelection(): ScopeSelection {
  return {
    roles: new Set(),
    bands: new Set(),
    tracks: new Set(),
    locations: new Set(),
    domains: new Set(),
    excluded: new Set(),
    excepted: new Set(),
    answers: null,
    includeUnstatedLevel: INCLUDE_UNSTATED_LEVEL_DEFAULT,
    experienceStage: null,
    targetStage: null,
  };
}

export const initialScopeDraftState: ScopeDraftState = {
  saved: emptySelection(),
  draft: emptySelection(),
  lastInScopeChanged: null,
  lastOnBoard: null,
  lastPromotion: null,
};

function sameSet(left: Set<string>, right: Set<string>) {
  return left.size === right.size && [...left].every((item) => right.has(item));
}

/** The ladder in taxonomy order. The catalog lists levels in whatever order it
    likes; `order` is the rank. */
export function stageOrderOf(levels: { slug: string; order: number }[] | null): string[] {
  if (!levels) return [];
  return [...levels].sort((a, b) => a.order - b.order).map((level) => level.slug);
}

/** The tiers between the two markers, in ladder order, either way round.
    Null when a marker names something the ladder does not carry. */
export function stageSpanOf(stageOrder: string[], experience: string, target: string): string[] | null {
  const indices = [stageOrder.indexOf(experience), stageOrder.indexOf(target)];
  if (indices.some((index) => index < 0)) return null;
  const [lo, hi] = [...indices].sort((a, b) => a - b);
  return stageOrder.slice(lo, hi + 1);
}

/** Seniority tiers the selected function(s) can realistically occupy: the union
    of each selected track's gate, and the whole ladder when nothing is selected
    or nothing declares one. */
export function allowedBandsOf(
  tracks: { slug: string; allowed_bands?: string[] | null }[] | null,
  selectedTracks: Set<string>,
  stageOrder: string[],
): Set<string> {
  const all = new Set(stageOrder);
  if (!tracks || selectedTracks.size === 0) return all;
  const union = new Set<string>();
  for (const track of tracks) {
    if (selectedTracks.has(track.slug)) {
      for (const band of track.allowed_bands ?? []) union.add(band);
    }
  }
  return union.size ? union : all;
}

export interface ScopeDirtiness {
  /** The locations axis changed. Joint counts are location-blind, so the impact
      estimate cannot price this in — surface a caveat instead. */
  locationsDirty: boolean;
  /** The worlds axis changed — domain-blind joint counts, same caveat. */
  domainsDirty: boolean;
  /** Roles/bands/tracks changed — the axes the joint-count estimate covers. */
  estimableDirty: boolean;
  stagesDirty: boolean;
  dirty: boolean;
}

export function scopeDirtiness({ saved, draft }: ScopeDraftState): ScopeDirtiness {
  const locationsDirty = !sameSet(draft.locations, saved.locations) || !sameSet(draft.excepted, saved.excepted);
  // The veto rides with the worlds axis: both are the World step.
  const domainsDirty = !sameSet(draft.domains, saved.domains) || !sameSet(draft.excluded, saved.excluded);
  // Answers count only while the draft carries them: a flat edit drops them
  // (FLAT_ROLE_EDIT) and its lists carry the change instead.
  const estimableDirty =
    (draft.answers !== null && !sameAnswers(draft.answers, saved.answers)) ||
    !sameSet(draft.roles, saved.roles) ||
    !sameSet(draft.bands, saved.bands) ||
    !sameSet(draft.tracks, saved.tracks) ||
    draft.includeUnstatedLevel !== saved.includeUnstatedLevel;
  /* Only meaningful once a persona has been loaded (the wizard never loads one
     and commits through its own CTA, not through `dirty`). The span is not
     enough on its own: re-anchoring principal->director_plus as
     director_plus->principal is the same band set and a different answer to
     "where am I today", and only the markers remember which. */
  const stagesDirty =
    (saved.experienceStage !== null || saved.targetStage !== null) &&
    (draft.experienceStage !== saved.experienceStage || draft.targetStage !== saved.targetStage);
  return {
    locationsDirty,
    domainsDirty,
    estimableDirty,
    stagesDirty,
    dirty: estimableDirty || locationsDirty || domainsDirty || stagesDirty,
  };
}

/** The one save request: `PUT /api/settings` with the axes, the
    role answers, the vetoes and, when both are placed, the two level markers,
    which the server turns into the seniority span and keeps on the persona.
    Both markers or neither; the backend rejects half a pair. */
export function buildSaveRequest({ draft }: ScopeDraftState): ScopeSaveRequest {
  return {
    endpoint: "settings",
    body: {
      enabled_role_groups: [...draft.roles],
      enabled_seniority_bands: [...draft.bands],
      enabled_role_tracks: [...draft.tracks],
      enabled_location_groups: [...draft.locations],
      enabled_domain_groups: [...draft.domains],
      excluded_domain_groups: [...draft.excluded],
      excluded_location_groups: [...draft.excepted],
      include_unstated_level: draft.includeUnstatedLevel,
      ...(draft.answers ? { role_answers: answersWire(draft.answers) } : {}),
      ...(draft.experienceStage && draft.targetStage
        ? { experience_stage: draft.experienceStage, target_stage: draft.targetStage }
        : {}),
    },
  };
}

/** What a confirmed save is allowed to change.

    `saved` takes the echo whole — the server has those axes now, whatever the
    screen has since become. The DRAFT takes it only per axis, and only where
    that axis still matches the submission: a response describes the state at
    the click, so adopting it wholesale deletes every edit made while the
    request was in flight, silently and with the draft left reading clean. An
    axis nobody touched must still be adopted, or a server that normalizes (the
    server derives the seniority axis from the markers) leaves the draft dirty
    forever. */
export function applySaveResult(
  state: ScopeDraftState,
  { request, submitted, result }: ScopeSaveOutcome,
): ScopeDraftState {
  const adopted: Record<ScopeAxis, Set<string>> = {
    roles: new Set(result.enabled_role_groups),
    bands: new Set(result.enabled_seniority_bands),
    tracks: new Set(result.enabled_role_tracks),
    locations: new Set(result.enabled_location_groups),
    domains: new Set(result.enabled_domain_groups),
    excluded: new Set(result.excluded_domain_groups),
    excepted: new Set(result.excluded_location_groups),
  };
  const unedited: Partial<Record<ScopeAxis, Set<string>>> = {};
  for (const axis of SCOPE_AXES) {
    if (sameSet(state.draft[axis], submitted[axis])) unedited[axis] = adopted[axis];
  }
  // The answers and the switch follow the same rule: adopted into the draft
  // only where it has not moved.
  const answers = answersFrom(result.role_answers);
  const answersUnedited = sameAnswers(state.draft.answers, submitted.answers);
  const includeUnstatedLevel = result.include_unstated_level;
  const unstatedUnedited = state.draft.includeUnstatedLevel === submitted.includeUnstatedLevel;
  const { experience_stage: experienceStage, target_stage: targetStage } = request.body;
  const stages = experienceStage && targetStage
    ? { experienceStage, targetStage }
    : { experienceStage: state.saved.experienceStage, targetStage: state.saved.targetStage };
  return {
    ...state,
    saved: { ...state.saved, ...adopted, answers, includeUnstatedLevel, ...stages },
    draft: {
      ...state.draft,
      ...unedited,
      ...(answersUnedited ? { answers } : {}),
      ...(unstatedUnedited ? { includeUnstatedLevel } : {}),
    },
    lastInScopeChanged: result.in_scope_changed,
    lastOnBoard: result.on_board,
    lastPromotion: { promoted: result.promoted, pending: result.promotion_pending },
  };
}

/* An edit of the flat role or track lists (Welcome's checklists) makes the
   loaded answers stale: sent, they would win and drop the edit. So the draft
   stops carrying answers, and the server reads them off the edited lists. */
const FLAT_ROLE_EDIT = { answers: null } as const;

function toggled(selected: Set<string>, slug: string) {
  const next = new Set(selected);
  next.has(slug) ? next.delete(slug) : next.add(slug);
  return next;
}

export function scopeDraftReducer(state: ScopeDraftState, action: ScopeDraftAction): ScopeDraftState {
  switch (action.type) {
    case "catalog_loaded": {
      const { settings, domains: catalogDomains, initialSelection } = action;
      // The server always sends the answers: the saved ones, or with none
      // saved its own reading of the two flat lists.
      const savedAnswers = answersFrom(settings.role_answers);
      const blank = initialSelection === "empty";
      const next = {
        ...state,
        saved: {
          ...state.saved,
          roles: new Set(settings.enabled_role_groups),
          bands: new Set(settings.enabled_seniority_bands),
          tracks: new Set(settings.enabled_role_tracks),
          locations: new Set(settings.enabled_location_groups),
          domains: new Set(settings.enabled_domain_groups),
          excluded: new Set(settings.excluded_domain_groups),
          excepted: new Set(settings.excluded_location_groups),
          answers: savedAnswers,
          includeUnstatedLevel: settings.include_unstated_level,
        },
        draft: {
          ...state.draft,
          roles: new Set(blank ? [] : settings.enabled_role_groups),
          bands: new Set(blank ? [] : settings.enabled_seniority_bands),
          tracks: new Set(blank ? [] : settings.enabled_role_tracks),
          locations: new Set(blank ? [] : settings.enabled_location_groups),
          // Unlike the other axes, a fresh wizard draft starts with EVERY world
          // selected: the step is a narrowing, and "picked nothing" must mean
          // "lose nothing", not "track nothing".
          domains: new Set(blank ? catalogDomains : settings.enabled_domain_groups),
          excluded: new Set(blank ? [] : settings.excluded_domain_groups),
          excepted: new Set(blank ? [] : settings.excluded_location_groups),
          answers: blank ? null : savedAnswers,
          // A fresh wizard starts at the default, not unticked: an untouched
          // box must save what an untouched install already does.
          includeUnstatedLevel: blank ? INCLUDE_UNSTATED_LEVEL_DEFAULT : settings.include_unstated_level,
        },
      };
      return state.keepDraft ? { ...next, draft: state.draft } : next;
    }
    case "persona_loaded": {
      const { stages } = action;
      const placed = stages
        ? { experienceStage: stages.experience, targetStage: stages.target }
        : {};
      return {
        ...state,
        saved: { ...state.saved, ...placed },
        draft: state.keepDraft ? state.draft : { ...state.draft, ...placed },
      };
    }
    case "toggled":
      return {
        ...state,
        draft: {
          ...state.draft,
          [action.axis]: toggled(state.draft[action.axis], action.slug),
          ...(action.axis === "roles" || action.axis === "tracks" ? FLAT_ROLE_EDIT : {}),
        },
      };
    case "role_category_toggled": {
      const next = new Set(state.draft.roles);
      const allSelected = action.slugs.every((slug) => next.has(slug));
      for (const slug of action.slugs) allSelected ? next.delete(slug) : next.add(slug);
      return { ...state, draft: { ...state.draft, roles: next, ...FLAT_ROLE_EDIT } };
    }
    case "unstated_level_set":
      return { ...state, draft: { ...state.draft, includeUnstatedLevel: action.include } };
    case "locations_replaced":
      return { ...state, draft: { ...state.draft, locations: new Set(action.slugs) } };
    case "places_replaced":
      return {
        ...state,
        draft: { ...state.draft, locations: new Set(action.locations), excepted: new Set(action.excepted) },
      };
    case "roles_replaced":
      return { ...state, draft: { ...state.draft, roles: new Set(action.slugs), ...FLAT_ROLE_EDIT } };
    case "domains_replaced":
      return { ...state, draft: { ...state.draft, domains: new Set(action.slugs) } };
    case "excluded_replaced":
      return { ...state, draft: { ...state.draft, excluded: new Set(action.slugs) } };
    case "answers_replaced": {
      // The flat lists follow as the answers' projection, so every reader of
      // them (the level picker's gates, the Welcome surfaces) agrees.
      const { tracks, roles } = projectAnswers(action.answers, action.allFamilies);
      return { ...state, draft: { ...state.draft, answers: action.answers, tracks: new Set(tracks), roles: new Set(roles) } };
    }
    case "server_domains_adopted":
      /* The worlds list and veto the SERVER already persisted (accepting a
         suggestion). Saved takes them as they are; the draft takes only what
         the accept changed, on top of its own unsaved edits, so a World
         pick made before the accept survives it. With no edits the
         two sides meet and the draft stays clean: there is nothing to save. */
      {
        const moved = (before: Set<string>, after: Set<string>, draft: Set<string>) => {
          const next = new Set([...draft].filter((slug) => after.has(slug) || !before.has(slug)));
          for (const slug of after) if (!before.has(slug)) next.add(slug);
          return next;
        };
        const domains = new Set(action.slugs);
        const excluded = new Set(action.excluded);
        return {
          ...state,
          saved: { ...state.saved, domains, excluded },
          draft: {
            ...state.draft,
            domains: moved(state.saved.domains, domains, state.draft.domains),
            excluded: moved(state.saved.excluded, excluded, state.draft.excluded),
          },
        };
      }
    case "stage_placed": {
      const key = action.handle === "experience" ? "experienceStage" : "targetStage";
      if (state.draft[key] === action.slug) return state;
      return { ...state, draft: { ...state.draft, [key]: action.slug } };
    }
    case "bands_derived": {
      /* The seniority axis is ALWAYS the derived stage span, whatever else is
         saved. The dimmer band writes stages; this keeps the draft sets
         (impact, rail, save) in lockstep. Gated on anything else, moving the
         Level control would change no draft set, dirty nothing and offer no
         Save, while each save of an unrelated axis re-sent stale bands. With no
         band-level control anywhere, a divergence is never a choice, so nothing
         here can be overwriting one. */
      const { experienceStage, targetStage } = state.draft;
      if (!experienceStage || !targetStage) return state;
      const span = stageSpanOf(action.stageOrder, experienceStage, targetStage);
      if (!span) return state;
      const bands = new Set(span);
      if (sameSet(bands, state.draft.bands)) return state;
      return { ...state, draft: { ...state.draft, bands } };
    }
    case "save_confirmed":
      return applySaveResult(state, action.outcome);
  }
}

/* ---- What a scope change would cost, in postings ---- */

export interface ScopeImpact {
  total: number;
  complete: boolean;
}

export const NO_IMPACT: ScopeImpact = { total: 0, complete: false };

export function countSelectedScope(
  bandTrackCounts: Record<string, Record<string, number>>,
  selectedBands: Set<string>,
  selectedTracks: Set<string>,
) {
  return [...selectedBands].reduce(
    (sum, band) => sum + [...selectedTracks].reduce(
      (trackSum, track) => trackSum + (bandTrackCounts[band]?.[track] ?? 0),
      0,
    ),
    0,
  );
}

/** The roles a save would add (+) or remove (-), from each named family's
    band x track counts. Complete only when every family either side names can
    be priced that way (`joint_complete`). */
export function calculateScopeImpact(
  catalog: ScopeCatalog,
  savedRoles: Set<string>,
  savedBands: Set<string>,
  savedTracks: Set<string>,
  proposedRoles: Set<string>,
  proposedBands: Set<string>,
  proposedTracks: Set<string>,
): ScopeImpact {
  let total = 0;
  let complete = catalog.joint_counts_ready;
  for (const category of catalog.categories) {
    for (const group of category.groups) {
      const saved = savedRoles.has(group.slug);
      const proposed = proposedRoles.has(group.slug);
      if (!saved && !proposed) continue;
      if (!group.joint_complete) complete = false;
      if (proposed) total += countSelectedScope(group.band_track_counts, proposedBands, proposedTracks);
      if (saved) total -= countSelectedScope(group.band_track_counts, savedBands, savedTracks);
    }
  }
  return { total, complete };
}

/** Nothing has been read yet: no role at any level, nor one that states no
    level. Every count would be zero, so the walk says what was chosen instead
    of counting it. */
export function holdsNoRoles(catalog: { levels: readonly { count: number }[]; unstated_level_count?: number }): boolean {
  return (catalog.unstated_level_count ?? 0) === 0 && catalog.levels.every((level) => level.count === 0);
}
