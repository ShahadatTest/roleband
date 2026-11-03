import { errorText } from "../../api/errorText";
import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ScopeCatalog, ScopeLocation, ScopePreview, api } from "../../api";
import { useWriteQueue } from "../../hooks/useWriteQueue";
import { useMissionActions } from "../../context/MissionState";
import { forgetSetupProbe } from "../../routing/setupMode";
import {
  NO_IMPACT,
  allowedBandsOf,
  buildSaveRequest,
  calculateScopeImpact,
  holdsNoRoles,
  initialScopeDraftState,
  scopeDirtiness,
  scopeDraftReducer,
  stageOrderOf,
} from "./scopeDraftModel";
import type { SavePromotion, ScopeDraftState, ScopeImpact, ScopeSaveRequest, ScopeSelection } from "./scopeDraftModel";
import { keepProfileDraft, readProfileDraft } from "./profileDraftStash";
import { forgetSetupStash, keepSetupStash, readSetupStash } from "./setupStash";
import { buildScopeIndex, countUnderScope } from "./scopeCells";
import type { ScopeAxesSelection, ScopeIndex } from "./scopeCells";
import type { Answers } from "./walk/walkModel";
import { NO_PROGRESS, progressOf, type WalkProgress } from "./walk/walkProgress";
import {
  profileUseScopeDraftCouldnTCountRolesAt,
  profileUseScopeDraftCouldnTLoadYourRadar,
  profileUseScopeDraftCouldnTSaveYourRadar,
  profileUseScopeDraftRefreshingRoleCountsThisReads,
  profileUseScopeDraftThatRefreshWasDeferredBecause,
} from "../../copy/gen/profile";

/* Draft state for the tracking scope: the five axes, plus the two level
   markers on the persona (where the person is, where they aim), whose span is
   the seniority axis. The walk, the persona rail and the onboarding wizard
   all drive this one state machine.

   What the state BECOMES is `scopeDraftModel.ts` — one reducer over one
   {saved, draft} value, and the save request beside it. What is left here is the
   part that needs React: the two loads, the save and refresh requests, the
   transient flags nobody saves, and the context. */

export interface ScopeDraft {
  catalog: ScopeCatalog | null;
  error: string | null;
  saving: boolean;
  /** Where the "you are here" marker sits. */
  experienceStage: string | null;
  /** Where the stretched glow edge ends (either direction). */
  targetStage: string | null;
  setExperienceStage: (slug: string) => void;
  setTargetStage: (slug: string) => void;
  refreshing: boolean;
  refreshMessage: string | null;
  selectedRoles: Set<string>;
  selectedBands: Set<string>;
  selectedTracks: Set<string>;
  selectedLocations: Set<string>;
  /** The worlds axis. All-selected = no narrowing (the axis's neutral state);
      unclassified rows always stay in scope regardless (backend fail-open). */
  selectedDomains: Set<string>;
  /** Subjects the person is not interested in: a veto (see scopeDraftModel). */
  selectedExcluded: Set<string>;
  /** Places excepted inside the included ones. */
  selectedExcepted: Set<string>;
  /** Which roles of each kind; null until the walk sets them. */
  selectedAnswers: Answers | null;
  /** Whether roles whose level isn't stated are on the radar. */
  includeUnstatedLevel: boolean;
  /** The scope joint: the one shape that can be intersected.
      Counts beside a checkbox come from here, so "on your radar" means every
      axis, not the three the marginals happened to cover. `ready` false =
      no company's scan has produced cells yet; fall back to the
      pre-gate marginals and say so. */
  scopeIndex: ScopeIndex;
  /** Whether the walk shows role counts. Never in first-run setup: the first
      scan starts as setup opens, so its counts are partial, mostly zero, and
      say nothing about the answers. Nor before anything is read. */
  countsShown: boolean;
  /** The live draft, which is already the five sets the gate reads. */
  scopeSelection: ScopeAxesSelection;
  /** Seniority tiers the selected tracks can occupy (union of their gates; all
      tiers when no track is selected). The dimmer disables the rest. */
  allowedBands: Set<string>;
  savedRoles: Set<string>;
  savedBands: Set<string>;
  savedTracks: Set<string>;
  savedLocations: Set<string>;
  savedDomains: Set<string>;
  savedExcluded: Set<string>;
  dirty: boolean;
  /** The locations axis changed. Joint counts are location-blind, so the
      impact estimate cannot price this in — surface a caveat instead. */
  locationsDirty: boolean;
  /** The worlds axis changed — domain-blind joint counts, same caveat. */
  domainsDirty: boolean;
  /** Roles/bands/tracks changed — the axes the joint-count estimate covers. */
  estimableDirty: boolean;
  impact: ScopeImpact;
  /** Roles the save would add (+) or remove (-), from the same joint the rail
      counts: every axis and the veto, not the marginals `impact` reads. Null
      when the joint is not ready or a place in the draft is not counted yet. */
  saveDelta: number | null;
  /** The walk's funnel under the draft. Counted here once per change and read
      by every screen that shows it (the rail, the Summary, World), so a
      draft change costs one count however many of them are mounted. */
  progress: WalkProgress;
  /** A city the draft names is being counted: the counts are re-read with
      it. False once priced, or when the read could not
      price it, and the screen then says it is counted after the save. */
  countingPlaces: boolean;
  /** The body a save would send now (JSON), "" while the draft is clean. What
      `useSavePreview` asks the server about. */
  saveBody: string;
  /** `in_scope_changed` from the last save response: ground truth for how many
      known jobs actually entered/left scope. Null until a save happens. */
  lastInScopeChanged: number | null;
  /** What the Board holds after the last save. */
  lastOnBoard: number | null;
  /** What the last save added from earlier scans. */
  lastPromotion: SavePromotion | null;
  toggleRole: (slug: string) => void;
  toggleBand: (slug: string) => void;
  toggleTrack: (slug: string) => void;
  toggleLocation: (slug: string) => void;
  toggleDomain: (slug: string) => void;
  /** One-click return to the neutral state (every world tracked). */
  selectAllDomains: () => void;
  /** Adopt the worlds list and veto the SERVER already persisted (suggestion
      accept): saved moves to them, the draft by what the accept changed, so
      unsaved edits survive and an untouched draft stays clean. */
  applyServerDomains: (slugs: string[], excluded: string[]) => void;
  /** Bulk location edit (clear all, clear a region and its descendants, convert
      an umbrella into explicit child picks). One write, so a many-market scope
      is emptied in one click rather than one per market, and so a multi-slug
      edit lands as a single draft state, not N racing toggles. */
  replaceLocations: (slugs: string[]) => void;
  /** The Where step's edit: the included places and the places excepted
      inside them, written together. */
  replacePlaces: (locations: string[], excepted: string[]) => void;
  /** Places the location search found that the catalog does not list (a
      city): added to `catalog.locations` so they draw,
      nest and read back like any place. Never saved by itself. */
  learnPlaces: (places: ScopeLocation[]) => void;
  /** Bulk role edit: the walk's "which roles exactly" step writes a whole
      family set per answer, the way a location reach writes a whole branch. */
  replaceRoles: (slugs: string[]) => void;
  /** Bulk worlds edit: the modifier list is the source of the set, so it
      writes the set whole rather than toggling toward it. */
  replaceDomains: (slugs: string[]) => void;
  /** The "not interested in" list, written whole like the worlds set. */
  replaceExcluded: (slugs: string[]) => void;
  /** Replace the answers whole; the flat role and track lists follow. */
  replaceAnswers: (answers: Answers) => void;
  setIncludeUnstatedLevel: (include: boolean) => void;
  toggleRoleCategory: (slugs: string[]) => void;
  /** Re-requests the scope catalog after a failed load. */
  reloadCatalog: () => void;
  /** Resolves true when the save persisted (false on error). */
  save: () => Promise<boolean>;
  refreshInventory: () => Promise<void>;
}

const ScopeDraftContext = createContext<ScopeDraft | null>(null);

const RECOUNT_EVERY_MS = 20_000;
const RECOUNT_READS = 15;
/** How long the draft must hold still before the save preview is asked for. */
const PREVIEW_DELAY_MS = 500;
/** How long the draft's cities must hold still before the counts are re-read
    with them: typing a search adds one place, not one read per keystroke. */
const CITY_READ_DELAY_MS = 400;

/** Cities one selection names, included or excepted. */
function citiesOf(selection: { locations: Set<string>; excepted: Set<string> }): string[] {
  return [...new Set([...selection.locations, ...selection.excepted])].filter((slug) => slug.startsWith("city_")).sort();
}

/* The catalog, asked early by the screen the walk follows (the welcome): the
   walk's first load takes it while it is fresh, so setup opens on its first
   question without waiting for it. Taken once; a stale one is asked again. */
const PRIMED_FOR_MS = 30_000;
let primed: { at: number; catalog: Promise<ScopeCatalog> } | null = null;

export function primeScopeCatalog(): void {
  if (primed && Date.now() - primed.at <= PRIMED_FOR_MS) return;
  const catalog = api.scopeCatalog([]);
  // Nobody may take it: its failure is the walk's to report, not the console's.
  catalog.catch(() => undefined);
  primed = { at: Date.now(), catalog };
}

function catalogFor(cities: readonly string[]): Promise<ScopeCatalog> {
  const taken = primed;
  primed = null;
  return taken && cities.length === 0 && Date.now() - taken.at <= PRIMED_FOR_MS ? taken.catalog : api.scopeCatalog(cities);
}

export function ScopeDraftProvider({
  children,
  initialSelection = "saved",
}: {
  children: ReactNode;
  /** Profile edits the persisted scope; first-run onboarding starts blank. */
  initialSelection?: "saved" | "empty";
}) {
  const { refreshStats } = useMissionActions();
  // Pure: reads the stash only (Strict Mode may call an initializer twice); the
  // mount effect below clears Profile's. Setup's answers come back from the
  // tab's own stash (./setupStash).
  const [state, dispatch] = useReducer(scopeDraftReducer, initialSelection, (mode): ScopeDraftState => {
    const carried = mode === "saved" ? readProfileDraft() : readSetupStash().draft ?? null;
    return carried ? { ...initialScopeDraftState, draft: carried, keepDraft: true } : initialScopeDraftState;
  });
  const { saved, draft, lastInScopeChanged, lastOnBoard, lastPromotion } = state;
  const [catalog, setCatalog] = useState<ScopeCatalog | null>(null);
  /** The cities the loaded joint can price (`scope_cells.cities`). */
  const pricedCities = useRef<Set<string>>(new Set());
  pricedCities.current = new Set(catalog?.scope_cells?.cities ?? []);
  /* Cities the draft names that the saved scope does not. The server prices a
     saved city on every read and these only when a read names them, so every
     catalog read below passes them (a ref: the reads keep one identity). */
  const unsavedCities = useMemo(() => {
    const known = new Set(citiesOf(saved));
    return citiesOf(draft).filter((slug) => !known.has(slug));
  }, [draft, saved]);
  const draftCities = useRef<string[]>(unsavedCities);
  draftCities.current = unsavedCities;
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  /* The catalog load catches its failure into `error`. Bumping this re-runs
     the effect below, which is the whole retry, so reloading the page is never
     the only way out. */
  const [catalogAttempt, setCatalogAttempt] = useState(0);

  useEffect(() => {
    if (!refreshMessage) return;
    const timeout = window.setTimeout(() => setRefreshMessage(null), 15_000);
    return () => window.clearTimeout(timeout);
  }, [refreshMessage]);

  useEffect(() => {
    let cancelled = false;
    catalogFor(draftCities.current)
      .then((next) => {
        if (cancelled) return;
        setCatalog(next);
        dispatch({
          type: "catalog_loaded",
          settings: next.settings,
          domains: (next.domains ?? []).map((domain) => domain.slug),
          initialSelection,
        });
      })
      .catch((reason) => {
        if (!cancelled) setError(errorText(reason, profileUseScopeDraftCouldnTLoadYourRadar()));
      });
    return () => { cancelled = true; };
  }, [initialSelection, catalogAttempt]);

  useEffect(() => {
    if (initialSelection === "empty") return;
    let cancelled = false;
    api.profile()
      .then((persona) => {
        if (cancelled) return;
        dispatch({
          type: "persona_loaded",
          stages: persona.profile
            ? {
              experience: persona.profile.experience_stage,
              target: persona.profile.target_stage,
            }
            : null,
        });
      })
      .catch(() => { /* no persona: the levels start unplaced */ });
    return () => { cancelled = true; };
  }, [initialSelection]);

  // The joint, decoded once per catalog load rather than per keystroke: the
  // interning is a wire format, and every count below scans plain cells.
  const scopeIndex = useMemo(() => buildScopeIndex(catalog?.scope_cells), [catalog]);
  const countsShown = initialSelection === "saved" && catalog !== null && !holdsNoRoles(catalog);

  const stageOrder = useMemo(() => stageOrderOf(catalog?.levels ?? null), [catalog]);
  const allowedBands = useMemo(
    () => allowedBandsOf(catalog?.tracks ?? null, draft.tracks, stageOrder),
    [catalog, draft.tracks, stageOrder],
  );

  // A track change that shrinks the allowed range never rewrites a placed
  // marker: the dimmer draws it inside the range, and the gate applies each
  // kind's own range.

  // The seniority axis is always the derived stage span.
  useEffect(() => {
    if (!draft.experienceStage || !draft.targetStage) return;
    dispatch({ type: "bands_derived", stageOrder });
  }, [stageOrder, draft.experienceStage, draft.targetStage]);

  const { dirty, locationsDirty, domainsDirty, estimableDirty } = useMemo(
    () => scopeDirtiness(state),
    [state],
  );

  // Read at unmount: the latest draft and whether it holds anything unsaved.
  const leaving = useRef({ draft: state.draft, dirty });
  leaving.current = { draft: state.draft, dirty };
  useEffect(() => {
    // Profile only (docs in ./profileDraftStash): first-run onboarding starts
    // blank by design. Cleared on mount, written back on unmount while dirty.
    if (initialSelection !== "saved") return;
    keepProfileDraft(null);
    return () => keepProfileDraft(leaving.current.dirty ? leaving.current.draft : null);
  }, [initialSelection]);

  /* Setup keeps each answer for the tab as it is given, once the catalog has
     filled the blank draft (before it, "every world" is still an empty set),
     and stops once a save has taken them. */
  const savedOnce = useRef(false);
  const setupCatalogLoaded = initialSelection === "empty" && catalog !== null;
  useEffect(() => {
    if (setupCatalogLoaded && !savedOnce.current) keepSetupStash({ draft });
  }, [setupCatalogLoaded, draft]);

  const impact = useMemo(
    () => (catalog
      ? calculateScopeImpact(
        catalog, saved.roles, saved.bands, saved.tracks,
        draft.roles, draft.bands, draft.tracks,
      )
      : NO_IMPACT),
    [catalog, saved.roles, saved.bands, saved.tracks, draft.roles, draft.bands, draft.tracks],
  );

  /* Each kind's own level range (`allowed_bands`), the half of an answer the
     gate holds besides its families. Carried on every selection the screens
     count with. */
  const trackBands = useMemo(
    // A kind with no declared range is ungated, as on the server
    // (`allowed_bands_for`): an empty set here would admit no level at all.
    () => new Map((catalog?.tracks ?? [])
      .filter((track) => (track.allowed_bands ?? []).length > 0)
      .map((track) => [track.slug, new Set(track.allowed_bands)] as const)),
    [catalog],
  );
  /* Each place's parent, for the place exceptions: the gate
     walks up from a posting's most specific place. */
  const placeParents = useMemo(
    () => new Map((catalog?.locations ?? [])
      .filter((location) => location.parent)
      .map((location) => [location.slug, location.parent as string] as const)),
    [catalog],
  );
  const scopeSelection = useMemo(() => ({ ...draft, trackBands, placeParents }), [draft, trackBands, placeParents]);

  /* A city the draft names and the joint does not price is counted by one
     re-read naming it, once the draft holds still. `doneKey` is the last set
     of cities a read was asked for: set when it answers, so a city the read
     could not price is not asked for again in a loop, and the screen falls
     back to "counted after you save". */
  const unpricedKey = useMemo(() => {
    const priced = new Set(catalog?.scope_cells?.cities ?? []);
    return unsavedCities.filter((slug) => !priced.has(slug)).join(",");
  }, [catalog, unsavedCities]);
  const [doneKey, setDoneKey] = useState("");
  const catalogLoaded = catalog !== null;
  /* The newest city read wins: an older one answering late would put back a
     catalog that prices fewer cities. */
  const cityRead = useRef(0);
  useEffect(() => {
    if (!catalogLoaded || unpricedKey === "" || unpricedKey === doneKey) return;
    const timer = window.setTimeout(() => {
      const attempt = (cityRead.current += 1);
      api.scopeCatalog(draftCities.current)
        .then((next) => { if (attempt === cityRead.current) setCatalog((prev) => withLearned(next, prev)); })
        .catch(() => { /* counted after the save instead */ })
        .finally(() => { if (attempt === cityRead.current) setDoneKey(unpricedKey); });
    }, CITY_READ_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [catalogLoaded, unpricedKey, doneKey]);
  const countingPlaces = unpricedKey !== "" && unpricedKey !== doneKey;

  /* The body a save would send now, "" while the draft is clean: what
     `useSavePreview` asks the server about. */
  const saveBody = useMemo(
    () => (dirty ? JSON.stringify(buildSaveRequest(state).body) : ""),
    [dirty, state],
  );

  const saveDelta = useMemo(() => {
    if (!scopeIndex.ready) return null;
    const priced = new Set(catalog?.scope_cells?.cities ?? []);
    if (citiesOf(draft).some((slug) => !priced.has(slug))) return null;
    return countUnderScope(scopeIndex, { ...draft, trackBands, placeParents })
      - countUnderScope(scopeIndex, { ...saved, trackBands, placeParents });
  }, [scopeIndex, catalog, draft, saved, trackBands, placeParents]);

  const progress = useMemo(
    () => (catalog ? progressOf(scopeIndex, catalog, scopeSelection, countingPlaces) : NO_PROGRESS),
    [catalog, scopeIndex, scopeSelection, countingPlaces],
  );

  /* Writes are serialized, not merely guarded. Every save PUTs the WHOLE
     scope, so two requests in the air means the install keeps whichever row the
     server wrote last — which is not necessarily the later write. A
     stale-response guard cannot reach that: it decides what the screen adopts,
     never what the database keeps. The queue makes submission order the
     persistence order, and because ordering is then total there is no
     out-of-order response left for a generation ref to catch. The shipped save
     buttons disable on `saving`, which is a second line and not a first: that
     `disabled` only exists once the provider has re-rendered, and this
     provider's re-render draws the whole role catalog.

     The queue itself is `hooks/useWriteQueue`, shared with the
     other screens that write. This provider uses one half of it: `exclusive` with
     no keys, because the subject is the whole radar and there is one of it.
     The chain stores a SETTLED tail, so a throw from outside the try block
     cannot poison it and leave every later save silently undispatched with
     `saving` stuck true.

     `refreshInventory` is not in this queue. It starts server-side work rather
     than writing the draft, the server already excludes a second one, and the
     answer to "is a refresh running" is the NEWEST attempt's — so that one is a
     generation guard, which is the right shape for it. */
  // Destructured: the verb must stay stable while `saving` moves, or `save`
  // takes a new identity on every write and any consumer listing it in a
  // dependency array spins.
  const { exclusive: queueSave, writing: saving } = useWriteQueue("scope-draft");
  const refreshAttempt = useRef(0);
  /* A started count runs server-side with no completion signal, so the counts
     are re-read while it runs: every RECOUNT_EVERY_MS, at most RECOUNT_READS
     times, stopping once every followed company is counted. Only the catalog
     is replaced, never the draft: what the person is answering stays put. */
  const recount = useRef<number | null>(null);
  const stopRecount = useCallback(() => {
    if (recount.current !== null) window.clearInterval(recount.current);
    recount.current = null;
  }, []);
  useEffect(() => stopRecount, [stopRecount]);

  const submitScope = useCallback(async (request: ScopeSaveRequest, submitted: ScopeSelection) => {
    // Cleared as the write STARTS, not as it is queued: a failure belongs on
    // screen until something newer is actually being attempted.
    setError(null);
    try {
      const result = await api.saveSettings(request.body);
      dispatch({ type: "save_confirmed", outcome: { request, submitted, result } });
      // A saved scope configures the install: "set up later" is over, and
      // setup's kept answers are saved.
      savedOnce.current = true;
      forgetSetupStash();
      forgetSetupProbe();
      refreshStats();
      // A city the joint cannot price yet (it carries only tracked cities)
      // is priced once it is saved: re-read the counts, never the draft.
      if (citiesOf(submitted).some((slug) => !pricedCities.current.has(slug))) {
        api.scopeCatalog(draftCities.current)
          .then((next) => setCatalog((prev) => withLearned(next, prev)))
          .catch(() => {});
      }
      return true;
    } catch (reason) {
      setError(errorText(reason, profileUseScopeDraftCouldnTSaveYourRadar()));
      return false;
    }
  }, [refreshStats]);

  const save = useCallback(() => {
    // Captured at the click. A queued write sends what the user had when they
    // asked for it, and `submitted` is what tells the response which axes it is
    // still entitled to speak for.
    const request = buildSaveRequest(state);
    const submitted = state.draft;
    // `saving` is then the QUEUE's, not one request's: it stays true until the
    // last queued write has drained, or the button re-arms over work that is
    // still outstanding. No keys — the subject is the whole radar, and there
    // is one of it.
    return queueSave([], () => submitScope(request, submitted));
  }, [state, submitScope, queueSave]);

  /* The places the person is answering with, saved or not: a count started
     from the walk asks the sources for them. A ref, so the verb
     keeps one identity while the draft moves. */
  const draftLocations = useRef(draft.locations);
  draftLocations.current = draft.locations;
  const refreshInventory = useCallback(async () => {
    const attempt = (refreshAttempt.current += 1);
    setRefreshing(true);
    setRefreshMessage(null);
    setError(null);
    try {
      const result = await api.refreshScopeCatalog([...draftLocations.current]);
      if (attempt !== refreshAttempt.current) return;
      if (result.status === "started") {
        setRefreshMessage(profileUseScopeDraftRefreshingRoleCountsThisReads());
        stopRecount();
        let reads = 0;
        recount.current = window.setInterval(() => {
          reads += 1;
          if (reads >= RECOUNT_READS) stopRecount();
          api.scopeCatalog(draftCities.current)
            .then((next) => {
              setCatalog((prev) => withLearned(next, prev));
              const cells = next.scope_cells;
              if (cells?.ready && !(cells.stale_companies ?? []).length && !(cells.missing_companies ?? []).length) stopRecount();
            })
            .catch(() => { /* the next read tries again */ });
        }, RECOUNT_EVERY_MS);
      } else {
        setRefreshMessage(profileUseScopeDraftThatRefreshWasDeferredBecause());
      }
    } catch (reason) {
      if (attempt !== refreshAttempt.current) return;
      setError(errorText(reason, profileUseScopeDraftCouldnTCountRolesAt()));
    } finally {
      if (attempt === refreshAttempt.current) setRefreshing(false);
    }
  }, [stopRecount]);

  /* Stable verbs, then a memoized value. A value rebuilt on every render, with
     fresh arrow functions for members, would re-render every consumer of this
     context each time, and the first `useCallback` that lists `save` in its
     deps would loop forever. */
  const setExperienceStage = useCallback(
    (slug: string) => dispatch({ type: "stage_placed", handle: "experience", slug }),
    [],
  );
  const setTargetStage = useCallback(
    (slug: string) => dispatch({ type: "stage_placed", handle: "target", slug }),
    [],
  );
  const toggleRole = useCallback((slug: string) => dispatch({ type: "toggled", axis: "roles", slug }), []);
  const toggleBand = useCallback((slug: string) => dispatch({ type: "toggled", axis: "bands", slug }), []);
  const toggleTrack = useCallback((slug: string) => dispatch({ type: "toggled", axis: "tracks", slug }), []);
  const toggleLocation = useCallback((slug: string) => dispatch({ type: "toggled", axis: "locations", slug }), []);
  const toggleDomain = useCallback((slug: string) => dispatch({ type: "toggled", axis: "domains", slug }), []);
  const selectAllDomains = useCallback(
    () => dispatch({ type: "domains_replaced", slugs: (catalog?.domains ?? []).map((domain) => domain.slug) }),
    [catalog],
  );
  const applyServerDomains = useCallback(
    (slugs: string[], excluded: string[]) => dispatch({ type: "server_domains_adopted", slugs, excluded }),
    [],
  );
  const learnPlaces = useCallback((places: ScopeLocation[]) => {
    setCatalog((prev) => {
      if (!prev) return prev;
      const known = new Set((prev.locations ?? []).map((location) => location.slug));
      const fresh = places.filter((place) => !known.has(place.slug));
      return fresh.length ? { ...prev, locations: [...(prev.locations ?? []), ...fresh] } : prev;
    });
  }, []);
  const replaceLocations = useCallback(
    (slugs: string[]) => dispatch({ type: "locations_replaced", slugs }),
    [],
  );
  const replacePlaces = useCallback(
    (locations: string[], excepted: string[]) => dispatch({ type: "places_replaced", locations, excepted }),
    [],
  );
  const replaceRoles = useCallback(
    (slugs: string[]) => dispatch({ type: "roles_replaced", slugs }),
    [],
  );
  const replaceDomains = useCallback(
    (slugs: string[]) => dispatch({ type: "domains_replaced", slugs }),
    [],
  );
  const allFamilies = useMemo(
    () => (catalog?.categories ?? []).flatMap((category) => category.groups.map((group) => group.slug)),
    [catalog],
  );
  const replaceAnswers = useCallback(
    (answers: Answers) => dispatch({ type: "answers_replaced", answers, allFamilies }),
    [allFamilies],
  );
  const replaceExcluded = useCallback(
    (slugs: string[]) => dispatch({ type: "excluded_replaced", slugs }),
    [],
  );
  const toggleRoleCategory = useCallback(
    (slugs: string[]) => dispatch({ type: "role_category_toggled", slugs }),
    [],
  );
  const setIncludeUnstatedLevel = useCallback(
    (include: boolean) => dispatch({ type: "unstated_level_set", include }),
    [],
  );
  const reloadCatalog = useCallback(() => {
    setError(null);
    setCatalogAttempt((n) => n + 1);
  }, []);

  const value = useMemo<ScopeDraft>(
    () => ({
      catalog, error, saving, refreshing, refreshMessage,
      experienceStage: draft.experienceStage,
      targetStage: draft.targetStage,
      setExperienceStage,
      setTargetStage,
      selectedRoles: draft.roles,
      selectedBands: draft.bands,
      selectedTracks: draft.tracks,
      selectedLocations: draft.locations,
      selectedDomains: draft.domains,
      selectedExcluded: draft.excluded,
      selectedExcepted: draft.excepted,
      selectedAnswers: draft.answers,
      includeUnstatedLevel: draft.includeUnstatedLevel,
      scopeIndex,
      countsShown,
      scopeSelection,
      allowedBands,
      savedRoles: saved.roles,
      savedBands: saved.bands,
      savedTracks: saved.tracks,
      savedLocations: saved.locations,
      savedDomains: saved.domains,
      savedExcluded: saved.excluded,
      dirty, locationsDirty, domainsDirty, estimableDirty, impact, saveDelta, progress, countingPlaces, saveBody,
      lastInScopeChanged, lastOnBoard, lastPromotion,
      toggleRole, toggleBand, toggleTrack, toggleLocation, toggleDomain,
      selectAllDomains, applyServerDomains, replaceLocations, replacePlaces, learnPlaces, replaceRoles, replaceDomains, replaceExcluded, replaceAnswers,
      setIncludeUnstatedLevel,
      toggleRoleCategory,
      reloadCatalog,
      save,
      refreshInventory,
    }),
    [
      catalog, error, saving, refreshing, refreshMessage,
      draft, setExperienceStage, setTargetStage,
      allowedBands, saved, scopeIndex, countsShown, scopeSelection,
      dirty, locationsDirty, domainsDirty, estimableDirty, impact, saveDelta, progress, countingPlaces, saveBody,
      lastInScopeChanged, lastOnBoard, lastPromotion,
      toggleRole, toggleBand, toggleTrack, toggleLocation, toggleDomain,
      selectAllDomains, applyServerDomains, replaceLocations, replacePlaces, learnPlaces, replaceRoles, replaceDomains, replaceExcluded, replaceAnswers,
      setIncludeUnstatedLevel,
      toggleRoleCategory,
      reloadCatalog, save, refreshInventory,
    ],
  );

  return createElement(ScopeDraftContext.Provider, { value }, children);
}

export function useScopeDraft(): ScopeDraft {
  const value = useContext(ScopeDraftContext);
  if (!value) throw new Error("useScopeDraft must be used within ScopeDraftProvider");
  return value;
}

/** What saving the draft would do to the Board, from the server: the save's
    own writes, rolled back. Asked for once the draft
    holds still, by the one screen that shows it, so a screen sharing the
    draft never sends a dry-run save it does not read. Keyed by the request
    body: an answer for an older draft is never shown against a newer one.
    Null while the draft is clean, while the first answer is on its way, or
    when it failed. */
export function useSavePreview(): ScopePreview | null {
  const { saveBody } = useScopeDraft();
  const [preview, setPreview] = useState<{ body: string; answer: ScopePreview } | null>(null);
  useEffect(() => {
    if (saveBody === "") return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      api.previewScope(JSON.parse(saveBody))
        .then((answer) => { if (!cancelled) setPreview({ body: saveBody, answer }); })
        .catch(() => { /* the review keeps its radar delta */ });
    }, PREVIEW_DELAY_MS);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [saveBody]);
  return preview !== null && preview.body === saveBody ? preview.answer : null;
}


/** A re-read catalog, keeping the places the search taught the old one that
    the server does not list yet (an unsaved city). */
function withLearned(next: ScopeCatalog, prev: ScopeCatalog | null): ScopeCatalog {
  const listed = new Set((next.locations ?? []).map((location) => location.slug));
  const learned = (prev?.locations ?? []).filter((location) => !listed.has(location.slug));
  return learned.length ? { ...next, locations: [...(next.locations ?? []), ...learned] } : next;
}
