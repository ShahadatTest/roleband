import { number as copyNumber } from "../../copy/format";
import { useMemo, useState } from "react";
import { DisclosureRates, DisclosureTrendDim, DisclosureTrends, InsightsScope, api } from "../../api";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { EChart } from "../../ui/EChart";
import {
  bandTrendSummary,
  buildBandTrendOption,
  buildDisclosureRateOption,
  buildDisclosureRateTrendOption,
  disclosureRateRows,
  disclosureRateSummary,
  disclosureTrendSummary,
  pct,
  unratedCount,
  withSteadyCohort,
} from "./charts/disclosure";
import { EmptyState, InfoTip, ResourceLoadState, Segmented } from "../../ui";
import {
  insightsCommonByLevel,
  insightsCommonLastDaysOrAllHistory,
  insightsCommonMarket,
  insightsDisclosurePanelAboutThePublishedBandTrend,
  insightsDisclosurePanelBandTrendLoadFailed,
  insightsDisclosurePanelBandTrendLoading,
  insightsDisclosurePanelByEmployer,
  insightsDisclosurePanelDisclosureBreakdown,
  insightsDisclosurePanelHistoryIsStillAccruingOne,
  insightsDisclosurePanelHowTheDisclosureRateIs,
  insightsDisclosurePanelMedianPublishedBand,
  insightsDisclosurePanelMedianPublishedBaseSalaryBand,
  insightsDisclosurePanelNoOpenRolesHaveBeen,
  insightsDisclosurePanelNoPayTransparencyHistoryYet,
  insightsDisclosurePanelNoPublishedBaseSalaryBand,
  insightsDisclosurePanelOfCheckedRolesStatePay,
  insightsDisclosurePanelOfOpenRolesHaveNot,
  insightsDisclosurePanelOverTime,
  insightsDisclosurePanelPayTransparency,
  insightsDisclosurePanelPayTransparencyOverTimeCovers,
  insightsDisclosurePanelPayTransparencyTrend,
  insightsDisclosurePanelPublishedBandTrend,
  insightsDisclosurePanelShareOfCheckedOpenRoles,
  insightsDisclosurePanelShareOfOpenRolesStating,
  insightsDisclosurePanelShareOfOpenRolesStatingOverTime,
  insightsDisclosurePanelTheMarketLineMovesWhen,
  insightsDisclosurePanelTheMedianFloorAndCeiling,
  insightsDisclosurePanelTheShareOfOpenRoles,
  insightsDisclosurePanelTrendBreakdown,
  insightsDisclosurePanelTrendLoadFailed,
  insightsDisclosurePanelTrendLoading,
  insightsDisclosurePanelWhoStatesPay,
} from "../../copy/gen/insights";
import { Msg } from "../../ui/Msg";
import { payBasisName } from "../../copy/vocab";

/**
 * Pay transparency: the disclosure RATE, and both it and the published band over
 * time. Sits beside the published-bands chart, which shows what employers print
 * but never how many of them print anything.
 *
 * The denominator is stated everywhere it is used. `open - checked` roles are
 * queued for the disclosure pass, not silent employers, so they are excluded from
 * the rate and reported separately — the panel must never let a scraping backlog
 * read as an employer choice.
 */

const GROUPS: { key: "company" | "level"; label: string }[] = [
  { key: "company", get label() { return insightsDisclosurePanelByEmployer(); } },
  { key: "level", get label() { return insightsCommonByLevel(); } },
];

const TREND_DIMS: { key: DisclosureTrendDim; label: string }[] = [
  { key: "overall", get label() { return insightsCommonMarket(); } },
  { key: "company", get label() { return insightsDisclosurePanelByEmployer(); } },
  { key: "level", get label() { return insightsCommonByLevel(); } },
];

function BacklogNote({ open, checked }: { open: number; checked: number }) {
  const pending = open - checked;
  if (pending <= 0) return null;
  return (
    <div className="sub">
      <Msg of={insightsDisclosurePanelOfOpenRolesHaveNot} elems={{ pending: copyNumber(pending), open: copyNumber(open) }} />
    </div>
  );
}

export function DisclosureRatePanel({ rates }: { rates: DisclosureRates }) {
  const [group, setGroup] = useState<"company" | "level">("company");
  const rows = useMemo(() => disclosureRateRows(rates, group), [rates, group]);
  const unrated = unratedCount(rates, group);
  const option = useMemo(() => buildDisclosureRateOption(rows), [rows]);
  const o = rates.overall;

  return (
    <div className="panel chart-panel chart-panel-wide">
      <div className="chart-panel-head">
        <div>
          <span className="eyebrow">{insightsDisclosurePanelPayTransparency()}</span>
          <h3>
            {insightsDisclosurePanelWhoStatesPay()}
            <InfoTip label={insightsDisclosurePanelHowTheDisclosureRateIs()}>
              {insightsDisclosurePanelTheShareOfOpenRoles()}
            </InfoTip>
          </h3>
          <BacklogNote open={o.open} checked={o.checked} />
        </div>
        <div className="chart-head-controls">
          {o.rate !== null && (
            <span className="chart-insight">
              <Msg of={insightsDisclosurePanelOfCheckedRolesStatePay} elems={{ rate: pct(o.rate), checked: copyNumber(o.checked) }} />
            </span>
          )}
          {rows.length > 0 && (
            <Segmented
              className="chart-seg"
              label={insightsDisclosurePanelDisclosureBreakdown()}
              value={group}
              onChange={setGroup}
              options={GROUPS.map((g) => ({ value: g.key, label: g.label }))}
            />
          )}
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="empty-hint">{insightsDisclosurePanelNoOpenRolesHaveBeen()}</div>
      ) : (
        <>
          <EChart
            ariaLabel={insightsDisclosurePanelShareOfOpenRolesStating({ group })}
            className="chart-disclosure-rate"
            height={Math.max(180, 40 + rows.length * 26)}
            option={option}
            summary={disclosureRateSummary(rows, unrated)}
          />
        </>
      )}
    </div>
  );
}

function AccruingNote({ dates }: { dates: string[] }) {
  if (dates.length > 1) return null;
  return (
    <div className="trends-note">
      {insightsDisclosurePanelHistoryIsStillAccruingOne()}
    </div>
  );
}

export function DisclosureTrendPanel({
  days,
  scope,
  minRoles,
}: {
  days: number;
  scope?: InsightsScope;
  /** The fewest checked roles the same-companies line may rest on. */
  minRoles: number;
}) {
  const [dim, setDim] = useState<DisclosureTrendDim>("overall");
  // The band medians are only meaningful pooled at the market grain — a median of
  // per-company medians is not a median — so this chart keeps its own market-wide
  // fetch instead of trying to derive one from whatever grouping is selected.
  const market = useAsyncResource<DisclosureTrends>(
    () => api.disclosureTrends("overall", days, scope),
    [days, scope],
    { keep: "stats/disclosure" },
  );
  // The market-wide answer is also the rate trend's "overall": a breakdown is
  // asked for only when another grouping is picked.
  const breakdown = useAsyncResource<DisclosureTrends | null>(
    () => (dim === "overall" ? Promise.resolve(null) : api.disclosureTrends(dim, days, scope)),
    [dim, days, scope],
    { keep: "stats/disclosure-by" },
  );
  const rate = dim === "overall" ? market : breakdown;
  const shown = useMemo(() => (rate.data ? withSteadyCohort(rate.data, minRoles) : null), [rate.data, minRoles]);

  const rateOption = useMemo(
    () => (shown ? buildDisclosureRateTrendOption(shown.dim, shown.dates, shown.series) : null),
    [shown],
  );
  const marketSeries = market.data?.series[0];
  const bandOption = useMemo(
    () => (market.data ? buildBandTrendOption(market.data.dates, marketSeries) : null),
    [market.data, marketSeries],
  );
  const hasBand = (marketSeries?.points ?? []).some((p) => p.low_p50 !== null);
  const window = insightsCommonLastDaysOrAllHistory({ period: days <= 0 ? "all" : "days", days });

  return (
    <>
      <div className="panel chart-panel chart-panel-wide">
        <div className="chart-panel-head">
          <div>
            <span className="eyebrow">{insightsDisclosurePanelOverTime()}</span>
            <h3>{insightsDisclosurePanelPayTransparencyTrend()}</h3>
            <div className="sub">{insightsDisclosurePanelShareOfCheckedOpenRoles({ window })}</div>
          </div>
          <Segmented
            className="chart-seg"
            label={insightsDisclosurePanelTrendBreakdown()}
            value={dim}
            onChange={setDim}
            options={TREND_DIMS.map((d) => ({ value: d.key, label: d.label }))}
          />
        </div>

        {!shown || !rateOption ? (
          <ResourceLoadState
            error={rate.error}
            loading={insightsDisclosurePanelTrendLoading()}
            failed={insightsDisclosurePanelTrendLoadFailed()}
            onRetry={rate.retry}
          />
        ) : shown.series.length === 0 ? (
          <EmptyState variant="preview" art="chart" title={insightsDisclosurePanelNoPayTransparencyHistoryYet()} />
        ) : (
          <>
            <AccruingNote dates={shown.dates} />
            {shown.dim === "overall" && shown.cohort && (
              <div className="trends-note">
                <Msg of={insightsDisclosurePanelTheMarketLineMovesWhen} elems={{ companies: copyNumber(shown.cohort.companies), since: shown.cohort.since }} />
              </div>
            )}
            <EChart
              ariaLabel={insightsDisclosurePanelShareOfOpenRolesStatingOverTime()}
              className="chart-disclosure-trend"
              height={240}
              option={rateOption}
              summary={disclosureTrendSummary(shown.dim, shown.dates, shown.series)}
            />
          </>
        )}
      </div>

      <div className="panel chart-panel chart-panel-wide">
        <div className="chart-panel-head">
          <div>
            <span className="eyebrow">{insightsDisclosurePanelOverTime()}</span>
            <h3>
              {insightsDisclosurePanelPublishedBandTrend()}
              <InfoTip label={insightsDisclosurePanelAboutThePublishedBandTrend()}>
                {insightsDisclosurePanelTheMedianFloorAndCeiling()}
              </InfoTip>
            </h3>
            <div className="sub">
              {insightsDisclosurePanelMedianPublishedBand({ basis: payBasisName(market.data?.basis ?? "base"), window })}
            </div>
          </div>
        </div>

        {!market.data || !bandOption ? (
          <ResourceLoadState
            error={market.error}
            loading={insightsDisclosurePanelBandTrendLoading()}
            failed={insightsDisclosurePanelBandTrendLoadFailed()}
            onRetry={market.retry}
          />
        ) : !hasBand ? (
          <EmptyState variant="preview" art="chart" title={insightsDisclosurePanelNoPublishedBaseSalaryBand()} />
        ) : (
          <>
            <AccruingNote dates={market.data.dates} />
            <EChart
              ariaLabel={insightsDisclosurePanelMedianPublishedBaseSalaryBand()}
              className="chart-band-trend"
              height={240}
              option={bandOption}
              summary={bandTrendSummary(market.data.basis, marketSeries)}
            />
          </>
        )}
      </div>
    </>
  );
}

export function DisclosurePanel({
  rates,
  days,
  scope,
  minRoles,
}: {
  rates: DisclosureRates;
  days: number;
  scope?: InsightsScope;
  minRoles: number;
}) {
  return (
    <>
      <DisclosureRatePanel rates={rates} />
      {/* Its daily snapshots are kept per company and level, with no
          discipline, so a discipline filter cannot reach the trends. */}
      {scope && scope.families.length > 0 && (
        <p className="hiring-note">{insightsDisclosurePanelPayTransparencyOverTimeCovers()}</p>
      )}
      <DisclosureTrendPanel days={days} scope={scope} minRoles={minRoles} />
    </>
  );
}
