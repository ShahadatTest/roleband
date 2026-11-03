import {
  radarModeClosed,
  radarModeOpen,
} from "../../copy/gen/radar";
import { sharedNotForMe } from "../../copy/gen/shared";
import { DEFAULT_FILTERS, type Filters } from "../../api";
import { amount, flag, oneOf, slugs, type Decoder, type MemoryShape } from "../../hooks/filterMemory";
import { MODE_PARAM, type BoardMode } from "./boardMode";

/** A band slug a stored filter may still hold (`junior`), read as the band
 *  that covers it. The server folds `?level_band=junior` the same way. Kept
 *  here, not in the shell's `format.ts`: only the Board's memory reads it. */
const LEGACY_BAND: Record<string, string> = { junior: "entry" };

/** Remembered levels, a folded band read as its heir: a Level filter saved on
 *  Junior comes back as Entry / Junior, not as a chip no option matches. */
const levelSlugs: Decoder<string[]> = (raw) => {
  const values = slugs(raw);
  return values === undefined ? undefined : [...new Set(values.map((slug) => LEGACY_BAND[slug] ?? slug))];
};

// The mode's vocabulary lives alone so the shell can read it without this table.
export { BOARD_MODES, MODE_PARAM, modeFromParam, type BoardMode } from "./boardMode";
/* Here, not in boardMode.ts: only the Board route reads the list, and the
   shell loads boardMode.ts, so a list defined there ships in the startup chunk. */
export const MODE_PARAMS = Object.values(MODE_PARAM) as readonly string[];

type FilterKind = "queryContext" | "railFilter" | "externalLens" | "pagination" | "transport";
export interface BoardLenses { newSignalsOnly: boolean; repostsOnly: boolean }
type Field = {
  kind: FilterKind;
  group?: string;
  reset?: boolean;
  lens?: keyof BoardLenses;
  /** Part of the MODE: which population the board is showing.
   *
   *  A mode is queryContext for the BASELINE (the fraction beside the search
   *  box reads "12 of 42 open roles", never "12 of everything the board has
   *  ever seen") and a railFilter for everything else: it counts toward
   *  `Filters · N` like any filter. Those two facts pull
   *  in opposite directions, which is why the marker exists instead of a
   *  fourth `kind`.
   *
   *  The three modes live in `More filters`, where they ARE filters: open
   *  roles is the board's default view, reachable from the top bar's own
   *  count, and the other two are somewhere you go on purpose and come back
   *  from. */
  mode?: true;
};

/** Exhaustive ownership, including optional/transport keys. Adding a Filters
 * key must decide its reset/count/baseline semantics in the same change. */
export const FILTER_FIELDS = {
  company: { kind: "railFilter" },
  level_band: { kind: "railFilter" },
  family: { kind: "railFilter" },
  track: { kind: "railFilter" },
  location_group: { kind: "railFilter" },
  domain: { kind: "railFilter" },
  workplace_type: { kind: "railFilter" },
  status: { kind: "queryContext", mode: true },
  q: { kind: "queryContext" },
  base_min: { kind: "railFilter", group: "comp" },
  base_max: { kind: "railFilter", group: "comp" },
  posted_within_days: { kind: "railFilter" },
  new_today_only: { kind: "externalLens", lens: "newSignalsOnly" },
  repost_today_only: { kind: "externalLens", lens: "repostsOnly" },
  favorites_only: { kind: "transport" },
  dismissed_only: { kind: "queryContext", mode: true },
  discloses_pay: { kind: "railFilter" },
  viewed: { kind: "railFilter" },
  ids: { kind: "transport" },
  sort: { kind: "queryContext" },
  order: { kind: "queryContext" },
  include_related: { kind: "pagination", reset: true },
  limit: { kind: "pagination", reset: false },
  offset: { kind: "pagination", reset: true },
} as const satisfies { [K in keyof Filters]-?: Field };

const fields = Object.entries(FILTER_FIELDS) as [keyof Filters, Field][];

export function boardRequestFilters(filters: Filters, lenses: BoardLenses): Filters {
  return {
    ...filters,
    ...Object.fromEntries(fields.filter(([, field]) => field.lens)
      .map(([key, field]) => [key, lenses[field.lens!]])),
  };
}

/** One per chosen value, one per refinement (the comp pair is one), one per lens. */
/** What NARROWS the population you chose: everything the register does except
 *  choose it. This is the fraction's numerator test: "34 of 34 closed roles"
 *  is not a fraction, it is a count wearing one, because the mode picked the
 *  34 rather than filtering them down. */
export function countNarrowingFilters(filters: Filters, lenses: BoardLenses): number {
  const request = boardRequestFilters(filters, lenses);
  const groups = new Map<string, number>();
  for (const [key, field] of fields) {
    if (field.mode) continue;
    if (field.kind !== "railFilter" && field.kind !== "externalLens") continue;
    const value = request[key];
    const count = Array.isArray(value) ? value.length
      : value != null && value !== DEFAULT_FILTERS[key] ? 1 : 0;
    const group = field.group ?? key;
    groups.set(group, Math.max(groups.get(group) ?? 0, count));
  }
  return [...groups.values()].reduce((sum, count) => sum + count, 0);
}

/** Everything the reader can clear, mode included: the number on the folded
 *  register's opener and the drawer's own head. The mode counts as ONE, not
 *  two: `status` and `dismissed_only` move together. */
export function countActiveFilters(filters: Filters, lenses: BoardLenses): number {
  return countNarrowingFilters(filters, lenses) + (boardMode(filters) === "open" ? 0 : 1);
}

/* Which filters live behind the situational drawer. The register
 * ranks its groups by how often a reader reaches for them: Company, Location
 * and Level are always on screen; these are the questions asked once and then
 * dropped. The drawer wears this count on its head and opens itself when it is
 * non-zero, because a register may fold options away and may never fold STATE
 * away.
 *
 * The comp floor and ceiling are both here: split across the door, one filter
 * would make a reader setting a range meet the same control in two places.
 */
const SITUATIONAL: (keyof Filters)[] = [
  "family", "track", "posted_within_days", "discloses_pay",
  "base_min", "base_max", "workplace_type", "domain",
];

export function countSituationalFilters(filters: Filters): number {
  // The MODE is in here too, and it counts as one: a drawer showing nothing
  // on its head while hiding "Showing: Closed" is exactly the
  // state-folded-away this register may not do.
  const mode = boardMode(filters) === "open" ? 0 : 1;
  /* Grouped, the way `countNarrowingFilters` is. Counted per KEY, a
     floor-and-ceiling range would say "More filters · 2" under a summary
     reading "Filters · 1", and two numbers for one filter is the drawer
     miscounting rather than the reader mis-setting it. */
  const situational = new Set<keyof Filters>(SITUATIONAL);
  const groups = new Map<string, number>();
  for (const [key, field] of fields) {
    if (!situational.has(key)) continue;
    const value = filters[key];
    const count = Array.isArray(value) ? value.length
      : value != null && value !== DEFAULT_FILTERS[key] ? 1 : 0;
    const group = field.group ?? key;
    groups.set(group, Math.max(groups.get(group) ?? 0, count));
  }
  return [...groups.values()].reduce((sum, count) => sum + count, mode);
}

/** Query context, page size and transport survive Reset all.
 *
 * The MODE is NOT in here: it is URL state with exactly one writer, the route
 * (`onModeChange`). Patching it here as well would make two writers that
 * race, and the filters would go open while `?show=closed` stays in the
 * address bar. AppState lenses are also cleared by the toolbar; their request
 * projections reset here. */
export const RESET_FILTERS: Partial<Filters> = {
  ...Object.fromEntries(
    fields.filter(([, field]) => field.kind === "railFilter" || field.kind === "externalLens" || field.reset)
      .map(([key]) => [key, DEFAULT_FILTERS[key]]),
  ),
};

/* ---- what the board remembers between visits (hooks/filterMemory) --------- */

/** The storage key for the board's chosen filters. Its disclosures (which
 *  groups the reader opened) are a separate concern under `${SCOPE}:open`. */
export const BOARD_MEMORY_SCOPE = "board";

/** Exactly the `railFilter` keys, one decoder each, and that is a RULE rather
 *  than a list somebody curated: memory holds what the register narrows by and
 *  nothing else, so it lines up with `Reset all` and can be checked against
 *  `FILTER_FIELDS` (`filters.test.ts` names any key that drifts).
 *
 *  What that rule deliberately keeps OUT, each for its own reason:
 *
 *   - **the MODE** (`status`, `dismissed_only`). Open roles is the board's
 *     default view and the top bar's own count is the link back to it;
 *     a board that reopened on the Closed pile would leave that
 *     link reading inactive on every fresh load. The mode already survives a
 *     reload on its own: it is in `?show=`.
 *   - **the query** (`q`). It is the context a count is measured in, not a
 *     narrowing of it, and it lives in MissionState rather than here:
 *     remembering half of one search box is worse than remembering none of it.
 *   - **sort/order**. Not a filter: "Best fit" is the board's answer to what
 *     matters, and a sort chosen once for one question should not quietly
 *     outrank it for a month.
 *   - **the mission lenses** (`new_today_only`, `repost_today_only`). Their
 *     truth is the topbar chip in AppState; these keys are its projection on
 *     the wire, and storing a projection is how two writers start.
 *   - **paging and transport** (`offset`, `limit`, `include_related`, `ids`,
 *     `favorites_only`). A page number belongs to the list it was counted on.
 */
export const BOARD_MEMORY_SHAPE: MemoryShape<Filters> = {
  company: slugs,
  level_band: levelSlugs,
  family: slugs,
  track: slugs,
  location_group: slugs,
  domain: slugs,
  workplace_type: slugs,
  base_min: amount,
  base_max: amount,
  posted_within_days: amount,
  discloses_pay: flag,
  viewed: oneOf(["", "unread", "read"] as const),
};

/** A baseline removes narrowing, pagination/expansion and other-screen
 * transport constraints, retaining only this Board query's identity. */
export function baselineFilters(filters: Filters): Filters {
  return {
    ...DEFAULT_FILTERS,
    ...Object.fromEntries(fields.filter(([, field]) => field.kind === "queryContext")
      .map(([key]) => [key, filters[key]])),
    limit: 1,
  };
}

export function baselineKey(filters: Filters): string {
  return JSON.stringify(fields.filter(([, field]) => field.kind === "queryContext")
    .map(([key]) => [key, filters[key]]));
}

/* ---- the mode: which population, not how it is narrowed --------
 *
 * Open is the board's DEFAULT view and the top bar's own "N open roles" count
 * is the way back to it. Closed and Not-for-me are somewhere a
 * reader goes on purpose, rarely, so they live at the foot of
 * `More filters` rather than in a strip above every list.
 *
 * Not-for-me carries no status: a role the reader marked is theirs whatever
 * the market did with the posting, so `status` is cleared rather than pinned
 * to open; otherwise a role marked in June leaves the pile the night its
 * posting closes, which is the one place it has to stay.
 */
export const MODE_FILTERS: Record<BoardMode, Pick<Filters, "status" | "dismissed_only">> = {
  open: { status: "open", dismissed_only: false },
  closed: { status: "closed", dismissed_only: false },
  dismissed: { status: "", dismissed_only: true },
};

export const MODE_LABEL: Record<BoardMode, string> = {
  get open() { return radarModeOpen(); },
  get closed() { return radarModeClosed(); },
  get dismissed() { return sharedNotForMe(); },
};

/** The bin wins over the market: a role you marked is in the Not-for-me tab
 *  whatever its status, which is what makes the three modes a partition the
 *  user can reason about. */
export function boardMode(filters: Pick<Filters, "status" | "dismissed_only">): BoardMode {
  if (filters.dismissed_only) return "dismissed";
  return filters.status === "closed" ? "closed" : "open";
}

