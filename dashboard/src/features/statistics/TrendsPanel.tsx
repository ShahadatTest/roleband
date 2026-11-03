import { timestamp as copyTimestamp } from "../../copy/format";
import { InsightsScope, SkillSeries, SkillTrends, api } from "../../api";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { SkillTrendChart } from "./charts/StatisticsCharts";
import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { EmptyState } from "../../ui/EmptyState";
import { InsightHero, n } from "./InsightHero";
import {
  insightsCommonLastDaysOrAllHistory,
  insightsCommonSkills,
  insightsTrendsPanelChangePoints,
  insightsTrendsPanelCurrentLedger,
  insightsTrendsPanelDays,
  insightsTrendsPanelDemandHistory,
  insightsTrendsPanelEachSkillSShareOf,
  insightsTrendsPanelHistory,
  insightsTrendsPanelHistoryAccruesOneDayPer,
  insightsTrendsPanelHistoryIsStillAccruingOne,
  insightsTrendsPanelInTheLedger,
  insightsTrendsPanelLatestDay,
  insightsTrendsPanelLeaderShareLine,
  insightsTrendsPanelLeaderSShare,
  insightsTrendsPanelLoadFailed,
  insightsTrendsPanelLoading,
  insightsTrendsPanelNoSkillHistoryYet,
  insightsTrendsPanelNoneYet,
  insightsTrendsPanelNothingToPlotYet,
  insightsTrendsPanelNow,
  insightsTrendsPanelOfSkillMentions,
  insightsTrendsPanelOfSkillMentionsOpenRoles,
  insightsTrendsPanelOfTheSeries,
  insightsTrendsPanelSkillDemandOverTime,
  insightsTrendsPanelSkillLeads,
  insightsTrendsPanelTopPlottedInLedger,
  insightsTrendsPanelWhatIsMeasuredChangedOn,
} from "../../copy/gen/insights";
import { Msg } from "../../ui/Msg";
import { skillName } from "../../copy/vocab";

const W = 100;
const H = 30;
const PAD = 2;

// Build an SVG polyline (or a flat baseline for a single sample) for one series,
// scaled against a shared max so every sparkline shares a comparable y-axis.
function spark(series: SkillSeries, max: number): { path: string; cx: number; cy: number } {
  const pts = series.points;
  const y = (v: number) => H - PAD - (v / max) * (H - 2 * PAD);
  if (pts.length <= 1) {
    const cy = y(pts.length ? pts[0].share : 0);
    return { path: `M0,${cy} L${W},${cy}`, cx: W, cy };
  }
  const coords = pts.map((p, i) => {
    const x = (i / (pts.length - 1)) * W;
    return [x, y(p.share)] as const;
  });
  const path = coords.map(([x, yy], i) => `${i ? "L" : "M"}${x.toFixed(1)},${yy.toFixed(1)}`).join(" ");
  const [cx, cy] = coords[coords.length - 1];
  return { path, cx, cy };
}

export function TrendsPanel({ days, scope }: { days: number; scope?: InsightsScope }) {
  const { data, error, retry } = useAsyncResource<SkillTrends>(
    () => api.skillTrends({ days, limit: 10 }, scope),
    [days, scope],
    { keep: "stats/skill-trends" },
  );

  if (!data) return <ResourceLoadState error={error} loading={insightsTrendsPanelLoading()} failed={insightsTrendsPanelLoadFailed()} onRetry={retry} />;

  const accruing = data.dates.length <= 1;
  // Shares of the day's skill mentions, so the sparklines share an axis
  // that does not jump when the measured set changes.
  const max = Math.max(0.0001, ...data.series.flatMap((s) => s.points.map((p) => p.share)));
  const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
  const points = (x: number) => `${x > 0 ? "+" : ""}${(x * 100).toFixed(1)}`;
  const day = (iso: string) =>
    copyTimestamp(new Date(`${iso}T00:00:00Z`), { month: "short", day: "numeric", timeZone: "UTC" });
  const window = insightsCommonLastDaysOrAllHistory({ period: days <= 0 ? "all" : "days", days });

  const lead = data.series[0];
  // A change compares the window's first day with its last, so it is stated
  // only when both measured the same set; across a set change it would
  // measure the companies and skills that arrived, not demand.
  const steady = data.set_changes.length === 0;
  const ledger = steady ? "" : " is-share-only";
  return (
    <>
      <InsightHero
        tab="trends"
        figure={lead ? insightsTrendsPanelSkillLeads({ skill: skillName(lead.term) }) : insightsTrendsPanelNothingToPlotYet()}
        line={
          lead
            ? insightsTrendsPanelLeaderShareLine({ current_share: pct(lead.current_share), days: n(data.dates.length), window })
            : insightsTrendsPanelHistoryAccruesOneDayPer({ window })
        }
        kpis={[
          { label: insightsTrendsPanelLeaderSShare(), value: lead ? pct(lead.current_share) : "0%", sub: insightsTrendsPanelOfSkillMentions() },
          { label: insightsCommonSkills(), value: n(data.series.length), sub: insightsTrendsPanelInTheLedger() },
          { label: insightsTrendsPanelHistory(), value: n(data.dates.length), sub: insightsTrendsPanelDays({ count: data.dates.length }) },
          {
            label: insightsTrendsPanelLatestDay(),
            value: data.dates.length
              ? copyTimestamp(new Date(`${data.dates[data.dates.length - 1]}T00:00:00Z`), { month: "short", day: "numeric", timeZone: "UTC" })
              : insightsTrendsPanelNoneYet(),
            sub: insightsTrendsPanelOfTheSeries(),
          },
        ]}
      />
    <div className="panel trends-panel">
      <div className="trends-head chart-panel-head">
        <div>
          <span className="eyebrow">{insightsTrendsPanelDemandHistory()}</span>
          <h3>{insightsTrendsPanelSkillDemandOverTime()}</h3>
          <div className="sub">
            <Msg of={insightsTrendsPanelEachSkillSShareOf} elems={{ window: window }} />
          </div>
        </div>
        {data.series.length > 0 && (
          <span className="chart-insight">
            <Msg of={insightsTrendsPanelTopPlottedInLedger} elems={{ plotted: Math.min(6, data.series.length), total: data.series.length }} />
          </span>
        )}
      </div>

      {accruing && (
        <div className="trends-note">
          {insightsTrendsPanelHistoryIsStillAccruingOne()}
        </div>
      )}

      {data.series.length === 0 ? (
        <EmptyState variant="preview" art="chart" title={insightsTrendsPanelNoSkillHistoryYet()} />
      ) : (
        <>
          {data.set_changes.length > 0 && (
            <p className="hiring-note">
              <Msg of={insightsTrendsPanelWhatIsMeasuredChangedOn} elems={{ dates: data.set_changes.map(day).join(", ") }} />
            </p>
          )}
          <SkillTrendChart dates={data.dates} series={data.series} setChanges={data.set_changes} />
          <div className={`trend-ledger-head${ledger}`}>
            <span>{insightsTrendsPanelCurrentLedger()}</span>
            <span>{insightsTrendsPanelNow()}</span>
            {steady && <span>Δ</span>}
          </div>
          <div className="trend-rows">
          {data.series.map((s) => {
            const { path, cx, cy } = spark(s, max);
            const up = s.share_delta > 0;
            const down = s.share_delta < 0;
            return (
              <div className={`trend-row${ledger}`} key={s.term}>
                <span className="trend-name" title={skillName(s.term)}>{skillName(s.term)}</span>
                <svg
                  className="trend-spark"
                  viewBox={`0 0 ${W} ${H}`}
                  preserveAspectRatio="none"
                  aria-hidden="true"
                >
                  <path d={path} className="trend-line" fill="none" />
                  <circle cx={cx} cy={cy} r={2} className="trend-dot" />
                </svg>
                <span className="trend-now" role="img" aria-label={insightsTrendsPanelOfSkillMentionsOpenRoles({ current_share: String(pct(s.current_share)), current: s.current })}>
                  {pct(s.current_share)}
                </span>
                {steady && (
                  <span
                    className={`trend-delta ${up ? "up" : down ? "down" : "flat"}`}
                    role="img"
                    aria-label={insightsTrendsPanelChangePoints({ share_delta: String(points(s.share_delta)) })}
                  >
                    {up || down ? points(s.share_delta) : "0"}
                  </span>
                )}
              </div>
            );
          })}
          </div>
        </>
      )}
    </div>
    </>
  );
}
