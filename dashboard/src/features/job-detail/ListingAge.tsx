import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Job, type ListingEvent, type ListingHistory } from "../../api";
import { fmtDate, relDays } from "../../format";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import { Popover } from "../../ui/Popover";
import {
  roleJobDetailTeam,
  roleJobDetailWorkplace,
  roleListingAgeAnEarlierPostingWasListed,
  roleListingAgeCameBackSameRequisition,
  roleListingAgeChanged,
  roleListingAgeCompareThePostings,
  roleListingAgeCouldnTReadTheHistory,
  roleListingAgeDiscipline,
  roleListingAgeEmployerChangedItsDateTo,
  roleListingAgeEvents,
  roleListingAgeFirstListedPostings,
  roleListingAgeFirstSeenByRoleband,
  roleListingAgeGoneFromTheCareersPage,
  roleListingAgeHistory,
  roleListingAgeLevel,
  roleListingAgeListedFor,
  roleListingAgeListingHistory,
  roleListingAgeLocation,
  roleListingAgeNeverTheStart,
  roleListingAgePossiblyTheSameRoleNot,
  roleListingAgePosting,
  roleListingAgePublishedByTheEmployer,
  roleListingAgeReadingTheHistory,
  roleListingAgeReposted,
  roleListingAgeRetry,
  roleListingAgeReview,
  roleListingAgeRole,
  roleListingAgeRoleListedForAcrossPostings,
  roleListingAgeSameRoleMatchedAutomatically,
  roleListingAgeSince,
  roleListingAgeStatedPay,
  roleListingAgeStillListedAtTheLast,
  roleListingAgeTheEmployerSDate,
  roleListingAgeTheStart,
  roleListingAgeTitle,
  roleListingAgeWhenRolebandFirstSawIt,
} from "../../copy/gen/role";
import { Msg } from "../../ui/Msg";

/* How long a posting has been listed, said once, and its history on demand.
   The headline is the posting's own evidence: the earlier of the
   employer's first date and our first sighting; a later employer date is never
   the start. Role age, when confirmed or automatically matched earlier
   postings exist, is its own row: an inference never moves the headline. The
   history is read only when someone opens it, so an open costs nothing. */

const BASIS: Record<ListingHistory["headline"]["basis"], string> = {
  get employer() { return roleListingAgeTheEmployerSDate(); },
  get sighting() { return roleListingAgeWhenRolebandFirstSawIt(); },
};

/** The employer's fields the history names (the server sends only these). */
const FIELD: Record<string, string> = {
  get title() { return roleListingAgeTitle(); },
  get disclosed_base() { return roleListingAgeStatedPay(); },
  get level_band() { return roleListingAgeLevel(); },
  get family() { return roleListingAgeDiscipline(); },
  get locations() { return roleListingAgeLocation(); },
  get location() { return roleListingAgeLocation(); },
  get team() { return roleJobDetailTeam(); },
  get department() { return roleJobDetailTeam(); },
  get workplace_type() { return roleJobDetailWorkplace(); },
};

const fieldLabel = (field: string | null) =>
  field ? FIELD[field] ?? field.charAt(0).toUpperCase() + field.slice(1).replace(/_/g, " ") : roleListingAgePosting();

/** One history line, in words. `start` marks the event the headline counts from. */
export function eventLine(event: ListingEvent, basis: ListingHistory["headline"]["basis"]): { text: string; note?: string } {
  // A posting is named by its requisition or title; with neither, the line is
  // said without a name, never with a placeholder spliced in where one goes.
  const posting = event.req_id ?? event.title ?? null;
  const link = roleListingAgeSameRoleMatchedAutomatically({ choice: (event.link === "confirmed") ? "yes" : "no" });
  switch (event.kind) {
    case "employer_published":
      return { text: roleListingAgePublishedByTheEmployer(), note: basis === "employer" ? roleListingAgeTheStart() : undefined };
    case "first_seen":
      return { text: roleListingAgeFirstSeenByRoleband(), note: basis === "sighting" ? roleListingAgeTheStart() : undefined };
    case "closed":
      return { text: roleListingAgeGoneFromTheCareersPage() };
    case "reopened":
      return { text: roleListingAgeCameBackSameRequisition() };
    case "redated":
      return { text: roleListingAgeEmployerChangedItsDateTo({ to_at: String(fmtDate(event.to_at)) }), note: roleListingAgeNeverTheStart() };
    case "edited":
      return { text: roleListingAgeChanged({ choice: (event.count && event.count > 1) ? "yes" : "no", field: String(fieldLabel(event.field)), count: (event.count && event.count > 1) ? event.count : "" }) };
    case "earlier_posting":
      return {
        text: roleListingAgeAnEarlierPostingWasListed({ choice: (posting) ? "yes" : "no", choice2: (event.until) ? "yes" : "no", posting: (posting) ? String(posting) : "", until: (event.until) ? String(fmtDate(event.until)) : "" }),
        note: link,
      };
    case "later_posting":
      return { text: roleListingAgeReposted({ choice: (posting) ? "yes" : "no", posting: (posting) ? String(posting) : "" }), note: link };
    case "last_seen":
      return { text: roleListingAgeStillListedAtTheLast() };
  }
}

const TONE: Partial<Record<ListingEvent["kind"], string>> = {
  closed: "is-closed",
  reopened: "is-reopened",
  redated: "is-reopened",
};

function HistoryPanel({
  jobId,
  onOpen,
  onClose,
  onShowPostings,
}: {
  jobId: number;
  onOpen: (id: number) => void;
  onClose: () => void;
  onShowPostings: () => void;
}) {
  const navigate = useNavigate();
  const history = useAsyncResource((signal) => api.jobHistory(jobId, signal), [jobId]);
  if (history.loading) return <p className="jd-history-note">{roleListingAgeReadingTheHistory()}</p>;
  if (history.error || !history.data) {
    return (
      <p className="jd-history-note">
        {roleListingAgeCouldnTReadTheHistory()}{" "}
        <Button variant="link" className="ui-btn-quiet" onClick={history.retry}>{roleListingAgeRetry()}</Button>
      </p>
    );
  }
  const { headline, role, events, unconfirmed } = history.data;
  const postings = events.filter((e) => e.kind === "earlier_posting" || e.kind === "later_posting").length;
  return (
    <>
      <ol className="timeline jd-history" aria-label={roleListingAgeEvents()}>
        {events.map((event, i) => {
          const line = eventLine(event, headline.basis);
          const other = (event.kind === "earlier_posting" || event.kind === "later_posting") && event.job_id != null;
          return (
            <li className={`tl-item${TONE[event.kind] ? ` ${TONE[event.kind]}` : ""}`} key={`${event.kind}-${i}`}>
              <span className="tl-dot" />
              <span className="tl-when">{fmtDate(event.at)}</span>
              <span>
                {other ? (
                  <Button variant="link" onClick={() => { onClose(); onOpen(event.job_id!); }}>{line.text}</Button>
                ) : line.text}
                {line.note && <span className="tl-when"> · {line.note}</span>}
              </span>
            </li>
          );
        })}
      </ol>
      {role && postings > 0 && (
        <p className="jd-history-note">
          <Msg of={roleListingAgeRoleListedForAcrossPostings} elems={{ days: relDays(role.days), postings: role.postings }} />{" "}
          <Button
            variant="link"
            className="ui-btn-quiet"
            onClick={() => {
              onClose();
              onShowPostings();
            }}
          >
            {roleListingAgeCompareThePostings()}
          </Button>
        </p>
      )}
      {unconfirmed.length > 0 && (
        <div className="jd-history-unconfirmed">
          {unconfirmed.map((other) => (
            <p className="jd-history-note" key={other.link_id}>
              <Msg of={roleListingAgePossiblyTheSameRoleNot} elems={{ value: other.req_id ?? other.title }} />{" "}
              <Button variant="link" className="ui-btn-quiet" onClick={() => { onClose(); navigate("/review"); }}>
                {roleListingAgeReview()}
              </Button>
            </p>
          ))}
        </div>
      )}
    </>
  );
}

/** The Details rows: "Listed for" with its basis and the history, and "Role"
    when earlier postings of the same role count. `onShowPostings` brings this
    cover's own posting stack into view, because a document-wide lookup would
    find the page behind an overlay first. The history opens across `column`,
    the side column these rows sit in, at its edges. */
export function ListingAge({
  job, column, onOpen, onShowPostings,
}: {
  job: Job;
  column: HTMLElement | null;
  onOpen: (id: number) => void;
  onShowPostings: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<HTMLButtonElement | null>(null);
  const basis = "listed_basis" in job ? job.listed_basis : null;
  const roleSince = "role_since" in job ? job.role_since : null;
  const rolePostings = "role_postings" in job ? job.role_postings : null;
  return (
    <>
      <dt>{roleListingAgeListedFor()}</dt>
      <dd className="jd-listed">
        <span>{relDays(job.listed_days)}</span>
        {job.listed_since && basis && (
          <span className="jd-listed-basis"><Msg of={roleListingAgeSince} elems={{ listed_since: fmtDate(job.listed_since), bASIS: BASIS[basis] }} /></span>
        )}
        <Button
          ref={setAnchor}
          variant="ghost"
          size="sm"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => setOpen((was) => !was)}
        >
          <Icon name="clock" size={13} /> {roleListingAgeHistory()}
        </Button>
        <Popover isOpen={open} onClose={() => setOpen(false)} anchor={anchor} within={column} label={roleListingAgeListingHistory()} className="app-overlay jd-history-popover">
          <div className="jd-history-title">{roleListingAgeListingHistory()}</div>
          {open && (
            <HistoryPanel jobId={job.id} onOpen={onOpen} onClose={() => setOpen(false)} onShowPostings={onShowPostings} />
          )}
        </Popover>
      </dd>
      {roleSince && rolePostings != null && rolePostings > 1 && (
        <>
          <dt>{roleListingAgeRole()}</dt>
          <dd><Msg of={roleListingAgeFirstListedPostings} elems={{ roleSince: fmtDate(roleSince), rolePostings: rolePostings }} /></dd>
        </>
      )}
    </>
  );
}
