import { MutableRefObject, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { shellApi, type Stats } from "../api/shell";
import { coverBackground } from "../routing/paths";
import { useVisibleInterval } from "../hooks/useVisibleInterval";

/**
 * What the reader is LOOKING FOR: the header counts, the board's query, and the
 * two mission lenses the top bar sets on the board.
 *
 * FOUR contexts, split by cadence rather than by topic. The query
 * changes on every keystroke, the stats up to every 60 seconds, the lenses when
 * someone clicks — and the verbs never change at all. One object would
 * re-render the app shell, the rail and the command palette on every character
 * typed into the board's search box, and none of them read the query; and the
 * board, which reads the lenses, would re-render on every new count.
 */
export interface MissionStateValue {
  /** A Mission-level starter lens, composed with the board's ordinary filters
   *  rather than replacing them. */
  newSignalsOnly: boolean;
  /** The counterpart lens: roles re-listed today (repost successors). */
  repostsOnly: boolean;
}

/** The board's search query, alone: it churns per keystroke, and only the
 *  board's toolbar and controller read it. */
export interface BoardQueryValue {
  search: string;
}

export interface MissionActions {
  refreshStats: () => void;
  setSearch: (q: string) => void;
  /** Attached by the board toolbar's input while the Board is mounted; null on
   *  every other route, which is what lets "/" fall back to the palette there.
   *  A stable ref object: writing `.current` re-renders nothing, which is the
   *  point — focus plumbing must not churn every consumer. */
  boardSearchRef: MutableRefObject<HTMLInputElement | null>;
  /** The top bar's counts are ONE choice (open roles / new / reposted /
   *  saved): each `show*` lands on the board wearing exactly that lens, and a
   *  second click on the chosen one keeps it rather than flipping back. */
  showNewSignals: () => void;
  clearNewSignals: () => void;
  showReposts: () => void;
  clearReposts: () => void;
  /** Open roles: both lenses off. The chip is a link to `/`, which does the
   *  navigating; this is the half a link cannot do while already on `/`. */
  clearLenses: () => void;
}

/** The address that opens the board on New: `/?lens=new`. */
const LENS_PARAM = "lens";
const NEW_LENS = "new";

const StatsCtx = createContext<{ stats: Stats | null } | null>(null);
const ValueCtx = createContext<MissionStateValue | null>(null);
const QueryCtx = createContext<BoardQueryValue | null>(null);
const ActionsCtx = createContext<MissionActions | null>(null);

export function MissionStateProvider({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  // react-router v7 does not keep one `navigate` identity across navigations,
  // so closing over it directly would churn the actions context every time the
  // user moved between tabs.
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  const [stats, setStats] = useState<Stats | null>(null);
  const [search, setSearch] = useState("");
  const boardSearchRef = useRef<HTMLInputElement | null>(null);
  const [newSignalsOnly, setNewSignalsOnly] = useState(false);
  const [repostsOnly, setRepostsOnly] = useState(false);

  // The newest read wins: every start takes the next generation and
  // only the newest may write, as `useAsyncResource` does for feature reads. A
  // save's refresh and the 60s poll are two starts against the same inputs, and
  // without it the slower one wins by finishing last. Unmounting retires them all.
  const statsGeneration = useRef(0);
  const refreshStats = useCallback(() => {
    const generation = ++statsGeneration.current;
    shellApi.stats()
      .then((next) => {
        // An answer equal to the one on screen keeps its identity, so a poll
        // with nothing new renders nothing.
        if (generation === statsGeneration.current) setStats((current) => (sameStats(current, next) ? current : next));
      })
      .catch(() => {});
  }, []);
  useEffect(() => () => {
    statsGeneration.current += 1;
  }, []);

  useVisibleInterval(refreshStats, 60_000);

  const showNewSignals = useCallback(() => {
    setNewSignalsOnly(true);
    setRepostsOnly(false); // the two lenses are mutually exclusive
    navigateRef.current("/");
  }, []);
  const clearNewSignals = useCallback(() => setNewSignalsOnly(false), []);
  const showReposts = useCallback(() => {
    setRepostsOnly(true);
    setNewSignalsOnly(false);
    navigateRef.current("/");
  }, []);
  const clearReposts = useCallback(() => setRepostsOnly(false), []);
  const clearLenses = useCallback(() => {
    setNewSignalsOnly(false);
    setRepostsOnly(false);
  }, []);

  /* A lens lives exactly as long as the board it narrows. Outliving it, the
     lens would stay lit on other screens and come back on the board's next
     visit from ANY door — the rail, a company's "View N open roles", Back —
     narrowing a list nobody had asked to narrow. The ROUTED path, because a cover opened from the board (a role, the
     comparison) keeps the board mounted underneath, filters and all. Keyed on
     the path alone: `show*` sets the lens a render before its navigation lands
     (react-router commits location in a transition), and that render must not
     read as a departure. */
  const location = useLocation();
  const routedPath = (coverBackground(location) as { pathname: string }).pathname;
  useEffect(() => {
    if (routedPath !== "/") clearLenses();
  }, [routedPath, clearLenses]);

  /* `/?lens=new` is a door from outside the page (the Mac panel's new-roles
     count): it does what the top bar's New count does, then leaves the address,
     so the lens keeps its in-memory lifetime and a reload shows the open board. */
  useEffect(() => {
    if (location.pathname !== "/") return;
    const params = new URLSearchParams(location.search);
    if (params.get(LENS_PARAM) !== NEW_LENS) return;
    params.delete(LENS_PARAM);
    setNewSignalsOnly(true);
    setRepostsOnly(false);
    const rest = params.toString();
    navigateRef.current({ pathname: "/", search: rest ? `?${rest}` : "" }, { replace: true });
  }, [location.pathname, location.search]);

  const counts = useMemo(() => ({ stats }), [stats]);
  const value = useMemo<MissionStateValue>(
    () => ({ newSignalsOnly, repostsOnly }),
    [newSignalsOnly, repostsOnly],
  );
  const query = useMemo<BoardQueryValue>(() => ({ search }), [search]);
  const actions = useMemo<MissionActions>(
    () => ({
      refreshStats, setSearch, boardSearchRef, showNewSignals, clearNewSignals, showReposts, clearReposts, clearLenses,
    }),
    [refreshStats, showNewSignals, clearNewSignals, showReposts, clearReposts, clearLenses],
  );

  return (
    <ActionsCtx.Provider value={actions}>
      <StatsCtx.Provider value={counts}>
        <ValueCtx.Provider value={value}>
          <QueryCtx.Provider value={query}>{children}</QueryCtx.Provider>
        </ValueCtx.Provider>
      </StatsCtx.Provider>
    </ActionsCtx.Provider>
  );
}

function sameStats(current: Stats | null, next: Stats): boolean {
  if (current === null) return false;
  const scalar = (Object.keys(next) as (keyof Stats)[]).filter((key) => key !== "by_company");
  if (Object.keys(current).length !== Object.keys(next).length) return false;
  if (scalar.some((key) => current[key] !== next[key])) return false;
  const was = Object.entries(current.by_company);
  return was.length === Object.keys(next.by_company).length
    && was.every(([company, count]) => next.by_company[company] === count);
}

/** Header stats (open / new / saved). Refreshed after favorite changes. */
export function useMissionStats(): Stats | null {
  const v = useContext(StatsCtx);
  if (!v) throw new Error("useMissionStats must be used within MissionStateProvider");
  return v.stats;
}

export function useMissionState(): MissionStateValue {
  const v = useContext(ValueCtx);
  if (!v) throw new Error("useMissionState must be used within MissionStateProvider");
  return v;
}

export function useBoardQuery(): BoardQueryValue {
  const v = useContext(QueryCtx);
  if (!v) throw new Error("useBoardQuery must be used within MissionStateProvider");
  return v;
}

export function useMissionActions(): MissionActions {
  const v = useContext(ActionsCtx);
  if (!v) throw new Error("useMissionActions must be used within MissionStateProvider");
  return v;
}
