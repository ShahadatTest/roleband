import { number as copyNumber } from "../../copy/format";
import type {
  CompanyConnectorState,
  CompanyDirectoryMatch,
  CompanyDiscoveryCompany,
  CompanyDiscoveryState,
  CompanyOpenCounts,
  SyncTarget,
} from "../../api";
import { roundCount } from "../../counts";
import { ownValue } from "../../format";
import { flag, type MemoryShape } from "../../hooks/filterMemory";
import { narrowedBy, type NarrowingFilter } from "../../ui/emptyFilters";
import {
  companiesModelOtherCompanies,
  companiesModelYourAdditions,
} from "../../copy/gen/companies";
import { sectorName } from "../../copy/vocab";

/** What the ordering and estimates read of the open counts: the numbers alone. */
type OpenCountsOnly = Pick<CompanyOpenCounts, "counts">;

/* What the Companies register IS, apart from the provider that fetches it.
 *
 * Every projection below is a pure function of the three payloads (discovery,
 * open counts, sync targets) and the reader's filters, so "does a company in
 * two sectors get counted twice?" is answered without rendering a provider.
 *
 * Two rules the whole file rests on:
 *
 *  - **A company may belong to several sectors**, so it draws a row in each.
 *    Every TOTAL is computed on the flat company array, never by summing
 *    sections, which would count those companies twice.
 *  - **One visibility rule.** `registerVisibility` is the only predicate that
 *    decides whether a row is drawn, and the empty state re-runs that exact
 *    predicate with one filter released rather than writing a parallel
 *    condition: a second condition written for the message would let the
 *    message and the list fall out of step.
 */

/** A company can only feed the radar if something can actually read its board.
 *  This split is the organizing axis: `planned`/`parked` entries stay trackable
 *  (the intent is recorded) but must never look like working ones. */
const CONNECTABLE: ReadonlySet<CompanyConnectorState> = new Set<CompanyConnectorState>([
  "live",
  "ready",
  "family",
  "active",
]);

export const isConnectable = (company: CompanyDiscoveryCompany) =>
  CONNECTABLE.has(company.connector_state);

/** The register's three narrowing filters, as one state. */
export type RegisterFilters = {
  query: string;
  trackedOnly: boolean;
  showPlanned: boolean;
};

export type RegisterFilterKey = "query" | "tracked" | "planned";

/** The two register lenses that are a standing CHOICE rather than a moment's
 *  question, so they are the two the register remembers
 *  (`hooks/useFilterMemory`). The search box is not one of them: a query is
 *  the context a count is measured in, not a narrowing of it, and a screen
 *  that reopened with words already typed into its search field reads as
 *  broken rather than as helpful. */
export const COMPANIES_MEMORY_SCOPE = "companies";

export type RegisterLenses = Pick<RegisterFilters, "trackedOnly" | "showPlanned">;

export const COMPANIES_MEMORY_SHAPE: MemoryShape<RegisterLenses> = {
  trackedOnly: flag,
  showPlanned: flag,
};

/** Companies added by careers-page URL belong to no sector; they still need a home. */
export const UNSORTED_SLUG = "unsorted";

/** Every other company RoleBand can scan: its own group, apart from
 *  URL additions, because it is a set RoleBand found rather than a choice the
 *  user typed in. Drawn only when it has rows. */
export const DIRECTORY_SLUG = "other-companies";

/** The end of the register, where companies not on it are added: the set of
 *  other companies, and one company by its link. A scroll target, not a group. */
export const ADD_MORE_SLUG = "add-more";

/** Hours since an ISO moment: null when there is none or it is not a date,
 *  and never negative (a server clock ahead of ours is no future age). Here,
 *  not in `format.ts`: the register is its only reader, and `format.ts` rides
 *  in the shell chunk. */
export function hoursSince(iso: string | null | undefined, now: number = Date.now()): number | null {
  if (!iso) return null;
  const at = Date.parse(iso);
  return Number.isNaN(at) ? null : Math.max(0, (now - at) / 3_600_000);
}

/** Hours -> the shortest form that stays honest: a table cell's "36h"/"3d"
 *  (48 h cut, no "ago"). Not `format.ageLabel`, the freshness wording
 *  ("3d ago", 24 h cut): a different question, kept apart. */
export function shortAge(hours: number | null): string | null {
  if (hours === null) return null;
  if (hours < 48) return `${Math.round(hours)}h`;
  return `${Math.round(hours / 24)}d`;
}

/** A large count said plainly: "about 10,000", never "about 10,214", which
 *  claims a precision a set rebuilt monthly does not have. */
export function aboutCount(n: number): string {
  return copyNumber(roundCount(n));
}

/** A directory search hit drawn as a register row before it is followed.
 *
 *  `ready`, because that is what it is: a board RoleBand can read that nobody
 *  follows yet. Once followed the roster answers with the stored row, which
 *  replaces this one (the provider drops a hit whose slug the roster holds). */
export function directoryHitCompany(match: CompanyDirectoryMatch): CompanyDiscoveryCompany {
  return {
    slug: match.slug,
    display: match.display,
    careers_url: null,
    sectors: [],
    aliases: [],
    connector_state: "ready",
    parked_reason: null,
    selectable: true,
    tracked: match.tracked,
    enabled: match.enabled,
    visible: true,
    builtin: false,
    curated: false,
    wall: null,
    consented: false,
    directory: true,
    status: null,
  };
}

export interface SectorGroup {
  slug: string;
  display: string;
  /** Every company in this sector, regardless of filters. */
  members: CompanyDiscoveryCompany[];
  connectable: CompanyDiscoveryCompany[];
  /** Select-all domain: connectable AND selectable. */
  bulk: CompanyDiscoveryCompany[];
  trackedCount: number;
  /** Null until the counts aggregate lands — never 0 as a stand-in. */
  openRoles: number | null;
  /** What the register actually draws, in order: connectable first, then the
   *  planned tail. One list, because the ledger has no per-sector disclosure —
   *  a planned company is a muted ROW, not a hidden one. */
  rows: CompanyDiscoveryCompany[];
  /** Planned members the "Show planned" switch is currently withholding. */
  hiddenPlanned: number;
  /** No connector reaches any member. Not the same as "you picked none". */
  dormant: boolean;
}

export type CompanyAlert =
  | { kind: "blocked"; companies: string[] }
  | { kind: "paused"; companies: string[] }
  | { kind: "hidden"; companies: string[] };

/** What a search reads of a company, lower-cased: its name, its aliases and
 *  its sectors' names. Kept per company object, since a keystroke asks for
 *  every company's at least once; a new roster or new sector names make new
 *  text. */
const searchTexts = new WeakMap<CompanyDiscoveryCompany, { names: Record<string, string>; text: string }>();
function searchText(company: CompanyDiscoveryCompany, sectorNames: Record<string, string>): string {
  const kept = searchTexts.get(company);
  if (kept && kept.names === sectorNames) return kept.text;
  const text = [
    company.display,
    ...company.aliases,
    ...company.sectors.map((slug) => sectorNames[slug] ?? slug),
  ]
    .join(" ")
    .toLocaleLowerCase();
  searchTexts.set(company, { names: sectorNames, text });
  return text;
}

/* The register's visibility rule, in ONE place. */
export function registerVisibility(
  { query, trackedOnly, showPlanned }: RegisterFilters,
  chosen: ReadonlySet<string>,
  sectorNames: Record<string, string>,
) {
  const needle = query.trim().toLocaleLowerCase();
  const matchesSearch = (company: CompanyDiscoveryCompany) =>
    !needle || searchText(company, sectorNames).includes(needle);
  const searching = needle.length > 0;
  // A search overrides the planned switch: a sector cannot advertise "3 match"
  // and then draw two rows.
  const plannedVisible = showPlanned || searching;
  const passes = (company: CompanyDiscoveryCompany) =>
    (!trackedOnly || chosen.has(company.slug)) && matchesSearch(company);
  return {
    searching,
    plannedVisible,
    passes,
    /** Exactly the rows a sector draws: `passes`, and planned only when shown. */
    visible: (company: CompanyDiscoveryCompany) =>
      passes(company) && (isConnectable(company) || plannedVisible),
  };
}

export function enabledSet(state: CompanyDiscoveryState): Set<string> {
  return new Set(state.companies.filter((company) => company.enabled).map((company) => company.slug));
}

/** What one write sends: the companies it names, split by whether `next`
 *  follows them. Nothing else is sent, because the roster changes under the
 *  screen (the wider-market scan follows companies by itself) and a write
 *  restating the whole selection would undo that. */
export function selectionChange(
  next: ReadonlySet<string>,
  slugs: readonly string[],
): { follow: string[]; unfollow: string[] } {
  const named = [...new Set(slugs)].sort();
  return {
    follow: named.filter((slug) => next.has(slug)),
    unfollow: named.filter((slug) => !next.has(slug)),
  };
}

export function sectorNameMap(state: CompanyDiscoveryState | null): Record<string, string> {
  return Object.fromEntries((state?.sectors ?? []).map((sector) => [sector.slug, sectorName(sector.slug)]));
}

/** `null` while the counts aggregate is still in flight — never 0 as a stand-in. */
export function openRolesLookup(
  counts: OpenCountsOnly | null | undefined,
): (slug: string) => number | null {
  const map = counts?.counts;
  return (slug: string) => (map ? (ownValue(map, slug) ?? 0) : null);
}

/** Tracked first, then by volume, then catalog order — evaluated once per
 *  rebuild, never per keystroke. The provider decides WHEN to rebuild; this
 *  decides what the order is. */
export function buildOrderIndex(
  state: CompanyDiscoveryState | null,
  chosen: ReadonlySet<string>,
  counts: OpenCountsOnly | null | undefined,
): Map<string, number> {
  const map = new Map<string, number>();
  if (!state) return map;
  const catalogIndex = new Map(state.companies.map((company, index) => [company.slug, index]));
  const roles = (slug: string) => ownValue(counts?.counts, slug) ?? 0;
  [...state.companies]
    .sort((left, right) => {
      const byTracked = (chosen.has(left.slug) ? 0 : 1) - (chosen.has(right.slug) ? 0 : 1);
      if (byTracked !== 0) return byTracked;
      if (counts) {
        const delta = roles(right.slug) - roles(left.slug);
        if (delta !== 0) return delta;
      }
      return (catalogIndex.get(left.slug) ?? 0) - (catalogIndex.get(right.slug) ?? 0);
    })
    .forEach((company, index) => map.set(company.slug, index));
  return map;
}

export function buildSectorGroups({
  state,
  chosen,
  filters,
  sectorNames,
  orderIndex,
  openRoles,
  countsReady,
  directoryHits = [],
}: {
  state: CompanyDiscoveryState | null;
  chosen: ReadonlySet<string>;
  filters: RegisterFilters;
  sectorNames: Record<string, string>;
  orderIndex: ReadonlyMap<string, number>;
  openRoles: (slug: string) => number | null;
  countsReady: boolean;
  /** Directory search hits the roster does not hold yet. */
  directoryHits?: readonly CompanyDiscoveryCompany[];
}): SectorGroup[] {
  if (!state) return [];
  const { plannedVisible, passes } = registerVisibility(filters, chosen, sectorNames);

  // Every list reads the frozen order above, so a sector's rows keep their
  // positions while you work through them.
  const byVolume = (left: CompanyDiscoveryCompany, right: CompanyDiscoveryCompany) =>
    (orderIndex.get(left.slug) ?? 0) - (orderIndex.get(right.slug) ?? 0);

  const build = (
    slug: string,
    display: string,
    members: CompanyDiscoveryCompany[],
    admit: (company: CompanyDiscoveryCompany) => boolean = passes,
  ): SectorGroup => {
    const connectable = members.filter(isConnectable);
    // Built BEFORE `bulk`, because `bulk` is derived from it. Select-all acts
    // on exactly the rows this sector is showing — see the `bulk` note below.
    const rows = [
      ...connectable.filter(admit).sort(byVolume),
      ...(plannedVisible
        ? members.filter((company) => !isConnectable(company)).filter(admit).sort(byVolume)
        : []),
    ];
    return {
      slug,
      display,
      members,
      connectable,
      // "Follow all" means every company in THIS sector that is on screen and
      // that the roster will accept — no exceptions, nothing from elsewhere.
      // So it is built from `rows`, not from all members: a search that left
      // one row on screen must not enroll the whole sector, and a visible
      // `planned` row must not be skipped while the sector claims complete.
      //
      // `selectable` stays in: it is the roster PUT's own guard (a `parked`
      // source raises `CompanyError` -> 400), so including one would fail the
      // whole write. `isConnectable` does not: tracking a `planned` company
      // is a supported action one row at a time, and the selection is defined
      // as recording intent without overstating connector readiness.
      bulk: rows.filter((company) => company.selectable),
      trackedCount: members.filter((company) => chosen.has(company.slug)).length,
      // Tracked members only: an untracked company is never collected, so
      // folding its 0 in would pass our own inaction off as a measurement.
      openRoles: countsReady
        ? members
            .filter((company) => chosen.has(company.slug))
            .reduce((total, company) => total + (openRoles(company.slug) ?? 0), 0)
        : null,
      rows,
      hiddenPlanned: plannedVisible
        ? 0
        : members.filter((company) => !isConnectable(company)).filter(passes).length,
      dormant: connectable.length === 0,
    };
  };

  const built = state.sectors.map((sector) =>
    build(
      sector.slug,
      sectorName(sector.slug),
      state.companies.filter((company) => company.sectors.includes(sector.slug)),
    ),
  );
  const orphans = state.companies.filter(
    (company) => company.sectors.length === 0 && !company.directory,
  );
  if (orphans.length > 0) {
    built.push(
      build(UNSORTED_SLUG, companiesModelYourAdditions(), orphans),
    );
  }
  const held = new Set(state.companies.map((company) => company.slug));
  const hits = directoryHits.filter((company) => !held.has(company.slug));
  const hitSlugs = new Set(hits.map((company) => company.slug));
  const listed = [...state.companies.filter((company) => company.directory), ...hits];
  if (listed.length > 0) {
    built.push(
      build(
        DIRECTORY_SLUG,
        companiesModelOtherCompanies(),
        listed,
        // A hit already matched on the server — by name or by its board's
        // address, which the row does not show — so the text filter must not
        // second-guess it. "Following only" still applies: a hit is unfollowed.
        (company) =>
          hitSlugs.has(company.slug)
            ? !filters.trackedOnly || chosen.has(company.slug)
            : passes(company),
      ),
    );
  }
  return built;
}

/* Why the register is empty, measured rather than guessed.
 *
 * `null` while it has rows. Otherwise every filter that is actually holding
 * rows back, each carrying what releasing it alone would reveal — so the copy
 * can say "2 in the catalog match" instead of asserting a company does not
 * exist. An empty array means no filter is responsible and the catalog itself
 * came back empty, which is a load problem and not something widening fixes.
 */
export function registerEmptyReasons({
  state,
  chosen,
  filters,
  sectorNames,
}: {
  state: CompanyDiscoveryState | null;
  chosen: ReadonlySet<string>;
  filters: RegisterFilters;
  sectorNames: Record<string, string>;
}): NarrowingFilter<RegisterFilterKey>[] | null {
  if (!state) return null;
  const count = (over: Partial<RegisterFilters>) =>
    state.companies.filter(
      registerVisibility({ ...filters, ...over }, chosen, sectorNames).visible,
    ).length;
  // Every company sits in at least one section (sectorless ones land in "Your
  // additions"), so "no company is visible" and "no section has rows" are the
  // same statement.
  if (count({}) > 0) return null;
  return narrowedBy<RegisterFilterKey>([
    { key: "query", active: filters.query.trim().length > 0, released: count({ query: "" }) },
    { key: "tracked", active: filters.trackedOnly, released: count({ trackedOnly: false }) },
    { key: "planned", active: !filters.showPlanned, released: count({ showPlanned: true }) },
  ]);
}

/** What the register says about roles it is tracking but cannot collect. */
export function buildAlerts(tracked: readonly CompanyDiscoveryCompany[]): CompanyAlert[] {
  const names = (predicate: (company: CompanyDiscoveryCompany) => boolean) =>
    tracked.filter(predicate).map((company) => company.display);
  const blocked = names((company) => company.connector_state === "parked");
  const paused = names(
    (company) => !isConnectable(company) && company.connector_state !== "parked",
  );
  const hidden = names((company) => !company.visible);
  const out: CompanyAlert[] = [];
  if (blocked.length) out.push({ kind: "blocked", companies: blocked });
  if (paused.length) out.push({ kind: "paused", companies: paused });
  if (hidden.length) out.push({ kind: "hidden", companies: hidden });
  return out;
}

/** The register's headline numbers, all computed on the flat tracked array. */
export function trackedSummary({
  tracked,
  openRoles,
  countsReady,
}: {
  tracked: readonly CompanyDiscoveryCompany[];
  openRoles: (slug: string) => number | null;
  countsReady: boolean;
}) {
  return {
    trackedTotal: tracked.length,
    trackedOpenRoles: countsReady
      ? tracked.reduce((total, company) => total + (openRoles(company.slug) ?? 0), 0)
      : null,
    trackedLive: tracked.filter(
      (company) => isConnectable(company) && company.connector_state !== "ready",
    ).length,
    trackedReady: tracked.filter((company) => company.connector_state === "ready").length,
    maxOpenRoles: countsReady
      ? Math.max(0, ...tracked.map((company) => openRoles(company.slug) ?? 0))
      : 0,
  };
}

/* The three projections of the sync-target payload. The run itself belongs to
 * the header; the register only says which companies it may ask for, how each
 * went last time, and which are worth retrying. */

export function syncableSlugs(targets: readonly SyncTarget[] | undefined): Set<string> {
  return new Set((targets ?? []).map((target) => target.slug));
}

export function sourceStatusLookup(
  targets: readonly SyncTarget[] | undefined,
): (slug: string) => SyncTarget | null {
  const map = new Map((targets ?? []).map((target) => [target.slug, target]));
  return (slug: string) => map.get(slug) ?? null;
}

export function failedSources(
  targets: readonly SyncTarget[] | undefined,
): { slug: string; display: string }[] {
  return (targets ?? [])
    .filter((target) => target.retryable)
    .map((target) => ({ slug: target.slug, display: target.display }));
}

/* --- The curated list ------------------------------------------------------
 *
 * RoleBand starts a user on a curated list of well-known companies. The
 * toolbar's Follow all widens that to every company listed in the sectors, and
 * Curated list only narrows it back. The API decides membership (`curated`,
 * one rule server-side); this file only decides which rows those two govern
 * and what following them would cost. */

/** Connector states that promise a scan. `active` is not one of them here: it
 *  is a company the user added by link, or found by name, which is their own
 *  choice and not part of any list RoleBand ships, so neither action touches it. */
const LISTED_STATES: ReadonlySet<CompanyConnectorState> = new Set<CompanyConnectorState>([
  "live",
  "ready",
  "family",
]);

/** The companies Follow all follows: every company in the sectors RoleBand can
 *  scan, curated or not. Planned and parked companies are never counted: the
 *  action promises companies it can scan. */
export function listedCompanies(state: CompanyDiscoveryState | null): CompanyDiscoveryCompany[] {
  if (!state) return [];
  return state.companies.filter(
    (company) => company.selectable && LISTED_STATES.has(company.connector_state),
  );
}

/** The companies Curated list only unfollows: the listed ones not curated. */
export function otherCompanies(state: CompanyDiscoveryState | null): CompanyDiscoveryCompany[] {
  return listedCompanies(state).filter((company) => !company.curated);
}

/** Roles a set of companies would likely add, read from stored open counts. */
export type FollowVolume = "thousands" | "hundreds" | null;

export interface FollowEstimate {
  /** `null` when the stored counts say too little to name an order of
   *  magnitude; the copy then says "more roles" rather than guess. */
  volume: FollowVolume;
}

/** The roles following `companies` would put on the radar, read from stored
 *  counts or absent, never estimated from a rule of thumb. Only a company that
 *  can be scanned brings roles. */
export function followEstimate(
  companies: readonly CompanyDiscoveryCompany[],
  counts: OpenCountsOnly | null | undefined,
): FollowEstimate {
  const scanned = companies.filter(isConnectable);
  const roles = scanned.reduce((sum, company) => sum + (ownValue(counts?.counts, company.slug) ?? 0), 0);
  const volume: FollowVolume = roles >= 1000 ? "thousands" : roles >= 100 ? "hundreds" : null;
  return { volume };
}
