import { InsightsScope, StatisticsOverview, api } from "../../api";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { companyName } from "../../format";
import { listedFor } from "./ageCopy";
import { OverviewSignalChart } from "./charts/StatisticsCharts";
import { InfoTip } from "../../ui/InfoTip";
import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { JobLinkRow } from "../../patterns/jobs/JobLinkRow";
import { InsightHero, n } from "./InsightHero";
import {
  insightsCommonClosed,
  insightsCommonLastDaysOrAllTime,
  insightsCommonNew,
  insightsCommonOpenRoles,
  insightsOverviewPanelAboutTheDemandField,
  insightsOverviewPanelCompanies,
  insightsOverviewPanelLargestGroups,
  insightsOverviewPanelLeadsRoles,
  insightsOverviewPanelLoadFailed,
  insightsOverviewPanelLoading,
  insightsOverviewPanelMostNamedSkills,
  insightsOverviewPanelNoGroupsBuiltYet,
  insightsOverviewPanelNoOpenRoles,
  insightsOverviewPanelOpenTheLongest,
  insightsOverviewPanelOpenedClosed,
  insightsOverviewPanelTheRolesAdvertisedLongestThat,
  insightsOverviewPanelTheSkillsOpenRolesName,
  insightsOverviewPanelWhatIsPullingTheMarket,
  insightsOverviewPanelWhatOpenTheLongestMeans,
} from "../../copy/gen/insights";
import { Msg } from "../../ui/Msg";
import { skillName } from "../../copy/vocab";
import { clusterLabel, overviewBrief } from "./names";

export function OverviewPanel({
  days,
  scope,
  onOpen,
  advanced = false,
}: {
  days: number;
  scope?: InsightsScope;
  onOpen: (id: number, companySlug?: string | null) => void;
  /** The advanced view adds the largest groups and the roles open longest. */
  advanced?: boolean;
}) {
  const { data, error, retry } = useAsyncResource<StatisticsOverview>(
    () => api.statisticsOverview(days, scope),
    [days, scope],
    { keep: "stats/overview" },
  );

  if (!data) return <ResourceLoadState error={error} loading={insightsOverviewPanelLoading()} failed={insightsOverviewPanelLoadFailed()} onRetry={retry} />;

  const window = insightsCommonLastDaysOrAllTime({ period: days <= 0 ? "all" : "days", days });
  const k = data.kpis;

  return (
    <>
      <InsightHero
        tab="overview"
        figure={insightsOverviewPanelOpenedClosed({ new_count: String(n(k.new_count)), closed_count: String(n(k.closed_count)) })}
        line={overviewBrief(data, advanced)}
        kpis={[
          { label: insightsCommonOpenRoles(), value: n(k.open_total), sub: insightsOverviewPanelCompanies({ companies: String(n(k.companies)) }) },
          { label: insightsCommonNew(), value: n(k.new_count), sub: window, tone: "good" },
          { label: insightsCommonClosed(), value: n(k.closed_count), sub: window },
        ]}
      />

      {data.top_skills.length > 0 && (
        <div className="panel chart-panel chart-panel-wide">
          <div className="chart-panel-head">
            <div>
              <span className="eyebrow">{insightsOverviewPanelMostNamedSkills()}</span>
              <h3>
                {insightsOverviewPanelWhatIsPullingTheMarket()}
                <InfoTip label={insightsOverviewPanelAboutTheDemandField()}>
                  {insightsOverviewPanelTheSkillsOpenRolesName()}
                </InfoTip>
              </h3>
            </div>
            <span className="chart-insight"><Msg of={insightsOverviewPanelLeadsRoles} elems={{ display: skillName(data.top_skills[0].term), job_count: n(data.top_skills[0].job_count) }} /></span>
          </div>
          <OverviewSignalChart skills={data.top_skills} />
        </div>
      )}

      {/* Two cards of three rows each, and no skills list: it would draw
          the chart above a second time. */}
      {advanced && <div className="demand-grid">
        <div className="panel">
          <h3>{insightsOverviewPanelLargestGroups()}</h3>
          {data.top_clusters.length === 0 && <p className="hiring-note">{insightsOverviewPanelNoGroupsBuiltYet()}</p>}
          {data.top_clusters.map((c) => (
            <div className="bar-row" key={c.id}>
              <span title={clusterLabel(c)}>{clusterLabel(c)}</span>
              <div className="bar-track">
                <div
                  className="bar-fill"
                  style={{ width: `${(c.size / Math.max(1, data.top_clusters[0].size)) * 100}%` }}
                />
              </div>
              <span className="val">{n(c.size)}</span>
            </div>
          ))}
        </div>

        <div className="panel">
          <h3>
            {insightsOverviewPanelOpenTheLongest()}
            <InfoTip label={insightsOverviewPanelWhatOpenTheLongestMeans()}>
              {insightsOverviewPanelTheRolesAdvertisedLongestThat()}
            </InfoTip>
          </h3>
          {data.longest_open.length === 0 && <p className="hiring-note">{insightsOverviewPanelNoOpenRoles()}</p>}
          {data.longest_open.map((job) => (
            <JobLinkRow className="mini-job" key={job.id} jobId={job.id} company={job.company} onOpen={onOpen}>
              <div>
                <div className="mj-title" data-selection="content">{job.title}</div>
                <div className="mj-meta">
                  {[companyName(job.company), listedFor(job.listed_days)].filter(Boolean).join(" · ")}
                </div>
              </div>
            </JobLinkRow>
          ))}
        </div>
      </div>}
    </>
  );
}
