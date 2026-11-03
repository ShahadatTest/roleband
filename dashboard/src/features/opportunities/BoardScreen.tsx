import { shellNavRadar } from "../../copy/gen/shell";
import {
  radarEmptyClosed,
  radarEmptyClosedTitle,
  radarEmptyNotForMe,
  radarEmptyNotForMeTitle,
  radarExactHead,
  radarExcludeOffer,
  radarLevelNotPlacedNote,
  radarBoardFreshChanged,
  radarBoardFreshMore,
  radarBoardFreshShow,
  radarLoadFailed,
  radarLoading,
  radarOtherHead,
  radarShowAll,
  radarShowOther,
  radarTruncated,
  radarTruncatedOther,
} from "../../copy/gen/radar";
import { useCallback, useRef } from "react";
import type { Job } from "../../api";
import { useJobActions, useJobWorkspace } from "../../context/JobWorkspace";
import { useMissionActions, useMissionState } from "../../context/MissionState";
import { useMediaQuery } from "../../hooks/useMediaQuery";
import { useMeasuredCssSize } from "../../hooks/useMeasuredCssSize";
import { AsyncBoundary, Button, EmptyState, RAIL_QUERY } from "../../ui";
import { RailShell } from "../../patterns/RailShell";
import { PageHeader } from "../../patterns/PageHeader";
import { Pager } from "../../patterns/Pager";
import { CompareBeacon } from "../../patterns/jobs/CompareBeacon";
import { DismissBeacon } from "../../patterns/jobs/DismissBeacon";
import { JobCard } from "../../patterns/jobs/JobCard";
import { JobList } from "../../patterns/jobs/JobList";
import { RowSkeleton } from "../../ui/RowSkeleton";
import { BoardFilters } from "./BoardFilters";
import { BoardToolbar } from "./BoardToolbar";
import { FirstScanLine, FirstScanReread, ListEndNote, OpenBoardEmpty } from "./FirstScanStates";
import { RESET_FILTERS, countNarrowingFilters } from "./filters";
import { SearchInterpretation } from "./SearchInterpretation";
import { useBoardController, type CompanyLens, type ExclusionOffer } from "./useBoardController";
import { LEVEL_NOT_PLACED_OPTION, NOUN, count } from "../../copy/vocabulary";
import "../../patterns/jobs/job-page.css";
import "./board-shell.css";

export function BoardScreen(props: CompanyLens) {
  const { newSignalsOnly, repostsOnly } = useMissionState();
  const { clearNewSignals, clearReposts } = useMissionActions();
  const { viewedIds, compareIds, compareFull, compareCap } = useJobWorkspace();
  const { openJob, toggleCompare } = useJobActions();
  const {
    filters, facets, facetsError, retryFacets, list, listError, retryList, baseline, bestFitUnranked,
    mode, onModeChange,
    total, isDirect, relatedTotal, expanded, pageableTotal,
    update, updateFilters, onSort, toggleFav, dismiss,
    dismissal, undoDismiss, excludeVocabulary, fresh, showFresh, rereadDuringScan,
  } = useBoardController(props);
  // The toolbar's Reset all, offered again where the board's filters emptied it.
  const narrowed = countNarrowingFilters(filters, { newSignalsOnly, repostsOnly }) > 0;
  const clearAll = useCallback(() => {
    clearNewSignals();
    clearReposts();
    updateFilters(RESET_FILTERS);
  }, [clearNewSignals, clearReposts, updateFilters]);
  const railMode = useMediaQuery(RAIL_QUERY);
  const rootRef = useRef<HTMLElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  useMeasuredCssSize({ rootRef, elementRef: toolbarRef, property: "--board-toolbar-h" });

  // One row renderer for BOTH sections: the exact and related lists must never
  // drift apart on row features (the render-layer twin of patchJob/removeJob).
  const inLens = filters.dismissed_only;
  const renderRow = useCallback(
    (job: Job) => (
      <JobCard
        key={job.id}
        job={job}
        viewed={job.viewed_at != null || viewedIds.has(job.id)}
        onOpen={() => openJob(job.id, job.company)}
        onToggleFav={() => toggleFav(job)}
        onDismiss={() => dismiss(job)}
        foot={inLens && <ExclusionOffers job={job} onExclude={excludeVocabulary} />}
        compareOn={compareIds.has(job.id)}
        onToggleCompare={() => toggleCompare(job.id)}
        compareDisabled={compareFull}
        compareCap={compareCap}
      />
    ),
    [compareCap, compareFull, compareIds, dismiss, excludeVocabulary, inLens, openJob, toggleCompare, toggleFav, viewedIds]
  );

  /* Best fit puts the roles at a level we place first and says where
     they end: `placed_total` is an index of the whole list, so the head of the
     second group lands on whichever page holds it, top of the page included.
     Never on a column sort or a typed search (no `placed_total`), and never
     when every role on the Board is placed. */
  const placedTotal = !isDirect ? list?.placed_total ?? null : null;
  const unplacedTotal = placedTotal != null && list ? list.total - placedTotal : 0;
  const groupStart = placedTotal != null && unplacedTotal > 0 ? placedTotal - filters.offset : null;

  /* A dismissed row leaves a zero-height SEAM where it was — rendered before
     the row that followed it (or last), so the way-back beacon in the margin
     has a line to be level with (margin.css, DismissBeacon). Positional by
     the following row's id rather than by index, so the seam survives the
     list closing up around it. One at a time. */
  const withSeams = useCallback(
    (rows: Job[], section: "items" | "related_items") => {
      const here = dismissal?.section === section ? dismissal : null;
      const headAt = section === "items" ? groupStart : null;
      if (!here && headAt == null) return rows.map(renderRow);
      const out: React.ReactNode[] = [];
      const seam = here && <div key={`seam-${here.job.id}`} className="job-seam" data-seam-for={here.job.id} />;
      rows.forEach((row, i) => {
        if (i === headAt) out.push(<LevelNotPlacedHead key="level-not-placed" n={unplacedTotal} />);
        if (here && here.beforeId === row.id) out.push(seam);
        out.push(renderRow(row));
      });
      if (here && (here.beforeId === null || !rows.some((row) => row.id === here.beforeId))) out.push(seam);
      return out;
    },
    [dismissal, groupStart, renderRow, unplacedTotal],
  );

  /* The register, defined ONCE for both of its homes: the pinned rail below
     and the toolbar's Filters panel. Two JSX copies drift apart on props (one
     home missing `facetsError`/`onRetryFacets` leaves the rail an empty
     <aside> with nothing to click when facets fail). Same shape as
     NotificationScreen, for the same reason. */
  const register = (
    <BoardFilters
      facets={facets}
      facetsError={facetsError}
      onRetryFacets={retryFacets}
      filters={filters}
      update={updateFilters}
      mode={mode}
      onModeChange={onModeChange}
    />
  );

  /* The content column: everything that lists roles, laid out in the page's
     one scroll (board-shell.css). One definition rendered in
     either home so the two layouts can never drift apart on list features. */
  const content = (
    <div className="board-content job-margin-host" ref={hostRef}>
      {/* A list in hand stays on screen through a later failure; only a
          first read that failed is said in its place. */}
      <AsyncBoundary
        resource={{ data: list, error: list ? null : listError, loading: !list && !listError, retry: retryList }}
        loading={radarLoading()}
        failed={radarLoadFailed()}
        skeleton={<JobList><RowSkeleton rows={9} /></JobList>}
      >
      {() => total === 0 && relatedTotal === 0 ? (
        // Empty only when BOTH sections are: `total` counts the exact section
        // alone on a direct response, and dismissing its last row must not wipe
        // a still-populated related list off the screen.
        // Which empty is this? Without a per-pile count the screen cannot
        // measure it, and three `limit=1` requests on every board load for a
        // number nothing shows would not pay for one. The lens's own sentence is right far more often than not,
        // since an unfiltered empty pile is the common case.
        inLens ? (
          // The lens's empty state teaches the control, where a bare
          // "1 of 40 roles" over an empty table would say nothing. Its way out
          // is the MODE, and the mode is URL state, so it asks the
          // route rather than patching `filters`, like every other control
          // that moves the board between populations.
          <EmptyState title={radarEmptyNotForMeTitle()}>
            {radarEmptyNotForMe()}{" "}
            <Button variant="link" onClick={() => onModeChange("open")}>
              {radarShowAll()}
            </Button>
          </EmptyState>
        ) : mode === "closed" ? (
          <EmptyState title={radarEmptyClosedTitle()}>
            {radarEmptyClosed()}
          </EmptyState>
        ) : (
          <OpenBoardEmpty narrowed={narrowed} onClear={clearAll} />
        )
      ) : (
        <>
          {/* Direct-match header: names the identity claim. Rendered
              only when exact rows exist — no exact row means the ordinary
              exploratory list, never an empty exact shell. */}
          {isDirect && list!.items.length > 0 && (
            <h2 className="search-section-head">{radarExactHead({ count: list!.items.length })}</h2>
          )}
          <JobList sortControl={{ sort: filters.sort, order: filters.order, onSort }}>
            {withSeams(list!.items, "items")}
          </JobList>
          {/* Related expansion is an explicit, countable button — never
              a silent collapsed region, and absent entirely at zero. */}
          {isDirect && relatedTotal > 0 && !expanded && (
            <div className="search-related-disclosure">
              <Button className="search-related-toggle" onClick={() => update({ include_related: true, offset: 0 })}>
                {radarShowOther({ count: relatedTotal })}
              </Button>
            </div>
          )}
          {expanded && (
            <>
              <h2 className="search-section-head">{radarOtherHead({ count: relatedTotal })}</h2>
              <JobList>{withSeams(list!.related_items ?? [], "related_items")}</JobList>
            </>
          )}
          <Pager total={pageableTotal} pageSize={filters.limit} offset={filters.offset}
            onOffsetChange={(offset) => update({ offset })} />
          {/* The end of a list that ends: not a lens, not a typed search's
              sections, not a ranking cut at its ceiling (that says so itself). */}
          {!inLens && mode === "open" && !isDirect && !list!.ranking_truncated
            && filters.offset + list!.items.length >= total && (
            <ListEndNote narrowed={narrowed} onClear={clearAll} />
          )}
        </>
      )}
      </AsyncBoundary>
      {/* The ledger margin: the compare beacon level with the row selected
          last, and the one way-back beacon level with its seam (margin.css).
          OUTSIDE the list branch: dismissing the last row on the page empties
          the list, and the way back must survive that — with no seam to be
          level with, the pill docks. */}
      {list && <CompareBeacon host={hostRef} anchorVersion={list} />}
      {list && dismissal && (
        <DismissBeacon
          key={dismissal.job.id}
          host={hostRef}
          anchorVersion={list}
          dockSlot={1}
          dismissal={dismissal}
          onUndo={undoDismiss}
        />
      )}
    </div>
  );

  return (
    <main className="main board-main job-margin-page" data-design-system="app" ref={rootRef}>
      <PageHeader title={shellNavRadar()} />

      <BoardToolbar
        toolbarRef={toolbarRef}
        register={register}
        filters={filters}
        update={updateFilters}
        total={total}
        baseTotal={baseline.total}
        baselineError={baseline.error}
        onRetryBaseline={baseline.retry}
        onModeChange={onModeChange}
        railMode={railMode}
        newSignalsOnly={newSignalsOnly}
        clearNewSignals={clearNewSignals}
        repostsOnly={repostsOnly}
        clearReposts={clearReposts}
        bestFitUnranked={bestFitUnranked}
      />

      <SearchInterpretation parsed={list?.parsed} />

      {/* The first scan reads on: its line over a list that has roles, and
          the list read again as it finds more. */}
      {mode === "open" && !inLens && (total > 0 || relatedTotal > 0) && <FirstScanLine />}
      <FirstScanReread onReread={rereadDuringScan} />

      {/* A scan ended while the list was open: the update waits for the reader,
          so no row moves under them mid-read. */}
      {fresh && (
        <div className="empty-hint" role="status">
          {fresh.more > 0 ? radarBoardFreshMore({ count: fresh.more }) : radarBoardFreshChanged()}{" "}
          <Button variant="ghost" size="sm" onClick={showFresh}>
            {radarBoardFreshShow()}
          </Button>
        </div>
      )}

      {/* The intent-ranked order is deliberately UNANNOUNCED here: a
          "Ranked by your direction" strip would break the page's visual line.
          The per-row why-world chips are the in-list signal, and the Sort
          control names the order on request. */}

      {/* Best match ranks a bounded candidate pool. When the query matches more
          than the pool ceiling, what you can page through is a slice — and the
          count above it is the slice, not the market. Saying so is the whole
          point: a truncated ranking presented as a total is indistinguishable
          from a small market. On a direct-match response the truncated thing is
          the RELATED section, never the exact set — the copy must name the
          number the flag actually qualifies, or it reads "top 1 of 4,000". */}
      {list?.ranking_truncated && (
        <div className="search-truncation-note" role="note">
          {isDirect ? (
            radarTruncatedOther({ shown: relatedTotal, matched: list.matched ?? relatedTotal })
          ) : (
            radarTruncated({ shown: total, matched: list.matched ?? total })
          )}
        </div>
      )}

      {/* The shell row: the filter register stands beside the list at rail
          widths, and the content column carries the flex chain down to the
          list. Below rail widths the column renders alone —
          the toolbar's Filters panel serves the same register there. */}
      <RailShell railMode={railMode} register={register} className="board-shell">
        {content}
      </RailShell>
    </main>
  );
}

/* The head of Best fit's second group: roles whose level we cannot
   place on the shared levels, because the posting names none or names one in
   the company's own terms we have not mapped. A heading, so it stays
   selectable; its count is an instrument reading, so it is chrome. */
function LevelNotPlacedHead({ n }: { n: number }) {
  return (
    <div className="level-group-head">
      <h2 className="level-group-title">
        {LEVEL_NOT_PLACED_OPTION()}
        <span className="level-group-count" data-selection="chrome">{count(NOUN.role, n)}</span>
      </h2>
      <p className="level-group-note">
        {radarLevelNotPlacedNote()}
      </p>
    </div>
  );
}

/* The Not-for-me lens's line under a row: the employer's own team/department
   vocabulary, verbatim, as the offer to make it a standing per-company
   exclusion. The ONLY path to a rule: nothing is learned without the click.
   It is not in the dismiss beacon's reveal, because a rule is a decision made
   on review, not in the seconds after a click. */
function ExclusionOffers({ job, onExclude }: { job: Job; onExclude: (offer: ExclusionOffer) => void }) {
  const offers: ExclusionOffer[] = [];
  if (job.team) offers.push({ company: job.company, kind: "team", value: job.team });
  if (job.department && job.department !== job.team) {
    offers.push({ company: job.company, kind: "department", value: job.department });
  }
  if (offers.length === 0) return null;
  return (
    <>
      {offers.map((offer) => (
        <Button
          key={offer.kind}
          variant="link"
          className="ui-btn-quiet"
          onClick={(e) => {
            e.stopPropagation();
            onExclude(offer);
          }}
        >
          {radarExcludeOffer({ value: offer.value })}
        </Button>
      ))}
    </>
  );
}
