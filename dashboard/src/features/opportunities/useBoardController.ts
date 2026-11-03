import {
  radarExcludeDone,
  radarExcludeFailed,
  radarRestoreFailed,
  radarSaveFailed,
  radarUnsaveFailed,
} from "../../copy/gen/radar";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSyncEpoch } from "../../context/SyncState";
import { DEFAULT_FILTERS, Facets, Filters, Job, JobList as JobListData, JobSort, api } from "../../api";
import { useJobWorkspace } from "../../context/JobWorkspace";
import { useBoardQuery, useMissionActions, useMissionState } from "../../context/MissionState";
import { useToast } from "../../ui";
import { useAsyncResource, useRefetchOn } from "../../hooks/useAsyncResource";
import { useRoleSaves } from "../../hooks/useRoleSaves";
import { useRememberedState } from "../../hooks/useFilterMemory";
import { useBoardBaseline } from "./useBoardBaseline";
import { patchJob, removeJob } from "./jobListState";
import {
  BOARD_MEMORY_SCOPE,
  BOARD_MEMORY_SHAPE,
  MODE_FILTERS,
  boardMode,
  boardRequestFilters,
  type BoardMode,
} from "./filters";

export interface BoardDismissal {
  job: Job;
  /** Where the row was: before this row (null = it was last) of this section. */
  beforeId: number | null;
  section: "items" | "related_items";
}

/** How long the way back stays in the margin. Undo is for an accident, and
 *  an accident is singular: one pill, one name, one click. */
export const DISMISS_TTL_MS = 8000;

/** The vocabulary a row offers as a standing exclusion:
 *  the employer's own team/department, verbatim. Offered in the Not-for-me
 *  lens, where a rule is a decision made on review. */
export interface ExclusionOffer {
  company: string;
  kind: "team" | "department";
  value: string;
}

/** The seam a row will leave: the id of the row after it, in its section. */
function seamFor(list: JobListData | null, id: number): Pick<BoardDismissal, "beforeId" | "section"> {
  for (const section of ["items", "related_items"] as const) {
    const rows = list?.[section] ?? [];
    const i = rows.findIndex((job) => job.id === id);
    if (i !== -1) return { section, beforeId: rows[i + 1]?.id ?? null };
  }
  return { section: "items", beforeId: null };
}

export interface CompanyLens {
  companyParam: string[];
  onCompanyParamChange: (companies: string[]) => void;
  /** Which population the board is showing, from `?show=`. */
  mode: BoardMode;
  onModeChange: (mode: BoardMode) => void;
}

export function useBoardController({
  companyParam, onCompanyParamChange, mode, onModeChange,
}: CompanyLens) {
  const { search } = useBoardQuery();
  const { newSignalsOnly, repostsOnly } = useMissionState();
  const { refreshStats } = useMissionActions();
  const { favVersion } = useJobWorkspace();
  const { toast } = useToast();
  const saveRole = useRoleSaves();
  /* The company filter lives in `?company=` (the shared list-param hook), so a
     deep link (the company profile's "View N open roles" button lands here as
     `/?company=google`) arrives filtered and the board stays shareable. Only
     `company` and the mode are URL state.

     The rest is REMEMBERED (hooks/filterMemory): every railFilter comes back
     as the reader left it, across a reload and across leaving the screen. The
     address still outranks memory on the one key both can speak for — a link
     that names a company is a choice made just now, and memory is a choice
     made last night. */
  /* A query already in the header box when the Board mounts (the palette's
     "Search roles" lands here with one) is part of the FIRST request, as the
     debounce below would make it, so the unfiltered Board is never asked for
     first. The query is MissionState's, never remembered. */
  const mountQuery = search.trim() ? { q: search, sort: "relevance" as const } : {};
  const [filters, setFilters, { restored }] = useRememberedState<Filters>({
    scope: BOARD_MEMORY_SCOPE,
    defaults: { ...DEFAULT_FILTERS, ...MODE_FILTERS[mode] },
    shape: BOARD_MEMORY_SHAPE,
    override: companyParam.length > 0 || search.trim()
      ? { ...(companyParam.length > 0 ? { company: companyParam } : {}), ...mountQuery }
      : undefined,
  });

  // The register's vocabulary, on the shared resource so a failed fetch is a
  // value the register can show and retry. BoardFilters renders nothing without
  // `facets`, so a failure left as null would hide the whole register for good.
  const facetsResource = useAsyncResource<Facets>((signal) => api.facets(signal), [], { keep: "facets" });
  const facets = facetsResource.data;
  const refreshFacets = facetsResource.refresh;

  /* ONE direction for the company too: `?company=` -> filters, the
     same rule as the mode. A filters -> URL mirror breaks because the board
     stays mounted when the address changes: the top bar's "open roles" link
     to `/` finds `filters.company` still holding the company, the mirror
     re-fires on the new params, and it writes `?company=` straight back. So
     nothing on the board answers the URL by writing it: an address that moves on its own —
     a link, Back, a deep link — is applied here, and a control writes the URL
     itself (`routeCompany` below). Keyed on the JOINED list: `getAll` hands
     back a fresh array every render, which as a dependency would fire on
     every render. */
  const companyKey = companyParam.join("\n");
  /* What the address said when this screen mounted. The effect below applies
     the URL only once it MOVES, which is what lets memory seed a company the
     address is silent about: its first pass would otherwise read that silence
     as "no company" and wipe the restored selection before the first request
     went out. A later move to an empty `?company=` is still applied — that is
     the top bar's "open roles" link clearing it, not silence. */
  const appliedCompany = useRef(companyKey);
  useEffect(() => {
    if (companyKey === appliedCompany.current) return;
    appliedCompany.current = companyKey;
    const company = companyKey ? companyKey.split("\n") : [];
    setFilters((f) =>
      f.company.length === company.length && f.company.every((slug, i) => slug === company[i])
        ? f
        // A company change is a filter edit: it collapses the related
        // expansion and goes back to the first page, like every other.
        : { ...f, company, include_related: false, offset: 0 },
    );
  }, [companyKey, setFilters]);

  /* The write half: a control that changes the company writes the URL from
     its own handler — never from an effect, which would re-fire on the new
     params and write the old company back.

     It ALSO applies the value locally, in the same handler, and that is not a
     second writer racing the first: nothing writes filters -> URL, so the two
     cannot chase each other (two EFFECTS mirroring each other would). It is
     there because react-router commits a location
     in a transition. The register's checkboxes are controlled by
     `filters.company`, so a URL-only write would snap the box back until the
     transition landed, and a second click inside that window would compute its
     selection from the stale list and drop the first choice. The effect above
     then finds the URL equal to the filters and does nothing.

     ONE url write per edit: Reset all clears the company in the same call that
     clears everything else, because a second write from another tick resolves
     against params a pending transition has not committed.
     Through a ref so the verbs keep one identity: the route's setter is
     rebuilt on every change of the params. */
  const companyWriter = useRef(onCompanyParamChange);
  companyWriter.current = onCompanyParamChange;
  const routeCompany = useCallback((patch: Partial<Filters>) => {
    if ("company" in patch) companyWriter.current(patch.company ?? []);
  }, []);

  /* A REMEMBERED company still has to reach the address, once, at mount.
     Without it the register would show a company the URL does not name, and
     `/` — the top bar's "N open roles" link, the documented way back to the
     unfiltered board — would already be the address we are on, so
     clicking it would change nothing. Writing it keeps the one-writer rule
     intact instead of breaking it: after this the address is again the only
     thing that moves the company.

     Refs throughout, so this is a true mount effect: `restored` and the
     mount-time `companyKey` do not change, and the writer is a ref because
     the route rebuilds its setter on every navigation. */
  const seededCompany = useRef(restored.company ?? []);
  const arrivedWithCompany = useRef(companyKey.length > 0);
  useEffect(() => {
    if (arrivedWithCompany.current || seededCompany.current.length === 0) return;
    companyWriter.current(seededCompany.current);
  }, []);

  /* ONE direction: `?show=` -> filters, and nothing writes the other way.
     Every control that changes the mode calls `onModeChange`, which
     changes the URL, which lands here.

     A mirror in BOTH directions oscillates, alternating modes while the list
     renders empty. Equality guards on each side cannot stop it, because the
     two effects do not run in the same tick: the answer is one writer, not a
     better guard. */
  useEffect(() => {
    setFilters((f) => (boardMode(f) === mode ? f : { ...f, ...MODE_FILTERS[mode], offset: 0 }));
  }, [mode, setFilters]);

  // The header search box (shared state) drives the board query, debounced.
  // A non-empty query switches sorting to "relevance" (the hybrid Best-match
  // path); clearing it returns to the default sort, which is relevance too.
  // A non-relevance choice holds while the box is empty; a query replaces it.
  useEffect(() => {
    const t = setTimeout(
      () =>
        setFilters((f) => {
          const q = search.trim();
          const sort = q ? "relevance" : f.sort === "relevance" ? DEFAULT_FILTERS.sort : f.sort;
          // An unchanged query is no edit: no duplicate initial request, no
          // reload when the shell writes the same value back, and no reset of
          // a page turned while the box was settling.
          if (f.q === search && f.sort === sort) return f;
          // Query edit/clear collapses the related expansion: the
          // expansion answered the PREVIOUS query, and leaking it would page a
          // related section the new query does not have.
          return { ...f, q: search, sort, offset: 0, include_related: false };
        }),
      250
    );
    return () => clearTimeout(t);
  }, [search, setFilters]);

  const {
    data: list,
    error: listError,
    mutate: mutateList,
    retry: retryList,
    refresh: refreshList,
  } = useAsyncResource<JobListData>(
    (signal) => api.jobs(boardRequestFilters(filters, { newSignalsOnly, repostsOnly }), signal),
    [filters, newSignalsOnly, repostsOnly],
  );
  // Estimates moved together, or a role was saved somewhere: re-read the page
  // in place, so the reader keeps their rows and their scroll.
  const { referenceVersion, runVersion } = useSyncEpoch();
  useRefetchOn(referenceVersion, refreshList);
  useRefetchOn(favVersion, refreshList);

  /* A scan that ends while the Board is open. The filter counts re-read in
     place; the list is read again in the background and OFFERED (`fresh`),
     never swapped in under the reader, whose rows would move mid-read.
     `showFresh` takes it. An edit to the filters or a later read of the list
     makes the offer stale, so either withdraws it. */
  const [fresh, setFresh] = useState<{ list: JobListData; more: number } | null>(null);
  const asked = useRef({ filters, lenses: { newSignalsOnly, repostsOnly }, list });
  asked.current = { filters, lenses: { newSignalsOnly, repostsOnly }, list };
  const readFresh = useCallback(async () => {
    void refreshFacets({ preserveData: true });
    const { filters: shown, lenses, list: current } = asked.current;
    if (!current) return;
    try {
      const next = await api.jobs(boardRequestFilters(shown, lenses));
      if (asked.current.filters !== shown || asked.current.list !== current) return;
      setFresh(sameRows(current, next) ? null : { list: next, more: Math.max(0, next.total - current.total) });
    } catch {
      // A background read that failed offers nothing; the list on screen stands.
    }
  }, [refreshFacets]);
  useRefetchOn(runVersion, readFresh);
  /* The first scan's re-read (FirstScanReread): an empty board takes the new
     list at once, since no row can move under the reader; a list on screen
     is offered it, as at a scan's end. */
  const rereadDuringScan = useCallback(() => {
    const current = asked.current.list;
    if (current && current.total === 0 && (current.related_total ?? 0) === 0) void refreshList({ preserveData: true });
    else void readFresh();
  }, [readFresh, refreshList]);
  useEffect(() => setFresh(null), [filters, list]);
  const showFresh = useCallback(() => {
    if (fresh) mutateList(() => fresh.list);
    setFresh(null);
  }, [fresh, mutateList]);

  const update = useCallback((patch: Partial<Filters>) => {
    routeCompany(patch);
    setFilters((f) => ({ ...f, ...patch }));
  }, [routeCompany, setFilters]);

  const [baselineVersion, setBaselineVersion] = useState(0);
  const invalidateBaseline = useCallback(() => setBaselineVersion((version) => version + 1), []);
  const baseline = useBoardBaseline({
    filters, lenses: { newSignalsOnly, repostsOnly }, list,
    version: String(baselineVersion),
  });

  // Explicit filter edits re-evaluate the direct match under new filters, so
  // they collapse the related expansion too. The pager keeps the raw
  // `update` — request offset pages the related section while it is open.
  const updateFilters = useCallback(
    (patch: Partial<Filters>) => {
      routeCompany(patch);
      setFilters((f) => ({ ...f, ...patch, include_related: false, offset: 0 }));
    },
    [routeCompany, setFilters]
  );

  // Clicking a column header sorts by it; clicking the active column flips
  // direction. Either way pagination resets to the first page.
  const onSort = useCallback(
    (key: JobSort) =>
      setFilters((f) => ({
        ...f,
        sort: key,
        order: f.sort === key && f.order === "desc" ? "asc" : "desc",
        offset: 0,
        include_related: false,
      })),
    [setFilters]
  );

  const toggleFav = useCallback(
    (job: Job) => {
      const next = !job.is_favorite;
      // One writer per role across every surface: writes go in
      // click order, and only the newest one's failure repaints the star.
      saveRole({
        jobId: job.id, was: job.is_favorite, next,
        show: (on) => mutateList((prev) => (prev ? patchJob(prev, job.id, { is_favorite: on }) : prev)),
        send: () => api.setFavorite(job.id, next),
      })
        .then(refreshStats)
        .catch(() => {
          // The star springs back on its own, which without a word reads as the
          // click having missed.
          toast({ key: "board", text: next ? radarSaveFailed({ title: job.title }) : radarUnsaveFailed({ title: job.title }) });
        });
    },
    [mutateList, refreshStats, toast, saveRole]
  );

  /* The dismiss flow. Dismissing removes the row optimistically and records
     WHERE it was — the id of the row that followed it, in which section — so
     the list can render a zero-height seam there and the way-back pill can
     sit level with it in the margin (patterns/jobs/DismissBeacon). ONE at a
     time: a second dismissal replaces the first, so the pill moves to the
     newest row's line and never stacks. It leaves on its own after
     DISMISS_TTL_MS; everything older is in the Not-for-me lens. */
  const [dismissal, setDismissal] = useState<BoardDismissal | null>(null);
  const mounted = useRef(false);
  const ttl = useRef<number | null>(null);
  const clearTtl = useCallback(() => {
    if (ttl.current !== null) window.clearTimeout(ttl.current);
    ttl.current = null;
  }, []);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      clearTtl();
    };
  }, [clearTtl]);
  // A new query is a new page: the way back offered for the last one does not
  // describe it.
  useEffect(() => {
    clearTtl();
    setDismissal(null);
  }, [filters, clearTtl]);

  /** Show one way back for DISMISS_TTL_MS, replacing any other. */
  const offerWayBack = useCallback(
    (offered: BoardDismissal) => {
      clearTtl();
      setDismissal(offered);
      ttl.current = window.setTimeout(() => {
        ttl.current = null;
        setDismissal((prev) => (prev?.job.id === offered.job.id ? null : prev));
      }, DISMISS_TTL_MS);
    },
    [clearTtl]
  );

  const dismiss = useCallback(
    (job: Job) => {
      if (job.is_dismissed) {
        // Not-for-me lens: the same button restores.
        mutateList((prev) => (prev ? removeJob(prev, job.id) : prev));
        api.undismissJob(job.id).then(invalidateBaseline).catch(retryList);
        return;
      }
      const seam = seamFor(list, job.id);
      mutateList((prev) => (prev ? removeJob(prev, job.id) : prev));
      api
        .dismissJob(job.id)
        .then(() => {
          invalidateBaseline();
          if (!mounted.current) return;
          offerWayBack({ job, ...seam });
        })
        .catch(() => retryList());
    },
    [list, mutateList, retryList, invalidateBaseline, offerWayBack]
  );

  const undoDismiss = useCallback(
    (job: Job) => {
      clearTtl();
      const offered = dismissal?.job.id === job.id ? dismissal : null;
      setDismissal((prev) => (prev?.job.id === job.id ? null : prev));
      api
        .undismissJob(job.id)
        .then(() => { invalidateBaseline(); void refreshList({ preserveData: true }); })
        .catch(() => {
          // The role is still hidden: put its way back where it was, with a
          // fresh clock, and say the restore did not happen. Cleared and
          // unhandled, the role would stay hidden with nothing to try again.
          if (mounted.current && offered) offerWayBack(offered);
          toast({ key: "board", text: radarRestoreFailed({ title: job.title }), tone: "error" });
        });
    },
    [dismissal, refreshList, invalidateBaseline, clearTtl, offerWayBack, toast]
  );

  const excludeVocabulary = useCallback(
    ({ company, kind, value }: ExclusionOffer) => {
      api
        .createScopeRule({ company, kind, value })
        .then((saved) => {
          invalidateBaseline();
          const n = saved.in_scope_changed;
          toast({
            key: "board",
            text: radarExcludeDone({ count: n, value }),
          });
          refreshStats();
          void refreshList({ preserveData: true });
        })
        .catch(() => toast({ key: "board", text: radarExcludeFailed({ value }) }));
    },
    [refreshStats, refreshList, invalidateBaseline, toast]
  );

  // The header lenses live OUTSIDE `filters` (AppState), but toggling them
  // changes the request identity exactly like a filter edit — so they collapse
  // the related expansion and reset paging the same way. Without this,
  // an expanded page-3 related section rides into the lens's new result set.
  const lensesMounted = useRef(false);
  useEffect(() => {
    if (!lensesMounted.current) {
      lensesMounted.current = true;
      return;
    }
    setFilters((f) =>
      f.include_related || f.offset !== 0 ? { ...f, include_related: false, offset: 0 } : f
    );
  }, [newSignalsOnly, repostsOnly, setFilters]);

  const total = list?.total ?? 0;
  // Direct-match responses section the page: an unpaginated exact set,
  // and a related section behind an explicit disclosure. Request offset pages
  // the RELATED section while it is open; a collapsed direct response has
  // nothing to page.
  const isDirect = list?.query_kind === "exact_title" || list?.query_kind === "identifier";
  const relatedTotal = list?.related_total ?? 0;
  const expanded = isDirect && Boolean(filters.include_related) && relatedTotal > 0;
  const pageableTotal = isDirect ? (expanded ? relatedTotal : 0) : total;
  // Best fit with nothing to rank by yet (no saved role, no aim): the server
  // falls back to the default order and leaves `ranked_by` off, so the sort
  // must stop claiming a fit ranking it did not get.
  const bestFitUnranked = filters.sort === "relevance" && !filters.q && list != null && list.ranked_by !== "intent";

  return {
    filters, facets, list, listError, retryList, baseline, mode, onModeChange,
    facetsError: facetsResource.error,
    retryFacets: facetsResource.retry,
    total, isDirect, relatedTotal, expanded, pageableTotal, bestFitUnranked,
    update, updateFilters, onSort, toggleFav, dismiss,
    dismissal, undoDismiss, excludeVocabulary,
    fresh: fresh ? { more: fresh.more } : null, showFresh, rereadDuringScan,
  };
}

/** Whether two reads of one page list the same rows in the same order. */
function sameRows(a: JobListData, b: JobListData): boolean {
  const ids = (list: JobListData) => [...list.items, ...(list.related_items ?? [])].map((job) => job.id).join(",");
  return a.total === b.total && ids(a) === ids(b);
}
