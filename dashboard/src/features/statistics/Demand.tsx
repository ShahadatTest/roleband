import { timestamp as copyTimestamp, number as copyNumber } from "../../copy/format";
import { useState } from "react";
import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { Demand as DemandData, HiringRegion, InsightsScope, api } from "../../api";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { LOC_LABEL, companyName } from "../../format";
import { payPoint } from "../../payShown";
import { usePayCoverage } from "../../payCoverage";
import { listedFor } from "./ageCopy";
import { Icon } from "../../ui/Icon";
import { InfoTip } from "../../ui/InfoTip";
import { Button, SearchField, Sheet } from "../../ui";
import { HiringCompaniesChart, type HiringBar } from "./charts/StatisticsCharts";
import { JobLinkRow } from "../../patterns/jobs/JobLinkRow";
import { count, NOUN } from "../../copy/vocabulary";
import { matchCompanies, topCompanies } from "./hiring";
import { InsightHero, n } from "./InsightHero";
import {
  insightsCommonAllCompanies,
  insightsCommonByCompany,
  insightsCommonClosed,
  insightsCommonCompanies,
  insightsCommonNew,
  insightsCommonOpenRoles,
  insightsDemandARoleOpenInSeveral,
  insightsDemandAbout,
  insightsDemandAllCompaniesHiring,
  insightsDemandAllOf,
  insightsDemandAndMoreCountries,
  insightsDemandChangedRepeatedlyWithoutAClosure,
  insightsDemandClosedThenReappearedARepeated,
  insightsDemandEachRoleCountsOnceHowever,
  insightsDemandEachRoleOnce,
  insightsDemandFindACompany,
  insightsDemandHiringNowTodayNewClosed,
  insightsDemandHowCompaniesAreCounted,
  insightsDemandHowRegionsAreCounted,
  insightsDemandLast2Days,
  insightsDemandListedOverAYearAre,
  insightsDemandLoadFailed,
  insightsDemandLoading,
  insightsDemandLongestOpenRoles,
  insightsDemandMoreHold,
  insightsDemandNameNoPlaceWeCan,
  insightsDemandNoDataYet,
  insightsDemandNoOpenRolesAtThese,
  insightsDemandNoOpenRolesYet,
  insightsDemandNoneDetectedYet,
  insightsDemandOf,
  insightsDemandOpen,
  insightsDemandOpenRolesByCompany,
  insightsDemandOpenRolesByRegion,
  insightsDemandPotentialHardToFillSignal,
  insightsDemandReposted,
  insightsDemandRepostedRoles,
  insightsDemandShowAll,
  insightsDemandToday,
  insightsDemandUpdatedButNeverClosed,
  insightsDemandUpdatedTimes,
  insightsDemandWithAnOpenRole,
  insightsOtherCompanies,
  insightsYourCompanies,
} from "../../copy/gen/insights";
import { Msg } from "../../ui/Msg";

/** Leaders shown per view; the rest fold into one row that still counts them. */
const TOP_COMPANIES = 15;
const TOP_COUNTRIES = 8;
const LIST_ROWS = 5;

const SIDE_LABEL: Record<InsightsScope["side"], string> = {
  get all() { return insightsCommonAllCompanies(); },
  get yours() { return insightsYourCompanies(); },
  get other() { return insightsOtherCompanies(); },
};

const place = (key: string) => LOC_LABEL[key] ?? key;

export function DemandView({
  onOpen,
  scope,
  advanced = false,
}: {
  onOpen: (id: number, companySlug?: string | null) => void;
  scope?: InsightsScope;
  /** The advanced view adds the longest-open, reposted and updated lists. */
  advanced?: boolean;
}) {
  /* The error path is real, never a hardcoded `error={null}`: without it a
     failed /api/demand renders a spinner that never resolves, with no message
     and no retry, and the only escape is a page reload. The `loading-spinner`
     ratchet measures the markup and cannot see that. */
  const { data, error, retry } = useAsyncResource<DemandData>(() => api.demand(scope), [scope], { keep: "stats/demand" });
  const cover = usePayCoverage();
  const side = scope?.side ?? "all";
  const [allOpen, setAllOpen] = useState(false);
  if (!data) {
    return (
      <div className="stats-view">
        <ResourceLoadState error={error} loading={insightsDemandLoading()} failed={insightsDemandLoadFailed()} onRetry={retry} />
      </div>
    );
  }

  const hiring = data.companies.filter((c) => c.open > 0).length;
  const { rows, rest, total } = topCompanies(data.companies, TOP_COMPANIES);
  const sideOpen = rows.reduce((n, c) => n + c.open, 0) + (rest?.open ?? 0);
  const bars: HiringBar[] = rows.map((c) => ({
    label: companyName(c.company),
    open: c.open,
    fresh: c.new_today,
    closed: c.closed_today,
  }));

  return (
    <>
      <InsightHero
        tab="demand"
        figure={insightsDemandOpen({ role: String(count(NOUN.role, data.open_total)) })}
        line={insightsDemandHiringNowTodayNewClosed({ company: String(count(NOUN.company, hiring)), new_today: String(n(data.new_today)), closed_today: String(n(data.closed_today)) })}
        kpis={[
          { label: insightsCommonOpenRoles(), value: n(data.open_total), sub: insightsDemandEachRoleOnce() },
          { label: insightsCommonCompanies(), value: n(hiring), sub: insightsDemandWithAnOpenRole() },
          { label: insightsCommonNew(), value: n(data.new_today), sub: insightsDemandLast2Days(), tone: "good" },
          { label: insightsCommonClosed(), value: n(data.closed_today), sub: insightsDemandToday() },
        ]}
      />

      <div className="panel chart-panel chart-panel-wide hiring-companies">
        <div className="chart-panel-head">
          <div>
            <span className="eyebrow">{insightsCommonByCompany()}</span>
            <h3>
              {insightsDemandOpenRolesByCompany()}
              <InfoTip label={insightsDemandHowCompaniesAreCounted()}>
                {insightsDemandEachRoleCountsOnceHowever()}
              </InfoTip>
            </h3>
          </div>
          <span className="chart-insight">{SIDE_LABEL[side]}</span>
        </div>
        {bars.length > 0 ? (
          <HiringCompaniesChart bars={bars} />
        ) : (
          <p className="hiring-note">{insightsDemandNoOpenRolesAtThese()}</p>
        )}
        {/* The tail is a sentence, not a bar: drawn, its sum would flatten
            the leaders beside it. */}
        {rest && (
          <div className="hiring-foot">
            <p className="hiring-note">
              {insightsDemandMoreHold({
                companies: count(NOUN.company, rest.companies),
                roles: count(NOUN.role, rest.open),
                share: sideOpen > 0 ? "known" : "none",
                percent: sideOpen > 0 ? Math.round((rest.open / sideOpen) * 100) : 0,
              })}
            </p>
            <Button variant="link" onClick={() => setAllOpen(true)}>
              <Msg of={insightsDemandShowAll} elems={{ company: count(NOUN.company, total) }} />
            </Button>
          </div>
        )}
      </div>
      <AllCompanies data={data} title={SIDE_LABEL[side]} isOpen={allOpen} onClose={() => setAllOpen(false)} />

      <RegionsPanel regions={data.regions} unplaced={data.unplaced} />

      {advanced && <div className="demand-grid">
        <RoleList
          title={insightsDemandLongestOpenRoles()}
          tip={insightsDemandPotentialHardToFillSignal()}
          empty={insightsDemandNoDataYet()}
          note={
            data.listed_over_a_year > 0
              ? insightsDemandListedOverAYearAre({ role: String(count(NOUN.role, data.listed_over_a_year)) })
              : null
          }
          rows={data.longest_open.slice(0, LIST_ROWS).map((j) => ({
            job: j,
            meta: [companyName(j.company), listedFor(j.listed_days)].filter(Boolean).join(" · "),
            value: payPoint(j, cover).text,
          }))}
          onOpen={onOpen}
        />
        <RoleList
          title={insightsDemandRepostedRoles()}
          tip={insightsDemandClosedThenReappearedARepeated()}
          empty={insightsDemandNoneDetectedYet()}
          rows={data.most_reposted.slice(0, LIST_ROWS).map((j) => ({
            job: j,
            meta: insightsDemandReposted({ company: String(companyName(j.company)), repost_count: j.repost_count }),
            value: payPoint(j, cover).text,
          }))}
          onOpen={onOpen}
        />
        <RoleList
          title={insightsDemandUpdatedButNeverClosed()}
          tip={insightsDemandChangedRepeatedlyWithoutAClosure()}
          empty={insightsDemandNoneDetectedYet()}
          rows={data.most_updated_open.slice(0, LIST_ROWS).map((j) => ({
            job: j,
            meta: (
              <>
                {companyName(j.company)}
                <span className="update-counter" role="img" aria-label={insightsDemandUpdatedTimes({ update_count: j.update_count })} title={insightsDemandUpdatedTimes({ update_count: j.update_count })}>
                  <Icon name="refresh" size={11} />
                  <span>{j.update_count}</span>
                </span>
              </>
            ),
            value: j.last_updated_at ? copyTimestamp(new Date(j.last_updated_at), { year: "numeric", month: "numeric", day: "numeric" }) : "",
          }))}
          onOpen={onOpen}
        />
      </div>}
    </>
  );
}

function RoleList({
  title,
  tip,
  empty,
  note = null,
  rows,
  onOpen,
}: {
  title: string;
  tip: string;
  empty: string;
  note?: string | null;
  rows: { job: { id: number; company: string; title: string }; meta: React.ReactNode; value: string }[];
  onOpen: (id: number, companySlug?: string | null) => void;
}) {
  return (
    <div className="panel">
      <h3>
        {title}
        <InfoTip label={insightsDemandAbout({ title: String(title.toLowerCase()) })}>{tip}</InfoTip>
      </h3>
      {rows.length === 0 && <div style={{ color: "var(--app-text-faint)" }}>{empty}</div>}
      {rows.map(({ job, meta, value }) => (
        <JobLinkRow className="mini-job" key={job.id} jobId={job.id} company={job.company} onOpen={onOpen}>
          <div>
            <div className="mj-title" data-selection="content">{job.title}</div>
            <div className="mj-meta">{meta}</div>
          </div>
          <span className="n">{value}</span>
        </JobLinkRow>
      ))}
      {note && <p className="hiring-note">{note}</p>}
    </div>
  );
}

function RegionsPanel({ regions, unplaced }: { regions: HiringRegion[]; unplaced: number }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const max = Math.max(1, ...regions.map((r) => r.open));
  return (
    <div className="panel hiring-regions">
      <h3>
        {insightsDemandOpenRolesByRegion()}
        <InfoTip label={insightsDemandHowRegionsAreCounted()}>
          {insightsDemandARoleOpenInSeveral()}
        </InfoTip>
      </h3>
      {regions.length === 0 && <div style={{ color: "var(--app-text-faint)" }}>{insightsDemandNoOpenRolesYet()}</div>}
      {regions.map((region) => {
        const isOpen = expanded === region.key;
        const countries = region.countries.slice(0, TOP_COUNTRIES);
        const more = region.countries.length - countries.length;
        const countryMax = Math.max(1, ...countries.map((c) => c.open), region.region_wide);
        return (
          <div className="hiring-region" key={region.key}>
            <div className="bar-row">
              <span>
                <Button
                  variant="link"
                  aria-expanded={isOpen}
                  onClick={() => setExpanded(isOpen ? null : region.key)}
                >
                  {place(region.key)}
                </Button>
              </span>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${(region.open / max) * 100}%` }} />
              </div>
              <span className="val">{copyNumber(region.open)}</span>
            </div>
            {isOpen && (
              <div className="hiring-countries">
                {countries.map((c) => (
                  <div className="bar-row" key={c.key}>
                    <span>{place(c.key)}</span>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${(c.open / countryMax) * 100}%` }} />
                    </div>
                    <span className="val">{copyNumber(c.open)}</span>
                  </div>
                ))}
                {region.region_wide > 0 && (
                  <div className="bar-row hiring-region-wide">
                    <span><Msg of={insightsDemandAllOf} elems={{ region: place(region.key) }} /></span>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${(region.region_wide / countryMax) * 100}%` }} />
                    </div>
                    <span className="val">{copyNumber(region.region_wide)}</span>
                  </div>
                )}
                {more > 0 && <p className="hiring-note">{insightsDemandAndMoreCountries({ more })}</p>}
              </div>
            )}
          </div>
        );
      })}
      {unplaced > 0 && (
        <p className="hiring-note">
          <Msg of={insightsDemandNameNoPlaceWeCan} elems={{ role: count(NOUN.role, unplaced) }} />
        </p>
      )}
    </div>
  );
}

function AllCompanies({
  data,
  title,
  isOpen,
  onClose,
}: {
  data: DemandData;
  title: string;
  isOpen: boolean;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const { rows } = topCompanies(data.companies, Number.MAX_SAFE_INTEGER);
  const shown = matchCompanies(rows, query, companyName);
  const max = Math.max(1, ...rows.map((c) => c.open));
  return (
    <Sheet isOpen={isOpen} onClose={onClose} label={insightsDemandAllCompaniesHiring()} className="hiring-sheet app-overlay">
      {/* A portal leaves the screen's design-system root, so the sheet names
          its own, as Cover does: the bar rows are styled under it. */}
      <div className="hiring-sheet-body" data-design-system="app">
      <div className="hiring-sheet-head">
        <h3>{title}</h3>
        <SearchField label={insightsDemandFindACompany()} value={query} onChange={setQuery} size="sm" />
        <span className="hiring-note" data-selection="chrome">
          <Msg of={insightsDemandOf} elems={{ shown: copyNumber(shown.length), companies: count(NOUN.company, rows.length) }} />
        </span>
      </div>
      <div className="hiring-sheet-list">
        {shown.map((c) => (
          <div className="bar-row" key={c.company}>
            <span>{companyName(c.company)}</span>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${(c.open / max) * 100}%` }} />
            </div>
            <span className="val">{copyNumber(c.open)}</span>
          </div>
        ))}
      </div>
      </div>
    </Sheet>
  );
}
