import { useRef } from "react";
import { CompareBeacon } from "../../patterns/jobs/CompareBeacon";
import { JobCard } from "../../patterns/jobs/JobCard";
import { JobList } from "../../patterns/jobs/JobList";
import { PageHeader } from "../../patterns/PageHeader";
import { ResultsSummary } from "../../patterns/ResultsSummary";
import { AsyncBoundary, EmptyState, Icon } from "../../ui";
import { RowSkeleton } from "../../ui/RowSkeleton";
import { useSavedController } from "./useSavedController";
import { STAGE_LABEL } from "../../copy/vocabulary";
import "../../patterns/jobs/job-page.css";
import {
  savedScreenLoadFailed,
  savedScreenNothingSavedYet,
  savedScreenProgress,
  savedScreenTapTheOnAnyRole,
} from "../../copy/gen/saved";
import { Msg } from "../../ui/Msg";
import { shellNavSaved } from "../../copy/gen/shell";

export function SavedScreen() {
  const {
    items, total, stages, loading, failed, retry, unfavorite,
    openJob, viewedIds, compareIds, toggleCompare, compareFull, compareCap,
  } = useSavedController();
  const hostRef = useRef<HTMLDivElement>(null);

  return (
    <main className="main board-main" data-design-system="app">
      {/* No "Compare saved" verb: it would set a selection and go nowhere,
          and with a cap of three it could only ever be honest for three saved
          roles. Picking rows here raises
          the same beacon the Radar has, which is the one way in. */}
      <PageHeader title={shellNavSaved()} />
      <div className="results-head">
        {/* A fraction only while the page is short of the set — the Board's
            rule: an unnarrowed count is a count, not "4 of 4".
            Here the narrowing is OUR page size rather than a filter, so the
            fraction is the only thing that says roles are missing. */}
        <ResultsSummary
          count={items.length}
          total={total > items.length ? total : null}
          noun="role"
        />
      </div>

      <AsyncBoundary
        resource={{ data: items, error: failed, loading, retry }}
        failed={savedScreenLoadFailed()}
        skeleton={<JobList><RowSkeleton rows={4} /></JobList>}
        isEmpty={(rows) => rows.length === 0}
        empty={
          <EmptyState title={savedScreenNothingSavedYet()}>
            {/* Renders the real glyph rather than describing it with a ★, so this
                copy cannot drift from whatever StarButton actually shows. */}
            <Msg of={savedScreenTapTheOnAnyRole} elems={{ icon: <Icon name="star" size={12} /> }} />
          </EmptyState>
        }
      >
        {() => (
        <div className="job-margin-host" ref={hostRef}>
        <JobList>
          {items.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              viewed={job.viewed_at != null || viewedIds.has(job.id)}
              onOpen={() => openJob(job.id, job.company)}
              onToggleFav={() => unfavorite(job)}
              compareOn={compareIds.has(job.id)}
              onToggleCompare={() => toggleCompare(job.id)}
              compareDisabled={compareFull}
              compareCap={compareCap}
              foot={stages.has(job.id) ? (
                <span className="saved-progress">{savedScreenProgress({ stage: STAGE_LABEL[stages.get(job.id)!] })}</span>
              ) : undefined}
            />
          ))}
        </JobList>
          <CompareBeacon host={hostRef} anchorVersion={items} />
        </div>
        )}
      </AsyncBoundary>
    </main>
  );
}
