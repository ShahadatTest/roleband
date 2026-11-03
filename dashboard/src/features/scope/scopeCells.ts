/**
 * The scope joint: counting postings the way the backend gate actually counts.
 *
 * Every other number in the scope catalog is a MARGINAL — postings per band,
 * per domain, per location — and marginals cannot be intersected. Worse, the
 * domain marginal counts a multi-label posting once per world, so they do not
 * even sum. Intersecting band x track and showing location and domain at
 * full-market volume overstates by a wide margin.
 *
 * `scope_cells` is one row per distinct (role, band, track, locations,
 * domains) coordinate, so the real gate can be applied here. The gate below
 * MUST stay identical to `enricher.passes_filters` in the backend; the one
 * thing it cannot express is `rule_excluded`, which matches a posting's
 * verbatim team/department and no aggregate can carry. Counts here are
 * therefore an upper bound by however many learned exclusion rules match.
 *
 * Empty axes are not symmetric, and the asymmetry is deliberate upstream:
 * an empty bands/tracks/locations/roles selection admits NOTHING, while an
 * empty domains selection means "no narrowing" and admits everything. An
 * unclassified posting (`domains: []`) also always passes the domain axis.
 * Both are why `domain_sets` ships its empty entry — dropping it silently
 * re-implements the gate wrongly.
 */

import type { components } from "../../api.gen";
import { UNSTATED_LEVEL } from "../../copy/vocabulary";

export type ScopeCellsPayload = components["schemas"]["ScopeCells"];

/** The band a cell carries when its postings state no level.
 *  Not a level: the backend stores such a posting at `mid` for sorting only
 *  and counts it under this key, and the gate passes it by
 *  `includeUnstatedLevel`, never by a band or a kind's level range. The key
 *  lives in `copy/vocabulary.ts`, which the Board's Level facet reads too. */
export { UNSTATED_LEVEL };

/** Whether roles whose level isn't stated pass when nobody has said. The
 *  backend's `levels.INCLUDE_UNSTATED_LEVEL_DEFAULT`; the shared fixture
 *  `level_basis_gate.json` holds both to one value. */
export const INCLUDE_UNSTATED_LEVEL_DEFAULT = true;

/** One decoded coordinate. Slugs, not indices — the interning is wire-only. */
export interface ScopeCell {
  role: string;
  band: string;
  track: string;
  locations: string[];
  domains: string[];
  count: number;
}

export interface ScopeAxesSelection {
  roles: Set<string>;
  bands: Set<string>;
  tracks: Set<string>;
  locations: Set<string>;
  domains: Set<string>;
  /** Subjects the person is not interested in: a veto, not an axis. A cell
      tagged with any of them fails whatever else it is about. Absent means
      nothing is excluded. */
  excluded?: Set<string>;
  /** Which roles of each kind. When present, the role part of
      the gate is an OR over them: the cell's kind has an answer, the answer
      is "any" or names the cell's family, and `trackBands` (each kind's own
      level range) holds its band. The flat `roles` and `tracks` are then not
      read. Absent: the flat cross product, for a caller with no answers. */
  answers?: ReadonlyMap<string, "any" | ReadonlySet<string>> | null;
  trackBands?: ReadonlyMap<string, ReadonlySet<string>>;
  /** Places excepted inside the included ones ("the US except New York"),
      read per place by `placeAdmits` with `placeParents` (each
      place's parent). Absent or empty: the plain overlap. */
  excepted?: ReadonlySet<string>;
  placeParents?: ReadonlyMap<string, string>;
  /** Whether postings that state no level pass the level axis.
      Absent means they do not, the backend's default. */
  includeUnstatedLevel?: boolean;
}

export interface ScopeIndex {
  ready: boolean;
  cells: ScopeCell[];
  /** Companies the cells cover, and followed companies not yet scanned. */
  companies: string[];
  missingCompanies: string[];
  /** Followed companies whose catalog predates the joint: left out of the
      cells until their next complete scan, and named on screen. */
  staleCompanies: string[];
}

export const EMPTY_SCOPE_INDEX: ScopeIndex = {
  ready: false,
  cells: [],
  companies: [],
  missingCompanies: [],
  staleCompanies: [],
};

/**
 * Undo the wire interning once, so every later count is a plain scan.
 *
 * A cell whose indices fall outside the dictionaries is dropped rather than
 * throwing: this is a projection of a database the client does not control,
 * and one malformed row must not blank a screen.
 */
export function buildScopeIndex(payload: ScopeCellsPayload | undefined | null): ScopeIndex {
  if (!payload) return EMPTY_SCOPE_INDEX;
  const { roles, bands, tracks, location_sets: locationSets, domain_sets: domainSets } = payload;
  const cells: ScopeCell[] = [];
  for (const row of payload.cells ?? []) {
    if (!Array.isArray(row) || row.length !== 6) continue;
    const [roleIndex, bandIndex, trackIndex, locationIndex, domainIndex, count] = row;
    const role = roles[roleIndex];
    const band = bands[bandIndex];
    const track = tracks[trackIndex];
    const locations = locationSets[locationIndex];
    const domains = domainSets[domainIndex];
    if (role === undefined || band === undefined || track === undefined) continue;
    if (locations === undefined || domains === undefined) continue;
    if (typeof count !== "number" || count <= 0) continue;
    cells.push({ role, band, track, locations, domains, count });
  }
  return {
    ready: Boolean(payload.ready),
    cells,
    companies: payload.companies ?? [],
    missingCompanies: payload.missing_companies ?? [],
    staleCompanies: payload.stale_companies ?? [],
  };
}

function overlaps(values: string[], selected: Set<string>): boolean {
  for (const value of values) if (selected.has(value)) return true;
  return false;
}

/**
 * The location gate for one posting's places. Mirrors
 * `taxonomy.place_scope.place_admits`: the posting's most specific places are
 * the ones none of its others sits under, and it is in when one of them meets
 * an included place before an excepted one on the way up. So "the US except
 * New York" keeps a remote-US role and a New York or Austin role, and drops a
 * New York one. The cells carry only the cities a person named, which is the
 * set the backend reads too.
 */
export function placeAdmits(
  places: readonly string[],
  included: ReadonlySet<string>,
  excepted?: ReadonlySet<string>,
  parents?: ReadonlyMap<string, string>,
): boolean {
  if (!excepted || excepted.size === 0) return places.some((place) => included.has(place));
  const inner = new Set<string>();
  for (const place of places) {
    for (let up = parents?.get(place); up !== undefined; up = parents?.get(up)) inner.add(up);
  }
  for (const place of places) {
    if (inner.has(place)) continue;
    for (let at: string | undefined = place; at !== undefined; at = parents?.get(at)) {
      if (included.has(at)) return true;
      if (excepted.has(at)) break;
    }
  }
  return false;
}

export type ScopeAxis = "roles" | "bands" | "tracks" | "locations" | "domains";

/** The value(s) a cell carries on one axis. Three axes are scalar and two are
 *  set-valued, and the gate treats set-valued ones as OVERLAP. */
function valuesOn(cell: ScopeCell, axis: ScopeAxis): string[] {
  switch (axis) {
    case "roles": return [cell.role];
    case "bands": return [cell.band];
    case "tracks": return [cell.track];
    case "locations": return cell.locations;
    case "domains": return cell.domains;
  }
}

/**
 * The gate, cell by cell. Mirrors `enricher.passes_filters` exactly.
 *
 * `skip` leaves one axis out, which is what every per-option count needs: a
 * card asks "how many would THIS bring me", and requiring the option to be
 * ticked already would make every unticked card read zero.
 */
export function cellPasses(
  cell: ScopeCell,
  selection: ScopeAxesSelection,
  skip?: ScopeAxis,
): boolean {
  const unstated = cell.band === UNSTATED_LEVEL;
  if (selection.answers) {
    const answer = selection.answers.get(cell.track);
    if (skip !== "tracks" && answer === undefined) return false;
    if (skip !== "roles" && answer !== undefined && answer !== "any" && !answer.has(cell.role)) return false;
    // A kind's level range is part of its answer, so it holds even while the
    // level axis is skipped (per-rung counts). A posting that states no level
    // has no band to range over: the switch below decides it.
    const range = selection.trackBands?.get(cell.track);
    if (!unstated && range && !range.has(cell.band)) return false;
  } else {
    if (skip !== "roles" && !selection.roles.has(cell.role)) return false;
    if (skip !== "tracks" && !selection.tracks.has(cell.track)) return false;
  }
  if (skip !== "bands") {
    // An empty level axis admits nothing, unstated postings included.
    if (selection.bands.size === 0) return false;
    if (unstated ? !selection.includeUnstatedLevel : !selection.bands.has(cell.band)) return false;
  }
  if (skip !== "locations"
      && !placeAdmits(cell.locations, selection.locations, selection.excepted, selection.placeParents)) {
    return false;
  }
  // Narrows only when both sides have an opinion — see the module note.
  if (skip !== "domains" && selection.domains.size > 0 && cell.domains.length > 0
      && !overlaps(cell.domains, selection.domains)) {
    return false;
  }
  if (skip !== "domains" && selection.excluded && overlaps(cell.domains, selection.excluded)) return false;
  return true;
}

/** Postings passing the whole gate. */
export function countUnderScope(index: ScopeIndex, selection: ScopeAxesSelection): number {
  let total = 0;
  for (const cell of index.cells) if (cellPasses(cell, selection)) total += cell.count;
  return total;
}

/** Postings each role group contributes under the other four axes. */
export function countByRole(index: ScopeIndex, selection: ScopeAxesSelection): Map<string, number> {
  return countByOption(index, selection, "roles");
}

/**
 * Per option of one axis: postings carrying that option that clear the OTHER
 * four axes.
 *
 * This is the honest number beside a checkbox. It is deliberately not "what
 * the total would become if I ticked this" — that reads as the whole radar on
 * every already-ticked card — and emphatically not the option's whole-market
 * inventory, which overstates the worlds axis by a wide margin.
 *
 * An option the cells never mention is absent from the map rather than zero:
 * the caller decides whether "no postings" or "nothing known" is the honest
 * word for it.
 */
export function countByOption(
  index: ScopeIndex,
  selection: ScopeAxesSelection,
  axis: ScopeAxis,
): Map<string, number> {
  const out = new Map<string, number>();
  for (const cell of index.cells) {
    if (!cellPasses(cell, selection, axis)) continue;
    for (const value of valuesOn(cell, axis)) {
      out.set(value, (out.get(value) ?? 0) + cell.count);
    }
  }
  return out;
}
