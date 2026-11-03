/* Scope: the catalogs, saved settings, the persona profile and exclusion rules.
   One domain of the typed client; `index.ts` composes `api`. */

import type { Schemas } from "./schemas";
import { getJSON, putJSON, postJSON, deleteJSON } from "./transport";

/** `POST /api/scope/refresh`: its `status`, and `max_list` when a capped scan started. */
export type ScopeRefreshResult = Schemas["ScopeRefreshResponse"];

/* Scope, settings and profile wire types are aliases of the generated schemas
   (`tracker/api/schemas/scope.py`). What each value means is
   documented on the Pydantic model; change it there and regenerate. */

/** The five saved scope axes, each in taxonomy order. */
export type ScopeAxes = Schemas["ScopeAxes"];

/** `PUT /api/settings`. The intent statement and the two stage markers are
 *  write-only passengers: omitted = untouched, "" = cleared, and the stages
 *  travel together and derive the seniority axis from their span. */
export type ScopeSettingsPayload = Schemas["SettingsPayload"];

/** What a settings save answers with: the axes as saved, and how many rows
 *  changed scope. The passengers are never echoed. */
export type ScopeSettingsSaveResult = Schemas["SettingsSaveResponse"];

/** How a company grades one stage: exactly one of `company_wide` (a ladder
 *  spanning every function, e.g. Google L5) or `per_track` (a grade valid only
 *  inside certain functions, e.g. Apple ICT4 for technical roles). */
export type DecoderCell = Schemas["DecoderCell"];

export type ScopeLevel = Schemas["ScopeLevel"];

/** The persona: where the user is today, where they are aiming, and the aim
 *  sentence. Saved through `PUT /api/settings` with the scope; it
 *  holds no copy of the scope. */
export type StoredPersonaProfile = Schemas["StoredPersonaProfile"];

export type ProfileState = Schemas["ProfileStateResponse"];

export type ScopeTrack = Schemas["ScopeTrack"];


export type ScopeRoleGroup = Schemas["ScopeRoleGroup"];

export type ScopeCategory = Schemas["ScopeCategory"];

export type ScopeCatalogCompany = Schemas["ScopeCatalogCompany"];

/** One node of the nested location axis (metro -> country -> region).
 *  `uncovered_by` names tracked companies whose source cannot be asked about
 *  the region: an unasked region returns exactly what an empty one does. */
export type ScopeLocation = Schemas["ScopeLocation"];

/** One world (business domain) the market's roles live in — the 5th scope
 *  axis. Counts overlap across worlds: they answer "what would turning this off
 *  remove", not "how do these sum". */
export type ScopeDomain = Schemas["ScopeDomain"];

/** The joint over role x band x track x locations x domains — the
 *  one shape in this payload that can be INTERSECTED. Every other count is a
 *  marginal, and the domain marginal counts a multi-label posting once per
 *  world, so they do not sum. Decode it with `features/scope/scopeCells.ts`;
 *  the indices are a wire format and mean nothing on their own. */
export type ScopeCells = Schemas["ScopeCells"];

export type ScopeCatalog = Schemas["ScopeCatalogResponse"];

/** `POST /api/scope/preview`: what saving a draft would do to the Board,
    before it happens. Nothing is written. */
export type ScopePreview = Schemas["ScopePreviewResponse"];

/** The location search: taxonomy places and cities, best
    first, plus any political union the query names. */
export type PlaceSearch = Schemas["PlaceSearchResponse"];
export type PlaceResult = Schemas["PlaceResult"];
export type UnionResult = Schemas["UnionResult"];

/** A learned per-company exclusion in the employer's own vocabulary.
 *  Written only by explicit confirmation; part of what `in_scope` projects. */
export type ScopeRule = Schemas["ScopeRule"];

/** What `createScopeRule` sends: the two kinds the endpoint accepts. */
export type ScopeRulePayload = Schemas["ScopeRulePayload"];

/** Settings > Data retention: the saved window (null = Never), what
    each choice would remove now, and the last removal. */
export type RetentionState = Schemas["RetentionState"];
export type RetentionChoice = Schemas["RetentionChoice"];
export type RetentionUpdate = Schemas["RetentionUpdate"];
/** Settings > Language and region (docs/copy.md):
 *  the catalog the dashboard speaks and the region it formats for (null =
 *  the operating system's). */
export type LocaleSettings = Schemas["LocaleSettings"];

export const scopeApi = {
  /** The saved scope axes; the Levels tab reads the person's career tracks. */
  scopeSettings: () => getJSON<ScopeAxes>("/api/settings"),
  /** `cities`: cities the draft names and has not saved, priced in this read
      (the saved ones always are). */
  scopeCatalog: (cities: readonly string[] = []) =>
    getJSON<ScopeCatalog>(cities.length
      ? `/api/scope/catalog?${cities.map((city) => `cities=${encodeURIComponent(city)}`).join("&")}`
      : "/api/scope/catalog"),
  searchPlaces: (query: string, limit = 10, signal?: AbortSignal) =>
    getJSON<PlaceSearch>(`/api/scope/places?q=${encodeURIComponent(query)}&limit=${limit}`, signal),
  /** `locations`: places being answered and not yet saved, asked for beside
      the saved ones. */
  refreshScopeCatalog: (locations: string[] = []) =>
    postJSON<ScopeRefreshResult>("/api/scope/refresh", { locations } satisfies Schemas["ScopeRefreshRequest"]),
  saveSettings: (scope: ScopeSettingsPayload) => putJSON<ScopeSettingsSaveResult>("/api/settings", scope),
  previewScope: (scope: ScopeSettingsPayload) => postJSON<ScopePreview>("/api/scope/preview", scope),
  scopeRules: () => getJSON<Schemas["ScopeRuleList"]>("/api/scope/rules"),
  createScopeRule: (rule: ScopeRulePayload) =>
    postJSON<Schemas["ScopeRuleCreateResponse"]>("/api/scope/rules", rule),
  deleteScopeRule: (id: number) =>
    deleteJSON<Schemas["ScopeRuleDeleteResponse"]>(`/api/scope/rules/${id}`),
  retention: () => getJSON<RetentionState>("/api/settings/retention"),
  saveRetention: (update: RetentionUpdate) => putJSON<RetentionState>("/api/settings/retention", update),
  saveLocale: (choice: LocaleSettings) => putJSON<LocaleSettings>("/api/settings/locale", choice),
};
