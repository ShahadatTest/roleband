import type { ScopeCatalog } from "../../../api";
import { countUnderScope, INCLUDE_UNSTATED_LEVEL_DEFAULT, type ScopeAxesSelection, type ScopeIndex } from "../scopeCells";
import { asAny, isTrackSlug, rowsPicked, type RoleRow, type TrackSlug } from "./walkModel";
import { placeName } from "../../../copy/vocab";

/* The funnel the walk closes: from every open role at the companies the
   person follows down to the ones their answers keep, one step at a time.
   Each step's count is the joint gate applied cumulatively — the kind of
   role first, then the level on top of it, then where, then which roles,
   then interests — so a step's share is "what is still on the radar after
   this answer", never a marginal. All of it is the catalog's joint cells
   already on the page (`scopeCells`); nothing here asks the server. */

export type FunnelStep = "accountable" | "level" | "where" | "roles" | "subjects";
export const FUNNEL_ORDER: readonly FunnelStep[] = ["accountable", "level", "where", "roles", "subjects"];

export interface WalkProgress {
  /** Counts exist only once a scan has produced joint cells. */
  ready: boolean;
  /** Every open role at the followed companies, before any answer. */
  total: number;
  /** Roles still kept after each step, cumulative in FUNNEL_ORDER. */
  kept: Record<FunnelStep, number>;
  /** The first step whose share cannot be known yet, and every step after
      it: a city the draft names (included or excepted) that the joint does
      not price yet (`scope_cells.cities`), so its count is
      unknown, not zero. */
  pendingFrom: FunnelStep | null;
  /** Those cities, by name, for the line that says why. */
  pendingPlaces: string[];
  /** The counts are being re-read with those cities:
      "counting" rather than "after you save". */
  counting: boolean;
}

export const NO_PROGRESS: WalkProgress = {
  ready: false,
  total: 0,
  kept: { accountable: 0, level: 0, where: 0, roles: 0, subjects: 0 },
  pendingFrom: null,
  pendingPlaces: [],
  counting: false,
};

/** Whether `step` has a known share under `progress`. */
export function isPending(progress: WalkProgress, step: FunnelStep): boolean {
  return progress.pendingFrom !== null && FUNNEL_ORDER.indexOf(step) >= FUNNEL_ORDER.indexOf(progress.pendingFrom);
}

/** The selection that admits everything: every family, band, track and
    place the catalog knows, roles whose level isn't stated, and no
    opinion on worlds (which the gate reads as "no narrowing"). */
function everything(catalog: ScopeCatalog): ScopeAxesSelection {
  return {
    roles: new Set(catalog.categories.flatMap((category) => category.groups.map((group) => group.slug))),
    bands: new Set(catalog.levels.map((level) => level.slug)),
    tracks: new Set(catalog.tracks.map((track) => track.slug)),
    locations: new Set((catalog.locations ?? []).map((location) => location.slug)),
    domains: new Set(),
    includeUnstatedLevel: true,
  };
}

/** The draft as the funnel reads it, one cumulative selection per step. */
function layersOf(catalog: ScopeCatalog, draft: ScopeAxesSelection): Record<FunnelStep, ScopeAxesSelection> & { all: ScopeAxesSelection } {
  const all = everything(catalog);
  /* With answers, the Role layer is every chosen kind as "any", each within
     its own level range; the Which roles layer then applies what each answer
     picked. Without (a draft the walk never wrote), the flat lists. */
  const afterRole: ScopeAxesSelection = draft.answers
    ? { ...all, tracks: draft.tracks, answers: asAny(draft.answers), trackBands: draft.trackBands }
    : { ...all, tracks: draft.tracks };
  const afterLevel: ScopeAxesSelection = {
    ...afterRole, bands: draft.bands, includeUnstatedLevel: draft.includeUnstatedLevel ?? INCLUDE_UNSTATED_LEVEL_DEFAULT,
  };
  const afterWhere: ScopeAxesSelection = {
    ...afterLevel, locations: draft.locations, excepted: draft.excepted, placeParents: draft.placeParents,
  };
  const afterRoles: ScopeAxesSelection = draft.answers
    ? { ...afterWhere, roles: draft.roles, answers: draft.answers }
    : { ...afterWhere, roles: draft.roles };
  const afterSubjects: ScopeAxesSelection = { ...afterRoles, domains: draft.domains, excluded: draft.excluded };
  return { all, accountable: afterRole, level: afterLevel, where: afterWhere, roles: afterRoles, subjects: afterSubjects };
}

export function progressOf(
  index: ScopeIndex, catalog: ScopeCatalog, draft: ScopeAxesSelection, counting = false,
): WalkProgress {
  if (!index.ready) return NO_PROGRESS;
  const layers = layersOf(catalog, draft);
  const total = countUnderScope(index, layers.all);
  const priced = new Set(catalog.scope_cells?.cities ?? []);
  const names = new Map((catalog.locations ?? []).map((location) => [location.slug, placeName(location)]));
  const pendingPlaces = [...new Set([...draft.locations, ...(draft.excepted ?? [])])]
    .filter((slug) => slug.startsWith("city_") && !priced.has(slug))
    .map((slug) => names.get(slug) ?? slug);
  return {
    ready: true,
    total,
    pendingFrom: pendingPlaces.length > 0 ? "where" : null,
    pendingPlaces,
    counting: counting && pendingPlaces.length > 0,
    kept: {
      accountable: countUnderScope(index, layers.accountable),
      level: countUnderScope(index, layers.level),
      where: countUnderScope(index, layers.where),
      roles: countUnderScope(index, layers.roles),
      subjects: countUnderScope(index, layers.subjects),
    },
  };
}

/** Roles the draft keeps before World that carry no subject. They pass
    every interest and every veto, so the World step
    names them as their own line, counted under the person's answers rather
    than across the whole market. `progress` is the same draft's funnel, the
    one the provider already counted. Null when the count is not known. */
export function untaggedUnder(
  index: ScopeIndex, catalog: ScopeCatalog, draft: ScopeAxesSelection, progress: WalkProgress,
): { untagged: number; of: number } | null {
  if (!progress.ready || isPending(progress, "subjects")) return null;
  const untagged = { ...index, cells: index.cells.filter((cell) => cell.domains.length === 0) };
  return { untagged: countUnderScope(untagged, layersOf(catalog, draft).roles), of: progress.kept.roles };
}

export interface VetoConflict {
  subject: string;
  track: TrackSlug;
  row: RoleRow;
  dropped: number;
  of: number;
}

/** "Not interested in" subjects that take out most of a role row the person
    picked on Which roles: "Finance & accounting" picked, and
    "Not interested in Finance & Accounting" said. The two steps ask about
    different things (what the role is; what the work is about) and mostly do
    not overlap, so neither is dropped; the one real contradiction is named. A row counts when that veto alone
    removes at least half of what Which roles keeps in it. */
export function vetoConflicts(
  index: ScopeIndex, catalog: ScopeCatalog, draft: ScopeAxesSelection,
): VetoConflict[] {
  const excluded = draft.excluded ?? new Set<string>();
  if (!index.ready || !draft.answers || excluded.size === 0) return [];
  const { roles: afterRoles } = layersOf(catalog, draft);
  const conflicts: VetoConflict[] = [];
  for (const [track, roles] of draft.answers) {
    if (roles === "any" || !isTrackSlug(track)) continue;
    for (const row of rowsPicked(track, roles)) {
      // The row as Which roles keeps it, before any interest.
      const only: ScopeAxesSelection = { ...afterRoles, answers: new Map([[track, new Set(row.families)]]) };
      const of = countUnderScope(index, only);
      if (of === 0) continue;
      for (const subject of excluded) {
        const dropped = of - countUnderScope(index, { ...only, excluded: new Set([subject]) });
        if (dropped * 2 >= of) conflicts.push({ subject, track, row, dropped, of });
      }
    }
  }
  return conflicts;
}

/** Places in the draft that a followed company's last scan never asked
    about. A source that lists only the places it is asked for
    (`scope_cells.scanned_places`) holds no roles for a place outside them yet,
    so the count reads short there until the save and that company's next
    scan. A place overlaps a scanned one when either sits inside the other. */
export function unscannedPlaces(
  catalog: ScopeCatalog,
  locations: ReadonlySet<string>,
): { places: string[]; companies: string[] } {
  const scanned = catalog.scope_cells?.scanned_places ?? {};
  const parents = new Map((catalog.locations ?? []).map((location) => [location.slug, location.parent ?? null]));
  const names = new Map((catalog.locations ?? []).map((location) => [location.slug, placeName(location)]));
  const chain = (slug: string) => {
    const out = [slug];
    for (let up = parents.get(slug); up; up = parents.get(up)) out.push(up);
    return out;
  };
  const overlaps = (a: string, b: string) => chain(a).includes(b) || chain(b).includes(a);
  const places = new Set<string>();
  const companies = new Set<string>();
  for (const [company, asked] of Object.entries(scanned)) {
    for (const place of locations) {
      if (asked.some((slug) => overlaps(place, slug))) continue;
      places.add(place);
      companies.add(company);
    }
  }
  const display = new Map((catalog.companies ?? []).map((company) => [company.slug, company.display]));
  return {
    places: [...places].map((slug) => names.get(slug) ?? slug),
    companies: [...companies].map((slug) => display.get(slug) ?? slug),
  };
}

/** Whether an optional step's saved answer removes roles from the step
    before it. It can while the step reads "any": the saved families are one
    list every answer shares, so another answer's narrowing (or one a dropped
    answer left behind) narrows this step too. The screen shows what the save
    does, not what the step's cards suggest. */
export function removes(progress: WalkProgress, step: "roles" | "subjects"): boolean {
  if (!progress.ready || isPending(progress, step)) return false;
  const before = FUNNEL_ORDER[FUNNEL_ORDER.indexOf(step) - 1];
  return progress.kept[step] < progress.kept[before];
}

/** "34%", "<1%", or "0%"; never a decimal — the bar is a feeling, not a fact. */
export function share(kept: number, total: number): string {
  if (total <= 0) return "0%";
  const percent = (kept / total) * 100;
  if (kept > 0 && percent < 1) return "<1%";
  return `${Math.round(percent)}%`;
}
