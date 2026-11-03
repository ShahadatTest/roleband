import { describe, expect, it } from "vitest";
import type { ScopeAxes, ScopeSettingsSaveResult } from "../../api";
import { INCLUDE_UNSTATED_LEVEL_DEFAULT } from "./scopeCells";
import {
  allowedBandsOf,
  applySaveResult,
  buildSaveRequest,
  holdsNoRoles,
  initialScopeDraftState,
  scopeDirtiness,
  scopeDraftReducer,
  stageOrderOf,
  stageSpanOf,
  type ScopeDraftAction,
  type ScopeDraftState,
  type ScopeSaveOutcome,
  type ScopeSelection,
} from "./scopeDraftModel";

/* The scope draft's transitions, with no provider around them.
 *
 * `useScopeDraft.test.tsx` renders the provider and proves the one save path
 * sends the right body. What it cannot reach cheaply is the rest of the
 * machine: what a catalog load seeds, what a persona load decides, and what a
 * save response is allowed to adopt. Those are the assertions here.
 */

const selection = (over: Partial<ScopeSelection> = {}): ScopeSelection => ({
  roles: new Set<string>(),
  bands: new Set<string>(),
  tracks: new Set<string>(),
  locations: new Set<string>(),
  domains: new Set<string>(),
  excluded: new Set<string>(),
  excepted: new Set<string>(),
  answers: null,
  includeUnstatedLevel: INCLUDE_UNSTATED_LEVEL_DEFAULT,
  experienceStage: null,
  targetStage: null,
  ...over,
});

const draftState = (over: Partial<ScopeDraftState> = {}): ScopeDraftState => ({
  ...initialScopeDraftState,
  ...over,
});

/** The catalog's settings as the server sends them: every axis, and the
    answers it reads off the flat lists when none are saved. */
const SETTINGS: ScopeAxes = {
  enabled_role_groups: ["software_engineering"],
  enabled_seniority_bands: ["senior", "staff"],
  enabled_role_tracks: ["technical"],
  enabled_location_groups: ["uk"],
  enabled_domain_groups: ["ai_ml"],
  excluded_domain_groups: [],
  excluded_location_groups: [],
  include_unstated_level: true,
  role_answers: [{ track: "technical", roles: ["software_engineering"] }],
};

/** A save's answer as the server sends it: the axes as saved, and the counts. */
const SAVED_SCOPE: ScopeSettingsSaveResult = {
  enabled_role_groups: ["software_engineering", "data"],
  enabled_seniority_bands: ["senior", "staff"],
  enabled_role_tracks: ["technical"],
  enabled_location_groups: ["uk"],
  enabled_domain_groups: ["ai_ml"],
  excluded_domain_groups: [],
  excluded_location_groups: [],
  include_unstated_level: true,
  role_answers: [{ track: "technical", roles: ["data", "software_engineering"] }],
  in_scope_changed: 3,
  on_board: 0,
  promoted: 0,
  promotion_pending: false,
};

/** Whether two types are the same both ways, for compile-time checks. */
type Equals<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type CatalogSettings = Extract<ScopeDraftAction, { type: "catalog_loaded" }>["settings"];
type SaveResult = ScopeSaveOutcome["result"];

describe("the wire types the model reads", () => {
  /* Checked by `tsc -b`, not by the test runner: the model takes the
     generated catalog settings and save response as they are, so a field the
     server drops or renames fails the compile instead of reading as an empty
     or absent axis at run time. */
  it("are the generated catalog settings and save response, not a widened copy", () => {
    const exact: [Equals<CatalogSettings, ScopeAxes>, Equals<SaveResult, ScopeSettingsSaveResult>] = [true, true];
    expect(exact).toEqual([true, true]);
  });

  it("refuse a payload with a server field dropped or renamed", () => {
    const asSettings = (value: CatalogSettings) => value;
    const asResult = (value: SaveResult) => value;
    // The full payloads are accepted, so the refusals below are not vacuous.
    expect(asSettings(SETTINGS)).toBe(SETTINGS);
    expect(asResult(SAVED_SCOPE)).toBe(SAVED_SCOPE);

    const { role_answers: _answers, ...withoutAnswers } = SETTINGS;
    const { enabled_domain_groups: worlds, ...withoutWorlds } = SETTINGS;
    const renamedWorlds = { ...withoutWorlds, enabled_world_groups: worlds };
    const { promoted: _promoted, ...withoutPromoted } = SAVED_SCOPE;
    const { include_unstated_level: unstated, ...withoutSwitch } = SAVED_SCOPE;
    const renamedSwitch = { ...withoutSwitch, include_unknown_level: unstated };

    // @ts-expect-error catalog settings without the role answers
    asSettings(withoutAnswers);
    // @ts-expect-error catalog settings whose worlds axis is renamed
    asSettings(renamedWorlds);
    // @ts-expect-error a save answer without the promoted count
    asResult(withoutPromoted);
    // @ts-expect-error a save answer whose level switch is renamed
    asResult(renamedSwitch);
  });
});

const LEVELS = [
  { slug: "senior", order: 3 },
  { slug: "entry", order: 1 },
  { slug: "staff", order: 4 },
  { slug: "mid", order: 2 },
];
const STAGE_ORDER = ["entry", "mid", "senior", "staff"];

describe("the scope draft's one save", () => {
  it("sends one request, to /api/settings, with the axes and both level markers", () => {
    const draft = selection({
      roles: new Set(["software_engineering"]),
      bands: new Set(["senior", "staff"]),
      tracks: new Set(["technical"]),
      locations: new Set(["uk"]),
      domains: new Set(["ai_ml"]),
      // Unticked, against the default: the body carries the person's choice.
      includeUnstatedLevel: false,
      experienceStage: "senior",
      targetStage: "staff",
    });

    const request = buildSaveRequest(draftState({ draft }));
    expect(request.endpoint).toBe("settings");
    expect(request.body).toEqual({
      enabled_role_groups: ["software_engineering"],
      enabled_seniority_bands: ["senior", "staff"],
      enabled_role_tracks: ["technical"],
      enabled_location_groups: ["uk"],
      enabled_domain_groups: ["ai_ml"],
      excluded_domain_groups: [],
      excluded_location_groups: [],
      include_unstated_level: false,
      experience_stage: "senior",
      target_stage: "staff",
    });
  });


  it("will not send half a pair of level markers", () => {
    /* The backend rejects half a pair: the two markers travel together or
       not at all. */
    const half = selection({ experienceStage: "senior", targetStage: null });
    const body = buildSaveRequest(draftState({ draft: half })).body;
    expect(body).not.toHaveProperty("experience_stage");
    expect(body).not.toHaveProperty("target_stage");
  });



  it("never carries the aim sentence", () => {
    /* Settings > Intelligence owns the aim sentence; the server keeps it when a
       scope save omits it. Sending anything here (even "") would overwrite
       what was saved there, so the key must be absent, not blank. */
    const draft = selection({ experienceStage: "senior", targetStage: "staff" });
    expect(buildSaveRequest(draftState({ draft })).body).not.toHaveProperty("intent_statement");
  });

});

describe("what a save response may adopt", () => {
  const afterSave = (state: ScopeDraftState, over: Partial<ScopeSaveOutcome> = {}) =>
    applySaveResult(state, {
      request: buildSaveRequest(state),
      submitted: state.draft,
      result: SAVED_SCOPE,
      ...over,
    });



  it("adopts the server's axes on both sides, so the draft lands clean", () => {
    const state = draftState({
      draft: selection({ roles: new Set(["software_engineering"]) }),
    });
    const next = afterSave(state);
    expect([...next.saved.roles]).toEqual(["software_engineering", "data"]);
    expect([...next.draft.roles]).toEqual(["software_engineering", "data"]);
    expect(scopeDirtiness(next).dirty).toBe(false);
  });

  it("keeps an axis the user edited while the write was in flight", () => {
    /* The response echoes the axes the SUBMISSION carried, which is not what
       the user has by the time it lands. Adopting it into the draft wholesale
       throws away every edit made since the click — the draft reads clean and
       the edit is gone with no error anywhere. Only `saved` may take the echo unconditionally: the server
       really does hold it. */
    const submitted = selection({ roles: new Set(["software_engineering"]) });
    const state = draftState({
      draft: selection({ roles: new Set(["software_engineering", "design"]) }),
    });
    const next = applySaveResult(state, {
      request: buildSaveRequest(draftState({ draft: submitted })),
      submitted,
      result: SAVED_SCOPE,
    });

    expect([...next.draft.roles]).toEqual(["software_engineering", "design"]);
    expect([...next.saved.roles]).toEqual(["software_engineering", "data"]);
    expect(scopeDirtiness(next).dirty).toBe(true);
  });

  it("still adopts the server's answer for the axes nobody touched", () => {
    /* Holding the whole draft back would be the opposite defect: the server
       normalizes (the persona path derives the seniority axis), so an axis the
       user left alone must take the server's version or it is dirty forever. */
    const submitted = selection({
      roles: new Set(["software_engineering"]),
      bands: new Set(["senior"]),
    });
    const state = draftState({
      draft: selection({
        roles: new Set(["software_engineering", "design"]),
        bands: new Set(["senior"]),
      }),
    });
    const next = applySaveResult(state, {
      request: buildSaveRequest(draftState({ draft: submitted })),
      submitted,
      result: SAVED_SCOPE,
    });

    expect([...next.draft.bands]).toEqual(["senior", "staff"]);
    expect([...next.draft.roles]).toEqual(["software_engineering", "design"]);
  });

  it("adopts the stage markers only when the save carried them", () => {
    const placed = draftState({
      draft: selection({ experienceStage: "senior", targetStage: "staff" }),
    });
    expect(afterSave(placed).saved).toMatchObject({ experienceStage: "senior", targetStage: "staff" });

    const half = draftState({
      saved: selection({ experienceStage: "mid", targetStage: "mid" }),
      draft: selection({ experienceStage: "senior", targetStage: null }),
    });
    expect(afterSave(half).saved).toMatchObject({ experienceStage: "mid", targetStage: "mid" });
  });

  it("adopts the echoed worlds, veto and excepted places, keeping one edited in flight", () => {
    /* The server stores the worlds set in a form that depends on the veto, so
       its echo can differ from what was sent and must reach both sides. */
    const submitted = selection({
      domains: new Set(["ai_ml"]),
      excluded: new Set(["ads"]),
      excepted: new Set(["city_new_york"]),
    });
    const state = draftState({ draft: { ...submitted, excluded: new Set(["ads", "crypto"]) } });
    const next = applySaveResult(state, {
      request: buildSaveRequest(draftState({ draft: submitted })),
      submitted,
      result: {
        ...SAVED_SCOPE,
        enabled_domain_groups: ["ai_ml", "fintech"],
        excluded_domain_groups: ["ads"],
        excluded_location_groups: ["city_new_york"],
      },
    });
    expect([...next.saved.domains]).toEqual(["ai_ml", "fintech"]);
    expect([...next.draft.domains]).toEqual(["ai_ml", "fintech"]);
    expect([...next.saved.excluded]).toEqual(["ads"]);
    expect([...next.draft.excluded]).toEqual(["ads", "crypto"]);
    expect([...next.saved.excepted]).toEqual(["city_new_york"]);
    expect([...next.draft.excepted]).toEqual(["city_new_york"]);
  });

  it("takes the counts and the promotion from the answer, a zero included", () => {
    const state = draftState();
    const promoted = afterSave(state, {
      result: { ...SAVED_SCOPE, in_scope_changed: 12, on_board: 40, promoted: 2, promotion_pending: true },
    });
    expect(promoted).toMatchObject({
      lastInScopeChanged: 12,
      lastOnBoard: 40,
      lastPromotion: { promoted: 2, pending: true },
    });
    // Nothing promoted is still an answer: the confirmation reads it as none.
    expect(afterSave(state).lastPromotion).toEqual({ promoted: 0, pending: false });
  });
});

describe("answers and the flat role lists", () => {
  it("a flat role or track edit drops the loaded answers, so the save cannot overrule the edit", () => {
    /* Welcome edits the flat lists. The answers read at load would travel with
       the save and win on the server, silently dropping the edit. */
    const answers = new Map([["technical", new Set(["software_engineering"])]]);
    const loaded = draftState({ draft: selection({ roles: new Set(["software_engineering"]), tracks: new Set(["technical"]), answers }) });
    const edits: ScopeDraftAction[] = [
      { type: "toggled", axis: "roles", slug: "security_engineering" },
      { type: "toggled", axis: "tracks", slug: "management" },
      { type: "role_category_toggled", slugs: ["design_ux"] },
    ];
    for (const action of edits) {
      const next = scopeDraftReducer(loaded, action);
      expect(next.draft.answers).toBeNull();
      expect(buildSaveRequest(next).body).not.toHaveProperty("role_answers");
    }
    // Any other edit keeps them, and they travel.
    const located = scopeDraftReducer(loaded, { type: "toggled", axis: "locations", slug: "uk" });
    expect(located.draft.answers).toBe(answers);
    expect(buildSaveRequest(located).body).toHaveProperty("role_answers", [{ track: "technical", roles: ["software_engineering"] }]);
  });

  it("replacing the answers keeps the flat lists as their projection", () => {
    const next = scopeDraftReducer(draftState(), {
      type: "answers_replaced",
      answers: new Map<string, "any" | Set<string>>([["management", "any"], ["technical", new Set(["software_engineering"])]]),
      allFamilies: ["engineering_management", "software_engineering", "design_ux"],
    });
    expect([...next.draft.tracks]).toEqual(["management", "technical"]);
    expect([...next.draft.roles]).toEqual(["engineering_management", "software_engineering", "design_ux"]);
  });
});

describe("what a load seeds", () => {
  it("puts the saved axes on both sides", () => {
    const next = scopeDraftReducer(initialScopeDraftState, {
      type: "catalog_loaded",
      settings: SETTINGS,
      domains: ["ai_ml", "fintech"],
      initialSelection: "saved",
    });
    expect([...next.draft.roles]).toEqual(["software_engineering"]);
    expect([...next.saved.roles]).toEqual(["software_engineering"]);
    expect(scopeDirtiness(next).dirty).toBe(false);
    // Two sides, never one set shared by both: a toggle would move the saved
    // axis with the draft and nothing would ever read as dirty.
    expect(next.draft.roles).not.toBe(next.saved.roles);
  });

  it("starts a wizard draft blank — except the worlds axis, which starts whole", () => {
    /* The worlds step is a NARROWING, so "picked nothing" has to mean "lose
       nothing". Every other axis starts empty for the same reason: the wizard
       asks, it does not pre-answer. */
    const next = scopeDraftReducer(initialScopeDraftState, {
      type: "catalog_loaded",
      settings: SETTINGS,
      domains: ["ai_ml", "fintech"],
      initialSelection: "empty",
    });
    expect(next.draft.roles.size).toBe(0);
    expect(next.draft.bands.size).toBe(0);
    expect(next.draft.locations.size).toBe(0);
    expect([...next.draft.domains]).toEqual(["ai_ml", "fintech"]);
  });

  it("starts a wizard draft at the level-not-stated default, a saved one at what was saved", () => {
    /* The box is an inclusion, not a question: a first-run Welcome that left it
       unticked would save "off" for a person who never chose, against the
       default an untouched install already has. */
    const saidNo = { ...SETTINGS, include_unstated_level: false };
    const wizard = scopeDraftReducer(initialScopeDraftState, {
      type: "catalog_loaded", settings: saidNo, domains: [], initialSelection: "empty",
    });
    expect(wizard.draft.includeUnstatedLevel).toBe(true);
    const saved = scopeDraftReducer(initialScopeDraftState, {
      type: "catalog_loaded", settings: saidNo, domains: [], initialSelection: "saved",
    });
    expect(saved.draft.includeUnstatedLevel).toBe(false);
    expect(saved.saved.includeUnstatedLevel).toBe(false);
  });

  it("reads the worlds, veto, excepted places and answers as the catalog sends them", () => {
    /* The saved worlds, not the catalog's whole list, and the server's own
       answers: with none saved it reads them off the flat lists itself. */
    const next = scopeDraftReducer(initialScopeDraftState, {
      type: "catalog_loaded",
      settings: { ...SETTINGS, excluded_domain_groups: ["ads"], excluded_location_groups: ["city_new_york"] },
      domains: ["ai_ml", "fintech", "ads"],
      initialSelection: "saved",
    });
    expect([...next.saved.domains]).toEqual(["ai_ml"]);
    expect([...next.draft.domains]).toEqual(["ai_ml"]);
    expect([...next.saved.excluded]).toEqual(["ads"]);
    expect([...next.draft.excepted]).toEqual(["city_new_york"]);
    expect(next.saved.answers).toEqual(new Map([["technical", new Set(["software_engineering"])]]));
    expect(next.draft.answers).toEqual(next.saved.answers);
    expect(scopeDirtiness(next).dirty).toBe(false);
  });

  it("places a loaded persona's levels on both sides, and none when there is no persona", () => {
    const fresh = scopeDraftReducer(initialScopeDraftState, { type: "persona_loaded", stages: null });
    expect(fresh.draft.experienceStage).toBeNull();

    const loadedPersona = scopeDraftReducer(initialScopeDraftState, {
      type: "persona_loaded",
      stages: { experience: "senior", target: "staff" },
    });
    expect(loadedPersona.draft).toMatchObject({ experienceStage: "senior", targetStage: "staff" });
    expect(loadedPersona.saved).toMatchObject({ experienceStage: "senior", targetStage: "staff" });
    expect(scopeDirtiness(loadedPersona).dirty).toBe(false);
  });

});

describe("the draft's edits", () => {
  const loaded = scopeDraftReducer(initialScopeDraftState, {
    type: "catalog_loaded",
    settings: SETTINGS,
    domains: ["ai_ml", "fintech"],
    initialSelection: "saved",
  });

  it("toggles one axis and leaves the rest where they were", () => {
    const on = scopeDraftReducer(loaded, { type: "toggled", axis: "locations", slug: "us" });
    expect([...on.draft.locations]).toEqual(["uk", "us"]);
    expect(on.draft.roles).toBe(loaded.draft.roles);
    expect(on.saved.locations).toBe(loaded.saved.locations);
    expect(scopeDirtiness(on)).toMatchObject({ locationsDirty: true, estimableDirty: false, dirty: true });

    const off = scopeDraftReducer(on, { type: "toggled", axis: "locations", slug: "us" });
    expect([...off.draft.locations]).toEqual(["uk"]);
    expect(scopeDirtiness(off).dirty).toBe(false);
  });

  it("treats a role category as all-or-nothing", () => {
    const all = scopeDraftReducer(loaded, {
      type: "role_category_toggled",
      slugs: ["software_engineering", "data"],
    });
    expect([...all.draft.roles]).toEqual(["software_engineering", "data"]);

    const none = scopeDraftReducer(all, {
      type: "role_category_toggled",
      slugs: ["software_engineering", "data"],
    });
    expect(none.draft.roles.size).toBe(0);
  });

  it("separates a world the user picked from one the server already stored", () => {
    /* Accepting a suggestion moves BOTH sides: the server persisted it, so
       there is nothing left to save. Selecting every world is an edit like any
       other and must read as dirty. */
    const picked = scopeDraftReducer(loaded, {
      type: "domains_replaced",
      slugs: ["ai_ml", "fintech"],
    });
    expect(scopeDirtiness(picked).domainsDirty).toBe(true);

    const accepted = scopeDraftReducer(loaded, {
      type: "server_domains_adopted",
      slugs: ["ai_ml", "fintech"],
      excluded: [],
    });
    expect([...accepted.draft.domains]).toEqual(["ai_ml", "fintech"]);
    expect([...accepted.saved.domains]).toEqual(["ai_ml", "fintech"]);
    expect(scopeDirtiness(accepted).domainsDirty).toBe(false);
  });

  it("keeps unsaved World edits through an accept, and takes only what the accept changed", () => {
    /* Picked "interested in fintech" and "not interested in ads", unsaved;
       then accepted a suggestion turning health on. Replacing the draft's
       whole list with the server's would drop both picks. */
    const edited = [
      { type: "domains_replaced", slugs: ["ai_ml", "fintech"] },
      { type: "excluded_replaced", slugs: ["ads"] },
    ] satisfies ScopeDraftAction[];
    const draft = edited.reduce(scopeDraftReducer, loaded);

    const on = scopeDraftReducer(draft, { type: "server_domains_adopted", slugs: ["ai_ml", "health"], excluded: [] });
    expect(new Set(on.draft.domains)).toEqual(new Set(["ai_ml", "fintech", "health"]));
    expect([...on.draft.excluded]).toEqual(["ads"]);
    expect(new Set(on.saved.domains)).toEqual(new Set(["ai_ml", "health"]));
    expect(scopeDirtiness(on).dirty).toBe(true);

    // A world-off the server wrote as a veto reaches the draft's veto too.
    const off = scopeDraftReducer(on, { type: "server_domains_adopted", slugs: ["health"], excluded: ["ai_ml"] });
    expect(new Set(off.draft.domains)).toEqual(new Set(["fintech", "health"]));
    expect(new Set(off.draft.excluded)).toEqual(new Set(["ads", "ai_ml"]));
    expect([...off.saved.excluded]).toEqual(["ai_ml"]);
  });

  it("dirties the draft when a stage moves, but only against a stored persona", () => {
    /* The span is not enough to tell: re-anchoring principal->director_plus as
       director_plus->principal is the same band set and a different answer to
       "where am I today". The wizard has no stored persona and commits through
       its own CTA, so an unplaced marker must not read as an edit. */
    const wizard = scopeDraftReducer(loaded, {
      type: "stage_placed",
      handle: "experience",
      slug: "senior",
    });
    expect(scopeDirtiness(wizard).stagesDirty).toBe(false);

    const stored = scopeDraftReducer(loaded, {
      type: "persona_loaded",
      stages: { experience: "senior", target: "staff" },
    });
    const moved = scopeDraftReducer(stored, { type: "stage_placed", handle: "target", slug: "senior" });
    expect(scopeDirtiness(moved)).toMatchObject({ stagesDirty: true, dirty: true });
  });


});

describe("the stage <-> band machine", () => {
  it("derives the seniority axis from the span", () => {
    /* Ungated: gated on anything else, the Level control would change no
       draft set. */
    const state = draftState({
      draft: selection({ experienceStage: "mid", targetStage: "staff" }),
    });
    const next = scopeDraftReducer(state, { type: "bands_derived", stageOrder: STAGE_ORDER });
    expect([...next.draft.bands]).toEqual(["mid", "senior", "staff"]);

    // Re-deriving the same span changes nothing, so it cannot churn renders.
    expect(scopeDraftReducer(next, { type: "bands_derived", stageOrder: STAGE_ORDER })).toBe(next);
  });

  it("derives nothing from half a span or an unplaced marker", () => {
    const half = draftState({ draft: selection({ experienceStage: "mid", targetStage: null }) });
    expect(scopeDraftReducer(half, { type: "bands_derived", stageOrder: STAGE_ORDER })).toBe(half);

    const unknown = draftState({
      draft: selection({ experienceStage: "mid", targetStage: "vp" }),
    });
    expect(scopeDraftReducer(unknown, { type: "bands_derived", stageOrder: STAGE_ORDER })).toBe(unknown);
  });

  it("reads a span in either direction", () => {
    expect(stageSpanOf(STAGE_ORDER, "staff", "mid")).toEqual(["mid", "senior", "staff"]);
    expect(stageSpanOf(STAGE_ORDER, "mid", "nonsense")).toBeNull();
  });


  it("orders the ladder by the catalog's order, not its listing", () => {
    expect(stageOrderOf(LEVELS)).toEqual(STAGE_ORDER);
    expect(stageOrderOf(null)).toEqual([]);
  });

  it("allows the union of the selected functions' tiers, and everything when none is selected", () => {
    const tracks = [
      { slug: "management", allowed_bands: ["senior", "staff"] },
      { slug: "technical", allowed_bands: ["entry", "mid", "senior", "staff"] },
      { slug: "unbounded", allowed_bands: null },
    ];
    expect([...allowedBandsOf(tracks, new Set(["management"]), STAGE_ORDER)]).toEqual(["senior", "staff"]);
    expect([...allowedBandsOf(tracks, new Set(["management", "technical"]), STAGE_ORDER)])
      .toEqual(["senior", "staff", "entry", "mid"]);
    expect([...allowedBandsOf(tracks, new Set(), STAGE_ORDER)]).toEqual(STAGE_ORDER);
    // A function that declares no gate cannot narrow the ladder to nothing.
    expect([...allowedBandsOf(tracks, new Set(["unbounded"]), STAGE_ORDER)]).toEqual(STAGE_ORDER);
  });
});

describe("whether anything has been read", () => {
  const levels = (...counts: number[]) => counts.map((count, order) => ({ slug: `l${order}`, order, count }));
  it("holds no roles only when no level has one and none lacks a level", () => {
    expect(holdsNoRoles({ levels: levels(0, 0, 0), unstated_level_count: 0 })).toBe(true);
    expect(holdsNoRoles({ levels: levels(0, 3, 0), unstated_level_count: 0 })).toBe(false);
    expect(holdsNoRoles({ levels: levels(0, 0), unstated_level_count: 12 })).toBe(false);
  });
});
