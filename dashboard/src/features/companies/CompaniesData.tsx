import { errorText } from "../../api/errorText";
import { useToast } from "../../ui/Toast";
import type { NarrowingFilter } from "../../ui/emptyFilters";
import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useDeferredValue,
  useRef,
  useState,
} from "react";
import { useSearchParams } from "react-router-dom";
import type {
  CompanyConsent,
  CompanyDirectoryStatus,
  CompanyDiscoveryCompany,
  CompanyDiscoveryState,
  CompanyOpenCounts,
  SyncTarget,
} from "../../api";
import { api } from "../../api";
import { CURATED_LIST } from "../../copy/vocabulary";
import { awaitingConsent, consentsFor, type FollowConfirmation, type FollowCopy } from "./followCopy";
import { useSyncActions, useSyncStatus } from "../../context/SyncState";
import type { AsyncResource } from "../../hooks/useAsyncResource";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { useRememberedState } from "../../hooks/useFilterMemory";
import { useStableResource } from "../../hooks/useStableResource";
import { useWriteQueue } from "../../hooks/useWriteQueue";
import {
  ADD_MORE_SLUG,
  buildAlerts,
  DIRECTORY_SLUG,
  buildOrderIndex,
  aboutCount,
  buildSectorGroups,
  COMPANIES_MEMORY_SCOPE,
  directoryHitCompany,
  COMPANIES_MEMORY_SHAPE,
  enabledSet,
  failedSources,
  followEstimate,
  isConnectable,
  openRolesLookup,
  selectionChange,
  listedCompanies,
  otherCompanies,
  registerEmptyReasons,
  sectorNameMap,
  sourceStatusLookup,
  syncableSlugs,
  trackedSummary,
  UNSORTED_SLUG,
  type CompanyAlert,
  type RegisterFilterKey,
  type RegisterLenses,
  type SectorGroup,
} from "./companiesModel";
import {
  companiesDataChangeUndone,
  companiesDataCompanyAddedToYourRoster,
  companiesDataCouldnTUndoThatChange,
  companiesDataUndo,
  companiesDataUnfollowed,
  companiesDataCuratedFollowFailed,
  companiesDataCuratedFollowResult,
  companiesDataFollowFailed,
  companiesDataFollowed,
  companiesDataSectorFollowResult,
  companiesDataVisibilityChanged,
  companiesDataVisibilityFailed,
  companiesDataWiderMarketFailed,
  companiesDataWiderMarketResult,
} from "../../copy/gen/companies";

/* The register's projections live in `companiesModel.ts`; they are re-exported
 * here because the section and index components read them from this module,
 * and a screen should not have to know which file a derivation moved to. */
export {
  ADD_MORE_SLUG,
  DIRECTORY_SLUG,
  isConnectable,
  UNSORTED_SLUG,
  type CompanyAlert,
  type RegisterFilterKey,
  type RegisterFilters,
  type SectorGroup,
} from "./companiesModel";

/* Shared state for the Companies ledger and its sector index.
 *
 * The register and the index read the same derived numbers, and an index link
 * must SCROLL to a sector that lives in the register — the same coupling
 * `ScopeDraftProvider` solves for Scope, answered the same way here.
 *
 * Selection is one `Set<string>` keyed by slug. A company may belong to several
 * sectors, so it renders a card in each of them; one set means both cards
 * light together, which is the truth rather than a bug. Every total is computed
 * on the flat company array, never by summing sections, which would count
 * those companies twice. */

/** A write that did not land, named by its subject.
 *
 *  A failure belongs to the write that caused it: only that subject's next
 *  attempt may clear it. One slot cleared by ANY write would let per-company
 *  queues erase each other's failures, including the only explanation for a
 *  switch that just rolled back under the reader's hand. */
export interface WriteFailure {
  /** The subject. Toast key, and the only thing allowed to clear this entry. */
  key: string;
  /** The whole sentence, already naming the row or the sector. */
  text: string;
}

/** The subject sentence always, then why, when the failure's code says why
 *  (api/errorText.ts). The server's English is never shown. */
const failureText = (sentence: string, caught: unknown) => {
  const why = errorText(caught, "");
  return why ? `${sentence} ${why}` : sentence;
};

/** One roster write: what it intends, what it touches, and what it says in
 *  either outcome. An options object because the failure half doubled the
 *  positional arguments, and `slugs` alone carries three jobs (busy keys,
 *  rollback scope, the toast's undo target). */
interface RosterWrite {
  /** The selection this write intends to persist. */
  next: Set<string>;
  /** The rows it changes: busy keys, and exactly what a failure puts back. */
  slugs: string[];
  /** Subject identity for the failure slot — one company or one sector, so a
   *  sector's failure never silently replaces a row's. */
  key: string;
  /** What to say if it does not land. Names the subject. */
  failure: string;
  /** The confirmation, given the selection as it stood before the write. */
  describe: (previous: Set<string>) => string;
  /** Consents the answered dialog gave, one per walled company it starts to
   *  collect. The Undo carries none: the stored consent covers a
   *  follow it puts back, and an Undo of a follow only removes one. */
  consents?: CompanyConsent[];
}

/** What the directory search said about the current query. */
export interface DirectorySearchState {
  /** Companies in the directory at all. */
  size: number;
  /** Companies matching the query; more than `shown` means the list is capped. */
  matchCount: number;
  /** Matches drawn as rows. */
  shown: number;
}

export interface CompaniesContextValue {
  resource: AsyncResource<CompanyDiscoveryState>;
  counts: AsyncResource<CompanyOpenCounts>;
  chosen: Set<string>;
  groups: SectorGroup[];
  trackedTotal: number;
  catalogTotal: number;
  trackedOpenRoles: number | null;
  /** Of the companies YOU track, not of the catalog. The toolbar says "your",
   *  so a catalog-wide connector count there would answer another question. */
  trackedLive: number;
  trackedReady: number;
  openRoles: (slug: string) => number | null;
  /** Largest tracked count, so every volume bar in the register is drawn
   *  against the same scale rather than per-sector. */
  maxOpenRoles: number;
  /** What the last run made of this source: health, staleness, age. Already
   *  fetched for the sync affordances — the connector column reads the same
   *  answer rather than inventing a second one. */
  sourceStatus: (slug: string) => SyncTarget | null;
  sectorNames: Record<string, string>;
  /** Rows with a write outstanding — queued or in flight, whichever verb put
   *  it there. Counted by the queue, so neither writer can re-arm a row the
   *  other still holds. */
  busy: ReadonlySet<string>;
  /** Write failures, one per subject. NOT one slot: the writes are keyed, so
   *  the failures are too, or any other row's write erases a message that is
   *  the only account of what happened to this one. */
  failures: WriteFailure[];
  alerts: CompanyAlert[];
  /** The search the rows answer: the box's text (`useCompaniesQuery`), a
   *  render behind it while a keystroke's rows are drawn. */
  query: string;
  setQuery: (value: string) => void;
  /** True while a search narrows the register. Planned rows are forced visible
   *  here: hiding a match because of an unrelated switch is a lie about the
   *  result count the index just printed. */
  searching: boolean;
  /** The directory's answer to the current query; null with no query, or
   *  while the first answer for it is in flight. */
  directorySearch: DirectorySearchState | null;
  trackedOnly: boolean;
  setTrackedOnly: (value: boolean) => void;
  /** Why the register is empty — the filters actually holding rows back, each
   *  with what releasing it alone would reveal. `null` while rows are showing;
   *  `[]` when no filter is to blame and the catalog itself is empty. */
  registerEmpty: NarrowingFilter<RegisterFilterKey>[] | null;
  showPlanned: boolean;
  setShowPlanned: (value: boolean) => void;
  focusedSector: string | null;
  focusSector: (slug: string) => void;
  scrollTarget: string | null;
  clearScrollTarget: () => void;
  toggleCompany: (company: CompanyDiscoveryCompany) => void;
  /** Follow all asks first (see `FollowConfirmation`); Unfollow all does not. */
  toggleSector: (group: SectorGroup) => void;

  /* --- The curated list ------------------------------------------------- */
  /** What the toolbar's list action does now: follow every listed company
   *  still unfollowed, go back to the curated list, or nothing to offer. */
  listAction: "follow-all" | "curated-only" | null;
  /** Ask to follow every listed company, or to unfollow all but the curated. */
  requestListAction: () => void;
  /** Ask to follow every listed company and the set of other companies, as
   *  one answer (setup's "Plus other companies"). */
  requestEverything: () => void;
  /** Followed walled companies the user never consented to: not scanned until the
   *  user answers their dialog. */
  awaitingConsent: CompanyDiscoveryCompany[];
  /** Open a followed walled company's consent dialog. */
  reviewConsent: (company: CompanyDiscoveryCompany) => void;
  /** The bulk write waiting on an answer, if any. */
  confirmation: FollowConfirmation | null;
  confirmFollow: (shown: { copy: FollowCopy; locale: string }) => void;
  dismissFollow: () => void;
  toggleVisible: (company: CompanyDiscoveryCompany) => Promise<void>;
  addByUrl: (payload: { name: string; careers_url: string }) => Promise<void>;

  /* --- Sync ------------------------------------------------------------- */
  /** Slugs a targeted sync may actually cover, straight from the pipeline's own
   *  target set. Tracked-and-connectable is close but not identical, and the
   *  card must not offer a run the backend would refuse. */
  syncable: Set<string>;
  /** Tracked sources worth re-attempting after the last full run. */
  failedSources: { slug: string; display: string }[];
}

/* The poll-derived pair, deliberately NOT in the value above.
 *
 * `useSyncStatus()` hands back a new object every poll, every 3 seconds while a
 * scrape runs. Read in the main value, it would re-render every register row on
 * each tick for a boolean that had not moved, and memoising the main value
 * cannot help: a memo over a dependency with a new identity every 3s has a new
 * identity every 3s.
 *
 * So `CompaniesDataProvider` never calls `useSyncStatus`. `CompaniesSyncProvider`
 * below is the only subscriber, it renders nothing but its children, and its
 * own value is keyed on `syncRunning`, a BOOLEAN, so a tick that does not flip
 * it produces no new identity either. `CompaniesData.isolation.test.tsx` holds
 * this by render count. */
/** What the register says about a scan it asked for, either way round.
 *
 *  The board's notice answers ONE question — did the ask land — and the run
 *  itself reports through the header control and the notification centre's
 *  per-company progress panel. So a failed trigger is the board's business
 *  (its ask did not land) and a failed RUN is not. */
export interface ScanNotice {
  /** The confirmation, raised only once the trigger has actually landed. */
  confirm: string;
  /** The confirmation when the companies joined the live run instead. */
  joined?: string;
  /** What to say when it did not. Names the company or the set. */
  failure: string;
}

export interface CompaniesSyncValue {
  /** A run is in flight or queued: there is only ever one. */
  syncRunning: boolean;
  /** The run is live, so a company asked for by name joins it. */
  scanLive: boolean;
  syncCompanies: (slugs: string[], notice: ScanNotice) => void;
}

/** The set of other companies, published apart from the register.
 *
 *  Its status is polled while the background scan is on its first pass, and
 *  every answer is a new object whose counts have moved. In the register's
 *  value it would re-render every row on each poll for a card only the end
 *  of the list draws, so only that card subscribes to it. The verbs that act
 *  on the set read the status through a ref, which keeps them, and the
 *  register's value, at one identity across polls.
 *  `CompaniesData.isolation.test.tsx` holds this by render count. */
interface CompaniesDirectoryValue {
  /** The whole set: its size, whether it is followed, and how far the
   *  background scan has read it. Null until it loads. */
  status: CompanyDirectoryStatus | null;
  /** Follow the whole set (asks first) or stop following it (does not). */
  requestDirectory: (following: boolean) => void;
}

/** The search box's own text. Apart from the register's value because it
 *  changes on every keystroke, and the rows follow it a render behind. */
export interface CompaniesQueryValue {
  query: string;
  setQuery: (value: string) => void;
}

const CompaniesContext = createContext<CompaniesContextValue | null>(null);
const CompaniesQueryContext = createContext<CompaniesQueryValue | null>(null);
const CompaniesSyncContext = createContext<CompaniesSyncValue | null>(null);
const CompaniesDirectoryContext = createContext<CompaniesDirectoryValue | null>(null);

export function useCompanies(): CompaniesContextValue {
  const value = useContext(CompaniesContext);
  if (!value) throw new Error("useCompanies must be used inside CompaniesDataProvider");
  return value;
}

export function useCompaniesQuery(): CompaniesQueryValue {
  const value = useContext(CompaniesQueryContext);
  if (!value) throw new Error("useCompaniesQuery must be used inside CompaniesDataProvider");
  return value;
}

export function useCompaniesSync(): CompaniesSyncValue {
  const value = useContext(CompaniesSyncContext);
  if (!value) throw new Error("useCompaniesSync must be used inside CompaniesDataProvider");
  return value;
}

export function useCompanyDirectory(): CompaniesDirectoryValue {
  const value = useContext(CompaniesDirectoryContext);
  if (!value) throw new Error("useCompanyDirectory must be used inside CompaniesDataProvider");
  return value;
}

/** The one subscriber to the sync poll. Renders only `children`, so a tick
 *  re-renders this component and nothing that reads the roster. */
function CompaniesSyncProvider({
  children,
  onSynced,
  reportFailure,
  clearFailure,
}: {
  children: ReactNode;
  onSynced: () => void;
  /* A REPORT path, not a clear-only `setError`: one that existed solely to
     blank a shared slot would let asking for a scan erase another row's write
     failure. These two speak for the `scan` subject and nothing else. */
  reportFailure: (key: string, text: string) => void;
  clearFailure: (key: string) => void;
}) {
  const { syncing, status } = useSyncStatus();
  const { triggerSync } = useSyncActions();
  const { toast } = useToast();

  // Guards a second trigger, so it must count queued work too: `running` is
  // a live pipeline only, and a request waiting for the next tick is just as
  // much a reason not to ask for another.
  const scanLive = status?.running ?? false;
  const syncRunning = syncing || scanLive || (status?.manual_queued?.length ?? 0) > 0;

  const syncCompanies = useCallback(
    (slugs: string[], notice: ScanNotice) => {
      if (slugs.length === 0 || (syncRunning && !scanLive)) return;
      // Only the `scan` subject, cleared as this attempt starts, so asking for
      // a scan never erases the account of a row write that just failed.
      clearFailure("scan");
      void triggerSync(slugs).then((started) => {
        if (!started) {
          // `triggerSync` swallows its own error to retire the optimistic
          // bridge and resolves either way, so `started` is the only sign
          // that the scan did not begin.
          reportFailure("scan", notice.failure);
          return;
        }
        toast({ key: "companies-sync", text: started === "joined" ? notice.joined ?? notice.confirm : notice.confirm });
        // Freshness and outcomes have moved on; the picker's own copy refetches
        // when it next opens, and this one is what the connector column and
        // the failed-source list read.
        onSynced();
      });
    },
    [syncRunning, scanLive, triggerSync, toast, onSynced, reportFailure, clearFailure],
  );

  const value = useMemo<CompaniesSyncValue>(
    () => ({ syncRunning, scanLive, syncCompanies }),
    [syncRunning, scanLive, syncCompanies],
  );
  return <CompaniesSyncContext.Provider value={value}>{children}</CompaniesSyncContext.Provider>;
}

export function CompaniesDataProvider({ children }: { children: ReactNode }) {
  /* Both published resources are held at a stable identity. `useAsyncResource`
     rebuilds its result literal every render, and these two are IN the context
     value — so without this the value can never be memoized and every register
     cell re-renders on any provider render. */
  const resource = useStableResource(useAsyncResource(api.companyDiscovery, [], { keep: "companies/discovery" }));
  // Second, independent request on purpose: this aggregate scans `jobs`, and
  // bundled into the roster payload it would hold the entire screen blank
  // behind it. The board paints as soon as it lands; each card fills its
  // count in place when this one does.
  const counts = useStableResource(useAsyncResource(api.companyOpenCounts, [], { keep: "companies/open-counts" }));
  // Third read, and the only one that knows about *runs*: which companies the
  // pipeline would accept, when each was last attempted, and how it went.
  const syncTargets = useAsyncResource(api.syncTargets, [], { keep: "companies/sync-targets" });
  const [searchParams, setSearchParams] = useSearchParams();
  /* Switches clicked whose write has not answered yet, oldest first, each
     slug with the state it was switched to. The screen shows the roster the
     server last answered with these laid over it, so an answer to an earlier
     write, or a refresh, never flips back a switch that is still on its way,
     and a write that fails puts back only what it touched. */
  const [pending, setPending] = useState<{ id: number; targets: Map<string, boolean> }[]>([]);
  const pendingIds = useRef(0);
  const [query, setQuery] = useState("");
  /* The rows follow the box one render behind: a keystroke paints the box at
     once, and the rows it matches are drawn in a render the next keystroke can
     interrupt. A first letter can match most of the catalog. */
  const shownQuery = useDeferredValue(query);
  const queryValue = useMemo<CompaniesQueryValue>(() => ({ query, setQuery }), [query]);
  /* The two standing lenses are REMEMBERED across visits; the query is not
     (companiesModel.ts says why). One state object rather than two, because
     that is the unit memory stores. */
  const [lenses, setLenses] = useRememberedState<RegisterLenses>({
    scope: COMPANIES_MEMORY_SCOPE,
    defaults: { trackedOnly: false, showPlanned: true },
    shape: COMPANIES_MEMORY_SHAPE,
  });
  const { trackedOnly, showPlanned } = lenses;
  const setTrackedOnly = useCallback(
    (value: boolean) => setLenses((prev) => ({ ...prev, trackedOnly: value })),
    [setLenses],
  );
  const setShowPlanned = useCallback(
    (value: boolean) => setLenses((prev) => ({ ...prev, showPlanned: value })),
    [setLenses],
  );
  const [scrollTarget, setScrollTarget] = useState<string | null>(null);
  const [failures, setFailures] = useState<WriteFailure[]>([]);
  const { toast } = useToast();

  /* Every write this screen makes, in one queue.
   *
   * Two shapes, and one chain is wrong for both. Visibility PATCHes one row,
   * so two rows must not wait on each other: one slow write would stall every
   * other eye. The roster PUT replaces the WHOLE selection
   * (`row.enabled = row.slug in desired`), so it has to order against every
   * outstanding write in both directions: it cannot start while a row PATCH is
   * in the air, because its response echoes a `visible` that is about to change
   * and the screen adopts that echo wholesale; and nothing may start while it
   * is, for the same reason in reverse.
   *
   * A generation ref would not do: it decides what the SCREEN adopts, never
   * what the database keeps, so two full-roster PUTs in the air would leave the
   * install on whichever transaction committed last while the screen shows the
   * one that answered last. `busy` is the queue's too, counted per row across
   * both verbs, so no writer can re-arm a row over work still outstanding.
   *
   * No stale-response guard anywhere near this: submission order is total, so
   * there is no out-of-order response for one to catch.
   *
   * Destructured, because the verbs must stay STABLE while `busy` moves. The
   * queue object's identity tracks `busy`/`writing`, so depending on the object
   * would hand every verb below a new identity on every write — and an unstable
   * verb is what the memoized context value exists to avoid. */
  const { exclusive: writeExclusive, keyed: writeKeyed, busy } = useWriteQueue("companies-register");

  const state = resource.data;
  const chosen = useMemo(() => {
    const shown = state ? enabledSet(state) : new Set<string>();
    for (const { targets } of pending) {
      for (const [slug, follows] of targets) {
        if (follows) shown.add(slug);
        else shown.delete(slug);
      }
    }
    return shown;
  }, [state, pending]);

  const openRoles = useMemo(() => openRolesLookup(counts.data), [counts.data]);

  const sectorNames = useMemo(() => sectorNameMap(state ?? null), [state]);

  const needle = shownQuery.trim();

  /* The whole set as one followable thing. Polled only while the
     background scan is still on its first pass, so the progress line moves;
     once every company has been read once there is nothing to watch. */
  const directoryStatus = useAsyncResource(api.companyDirectoryStatus, [], { keep: "companies/directory-status" });
  const { refresh: refreshDirectory, mutate: mutateDirectory } = directoryStatus;
  const scanStatus = directoryStatus.data;
  // The verbs read the status here, at the click, so a poll gives none of
  // them a new identity.
  const scanStatusRef = useRef(scanStatus);
  useEffect(() => { scanStatusRef.current = scanStatus; }, [scanStatus]);
  const firstPass = Boolean(scanStatus?.following && scanStatus.checked < scanStatus.to_check);
  useEffect(() => {
    if (!firstPass) return;
    const timer = setInterval(() => void refreshDirectory({ preserveData: true }), 15_000);
    return () => clearInterval(timer);
  }, [firstPass, refreshDirectory]);
  // A company the scan followed is a new roster row: read the roster again
  // when that count moves, so it appears under "Other companies".
  const withRoles = scanStatus?.with_roles ?? null;
  const seenWithRoles = useRef<number | null>(null);
  useEffect(() => {
    if (withRoles === null) return;
    if (seenWithRoles.current !== null && withRoles !== seenWithRoles.current) {
      // In the write queue: a read that started before a roster write could
      // otherwise answer after it, with the roster from before.
      void writeExclusive([], () => resource.refresh({ preserveData: true }));
      void counts.refresh({ preserveData: true });
    }
    seenWithRoles.current = withRoles;
  }, [withRoles, resource, counts, writeExclusive]);

  /* The directory is searched on the server: it is far too large to load, so
     the register asks for the few matching what was typed, never for the set.
     Debounced so a word typed at speed is one request, and under two
     characters nothing is asked at all: the server would answer nothing. */
  const [directoryNeedle, setDirectoryNeedle] = useState("");
  useEffect(() => {
    const next = needle.length >= 2 ? needle : "";
    if (!next) {
      setDirectoryNeedle("");
      return;
    }
    const timer = setTimeout(() => setDirectoryNeedle(next), 200);
    return () => clearTimeout(timer);
  }, [needle]);
  const directory = useAsyncResource(
    (signal) =>
      directoryNeedle ? api.searchCompanyDirectory(directoryNeedle, signal) : Promise.resolve(null),
    [directoryNeedle],
  );
  // Only an answer to the query on screen: a stale one would draw rows for a
  // word the reader has already deleted.
  const directoryAnswer = needle && directory.data && directoryNeedle === needle ? directory.data : null;
  const directoryHits = useMemo(
    () => (directoryAnswer ? directoryAnswer.matches.map(directoryHitCompany) : []),
    [directoryAnswer],
  );
  const directorySearch = useMemo<DirectorySearchState | null>(
    () =>
      directoryAnswer
        ? {
            size: directoryAnswer.size,
            matchCount: directoryAnswer.match_count,
            shown: directoryAnswer.matches.length,
          }
        : null,
    [directoryAnswer],
  );

  /* Row order is a SNAPSHOT, deliberately not a live function of selection.
   *
   * Ranking tracked-first straight off `chosen` would re-sort the list the
   * instant a switch flipped: the company you just touched would jump to the
   * top of its sector and everything between it would shift. Toggling
   * something is not a request to rearrange the page around it.
   *
   * So the order is recomputed only when the list is genuinely rebuilt (load,
   * search, a scope toggle, a company added, counts arriving) and never when
   * the selection changes. `orderKey` is exactly that list of triggers, and
   * `chosen` is read inside on purpose while being absent from the deps: the
   * memo captures the selection as it stood the last time the list was rebuilt.
   * A new selection takes effect in the order the next time you search, filter
   * or reload, which is what keeps the row under your cursor still. */
  const orderKey = [
    needle,
    trackedOnly,
    showPlanned,
    state?.companies.length ?? 0,
    counts.data ? 1 : 0,
    // The roster arrives once; that first transition has to produce a
    // snapshot, or nothing would rank as tracked.
    state ? 1 : 0,
  ].join("|");

  const orderSnapshot = useRef<{ key: string; value: Map<string, number> } | null>(null);
  if (!orderSnapshot.current || orderSnapshot.current.key !== orderKey) {
    // A keyed ref states the snapshot contract without lying to a dependency
    // analyzer: payload identities and selection may change while this key is
    // stable, and those changes deliberately keep row order frozen.
    orderSnapshot.current = { key: orderKey, value: buildOrderIndex(state ?? null, chosen, counts.data) };
  }
  const orderIndex = orderSnapshot.current.value;

  const groups = useMemo<SectorGroup[]>(
    () =>
      buildSectorGroups({
        state: state ?? null,
        chosen,
        filters: { query: shownQuery, trackedOnly, showPlanned },
        sectorNames,
        orderIndex,
        openRoles,
        countsReady: Boolean(counts.data),
        directoryHits,
      }),
    [
      state, chosen, counts.data, openRoles, orderIndex, shownQuery, trackedOnly, showPlanned,
      sectorNames, directoryHits,
    ],
  );

  /* Why the register is empty, measured rather than guessed.
   *
   * `null` while it has rows. Otherwise every filter that is actually holding
   * rows back, each carrying what releasing it alone would reveal — so the copy
   * can say "2 in the catalog match" instead of asserting a company does not
   * exist. An empty array means no filter is responsible and the catalog itself
   * came back empty, which is a load problem and not something widening fixes.
   */
  const registerEmpty = useMemo<NarrowingFilter<RegisterFilterKey>[] | null>(
    () =>
      registerEmptyReasons({
        state: state ?? null,
        chosen,
        filters: { query: shownQuery, trackedOnly, showPlanned },
        sectorNames,
      }),
    [state, chosen, shownQuery, trackedOnly, showPlanned, sectorNames],
  );

  const focusedSector = useMemo(() => {
    const requested = searchParams.get("sector");
    if (!requested) return null;
    if ([UNSORTED_SLUG, DIRECTORY_SLUG, ADD_MORE_SLUG].includes(requested)) return requested;
    return state?.sectors.some((sector) => sector.slug === requested) ? requested : null;
  }, [state, searchParams]);

  // A deep link should land ON its sector, not merely expand it somewhere below.
  const deepLinked = useRef(false);
  useEffect(() => {
    if (deepLinked.current || !state || !focusedSector) return;
    deepLinked.current = true;
    setScrollTarget(focusedSector);
  }, [state, focusedSector]);

  // `?sector=` focuses a section — it scrolls to it and marks it current in the
  // index. It deliberately does NOT filter: hiding the other sectors would put
  // a selector before the list, which this screen avoids.
  const focusSector = useCallback(
    (slug: string) => {
      const params = new URLSearchParams(searchParams);
      params.set("sector", slug);
      setSearchParams(params, { replace: true });
      setScrollTarget(slug);
    },
    [searchParams, setSearchParams],
  );

  /* Cleared as the write STARTS, not as it is queued: a failure belongs on
     screen until something newer is actually being attempted — and only its
     own subject's next attempt may clear it. */
  const clearFailure = useCallback((key: string) => {
    setFailures((current) => (current.some((entry) => entry.key === key)
      ? current.filter((entry) => entry.key !== key)
      : current));
  }, []);

  const reportFailure = useCallback((key: string, text: string) => {
    setFailures((current) => [...current.filter((entry) => entry.key !== key), { key, text }]);
  }, []);

  const clearScrollTarget = useCallback(() => setScrollTarget(null), []);

  /** Apply a selection change. The roster PUT is atomic and returns the whole
   *  discovery state, so one call both writes and refreshes — which is exactly
   *  why it is `exclusive` and not merely serialized against its own kind. */
  const commit = useCallback(
    (write: RosterWrite) => {
      if (!state) return Promise.resolve();
      const { next, slugs, key, failure, describe, consents } = write;
      const previous = chosen;
      const request = selectionChange(next, slugs);
      // Optimistic at the CLICK, not at the write. The queue may hold this
      // behind another one, and a switch that does not move until then reads
      // as a dead control; the request itself is already fixed, so what the
      // screen shows and what the server is told cannot drift apart.
      const id = ++pendingIds.current;
      setPending((current) => [...current, { id, targets: new Map(slugs.map((slug) => [slug, next.has(slug)])) }]);
      const settle = () => setPending((current) => current.filter((entry) => entry.id !== id));
      return writeExclusive(slugs, async () => {
        clearFailure(key);
        try {
          const saved = await api.setCompanySelection(request, consents ?? []);
          resource.mutate(() => saved);
          settle();
          toast({
            key: "companies-selection",
            text: describe(previous),
            action: {
              label: companiesDataUndo(),
              // Through the ref: a verb whose own undo calls it cannot list
              // itself as a dependency, and an unstable verb is what the
              // memoized context value exists to avoid.
              onClick: () => void commitRef.current({
                next: previous,
                slugs,
                key,
                failure: companiesDataCouldnTUndoThatChange(),
                describe: () => companiesDataChangeUndone(),
              }),
            },
          });
        } catch (caught) {
          // These rows go back to what the server holds; a later click on
          // them, still waiting, keeps its own overlay.
          settle();
          reportFailure(key, failureText(failure, caught));
        }
      });
    },
    [state, chosen, writeExclusive, resource, toast, clearFailure, reportFailure],
  );
  const commitRef = useRef(commit);
  useEffect(() => { commitRef.current = commit; }, [commit]);

  const writeCompany = useCallback((
    company: CompanyDiscoveryCompany,
    tracking: boolean,
    consents?: CompanyConsent[],
  ) => {
    const next = new Set(chosen);
    if (tracking) next.add(company.slug);
    else next.delete(company.slug);
    void commit({
      next,
      slugs: [company.slug],
      consents,
      key: `roster:${company.slug}`,
      failure: companiesDataFollowFailed({ direction: tracking ? "follow" : "unfollow", name: company.display }),
      describe: () => {
        if (!tracking) return companiesDataUnfollowed({ display: company.display });
        return companiesDataFollowed({ coverage: isConnectable(company) ? "covered" : "uncovered", company: company.display });
      },
    });
  }, [chosen, commit]);

  const [confirmation, setConfirmation] = useState<FollowConfirmation | null>(null);

  /** A walled company the user never consented to is followed through its own
   *  dialog: it states the company's policy, and following through it is the
   *  consent. Consent is asked once, so a company already consented to follows
   *  from the switch alone. Unfollowing a walled company always confirms. */
  const toggleCompany = useCallback((company: CompanyDiscoveryCompany) => {
    const tracking = !chosen.has(company.slug);
    if (tracking && awaitingConsent([company]).length > 0) {
      setConfirmation({ kind: "walled-follow", company });
      return;
    }
    if (!tracking && company.wall !== null) {
      setConfirmation({ kind: "walled-unfollow", company });
      return;
    }
    writeCompany(company, tracking);
  }, [chosen, writeCompany]);

  /** A followed walled company with no stored consent is not scanned until
   *  its user answers the same dialog a new follow gets. */
  const reviewConsent = useCallback((company: CompanyDiscoveryCompany) => {
    setConfirmation({ kind: "walled-follow", company });
  }, []);

  /** Select-all covers exactly `group.bulk` — this sector's on-screen rows that
   *  the roster will accept. One write. */
  const writeSector = useCallback((group: SectorGroup, tracking: boolean, consents?: CompanyConsent[]) => {
    const next = new Set(chosen);
    for (const company of group.bulk) {
      if (tracking) next.add(company.slug);
      else next.delete(company.slug);
    }
    const slugs = group.bulk.map((company) => company.slug);
    // The notice states what was actually written. A sector's rows can include
    // companies no connector reaches yet, and silently enrolling those under
    // the word "tracking" would overstate what the switch just bought.
    const paused = group.bulk.filter((company) => !isConnectable(company)).length;
    void commit({
      next,
      slugs,
      consents,
      // The sector is the subject, not its forty rows: one failure, named once.
      key: `roster:sector:${group.slug}`,
      failure: companiesDataFollowFailed({ direction: tracking ? "follow" : "unfollow", name: group.display }),
      describe: () =>
        companiesDataSectorFollowResult({ direction: tracking ? "follow" : "unfollow", sector: group.display, paused }),
    });
  }, [chosen, commit]);

  const toggleSector = useCallback((group: SectorGroup) => {
    const on = group.bulk.filter((company) => chosen.has(company.slug)).length;
    const tracking = on < group.bulk.length;
    if (!tracking) {
      writeSector(group, false);
      return;
    }
    const adding = group.bulk.filter((company) => !chosen.has(company.slug));
    // One company is what its own row's switch does, and that does not ask —
    // unless it is walled, when its own switch asks too.
    if (adding.length < 2) {
      if (awaitingConsent(adding).length > 0) setConfirmation({ kind: "walled-follow", company: adding[0] });
      else writeSector(group, true);
      return;
    }
    setConfirmation({
      kind: "sector",
      group,
      companies: adding,
      estimate: followEstimate(adding, counts.data),
    });
  }, [chosen, writeSector, counts.data]);

  const listed = useMemo(() => listedCompanies(state ?? null), [state]);
  const others = useMemo(() => otherCompanies(state ?? null), [state]);
  const unfollowedListed = useMemo(
    () => listed.filter((company) => !chosen.has(company.slug)),
    [listed, chosen],
  );
  const followedOthers = useMemo(
    () => others.filter((company) => chosen.has(company.slug)),
    [others, chosen],
  );
  // Follow all while anything listed is unfollowed; once everything is, the
  // same place offers the way back.
  const listAction: CompaniesContextValue["listAction"] =
    unfollowedListed.length > 0 ? "follow-all" : followedOthers.length > 0 ? "curated-only" : null;

  const requestListAction = useCallback(() => {
    if (unfollowedListed.length > 0) {
      setConfirmation({
        kind: "include",
        companies: unfollowedListed,
        estimate: followEstimate(unfollowedListed, counts.data),
      });
    } else if (followedOthers.length > 0) {
      setConfirmation({ kind: "exclude", companies: followedOthers });
    }
  }, [unfollowedListed, followedOthers, counts.data]);

  const requestEverything = useCallback(() => {
    setConfirmation({ kind: "everything", companies: unfollowedListed });
  }, [unfollowedListed]);

  const dismissFollow = useCallback(() => setConfirmation(null), []);

  /** The whole set, followed or not, in one write. Exclusive: stopping it
   *  switches roster rows off, so it orders against every roster write. */
  const writeDirectory = useCallback(
    (following: boolean) =>
      writeExclusive([], async () => {
        clearFailure("directory");
        try {
          // How many the set had added, read before stopping clears it.
          const added = scanStatusRef.current?.with_roles ?? 0;
          const status = await api.followCompanyDirectory(following);
          mutateDirectory(() => status);
          await resource.refresh({ preserveData: true });
          toast({
            key: "companies-directory",
            text: companiesDataWiderMarketResult({
              state: !following ? "stopped" : status.waiting_for_power ? "waiting" : "scanning",
              size: aboutCount(status.size),
              added,
            }),
            action: {
              label: companiesDataUndo(),
              onClick: () => void writeDirectoryRef.current(!following),
            },
          });
        } catch (caught) {
          reportFailure("directory", failureText(
            companiesDataWiderMarketFailed({ direction: following ? "start" : "stop" }),
            caught,
          ));
        }
      }),
    [writeExclusive, clearFailure, mutateDirectory, resource, toast, reportFailure],
  );
  const writeDirectoryRef = useRef(writeDirectory);
  useEffect(() => { writeDirectoryRef.current = writeDirectory; }, [writeDirectory]);

  const requestDirectory = useCallback((following: boolean) => {
    if (following) {
      setConfirmation({ kind: "directory", size: scanStatusRef.current?.size ?? 0 });
      return;
    }
    void writeDirectory(false);
  }, [writeDirectory]);

  const directoryValue = useMemo<CompaniesDirectoryValue>(
    () => ({ status: scanStatus, requestDirectory }),
    [scanStatus, requestDirectory],
  );

  /** The answer. One roster write either way, with the usual Undo. */
  const confirmFollow = useCallback((shown: { copy: FollowCopy; locale: string }) => {
    const pending = confirmation;
    setConfirmation(null);
    if (!pending) return;
    const consents = consentsFor(pending, shown);
    if (pending.kind === "sector") {
      writeSector(pending.group, true, consents);
      return;
    }
    if (pending.kind === "walled-follow" || pending.kind === "walled-unfollow") {
      writeCompany(pending.company, pending.kind === "walled-follow", consents);
      return;
    }
    if (pending.kind === "directory") {
      void writeDirectory(true);
      return;
    }
    // "everything" is the list's Follow all and the set's, answered once. Both
    // writes are exclusive, so the set starts after the roster write lands.
    const include = pending.kind !== "exclude";
    const next = new Set(chosen);
    for (const company of pending.companies) {
      if (include) next.add(company.slug);
      else next.delete(company.slug);
    }
    const direction = include ? "follow" : "unfollow";
    const count = pending.companies.length;
    if (count > 0) {
      void commit({
        next,
        slugs: pending.companies.map((company) => company.slug),
        consents,
        key: "roster:others",
        failure: companiesDataCuratedFollowFailed({ direction, count, curatedList: CURATED_LIST() }),
        describe: () => companiesDataCuratedFollowResult({ direction, count, curatedList: CURATED_LIST() }),
      });
    }
    if (pending.kind === "everything") void writeDirectory(true);
  }, [confirmation, chosen, commit, writeSector, writeCompany, writeDirectory]);

  /** Visibility, written the way `commit` writes tracking: the consequence is
   *  named and the way back rides with it. The eye's effect is entirely on
   *  ANOTHER screen — hiding a company removes its roles from Opportunities and
   *  changes nothing here but one icon — so this is the row action that most
   *  needs a sentence. Target state is explicit rather than a flip, because the
   *  Undo closure holds the company as it stood when the toast was raised.
   *
   *  One queue per COMPANY. The eye is not disabled while its write is in
   *  flight (only the row's `aria-busy` moves), so a second click during one
   *  is ordinary and can put a DIFFERENT target in the air. Only ordering the
   *  writes makes the install keep the value the reader asked for last; a
   *  response guard decides what the screen adopts, never what the database
   *  keeps. With the order total, completion order IS submission order, so no
   *  response guard is needed. Two different companies patch two different
   *  rows, so they never wait on each other. `busy` counts: a row that re-arms
   *  on the first reply would lie about the work still outstanding. */
  const setVisible = useCallback(
    (company: CompanyDiscoveryCompany, visible: boolean, describe: string) => {
      const { slug } = company;
      const key = `visible:${slug}`;
      return writeKeyed(slug, async () => {
        clearFailure(key);
        try {
          await api.updateCompany(slug, { visible });
          resource.mutate((current) =>
            current
              ? {
                  ...current,
                  companies: current.companies.map((candidate) =>
                    candidate.slug === slug ? { ...candidate, visible } : candidate,
                  ),
                }
              : current,
          );
          toast({
            key: "companies-visibility",
            text: describe,
            action: {
              label: companiesDataUndo(),
              onClick: () => void setVisibleRef.current(company, !visible, companiesDataChangeUndone()),
            },
          });
        } catch (caught) {
          // Mirrors the confirmation it failed to earn, so the failure names
          // its row either way round.
          reportFailure(key, failureText(
            companiesDataVisibilityFailed({ visibility: visible ? "shown" : "hidden", company: company.display }),
            caught,
          ));
        }
      });
    },
    [writeKeyed, resource, toast, clearFailure, reportFailure],
  );
  const setVisibleRef = useRef(setVisible);
  useEffect(() => { setVisibleRef.current = setVisible; }, [setVisible]);

  const toggleVisible = useCallback(
    (company: CompanyDiscoveryCompany) =>
      setVisible(
        company,
        !company.visible,
        companiesDataVisibilityChanged({ visibility: company.visible ? "hidden" : "shown", company: company.display }),
      ),
    [setVisible],
  );

  /* Sync is one run with one live state, and the header owns it. The board only
   * ever asks for a subset — the notice below is the board's own confirmation
   * that the ask landed; the run itself reports through the header control and
   * the notification centre's per-company progress panel. */
  const syncable = useMemo(() => syncableSlugs(syncTargets.data?.companies), [syncTargets.data]);
  const sourceStatus = useMemo(
    () => sourceStatusLookup(syncTargets.data?.companies),
    [syncTargets.data],
  );
  const retryable = useMemo(() => failedSources(syncTargets.data?.companies), [syncTargets.data]);
  // In place, so the connector column keeps its answers while the next one
  // loads. Stable, because the sync context's verb depends on it.
  const refreshSyncTargets = syncTargets.refresh;
  const onSynced = useCallback(
    () => void refreshSyncTargets({ preserveData: true }),
    [refreshSyncTargets],
  );
  /* Exclusive like the roster write, and for the same reason: it grows the
     catalog and then re-reads it, so a selection PUT that overlapped it would
     be ordered against a roster the server has already replaced. The re-read
     is awaited inside the slot for that reason, and it keeps the register on
     screen while it runs. It still rethrows (the dialog keeps its values on a
     failure), which the queue passes through to this caller while storing a
     settled tail, so one bad URL cannot strand every write behind it. */
  const addByUrl = useCallback(
    (payload: { name: string; careers_url: string }) =>
      writeExclusive([], async () => {
        clearFailure("add");
        try {
          await api.addCompany(payload);
          await resource.refresh({ preserveData: true });
          void counts.refresh({ preserveData: true });
          toast({ key: "companies-add", text: companiesDataCompanyAddedToYourRoster() });
        } catch (caught) {
          // The add-by-link dialog, the only caller, says this itself: a
          // dialog owns its failure feedback, and a toast would paint under
          // its scrim, unreadable. Rethrown as it came, so its code still
          // says why (api/errorText.ts).
          throw caught;
        }
      }),
    [writeExclusive, resource, counts, toast, clearFailure],
  );

  const tracked = useMemo(
    () => (state ? state.companies.filter((company) => chosen.has(company.slug)) : []),
    [state, chosen],
  );

  const alerts = useMemo<CompanyAlert[]>(() => buildAlerts(tracked), [tracked]);

  /** Followed, walled, and not consented: kept on the roster, never scanned. */
  const awaitingConsentList = useMemo(() => awaitingConsent(tracked), [tracked]);

  const summary = useMemo(
    () => trackedSummary({ tracked, openRoles, countsReady: Boolean(counts.data) }),
    [tracked, openRoles, counts.data],
  );

  /* One object, rebuilt only when something it publishes has moved. A fresh
     literal would hand every register row a new value on each provider
     render, and every row reads it to build its memoized view's props. The
     verbs above are `useCallback`s with
     complete dependencies for that reason, and the two resources are held at a
     stable identity by `useStableResource`; a dependency dropped to flatten a
     render count would break the busy control in
     `CompaniesData.isolation.test.tsx`. */
  const value = useMemo<CompaniesContextValue>(
    () => ({
      resource,
      counts,
      chosen,
      groups,
      ...summary,
      catalogTotal: state?.companies.length ?? 0,
      openRoles,
      sourceStatus,
      sectorNames,
      busy,
      failures,
      alerts,
      query: shownQuery,
      setQuery,
      searching: needle.length > 0,
      directorySearch,
      trackedOnly,
      setTrackedOnly,
      registerEmpty,
      showPlanned,
      setShowPlanned,
      focusedSector,
      focusSector,
      scrollTarget,
      clearScrollTarget,
      toggleCompany,
      toggleSector,
      listAction,
      requestListAction,
      requestEverything,
      awaitingConsent: awaitingConsentList,
      reviewConsent,
      confirmation,
      confirmFollow,
      dismissFollow,
      toggleVisible,
      addByUrl,
      syncable,
      failedSources: retryable,
    }),
    [
      resource, counts, chosen, groups, summary, state, openRoles, sourceStatus,
      sectorNames, busy, failures, alerts, shownQuery, needle, directorySearch,
      trackedOnly, registerEmpty,
      showPlanned, focusedSector, focusSector, scrollTarget, clearScrollTarget,
      toggleCompany, toggleSector, toggleVisible, addByUrl, syncable, retryable,
      setTrackedOnly, setShowPlanned, listAction, requestListAction, requestEverything, confirmation,
      awaitingConsentList, reviewConsent,
      confirmFollow, dismissFollow,
    ],
  );

  return (
    <CompaniesContext.Provider value={value}>
      <CompaniesQueryContext.Provider value={queryValue}>
        <CompaniesDirectoryContext.Provider value={directoryValue}>
          <CompaniesSyncProvider
            onSynced={onSynced}
            reportFailure={reportFailure}
            clearFailure={clearFailure}
          >
            {children}
          </CompaniesSyncProvider>
        </CompaniesDirectoryContext.Provider>
      </CompaniesQueryContext.Provider>
    </CompaniesContext.Provider>
  );
}
