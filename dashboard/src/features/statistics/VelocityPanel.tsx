import { InsightsScope, VelocityStats, api } from "../../api";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { companyName } from "../../format";
import { ageAggregateNote, employerDated } from "./ageCopy";
import { VelocityFlowChart } from "./charts/StatisticsCharts";
import { InfoTip } from "../../ui/InfoTip";
import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { InsightHero, n } from "./InsightHero";
import {
  insightsCommonClosed,
  insightsCommonCompany,
  insightsCommonLastDaysOrAllTime,
  insightsCommonUpdated,
  insightsVelocityPanelAgeOfOpenRoles,
  insightsVelocityPanelClosuresPullLeftOpeningsPush,
  insightsVelocityPanelCompanies,
  insightsVelocityPanelFromTheFirstScanThat,
  insightsVelocityPanelHiringFlow,
  insightsVelocityPanelHowLongPostingsStayUp,
  insightsVelocityPanelHowToReadHiringFlow,
  insightsVelocityPanelLoadFailed,
  insightsVelocityPanelLoading,
  insightsVelocityPanelMarketCurrent,
  insightsVelocityPanelMedianAge,
  insightsVelocityPanelMedianTimePosted,
  insightsVelocityPanelMoreAlreadyListedWhenTheir,
  insightsVelocityPanelNet,
  insightsVelocityPanelNetFlow,
  insightsVelocityPanelOpen,
  insightsVelocityPanelOpenCount,
  insightsVelocityPanelOpened,
  insightsVelocityPanelOpenedCount,
  insightsVelocityPanelOpenedClosed,
  insightsVelocityPanelThisBuildsUpAsRoles,
  insightsVelocityPanelTimePosted,
  insightsVelocityPanelWhatTimePostedMeasures,
} from "../../copy/gen/insights";
import { Msg } from "../../ui/Msg";
import { agingBandName } from "./names";

const days = (value: number | null) => (value == null ? "" : `${Math.round(value)}d`);

export function VelocityPanel({ days: period, scope }: { days: number; scope?: InsightsScope }) {
  const { data, error, retry } = useAsyncResource<VelocityStats>(
    () => api.velocity(period, scope),
    [period, scope],
    { keep: "stats/velocity" },
  );

  if (!data) return <ResourceLoadState error={error} loading={insightsVelocityPanelLoading()} failed={insightsVelocityPanelLoadFailed()} onRetry={retry} />;

  const k = data.kpis;
  const window = insightsCommonLastDaysOrAllTime({ period: period <= 0 ? "all" : "days", days: period });
  const openMax = Math.max(1, ...data.by_company.map((c) => c.open));
  const thinPosted = k.median_observed_listing_duration_days == null;

  return (
    <>
      <InsightHero
        tab="velocity"
        figure={insightsVelocityPanelOpenedCount({ opened: n(k.opened) })}
        line={
          [
            insightsVelocityPanelOpenCount({ open_total: n(k.open_total) }),
            k.median_days_open != null && insightsVelocityPanelMedianAge({ median_days_open: String(days(k.median_days_open)) }),
            k.median_observed_listing_duration_days != null &&
              insightsVelocityPanelMedianTimePosted({ median_observed_listing_duration_days: String(days(k.median_observed_listing_duration_days)) }),
            k.first_scan > 0 && insightsVelocityPanelMoreAlreadyListedWhenTheir({ first_scan: String(n(k.first_scan)) }),
          ]
            .filter(Boolean)
            .join(" · ")
        }
        kpis={[
          { label: insightsVelocityPanelOpened(), value: n(k.opened), sub: window, tone: "good" },
          { label: insightsCommonUpdated(), value: n(k.updated), sub: window },
          { label: insightsCommonClosed(), value: n(k.closed), sub: window },
          {
            label: insightsVelocityPanelNetFlow(),
            value: `${k.net >= 0 ? "+" : ""}${n(k.net)}`,
            sub: insightsVelocityPanelOpenedClosed(),
            tone: k.net > 0 ? "good" : undefined,
          },
        ]}
      />

      {data.by_company.length > 0 && (
        <div className="panel chart-panel chart-panel-wide">
          <div className="chart-panel-head">
            <div>
              <span className="eyebrow">{insightsVelocityPanelMarketCurrent()}</span>
              <h3>
                {insightsVelocityPanelHiringFlow()}
                <InfoTip label={insightsVelocityPanelHowToReadHiringFlow()}>
                  {insightsVelocityPanelClosuresPullLeftOpeningsPush()}
                </InfoTip>
              </h3>
            </div>
            <span className={`chart-insight ${k.net >= 0 ? "good" : "bad"}`}>
              <Msg of={insightsVelocityPanelNet} args={{ direction: k.net >= 0 ? "up" : "down" }} elems={{ net: n(k.net), window: window }} />
            </span>
          </div>
          <VelocityFlowChart companies={data.by_company} />
        </div>
      )}

      {/* One table for everything keyed by company: separate panels for
          activity, time posted and open roles would list the same companies
          three times, at three heights. */}
      <div className="panel vel-companies">
        <h3><Msg of={insightsVelocityPanelCompanies} elems={{ window: window }} /></h3>
        <table className="data-table vel-table">
          <thead>
            <tr>
              <th>{insightsCommonCompany()}</th>
              <th className="num vel-open-col">{insightsVelocityPanelOpen()}</th>
              <th className="num">{insightsVelocityPanelOpened()}</th>
              <th className="num">{insightsCommonClosed()}</th>
              <th className="num">{insightsCommonUpdated()}</th>
              <th className="num">
                {insightsVelocityPanelTimePosted()}
                <InfoTip label={insightsVelocityPanelWhatTimePostedMeasures()}>
                  {insightsVelocityPanelFromTheFirstScanThat()}
                </InfoTip>
              </th>
            </tr>
          </thead>
          <tbody>
            {data.by_company.map((c) => (
              <tr key={c.company}>
                <td>{companyName(c.company)}</td>
                <td className="num vel-open-col">
                  <span className="vel-open">
                    <span className="bar-track">
                      <span className="bar-fill" style={{ width: `${(c.open / openMax) * 100}%` }} />
                    </span>
                    <span>{n(c.open)}</span>
                  </span>
                </td>
                <td className="num pos">{n(c.opened)}</td>
                <td className="num">{n(c.closed)}</td>
                <td className="num">{n(c.updated)}</td>
                <td className="num">{c.median_observed_listing_duration_days != null ? days(c.median_observed_listing_duration_days) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="demand-grid vel-distributions">
        <div className="panel">
          <h3>{insightsVelocityPanelAgeOfOpenRoles()}</h3>
          <Bands bands={data.aging} />
          {/* The bands and the median age keep the first-sighting clock for a
              role we watched open; this says how much of the sample
              the employer also dated (analytics/age_basis). */}
          {ageAggregateNote(k.employer_dated_share) && (
            <div className="trends-note">{ageAggregateNote(k.employer_dated_share)}</div>
          )}
        </div>

        <div className="panel">
          <h3>{insightsVelocityPanelHowLongPostingsStayUp()}</h3>
          {thinPosted ? (
            <div className="trends-note">
              <Msg of={insightsVelocityPanelThisBuildsUpAsRoles} elems={{ closed_sample: k.closed_sample }} />
            </div>
          ) : (
            <Bands bands={data.posted} />
          )}
          {!thinPosted && employerDated(k.closed_employer_dated_share) && (
            <div className="trends-note">{employerDated(k.closed_employer_dated_share)}</div>
          )}
        </div>
      </div>
    </>
  );
}

function Bands({ bands }: { bands: VelocityStats["aging"] }) {
  const max = Math.max(1, ...bands.map((b) => b.count));
  return (
    <>
      {bands.map((b) => (
        <div className="bar-row" key={b.lo}>
          <span>{agingBandName(b.lo)}</span>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${(b.count / max) * 100}%` }} />
          </div>
          <span className="val">{n(b.count)}</span>
        </div>
      ))}
    </>
  );
}
