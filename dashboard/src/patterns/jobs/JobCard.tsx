import {
  jobsCareerTrack,
  jobsCompare,
  jobsCompareFull,
  jobsCompareFullCap,
  jobsCompareTitle,
  jobsLevelNotMappedTitle,
  jobsLevelNotStatedTitle,
  jobsLevelUnconfirmed,
  jobsLevelUnconfirmedTitle,
  jobsListedSinceEmployer,
  jobsListedSinceSeen,
  jobsLocMore,
  jobsMatchClose,
  jobsMatchCloseTitle,
  jobsMatchExact,
  jobsMatchExactTitle,
  jobsMatchPartial,
  jobsMatchPartialTitle,
  jobsPlaceSet,
  jobsPlaceSetTitle,
  jobsPlaces,
  jobsPlacesTitle,
  jobsRelated,
  jobsRelatedTitle,
  jobsReposted,
  jobsRestore,
  jobsRestoreTitle,
  jobsStackTitle,
  jobsStandingBadge,
  jobsStandingCardTitle,
  jobsTrackBusinessCustomer,
  jobsTrackManagement,
  jobsTrackProductProgram,
  jobsTrackTechnical,
  jobsUnfollowedBadge,
  jobsViewed,
  jobsWhyWorldTitle,
} from "../../copy/gen/jobs";
import { sharedBaseUnknown, sharedCountPosting, sharedNotForMe } from "../../copy/gen/shared";
import { useId, type ReactNode } from "react";
import { Badge, Content, Icon } from "../../ui";
import { Button } from "../../ui/Button";
import { Job } from "../../api";
import { BAND_LABEL, LOC_LABEL, fmtDate, relDays } from "../../format";
import { primaryLocation } from "./location";
import { CompanyChip } from "../companies/CompanyChip";
import { StarButton } from "./JobControls";
import "./job-row.css";
import { placeGroups } from "./placeGroups";
import { MatchBadge, isStanding, standingSigns } from "./JobBadges";
import { unfollowedSentence } from "./unfollowed";
import { list } from "../../copy/format";
import { domainName } from "../../copy/vocab";
import { LEVEL_NOT_MAPPED, LEVEL_NOT_STATED } from "../../copy/vocabulary";
import { usePayCoverage } from "../../payCoverage";
import { baseShown } from "../../payShown";

const TRACK_LABEL: Record<string, string> = {
  get management() { return jobsTrackManagement(); },
  get product_program() { return jobsTrackProductProgram(); },
  get technical() { return jobsTrackTechnical(); },
  get business_customer() { return jobsTrackBusinessCustomer(); },
};

// Qualitative match claim on the Best-match path: the label is the match
// class, never a score. Tones separate the identity claim from role-shape
// agreement and plain adjacency. "Exact match", not "Exact title": the same
// class covers a pasted URL/req_id, where no title was ever compared — a
// title-specific label (and tooltip) would be a false statement on those rows.
const MATCH_CLASS_LABEL: Record<string, { label: () => string; tone: "success" | "info" | "neutral"; title: () => string }> = {
  exact: { label: jobsMatchExact, tone: "success", title: jobsMatchExactTitle },
  close: { label: jobsMatchClose, tone: "info", title: jobsMatchCloseTitle },
  related: { label: jobsMatchPartial, tone: "neutral", title: jobsMatchPartialTitle },
};

/* One row of the signal list. Columns are owned by .job-list's --row-cols so
   every row aligns by construction: role | location | comp | age | actions.

   The role cell is the position FIRST, then one meta line of plain facts —
   company (mark + name), band, role kind, world — separated by middots, in
   muted ink, no pills, no plates. Colour on a row is for STATE only: the new-signal bar, the
   repost / twin / match badges, the saved star. A category never gets a hue. */
/** "May be an always-open posting: listed for a long time, listed 3 times.
 *  Patterns in how it is listed, ..." */
function standingTitle(reality: Parameters<typeof standingSigns>[0]): string {
  // The inline forms, from the catalog: no case surgery on a translated sentence.
  return jobsStandingCardTitle({ signs: list(standingSigns(reality, { inline: true })) });
}

const fullTitle = (cap: number | undefined) =>
  cap === undefined ? jobsCompareFull() : jobsCompareFullCap({ cap });

export function JobCard({
  job,
  viewed,
  onOpen,
  onToggleFav,
  onDismiss,
  foot,
  compareOn,
  onToggleCompare,
  compareDisabled,
  compareCap,
}: {
  job: Job;
  viewed?: boolean;
  onOpen: () => void;
  onToggleFav: () => void;
  /* "Not for me" (or restore, when the row is already dismissed). Optional:
     surfaces without a dismissal concept (Compare) simply omit it. */
  onDismiss?: () => void;
  /** One line under the facts, for what a lens has to say about THIS row
   *  (the Not-for-me lens's exclusion offer). Clicks inside must stop
   *  propagation themselves; the row opens on click. */
  foot?: ReactNode;
  compareOn: boolean;
  onToggleCompare: () => void;
  compareDisabled?: boolean;
  /** The size of the comparison, so the disabled toggle can say what the limit
   *  IS and not only that it was hit. Passed in rather than imported: the
   *  constant lives in the workspace context, which every screen that renders
   *  a row already reads, and this component is renderable without one. */
  compareCap?: number;
}) {
  const isViewed = viewed ?? job.viewed_at != null;
  const compareFull = Boolean(compareDisabled && !compareOn);
  const fullReasonId = useId();
  // The age slot shows how long the posting has been listed, and the row
  // lights when the server calls it new (`new_listing`), the rule the
  // header's New count and the New view read: a fresh age alone is not
  // enough, since a company's first read finds roles that were already up.
  const ageDays = job.listed_days;
  const isNew = job.new_listing;
  const stackCount = job.lineage_size ?? 0;
  const isStacked = stackCount > 1;
  const base = baseShown(job, usePayCoverage());
  // Names no level: its stored Mid is a placeholder, never shown.
  const notStated = job.level_basis === "none";
  // Names a level in the company's own terms we cannot place: the
  // title says it, so never "not stated"; the guessed band is never shown.
  const notMapped = job.level_basis === "unmapped";
  const unconfirmed = !notStated && !notMapped && job.level_confidence === "unconfirmed";
  const where = primaryLocation(job.locations);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.target !== e.currentTarget) return;
    // s and c are bare letters; held with a modifier they are the browser's
    // (Cmd+C copies, Cmd+S saves the page), so the row leaves them alone.
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen();
    } else if (e.key.toLowerCase() === "s") {
      e.preventDefault();
      onToggleFav();
    } else if (e.key.toLowerCase() === "c" && !compareFull) {
      e.preventDefault();
      onToggleCompare();
    }
  };

  return (
    <article
      className={`job-row ${isNew ? "is-new" : ""} ${isViewed ? "is-viewed" : ""} ${isStacked ? "is-stacked" : ""}`}
      data-job-id={job.id}
      onClick={onOpen}
      onKeyDown={onKeyDown}
      aria-keyshortcuts="Enter s c"
      tabIndex={0}
    >
      <span className="job-signal" aria-hidden="true" />
      <div className="jr-role">
        <h2 className="job-title" title={job.title}><Content text={job.title} /></h2>
        <div className="job-meta">
          <span className="job-fact job-fact-company">
            <CompanyChip slug={job.company} />
          </span>
          <span
            className="job-fact job-band"
            title={
              notStated ? jobsLevelNotStatedTitle()
                : notMapped ? jobsLevelNotMappedTitle()
                  : unconfirmed ? jobsLevelUnconfirmedTitle() : undefined
            }
          >
            {notStated
              ? <span className="job-band-note">{LEVEL_NOT_STATED()}</span>
              : notMapped
                ? <span className="job-band-note">{LEVEL_NOT_MAPPED()}</span>
                : BAND_LABEL[job.level_band] ?? job.level_band}
            {unconfirmed && <span className="job-band-note">{" · "}{jobsLevelUnconfirmed()}</span>}
          </span>
          <span className="job-fact" title={jobsCareerTrack()}>{TRACK_LABEL[job.track] ?? job.track}</span>
          {job.why_world && (
            <span className="job-fact" title={jobsWhyWorldTitle()}>
              {domainName(job.why_world)}
            </span>
          )}
          {/* No "new" chip here: the row already says it twice — the
              signal bar on its edge and the age slot, which lights in the
              positive ink — and a chip would push the facts into
              truncation at desktop widths. */}
          {/* The receded row IS the viewed signal (ink one step down, title and
              numeral one weight down; no tint, which measures about 1.07:1).
              The word stays for assistive tech only. */}
          {isViewed && <span className="sr-only">{jobsViewed()}</span>}
          {isStacked ? (
            <Badge shape="tag" variant="tint" tone="warning" title={jobsStackTitle()}>
              {sharedCountPosting({ count: stackCount })}
            </Badge>
          ) : (
            job.repost_count > 0 && <Badge shape="tag" variant="tint" tone="warning">{jobsReposted()}</Badge>
          )}
          {job.twin_count > 0 && (
            <Badge shape="tag" variant="tint" tone="accent" title={jobsRelatedTitle()}>
              {jobsRelated({ count: job.twin_count })}
            </Badge>
          )}
          {/* One role its employer lists once per place. Not the
              repost chip: nothing was listed again. Job detail names the
              places and carries the way to split it. */}
          {job.place_count != null && job.place_count > 1 && (
            <Badge
              tone="neutral"
              variant="soft"
              shape="tag"
              title={jobsPlacesTitle()}
            >
              {jobsPlaces({ count: job.place_count })}
            </Badge>
          )}
          {/* One role listed again at its one place. Not the repost
              chip either: the postings run side by side, nothing came back. */}
          {(job.place_count ?? 0) <= 1 && job.place_set_size != null && job.place_set_size > 1 && (
            <Badge
              tone="neutral"
              variant="soft"
              shape="tag"
              title={jobsPlaceSetTitle()}
            >
              {jobsPlaceSet({ count: job.place_set_size })}
            </Badge>
          )}
          {/* Job detail's verdict, shown on the row only at
              `possible`. The short label names the hedge; the title names
              each sign, in the words Job detail uses. */}
          {isStanding(job.posting_reality) && (
            <Badge
              tone="warning"
              variant="soft"
              shape="tag"
              title={standingTitle(job.posting_reality)}
            >
              {jobsStandingBadge()}
            </Badge>
          )}
          {/* Only a Saved or Compare row can carry it. */}
          {job.company_unfollowed && (
            <Badge tone="neutral" variant="soft" shape="tag" title={unfollowedSentence(job)}>
              {jobsUnfollowedBadge()}
            </Badge>
          )}
          {job.match_class && MATCH_CLASS_LABEL[job.match_class] && (
            <Badge
              tone={MATCH_CLASS_LABEL[job.match_class].tone}
              variant="soft"
              shape="tag"
              title={MATCH_CLASS_LABEL[job.match_class].title()}
            >
              {MATCH_CLASS_LABEL[job.match_class].label()}
            </Badge>
          )}
          <MatchBadge matchedVia={job.matched_via} />
        </div>
        {foot && <div className="job-foot">{foot}</div>}
      </div>
      {/* The city on line one, the region under it. A posting that lists
          several cities shows the first and counts the rest; the whole list
          is the cell's tooltip and, for assistive tech, text after the count
          (a tooltip is never read out). */}
      <div
        className="jr-loc"
        title={where.others.length > 0 ? [where.city, ...where.others].join(" · ") : undefined}
      >
        <span className="job-location">
          {where.city ? <Content text={where.city} /> : "—"}
          {where.others.length > 0 && (
            <span className="job-loc-more">
              {" "}+{where.others.length}
              <span className="sr-only"> {jobsLocMore({ places: list(where.others) })}</span>
            </span>
          )}
        </span>
        {placeGroups(job.location_groups).slice(0, 1).map((g) => (
          <span key={g} className="job-loc-group">
            {LOC_LABEL[g] ?? g}
          </span>
        ))}
      </div>
      {/* The numeral on line one and its age on line two: one cell, so the
          age needs no column of its own. A base nobody knows leaves line one
          empty, with no dash or words beside the numbers. Where the figure
          comes from, or why there is none, is the hover's, and text for
          assistive tech, which never reads a hover. */}
      <div className="jr-comp">
        <span className="comp" title={base.hint}>
          {base.text || <span className="sr-only">{sharedBaseUnknown()}</span>}
          {base.hint && <span className="sr-only"> {base.hint}</span>}
        </span>
        <span
          className="jr-age"
          title={
            // This posting's own age, from the earlier of the employer's first
            // date and our first sighting; earlier postings of the
            // role are the repost badge's and Job detail's to say.
            job.listed_since
              ? (job.listed_basis === "employer" ? jobsListedSinceEmployer : jobsListedSinceSeen)({ date: fmtDate(job.listed_since) })
              : undefined
          }
        >
          {relDays(ageDays)}
        </span>
      </div>
      <div className="jr-actions">
        {onDismiss && (
          <Button
            variant="icon"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              onDismiss();
            }}
            aria-label={job.is_dismissed ? jobsRestore() : sharedNotForMe()}
            title={job.is_dismissed ? jobsRestoreTitle() : sharedNotForMe()}
          >
            <Icon name={job.is_dismissed ? "refresh" : "eyeOff"} size={14} />
          </Button>
        )}
        {/* Full: still focusable, with the reason as its description, so a
            keyboard, touch or screen-reader user meets why, not only a hover. */}
        <Button
          variant="icon"
          size="sm"
          onClick={(e) => {
            e.stopPropagation();
            if (!compareFull) onToggleCompare();
          }}
          className="jr-compare"
          aria-disabled={compareFull || undefined}
          aria-describedby={compareFull ? fullReasonId : undefined}
          aria-pressed={compareOn}
          aria-label={jobsCompare()}
          title={compareFull ? fullTitle(compareCap) : jobsCompareTitle({ key: "c" })}
        >
          <Icon name={compareOn ? "check" : "columns"} size={14} />
        </Button>
        {compareFull && <span id={fullReasonId} className="sr-only">{fullTitle(compareCap)}</span>}
        <StarButton on={job.is_favorite} onToggle={onToggleFav} size={16} shortcut="s" />
      </div>
    </article>
  );
}
