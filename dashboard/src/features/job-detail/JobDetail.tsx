import "../../patterns/jobs/job-row.css";
import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { Badge } from "../../ui/Badge";
import { Button } from "../../ui/Button";
import { useEffect, useId, useRef, useState } from "react";
import { useSyncEpoch } from "../../context/SyncState";
import { useAsyncResource, useRefetchOn } from "../../hooks/useAsyncResource";
import { useSaveCommand } from "../../context/useSaveCommand";
import { useToast } from "../../ui/Toast";
import { Job, PursuitStage, SimilarJob, api, isNotFound } from "../../api";
import { STAGES, STAGE_LABEL } from "../../copy/vocabulary";
import { domainName, statusName } from "../../copy/vocab";
import { WORKPLACE_LABEL, companyName } from "../../format";
import { payPoint } from "../../payShown";
import { usePayCoverage } from "../../payCoverage";
import JobCompPanel from "./JobCompPanel";
import { JobDescription } from "./JobDescription";
import { JobRequirementsPanel } from "./JobRequirementsPanel";
import { LineageStack } from "./LineageStack";
import { ListingAge } from "./ListingAge";
import { PostingReality } from "./PostingReality";
import { unfollowedSentence } from "../../patterns/jobs/unfollowed";
import { applyAsk } from "./applyAsk";
import { PlaceSetSection } from "./PlaceSetSection";
import { TwinDeck } from "./TwinDeck";
import { Icon } from "../../ui/Icon";
import { Select } from "../../ui/Select";
import { CompanyChip } from "../../patterns/companies/CompanyChip";
import { BandBadge, LocBadge } from "../../patterns/jobs/JobBadges";
import { StarButton } from "../../patterns/jobs/JobControls";
import "./job-detail.css";
import { JobLinkRow } from "../../patterns/jobs/JobLinkRow";
import { Cover } from "../../patterns/Cover";
import { postingPlaces } from "../../patterns/jobs/location";
import { placeGroupsBeyond } from "../../patterns/jobs/placeGroups";
import {
  roleJobDetail1InComparePickOne,
  roleJobDetailAdvisoryBasis,
  roleJobDetailAdvisoryUnclear,
  roleJobDetailBack,
  roleJobDetailBack2,
  roleJobDetailCompare,
  roleJobDetailCompareIsFullMax,
  roleJobDetailCompareRoles,
  roleJobDetailCouldNotUnsaveThisRole,
  roleJobDetailCouldnTUpdateTheStage,
  roleJobDetailDescription,
  roleJobDetailDetails,
  roleJobDetailHardToPlace,
  roleJobDetailItSNoLongerIn,
  roleJobDetailLikelyOutsideYourWorlds,
  roleJobDetailLikelyYourKindOfRole,
  roleJobDetailMoreLikeThis,
  roleJobDetailNext,
  roleJobDetailNotStarted,
  roleJobDetailOtherCompanies,
  roleJobDetailPostings,
  roleJobDetailQuestionsTheEmployerAddedBeyond,
  roleJobDetailRadarSRead,
  roleJobDetailReposted,
  roleJobDetailRole,
  roleJobDetailSameCompany,
  roleJobDetailSetAStage,
  roleJobDetailSimilarity,
  roleJobDetailTrackingExplainer,
  roleJobDetailStage,
  roleJobDetailStatus,
  roleJobDetailTeam,
  roleJobDetailToApply,
  roleJobDetailViewApply,
  roleJobDetailWorkplace,
  roleJobDetailYourProgress,
} from "../../copy/gen/role";
import { Msg } from "../../ui/Msg";
import { Content } from "../../ui/Content";
import { shellLoadRoleFailed, shellLoadingRole } from "../../copy/gen/shell";

/** Similar positions shown per category (same company / other companies). */
const SIMILAR_PER_CATEGORY = 3;

/* Full-screen opportunity detail. Rendered by JobRoute at /job/:id — as a routed
   overlay over the current page (in-app navigation) or standalone (direct link /
   refresh). onBack pops history back to wherever the user came from. */
export function JobDetail({
  jobId,
  onBack,
  onOpen,
  onCompare = () => {},
  compareOn,
  compareCount,
  compareDisabled,
  compareCap,
  onToggleCompare,
  onViewCompare,
  onCompanyResolved,
  asOverlay = false,
}: {
  jobId: number;
  onBack: () => void;
  onOpen: (id: number, companySlug?: string | null) => void;
  /** Replace the selection with these roles and go to Compare. The twin deck's
   *  verb: "compare this posting with its twins" is a whole comparison, not an
   *  addition to one. */
  onCompare?: (ids: number[]) => void;
  /** This role is in the standing compare selection. */
  compareOn: boolean;
  /** How many roles the selection holds, this one included. The reader who
   *  picks while reading needs to know what they are picking INTO — one is a
   *  comparison still waiting for its other half, two is one they can go and
   *  read. */
  compareCount: number;
  /** The selection is at the cap. Only blocks ADDING; a selected role can
   *  always be taken back out. */
  compareDisabled: boolean;
  /** How many roles the comparison holds, so a blocked toggle can say why. */
  compareCap: number;
  onToggleCompare: () => void;
  /** Go to the comparison. Offered only once there is one to see (>= 2). */
  onViewCompare: () => void;
  /** True when this covers a page that is still mounted underneath (opened from
   *  a list). Then it is a modal dialog; reached by a direct link it is the
   *  page itself and must NOT claim to be one. */
  asOverlay?: boolean;
  // Reports the loaded job's company slug so a bare /job/:id URL can
  // canonicalize to /company/:slug/job/:id.
  onCompanyResolved?: (companySlug: string) => void;
}) {
  // On the shared resource, which aborts the request it supersedes: a slow
  // /jobs/:id for the PREVIOUS position never lands after the next one.
  const detail = useAsyncResource<Job>((signal) => api.job(jobId, signal), [jobId]);
  const compareFull = compareDisabled && !compareOn;
  const fullReasonId = useId();
  const { data: job, mutate: setJobData, refresh: refreshJob, error: notFoundError, loading, retry: retryJob } = detail;
  // Its estimate moved with a reference change: re-read it.
  const { referenceVersion } = useSyncEpoch();
  useRefetchOn(referenceVersion, refreshJob);
  const setJob = (next: Job | ((prev: Job | null) => Job | null)) =>
    setJobData((prev) => (typeof next === "function" ? next(prev) : next));
  const notFound = notFoundError != null;
  // Three per category, fetched as three: more near-identical rows under the
  // two category labels read as one wall of text. The cap is a reading limit, not a ranking one: applied at the request so nothing is
  // fetched to be hidden, and again on the response so the reader never sees
  // more than three even if a source ignores `limit`.
  const capped = (r: { items: SimilarJob[] }) => r.items.slice(0, SIMILAR_PER_CATEGORY);
  const similarWithin = useAsyncResource<SimilarJob[]>(
    (signal) => api.similar(jobId, "within", SIMILAR_PER_CATEGORY, signal).then(capped),
    [jobId],
  );
  const similarCross = useAsyncResource<SimilarJob[]>(
    (signal) => api.similar(jobId, "cross", SIMILAR_PER_CATEGORY, signal).then(capped),
    [jobId],
  );
  // The similar rows show pay too: a source switch re-reads them with the job.
  useRefetchOn(referenceVersion, similarWithin.refresh);
  useRefetchOn(referenceVersion, similarCross.refresh);
  const { toast } = useToast();
  // A confirmed save refreshes the counts and tells every reader of saved
  // state, the comparison under this cover included.
  const saveRole = useSaveCommand();
  const within = similarWithin.data ?? [];
  const cross = similarCross.data ?? [];

  const showSaved = (on: boolean) => setJob((prev) => prev && { ...prev, is_favorite: on });

  const toggleFav = () => {
    if (!job) return;
    const next = !job.is_favorite;
    // One writer per role across every surface. A failed write that
    // is still the newest rolls the star back to what the server holds at
    // once, rather than leaving it lit until the next load.
    saveRole({ jobId: job.id, was: job.is_favorite, next, show: showSaved, send: () => api.setFavorite(job.id, next) })
      .catch(() => {
        toast({ key: "job", text: roleJobDetailCouldNotUnsaveThisRole({ choice: (next) ? "yes" : "no" }) });
      });
  };

  const setStage = (stage: PursuitStage) => {
    if (!job) return;
    // Pursuing saves the role (server rule), so it is a save, ordered with the
    // star's writes: a stage set after an Unsave must not land before it.
    saveRole({
      jobId: job.id, was: job.is_favorite, next: true, show: showSaved,
      send: () => api.setPursuit(job.id, { stage }).then((result) => {
        setJob((prev) => prev && { ...prev, pursuit: result.pursuit });
        return result;
      }),
    }).catch(() => toast({ key: "job", text: roleJobDetailCouldnTUpdateTheStage() }));
  };

  // Once the job is loaded, report its company so a bare /job/:id URL can
  // canonicalize to the company-scoped position path.
  useEffect(() => {
    if (job) onCompanyResolved?.(job.company);
  }, [job, onCompanyResolved]);

  // Read what applying asks from the posting's own page, once, AFTER
  // the page is shown, so an open never waits on the source. The server says
  // whether there is anything to read; a failure shows nothing and the next
  // open may try again. It cannot loop: success clears the flag, and a failure
  // leaves the dependencies unchanged.
  const formReadable = job != null && "application_form_readable" in job && job.application_form_readable;
  const jobIdLoaded = job?.id;
  // The header's place line: the first few places, which its tags must not repeat.
  const places = job ? postingPlaces(job.locations).slice(0, 4) : [];
  // One ask per posting per open, whatever the detail says afterwards: the
  // refresh below reads the flag again, and a server that kept saying
  // "readable" must not turn that into a loop.
  const askedFor = useRef<number | null>(null);
  /** This cover's posting stack, for its History's "Compare the postings". */
  const lineageRef = useRef<HTMLElement>(null);
  /** The side column, which its History opens across. */
  const [aside, setAside] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!formReadable || jobIdLoaded == null || askedFor.current === jobIdLoaded) return;
    askedFor.current = jobIdLoaded;
    let live = true;
    api
      .readPostingPage(jobIdLoaded)
      .then((result) => {
        if (!live) return;
        setJobData((prev) =>
          prev && prev.id === jobIdLoaded
            ? { ...prev, application_form: result.application_form, application_form_readable: false }
            : prev,
        );
        // The page may also state the pay the text left out, which changes
        // the pay panel and the pay floor line: read the detail again, keeping
        // what is shown until it lands.
        if (result.outcome === "read") void refreshJob({ preserveData: true });
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [formReadable, jobIdLoaded, setJobData, refreshJob]);

  // Scroll to the top when switching between jobs (e.g. via a similar-role link).
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, [jobId]);

  const label = roleJobDetailRole({ choice: (job) ? "yes" : "no", title: (job) ? String(job.title) : "" });

  /* The screen's body. Identical in both shells — only the CONTAINER differs,
     because the two are different things to a keyboard and a screen reader:
     opened over a list this is a modal dialog, reached by a direct link it is
     the page itself. */
  const bar = (
    <>
        <Button onClick={onBack} aria-label={roleJobDetailBack2()}>
          <Icon name="arrowLeft" size={15} /> {roleJobDetailBack()}
        </Button>
        <div className="cover-bar-spacer" />
        {/* The standing selection, stated where the gesture is. Leaving the
            cover does not end it — it is server-backed — so the
            reader who picks here needs to be told what happens next: at one
            the comparison is waiting for its other half, at two it can be
            read. Without this the count lives only in the rail badge, and the
            beacon that would say it does not raise until the second role. */}
        {job && compareCount === 1 && (
          <span className="jd-compare-state" role="status">
            {roleJobDetail1InComparePickOne()}
          </span>
        )}
        {job && compareCount >= 2 && (
          <Button variant="link" onClick={onViewCompare}>
            <Msg of={roleJobDetailCompareRoles} elems={{ compareCount: compareCount }} /> <Icon name="arrowRight" size={13} />
          </Button>
        )}
        {job && (
          /* Visible text IS the accessible name, and `aria-pressed` carries the
             state — the row's icon-only twin has to spell both into a label,
             but here there is room to say it once. */
          <>
            {/* Full: still focusable, with the reason as its description. */}
            <Button
              onClick={() => { if (!compareFull) onToggleCompare(); }}
              aria-pressed={compareOn}
              aria-disabled={compareFull || undefined}
              aria-describedby={compareFull ? fullReasonId : undefined}
              title={compareFull ? roleJobDetailCompareIsFullMax({ compareCap: compareCap }) : undefined}
            >
              <Icon name={compareOn ? "check" : "columns"} size={15} />{" "}
              {roleJobDetailCompare({ choice: (compareOn) ? "yes" : "no" })}
            </Button>
            {compareFull && (
              <span id={fullReasonId} className="sr-only">{roleJobDetailCompareIsFullMax({ compareCap: compareCap })}</span>
            )}
          </>
        )}
        {job && <StarButton on={job.is_favorite} onToggle={toggleFav} size={20} />}
        {job && (
          <a className="ui-btn ui-btn-primary ui-btn-md" href={job.url} target="_blank" rel="noreferrer">
            {roleJobDetailViewApply()} <Icon name="external" size={15} />
          </a>
        )}
    </>
  );

  const body = (
    <>
        {loading && (
          <div className="jd-container">
            <ResourceLoadState error={null} loading={shellLoadingRole()} />
          </div>
        )}
        {notFound && (
          <div className="jd-container">
            {/* One error card app-wide, with a way out, never a bare "Not
                found" label with no retry. */}
            <ResourceLoadState
              error={notFoundError ?? new Error("not found")}
              failed={shellLoadRoleFailed()}
              onRetry={retryJob}
              gone={isNotFound(notFoundError) ? roleJobDetailItSNoLongerIn() : undefined}
            />
          </div>
        )}
        {job && (
          <div className="jd-container">
            <header className="jd-hero">
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                <CompanyChip slug={job.company} />
                <BandBadge band={job.level_band} confidence={job.level_confidence} basis={job.level_basis} />
                {(job.lineage_size ?? 0) > 1 ? (
                  <Badge shape="tag" variant="tint" tone="warning"><Msg of={roleJobDetailPostings} elems={{ lineage_size: job.lineage_size }} /></Badge>
                ) : (
                  job.repost_count > 0 && (
                    <Badge shape="tag" variant="tint" tone="warning"><Msg of={roleJobDetailReposted} elems={{ repost_count: job.repost_count }} /></Badge>
                  )
                )}
              </div>
              <h1><Content text={job.title} /></h1>
              <div className="job-meta">
                {places.map((l, i) => (
                  <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                    {i === 0 && <Icon name="pin" size={13} />} <Content text={l} />
                  </span>
                ))}
                {placeGroupsBeyond(job.location_groups, places).map((g) => (
                  <LocBadge key={g} slug={g} />
                ))}
              </div>
              {job.company_unfollowed && (
                <p className="jd-unfollowed">{unfollowedSentence(job)}</p>
              )}
            </header>

            {(job.lineage_size ?? 0) > 1 && <LineageStack ref={lineageRef} jobId={job.id} />}
            {/* The deck shows direct twins only, and the row counts them: a role
                with none asks for nothing. */}
            {job.twin_count > 0 && <TwinDeck jobId={job.id} onOpen={onOpen} onCompare={onCompare} />}
            <PlaceSetSection jobId={job.id} onOpen={onOpen} />

            <div className="jd-grid">
              <div className="jd-main">
                {/* ONE total, not two. The market median is a reconciliation line
                    inside the package, not a peer panel with its own headline, so a
                    disagreement is stated rather than left for the reader to
                    arbitrate. */}
                <JobCompPanel job={job} />

                <JobRequirementsPanel
                  requirements={job.requirements}
                  onShowSection={(key) =>
                    scrollRef.current
                      ?.querySelector(`.jd-section-${key}`)
                      ?.scrollIntoView({ behavior: "smooth", block: "start" })
                  }
                />

                <div className="section-title">{roleJobDetailDescription()}</div>
                <JobDescription
                  sections={job.description_sections}
                  fallback={job.description_text}
                />
              </div>

              <aside className="jd-aside" ref={setAside}>
                <div className="section-title">{roleJobDetailYourProgress()}</div>
                <div className="jd-pursuit">
                  {/* Stage select doubles as the "start pursuing" entry point:
                      picking any stage creates the pursuit (and saves the
                      role — pursuing implies saved, the server's rule). */}
                  <label className="jd-pursuit-label">
                    <span>{roleJobDetailNotStarted({ choice: (job.pursuit) ? "yes" : "no" })}</span>
                    <Select<PursuitStage | "">
                      label={roleJobDetailStage()}
                      value={job.pursuit?.stage ?? ""}
                      onChange={(stage) => stage && setStage(stage)}
                      options={[
                        ...(job.pursuit ? [] : [{ value: "" as const, label: roleJobDetailSetAStage() }]),
                        ...STAGES.map((stage) => ({ value: stage, label: STAGE_LABEL[stage] })),
                      ]}
                    />
                  </label>
                  {!job.pursuit && (
                    <p className="jd-pursuit-explainer">{roleJobDetailTrackingExplainer()}</p>
                  )}
                  {job.pursuit?.next_action && (
                    <div className="jd-pursuit-next"><Msg of={roleJobDetailNext} elems={{ next_action: job.pursuit.next_action }} /></div>
                  )}
                </div>

                {job.relevance_review && (
                  <>
                    <div className="section-title">{roleJobDetailRadarSRead()}</div>
                    {/* Advisory only: it never gates anything. The stored
                        rationale, model and confidence stay in the API for the
                        bench; the confidence is margin-derived, not a
                        probability, so no figure reaches the reader. */}
                    <div className="jd-advisory" data-relevance={job.relevance_review.relevance}>
                      <div className="jd-advisory-verdict">
                        {job.relevance_review.relevance === "relevant" && roleJobDetailLikelyYourKindOfRole()}
                        {job.relevance_review.relevance === "irrelevant" && roleJobDetailLikelyOutsideYourWorlds()}
                        {job.relevance_review.relevance === "uncertain" && roleJobDetailHardToPlace()}
                        {job.relevance_review.domain && (
                          <span className="jd-advisory-domain"> · {domainName(job.relevance_review.domain)}</span>
                        )}
                      </div>
                      {job.relevance_review.relevance === "uncertain" && (
                        <p className="jd-advisory-rationale">{roleJobDetailAdvisoryUnclear()}</p>
                      )}
                      <div className="jd-advisory-meta">{roleJobDetailAdvisoryBasis()}</div>
                    </div>
                  </>
                )}

                <div className="section-title">{roleJobDetailDetails()}</div>
                <dl className="kv">
                  <dt>{roleJobDetailTeam()}</dt>
                  <dd>{job.team || job.department ? <Content text={(job.team || job.department)!} /> : "—"}</dd>
                  <dt>{roleJobDetailWorkplace()}</dt>
                  <dd>{WORKPLACE_LABEL[job.workplace_type] ?? job.workplace_type}</dd>
                  {/* One age, with where it counts from; the dates behind it
                      are the history, on demand. */}
                  <ListingAge
                    job={job}
                    column={aside}
                    onOpen={(id) => onOpen(id)}
                    onShowPostings={() => lineageRef.current?.scrollIntoView({ block: "start" })}
                  />
                  <dt>{roleJobDetailStatus()}</dt>
                  <dd style={{ textTransform: "capitalize" }}>{statusName(job.status) ?? <Content text={job.status} />}</dd>
                  {/* Read from the posting's own page; absent until read. */}
                  {"application_form" in job && job.application_form && (
                    <>
                      <dt>{roleJobDetailToApply()}</dt>
                      <dd title={roleJobDetailQuestionsTheEmployerAddedBeyond()}>
                        {applyAsk(job.application_form)}
                      </dd>
                    </>
                  )}
                </dl>

                <PostingReality reality={job.posting_reality} />

                {(within.length > 0 || cross.length > 0) && (
                  <>
                    <div className="section-title">{roleJobDetailMoreLikeThis()}</div>
                    {cross.length > 0 && (
                      <div className="similar-group">
                        <div data-selection="chrome" className="similar-label">{roleJobDetailOtherCompanies()}</div>
                        {cross.map((s) => (
                          <SimilarRow key={s.id} job={s} onOpen={onOpen} />
                        ))}
                      </div>
                    )}
                    {within.length > 0 && (
                      <div className="similar-group">
                        <div data-selection="chrome" className="similar-label"><Msg of={roleJobDetailSameCompany} elems={{ company: companyName(job.company) }} /></div>
                        {within.map((s) => (
                          <SimilarRow key={s.id} job={s} onOpen={onOpen} />
                        ))}
                      </div>
                    )}
                  </>
                )}
              </aside>
            </div>
          </div>
        )}
    </>
  );

  /* The shell is patterns/Cover: opened from a list it is a modal
     dialog over the page still mounted underneath; reached by URL it is the
     page. This screen keeps `job-detail` on the root for its scoped rules. */
  return (
    <Cover label={label} asOverlay={asOverlay} onBack={onBack} bar={bar} className="job-detail" scrollRef={scrollRef}>
      {body}
    </Cover>
  );
}

function SimilarRow({ job, onOpen }: { job: SimilarJob; onOpen: (id: number, companySlug?: string | null) => void }) {
  const pay = payPoint(job, usePayCoverage());
  return (
    <JobLinkRow className="mini-job similar-row" jobId={job.id} company={job.company} onOpen={onOpen}>
      <div>
        <div className="mj-title" data-selection="content"><Content text={job.title} /></div>
        <div className="mj-meta">
          {companyName(job.company)}
          {pay.text !== "—" && <> · <span title={pay.hint}>{pay.text}</span></>}
        </div>
      </div>
      <span className="similar-score" title={roleJobDetailSimilarity()}>
        {Math.round(job.score * 100)}%
      </span>
    </JobLinkRow>
  );
}
