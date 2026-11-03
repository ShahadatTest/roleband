import { errorText } from "../../api/errorText";
import { number as copyNumber } from "../../copy/format";
// Settings > Intelligence: three instruments on the register material.
//
// The screen answers three human questions, one card each:
//   1. Role ranking          (on this computer; the field + the model)
//   2. MCP server            (cloud-connected; the data sheet + one gate)
//   3. Extended capabilities (your own model, the OS built-in model, services)
//
// Material: the shared register material (design/materials/register-material.css),
// by a body marker so portals inherit it, the same mechanism as Companies.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { useBodyAttribute } from "../../hooks/useBodyAttribute";
import {
  DEFAULT_FILTERS,
  IntelligenceFit,
  IntelligenceStatus,
  Job,
  api,
} from "../../api";
import { BAND_LABEL, companyName } from "../../format";
import { CompanyIcon, ResourceLoadState } from "../../ui";
import { positionPath } from "../../routing/paths";
import { AimLine } from "./AimLine";
import { AssistantsCard } from "./AssistantsCard";
import { CapabilitiesCard } from "./CapabilitiesCard";
import { FitBandKey, FitField } from "./FitField";
import { MatchingModel } from "./MatchingModel";
import { OriginBadge } from "./OriginBadge";
import "../../design/materials/register-material.css";
import "./IntelligenceSection.css";
import {
  aiIntelligenceSectionAllAreAtRightNow,
  aiIntelligenceSectionFitRanking,
  aiIntelligenceSectionFitRanking2,
  aiIntelligenceSectionIntelligence,
  aiIntelligenceSectionLoading,
  aiIntelligenceSectionMore,
  aiIntelligenceSectionNewRolesAddedToday,
  aiIntelligenceSectionNoNewRolesToday,
  aiIntelligenceSectionNothingLandsInRightNow,
  aiIntelligenceSectionOpenTheBoard,
  aiIntelligenceSectionPreparingMatchingMb,
  aiIntelligenceSectionPreview,
  aiIntelligenceSectionTheBoardKeepsWorkingMeanwhile,
  aiIntelligenceSectionTheStrongestOfRoles,
  aiIntelligenceSectionThisBand,
  aiIntelligenceSectionYourBestMatches,
  aiIntelligenceSectionBandLoadFailed,
  aiIntelligenceSectionMatchesLoadFailed,
} from "../../copy/gen/ai";
import { Msg } from "../../ui/Msg";
import { fitBandName } from "./serverText";

export function IntelligenceTab() {
  const [status, setStatus] = useState<IntelligenceStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tierMutationInFlight, setTierMutationInFlight] = useState(false);
  // Every mutation edge advances the epoch. A poll captures the epoch it began
  // under and may update state only if no mutation started OR finished while it
  // was away. A boolean is insufficient: a poll can begin before a PUT, then
  // resolve after that PUT finishes and overwrite its newer response.
  const tierMutationEpoch = useRef(0);
  const onTierMutationChange = useCallback((inFlight: boolean) => {
    tierMutationEpoch.current += 1;
    setTierMutationInFlight(inFlight);
  }, []);

  useBodyAttribute("data-material", "register");

  useEffect(() => {
    api
      .intelligence()
      .then(setStatus)
      .catch((e) => setError(errorText(e)));
  }, []);

  // Weights landing and a corpus re-embed are minutes-long background jobs
  // with no push channel; poll only while one runs. A poll that lands mid
  // tier-switch is dropped: the PUT's own response is the fresher truth.
  const settling =
    status != null && (status.matching.reembedding || status.matching.status === "downloading");
  useEffect(() => {
    if (!settling) return;
    let cancelled = false;
    const id = window.setInterval(() => {
      const requestEpoch = tierMutationEpoch.current;
      api
        .intelligence()
        .then((fresh) => {
          if (!cancelled && requestEpoch === tierMutationEpoch.current) setStatus(fresh);
        })
        .catch(() => {});
    }, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [settling]);

  return (
    <div className="intel" role="region" aria-label={aiIntelligenceSectionIntelligence()}>
      <RankingCard
        status={status}
        setStatus={setStatus}
        tierMutationInFlight={tierMutationInFlight}
        onTierMutationChange={onTierMutationChange}
      />
      <AssistantsCard />
      <CapabilitiesCard status={status} setStatus={setStatus} />
      {error && <div className="intel-error" role="alert">{error}</div>}
    </div>
  );
}

/* ---- card 1: how your roles are ranked ----------------------------------- */

/** How many of the best matches the card names. Three: the list is evidence
 *  that the ranking works, not a second board, and more rows push the model
 *  line below the fold. */
const TOP_MATCHES = 3;

const mb = (bytes: number) => Math.round(bytes / (1024 * 1024));

function shortLocation(job: Job): string | null {
  const first = job.locations?.[0];
  if (!first) return null;
  return first.split(",")[0].split(";")[0].trim() || null;
}

/** The company every top match belongs to, when they all share one. A real
 *  pattern worth naming ("all three are at one company"); silence when
 *  the list is mixed, rather than a sentence that says nothing. */
function sharedCompany(jobs: Job[]): string | null {
  if (jobs.length === 0) return null;
  const first = jobs[0].company;
  return jobs.every((j) => j.company === first) ? companyName(first) : null;
}

function RankingCard({
  status,
  setStatus,
  tierMutationInFlight,
  onTierMutationChange,
}: {
  status: IntelligenceStatus | null;
  setStatus: (s: IntelligenceStatus) => void;
  tierMutationInFlight: boolean;
  onTierMutationChange: (inFlight: boolean) => void;
}) {
  const [fit, setFit] = useState<IntelligenceFit | null>(null);
  // Which band of the field the preview list is showing; null = best matches.
  const [band, setBand] = useState<FitBandKey | null>(null);
  // A saved aim sentence re-ranks every role: the matches and a band's sample
  // are read again under it.
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const topResource = useAsyncResource<Job[]>(
    () => api.jobs({ ...DEFAULT_FILTERS, sort: "relevance", limit: TOP_MATCHES, offset: 0 })
      .then((list) => (list.ranked_by === "intent" ? list.items.slice(0, TOP_MATCHES) : [])),
    [revision],
  );
  const bandResource = useAsyncResource<Job[] | null>(
    () => (band == null
      ? Promise.resolve(null)
      : api.intelligenceFitBand(band, TOP_MATCHES).then((r) => r.items.slice(0, TOP_MATCHES))),
    [band, revision],
  );
  const top = topResource.data;

  // Read on mount, and again after the aim sentence is saved: a new sentence
  // re-ranks every role, so the field, the band samples and the preview are
  // all stale at once.
  const loadRanking = useCallback(() => {
    api
      .intelligenceFit()
      .then(setFit)
      .catch((e) => setError(errorText(e)));
  }, []);

  useEffect(loadRanking, [loadRanking]);

  const onAimSaved = useCallback(() => {
    setBand(null);
    setRevision((n) => n + 1);
    loadRanking();
  }, [loadRanking]);

  const matching = status?.matching ?? null;

  const ranked = fit?.ranked ?? false;
  const rankedToday = fit?.embedded_today ?? 0;

  const aside = matching?.reembedding ? (
    <span className="intel-aside">{aiIntelligenceSectionTheBoardKeepsWorkingMeanwhile()}</span>
  ) : matching?.status === "downloading" ? (
    <span className="intel-aside">
      <Msg of={aiIntelligenceSectionPreparingMatchingMb} elems={{ b: <b>{mb(matching.downloaded_bytes)}</b>, total_bytes: mb(matching.total_bytes) }} />
    </span>
  ) : fit && rankedToday > 0 ? (
    <span className="intel-aside">
      <span className="intel-dot is-live" aria-hidden="true" />
      <Msg of={aiIntelligenceSectionNewRolesAddedToday} args={{ count: rankedToday }} elems={{ n: <b>{copyNumber(rankedToday)}</b> }} />
    </span>
  ) : fit ? (
    <span className="intel-aside">
      <span className="intel-dot is-live" aria-hidden="true" />
      {aiIntelligenceSectionNoNewRolesToday()}
    </span>
  ) : null;


  return (
    <section
      className={`intel-card${
        matching?.reembedding || matching?.status === "downloading" || tierMutationInFlight
          ? " is-busy"
          : ""
      }`}
      aria-label={aiIntelligenceSectionFitRanking2()}
    >
      <div className="intel-head">
        <div className="intel-head-title">
          <h2>{aiIntelligenceSectionFitRanking()}</h2>
          <OriginBadge origin="local" />
        </div>
        {aside}
      </div>

      {fit && <AimLine fit={fit} onSaved={onAimSaved} />}

      {fit && ranked && (() => {
        const selInfo = band ? fit.bands.find((b) => b.key === band) ?? null : null;
        // undefined = the band's sample is still loading; the default view is
        // gated on `top` below, so it never renders the loading row.
        const shown = selInfo ? bandResource.data ?? undefined : top ?? undefined;
        // A failed read is said, never shown as an empty list.
        const failed = selInfo ? bandResource : topResource;
        const poolCount = selInfo ? selInfo.count : fit.total;
        return (
          <div className="intel-field">
            <FitField fit={fit} topCount={top?.length ?? 0} selected={band} onSelect={setBand} />
            <div className="intel-sel">
              {failed.error && (
                <ResourceLoadState
                  error={failed.error}
                  failed={selInfo ? aiIntelligenceSectionBandLoadFailed() : aiIntelligenceSectionMatchesLoadFailed()}
                  onRetry={failed.retry}
                />
              )}
              {!failed.error && (selInfo || (top && top.length > 0)) && (
                <>
                  <h3>
                    {aiIntelligenceSectionPreview()}
                    {selInfo ? (
                      <small>
                        <Msg of={aiIntelligenceSectionTheStrongestOfRoles} args={{ count: selInfo.count }} elems={{ label: fitBandName(selInfo.key), n: copyNumber(selInfo.count) }} />
                      </small>
                    ) : (
                      <small>
                        {aiIntelligenceSectionYourBestMatches()}
                        {top && sharedCompany(top) &&
                          (" " + aiIntelligenceSectionAllAreAtRightNow({ length: top.length, top: String(sharedCompany(top)) }))}
                      </small>
                    )}
                  </h3>
                  {shown === undefined ? (
                    <div className="intel-more">{aiIntelligenceSectionLoading()}</div>
                  ) : shown.length === 0 ? (
                    <div className="intel-more">
                      <Msg of={aiIntelligenceSectionNothingLandsInRightNow} elems={{ value: selInfo ? fitBandName(selInfo.key) : aiIntelligenceSectionThisBand() }} />
                    </div>
                  ) : (
                    <>
                      <ol>
                        {shown.map((job, i) => (
                          <li key={job.id}>
                            <i className="intel-rank">{i + 1}</i>
                            <CompanyIcon
                              slug={job.company}
                              display={companyName(job.company)}
                              size={18}
                            />
                            <span className="intel-sel-body">
                              <Link className="intel-sel-title" to={positionPath(job.company, job.id)}>
                                {job.title}
                              </Link>
                              <span className="intel-sel-sub">
                                {[
                                  companyName(job.company),
                                  shortLocation(job),
                                  job.level_band
                                    ? BAND_LABEL[job.level_band] ?? job.level_band
                                    : null,
                                ]
                                  .filter(Boolean)
                                  .join(" · ")}
                              </span>
                            </span>
                          </li>
                        ))}
                      </ol>
                      <div className="intel-more">
                        <Msg of={aiIntelligenceSectionMore} elems={{ max: copyNumber(Math.max(0, poolCount - shown.length)) }} />{" "}
                        <Link to="/">{aiIntelligenceSectionOpenTheBoard()}</Link>
                      </div>
                    </>
                  )}
                </>
              )}
            </div>
          </div>
        );
      })()}

      {matching && (
        <MatchingModel
          status={status!}
          setStatus={setStatus}
          onMutationChange={onTierMutationChange}
        />
      )}

      {error && <div className="intel-error" role="alert">{error}</div>}
    </section>
  );
}
