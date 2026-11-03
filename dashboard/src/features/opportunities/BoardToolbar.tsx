import { errorText } from "../../api/errorText";
import { commonTryAgain } from "../../copy/gen/common";
import {
  radarCountNotForMe,
  radarNewToday,
  radarNewTodayClear,
  radarOrderReverse,
  radarRepostedToday,
  radarRepostedTodayClear,
  radarReset,
  radarResetTitle,
  radarSearchLabel,
  radarSearchPlaceholder,
  radarShowAll,
  radarShowAllTitle,
  radarSort,
  radarSortAge,
  radarSortBestFit,
  radarSortBestFitUnranked,
  radarSortBestFitUnrankedWhy,
  radarSortBy,
  radarFieldCompany,
  radarFieldLevel,
  radarFieldLocation,
  radarSortNewest,
  radarFieldPayFull,
  radarFieldTitle,
  radarTotalFailed,
  radarTotalRetryAria,
} from "../../copy/gen/radar";
import type { ReactNode, RefObject } from "react";
import { SearchField } from "../../ui/SearchField";
import type { Filters, JobSort } from "../../api";
import { Button, FilterChip, Kbd, Select , Icon } from "../../ui";
import { useBoardQuery, useMissionActions } from "../../context/MissionState";
import { RESET_FILTERS, countActiveFilters, countNarrowingFilters, type BoardMode } from "./filters";
import { FilterSurface } from "../../patterns/FilterSurface";
import { ResultsSummary } from "../../patterns/ResultsSummary";

// [sort key, label]. An option in a native menu never shows a hover, so a
// label with a short form (Base) is spelled out here. A key is a `JobSort`, the set `/api/jobs` publishes, so
// one the route does not accept fails `tsc`. Labels are message functions,
// read at render (a module-level string would keep the language the app
// booted in).
const SORTS: [JobSort, () => string][] = [
  ["first_seen", radarSortNewest],
  ["location", radarFieldLocation],
  ["base_pay", radarFieldPayFull],
  ["days_open", radarSortAge],
  ["level_band", radarFieldLevel],
  ["company", radarFieldCompany],
  ["title", radarFieldTitle],
];

// "Best match" (relevance). With a query the backend ranks hybrid
// lexical+semantic+fuzzy results; without one it ranks by the standing intent
// vector (statement + favorites/pursuits - dismissals), falling back to the
// default order when no intent signal exists yet. Either way the order toggle
// is ignored. Always offered, query or not.
const RELEVANCE_SORT: [JobSort, () => string] = ["relevance", radarSortBestFit];

/* The board's toolbar, in the settings idiom: search leads the screen it
 * filters, the result count sits beside it as a fact, ordering hangs on the
 * right. This is the band that docks at the top of the scroll (board-shell.css),
 * so everything here stays reachable from row 200.
 *
 * The search input LIVES here but its state lives in AppState: the query
 * composes with lenses set from the topbar chips, and the shell's "/"
 * shortcut focuses it through `boardSearchRef`. Filtering itself lives in the
 * filter register (BoardFilters), rendered as the left rail at rail widths;
 * below them this toolbar grows a "Filters · N" opener so active state stays
 * countable even while the register is folded away.
 */
export function BoardToolbar({
  toolbarRef,
  register,
  filters,
  update,
  total,
  baseTotal = null,
  baselineError = null,
  onRetryBaseline,
  onModeChange,
  railMode,
  newSignalsOnly,
  clearNewSignals,
  repostsOnly,
  clearReposts,
  bestFitUnranked = false,
}: {
  toolbarRef?: RefObject<HTMLDivElement | null>;
  /** The filter register, built once by the screen and rendered in BOTH of its
   *  homes. Passed as an element rather than rebuilt here: two constructions
   *  drift apart on props such as the facets-failure pair (see BoardScreen). */
  register: ReactNode;
  filters: Filters;
  update: (patch: Partial<Filters>) => void;
  total: number;
  /** The count the same search and status would give with NO filter or lens
   *  on — what `total` is a subset of. Null until the route has measured it. */
  baseTotal?: number | null;
  baselineError?: Error | null;
  onRetryBaseline?: () => void;
  /** Back to the open board. The mode is URL state. */
  onModeChange: (mode: BoardMode) => void;
  /** True while the filter register renders as the left rail (>=1240px). */
  railMode: boolean;
  newSignalsOnly: boolean;
  clearNewSignals: () => void;
  repostsOnly: boolean;
  clearReposts: () => void;
  /** Best fit fell back to newest first: nothing to rank by yet. */
  bestFitUnranked?: boolean;
}) {
  const { search } = useBoardQuery();
  const { setSearch, boardSearchRef } = useMissionActions();

  const lenses = { newSignalsOnly, repostsOnly };
  const activeCount = countActiveFilters(filters, lenses);
  // The FRACTION asks how much of this population is on screen, so the choice
  // of population is not part of it: otherwise a reader who only
  // opened the Closed pile reads "34 of 34 roles", which looks like a filter
  // is holding something back when nothing is.
  const narrowed = countNarrowingFilters(filters, lenses) > 0;
  // The Not-for-me lens is a different list, not a narrowing of this one: it
  // reads "3 roles you marked not for me · Show all", never "3 of 40".
  const inLens = filters.dismissed_only;
  /* Clears every FILTER and lens. It deliberately leaves the mode alone: the
     mode is which list you are looking at, not how it is narrowed, and the way
     back to the open board is the top bar's own count of open roles. Clearing
     both here would also race: `setSearchParams` does not queue its
     functional form, so the company deletion would recompute from params that
     still carried `?show=`, and put it back. */
  const resetAll = () => {
    clearNewSignals();
    clearReposts();
    update(RESET_FILTERS);
  };
  /* The lens's way out, and it switches the whole MODE rather than clearing
     the flag. The Not-for-me pile carries an EMPTY `status`, so a
     role you marked stays yours after its posting closes; clearing
     `dismissed_only` on its own leaves that behind, and the list then shows
     open and closed roles together under a tab bar still reading Open. */
  const showAll = () => onModeChange("open");
  const relevance: [JobSort, () => string] = bestFitUnranked ? ["relevance", radarSortBestFitUnranked] : RELEVANCE_SORT;
  const sortOptions = [relevance, ...SORTS];
  const isRelevance = filters.sort === "relevance";

  return (
    <div className="board-toolbar app-toolbar" data-selection="chrome" ref={toolbarRef}>
      <SearchField
        ref={boardSearchRef}
        className="board-search-box"
        label={radarSearchLabel()}
        placeholder={radarSearchPlaceholder()}
        value={search}
        onChange={setSearch}
        trailing={<Kbd>/</Kbd>}
      />

      {/* The count is a fact; while anything narrows it, it is a FRACTION
          ("197 of 219 roles") and the undo sits right after it. The line
          never changes height, so nothing below it moves, where an undo row
          inside the register would shift every group down. */}
      <ResultsSummary
        count={total}
        total={narrowed && !inLens ? baseTotal : null}
        noun="role"
        meta={inLens ? (
          <>{" "}<span>{radarCountNotForMe()}</span></>
        ) : baselineError && (
          <>
            {" "}<span role="status">{radarTotalFailed()}</span>{" "}
            <Button variant="link" className="ui-btn-quiet" onClick={onRetryBaseline}
              aria-label={radarTotalRetryAria()} title={errorText(baselineError)}>{commonTryAgain()}</Button>
          </>
        )}
        reset={inLens ? (
          <Button variant="link" className="ui-btn-quiet" onClick={showAll}
            title={radarShowAllTitle()}>
            {radarShowAll()}
          </Button>
        ) : activeCount > 0 && (
          <Button variant="link" className="ui-btn-quiet" onClick={resetAll} title={radarResetTitle()}>
            {radarReset()}
          </Button>
        )}
      />

      {/* Mission lenses set from the topbar land here as removable chips, so
          the list never narrows by an invisible hand. */}
      {newSignalsOnly && (
        <FilterChip selected onClick={clearNewSignals} title={radarNewTodayClear()}>
          {radarNewToday()}
        </FilterChip>
      )}
      {repostsOnly && (
        <FilterChip selected onClick={clearReposts} title={radarRepostedTodayClear()}>
          {radarRepostedToday()}
        </FilterChip>
      )}

      <div className="board-toolbar-end">
        {/* The folded home of the register: opener + modal panel, one
            lifecycle for every screen (patterns/FilterSurface). */}
        <FilterSurface railMode={railMode} activeCount={activeCount}>
          {register}
        </FilterSurface>
        <div className="sort-select">
          <span>{radarSort()}</span>
          {/* BEFORE the select, and gone entirely on Best match (the backend
              ignores asc/desc there): the group is anchored to the bar's end,
              so the select's right edge stays on the page's own right line
              (hero badge, table edge, this) whether the toggle shows or not. */}
          <Button
            variant="icon"
            onClick={() => update({ order: filters.order === "desc" ? "asc" : "desc", offset: 0 })}
            title={radarOrderReverse()}
            aria-label={radarOrderReverse()}
            disabled={isRelevance}
          >
            <Icon name={filters.order === "desc" ? "arrowDown" : "arrowUp"} size={13} />
          </Button>
          {/* ui/Select owns the chevron's inset and a focus ring that does
              not linger after a click that chose nothing. */}
          <Select
            label={radarSortBy()}
            value={filters.sort}
            onChange={(sort) => update({ sort, offset: 0 })}
            options={sortOptions.map(([value, label]) => ({ value, label: label() }))}
            description={isRelevance && bestFitUnranked ? radarSortBestFitUnrankedWhy() : undefined}
          />
        </div>
      </div>

    </div>
  );
}
