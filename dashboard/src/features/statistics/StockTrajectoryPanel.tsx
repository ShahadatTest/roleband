import "../../patterns/figure-table.css";
import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { useMemo, useState } from "react";
import type { CompPackage, CompTrajectory } from "../../api";
import { api } from "../../api";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { useSourceSwitch } from "../../context/SyncState";
import { InsightHero } from "./InsightHero";
import { fmtComp, companyName } from "../../format";
import { TrajectoryShockChart } from "./charts/StatisticsCharts";
import { InfoTip } from "../../ui/InfoTip";
import { Abbr } from "../../ui/Abbr";
import { Button } from "../../ui/Button";
import {
  insightsCommonCompany,
  insightsStockTrajectoryPanelAboutPublicCompanyProjections,
  insightsStockTrajectoryPanelAtPriceChange,
  insightsStockTrajectoryPanelCashElection,
  insightsStockTrajectoryPanelChange,
  insightsStockTrajectoryPanelEquity,
  insightsStockTrajectoryPanelEquityFigure,
  insightsStockTrajectoryPanelEquityShare,
  insightsStockTrajectoryPanelEquityShockwave,
  insightsStockTrajectoryPanelHowStockTrajectoryIsProjected,
  insightsStockTrajectoryPanelHowToReadEquitySensitivity,
  insightsStockTrajectoryPanelLoadFailed,
  insightsStockTrajectoryPanelLoading,
  insightsStockTrajectoryPanelMedianTc,
  insightsStockTrajectoryPanelMedianTcFull,
  insightsStockTrajectoryPanelMedianTcTile,
  insightsStockTrajectoryPanelMedianTcTileFull,
  insightsStockTrajectoryPanelNoEquity,
  insightsStockTrajectoryPanelNoExposure,
  insightsStockTrajectoryPanelNoOpenRolesAtPublic,
  insightsStockTrajectoryPanelNoOpenRolesAtPublicYet,
  insightsStockTrajectoryPanelOfTcAtRisk,
  insightsStockTrajectoryPanelOfTcAtRiskFull,
  insightsStockTrajectoryPanelOptions,
  insightsStockTrajectoryPanelPaidInCashUnaffectedBy,
  insightsStockTrajectoryPanelPreIpoEquityIsIlliquid,
  insightsStockTrajectoryPanelPrivateCompanies,
  insightsStockTrajectoryPanelProjected,
  insightsStockTrajectoryPanelProjectedTc,
  insightsStockTrajectoryPanelProjectedTcFull,
  insightsStockTrajectoryPanelPublicCompanies,
  insightsStockTrajectoryPanelResetToToday,
  insightsStockTrajectoryPanelRsus,
  insightsStockTrajectoryPanelScenario,
  insightsStockTrajectoryPanelSensitivityExplained,
  insightsStockTrajectoryPanelSortedByEquityExposureOnly,
  insightsStockTrajectoryPanelSplitSource,
  insightsStockTrajectoryPanelSplitSourceExplained,
  insightsStockTrajectoryPanelStockMovesRePriceEquity,
  insightsStockTrajectoryPanelStockPriceChange,
  insightsStockTrajectoryPanelStockPriceChangePercent,
  insightsStockTrajectoryPanelStockTrajectory,
  insightsStockTrajectoryPanelTicker,
  insightsStockTrajectoryPanelToday,
  insightsStockTrajectoryPanelTypicalPackage,
  insightsStockTrajectoryPanelVsToday,
  insightsStockTrajectoryPanelWhoMovesWhenTheStock,
  insightsStockTrajectoryPanelWhyPrivateCompaniesDoNot,
} from "../../copy/gen/insights";
import { Msg } from "../../ui/Msg";

// Project a comp package onto a stock-price scenario: only the equity slice
// moves (base + bonus are fixed cash), so TC(d) = base + bonus + equity*(1+d).
function projectTc(p: CompPackage, priceChange: number): number {
  return Math.round(p.base + p.bonus + p.equity * (1 + priceChange));
}
const projectedDelta = (p: CompPackage, d: number) => Math.round(p.equity * d);

function fmtSigned(n: number): string {
  const s = fmtComp(Math.abs(n));
  return n < 0 ? `−${s}` : `+${s}`;
}
const fmtPct = (frac: number) => `${Math.round(frac * 100)}%`;

const VEHICLE_LABEL: Record<string, string> = {
  get rsu() { return insightsStockTrajectoryPanelRsus(); },
  get options() { return insightsStockTrajectoryPanelOptions(); },
  get none() { return insightsStockTrajectoryPanelNoEquity(); },
  get cash_election() { return insightsStockTrajectoryPanelCashElection(); },
};

// Says plainly whether a split was measured or guessed. The gap is material:
// a guessed split can give equity to a company that pays no stock at all.
function SplitSource({ source }: { source?: CompPackage["split_source"] }) {
  // Defensive: an absent split_source must render nothing, never throw:
  // one missing field should not take down the whole panel.
  if (!source) return null;
  return (
    <span className={`split-src split-src-${source}`} title={insightsStockTrajectoryPanelSplitSourceExplained({ split: source })}>
      {insightsStockTrajectoryPanelSplitSource({ split: source })}
    </span>
  );
}

// -75%..+200% in 5% steps; the scenario the equity slice is stress-tested at.
const SLIDER_MIN = -75;
const SLIDER_MAX = 200;
// At today's price the chart shows what a 10% move is worth to each company:
// a chart of zeros would ask a reader to act before telling them anything.
const SENSITIVITY = 0.1;

export function StockTrajectoryPanel() {
  const [pct, setPct] = useState(0); // stock price change, whole percent
  const { data, error, retry, refresh } = useAsyncResource<CompTrajectory>(api.compTrajectory, [], { keep: "stats/stock-trajectory" });
  // The split follows the source answering pay.
  useSourceSwitch(refresh);

  const d = pct / 100;

  const overall = data?.overall ?? null;
  const projected = useMemo(
    () => (overall ? projectTc(overall, d) : null),
    [overall, d],
  );

  if (!data) {
    return <ResourceLoadState error={error} loading={insightsStockTrajectoryPanelLoading()} failed={insightsStockTrajectoryPanelLoadFailed()} onRetry={retry} />;
  }

  if (!overall) {
    return (
      <div className="panel">
        <h3>{insightsStockTrajectoryPanelStockTrajectory()}</h3>
        <div className="empty-hint">
          {insightsStockTrajectoryPanelNoOpenRolesAtPublic()}
        </div>
      </div>
    );
  }

  const baseline = overall.median_tc;
  const delta = projected! - baseline;
  const sign = pct > 0 ? "up" : pct < 0 ? "down" : "flat";

  return (
    <>
      <InsightHero
        tab="trajectory"
        className="traj-cockpit"
        // At today's price the projection is today's figure again, so the
        // headline is what a move would act on: the equity share.
        figure={sign === "flat"
          ? insightsStockTrajectoryPanelEquityFigure({ share: fmtPct(overall.equity_pct) })
          : <Abbr
              short={insightsStockTrajectoryPanelProjectedTc({ projected: String(fmtComp(projected)) })}
              full={insightsStockTrajectoryPanelProjectedTcFull({ projected: String(fmtComp(projected)) })}
            />}
        line={<>{insightsStockTrajectoryPanelTypicalPackage({ split: overall.split_source })}
            <InfoTip label={insightsStockTrajectoryPanelHowStockTrajectoryIsProjected()}>
              {insightsStockTrajectoryPanelStockMovesRePriceEquity({ split: overall.split_source, bonus_pct: fmtPct(data.assumptions.bonus_pct) })}
            </InfoTip></>}
        kpis={[
          { label: insightsStockTrajectoryPanelToday(), value: fmtComp(baseline), sub: <Abbr short={insightsStockTrajectoryPanelMedianTcTile()} full={insightsStockTrajectoryPanelMedianTcTileFull()} /> },
          {
            label: insightsStockTrajectoryPanelProjected(),
            value: fmtComp(projected),
            sub: insightsStockTrajectoryPanelAtPriceChange({ move: sign, pct }),
            tone: sign === "up" ? "good" : sign === "down" ? "bad" : undefined,
          },
          {
            label: insightsStockTrajectoryPanelChange(),
            value: delta === 0 ? "$0" : fmtSigned(delta),
            sub: insightsStockTrajectoryPanelVsToday(),
            tone: delta > 0 ? "good" : delta < 0 ? "bad" : undefined,
          },
          { label: insightsStockTrajectoryPanelEquityShare(), value: fmtPct(overall.equity_pct), sub: <Abbr short={insightsStockTrajectoryPanelOfTcAtRisk()} full={insightsStockTrajectoryPanelOfTcAtRiskFull()} /> },
        ]}
      >


          <label className="traj-slider-row">
            <span className="traj-slider-label">
              {insightsStockTrajectoryPanelStockPriceChange()}
              <output className="traj-slider-val" aria-live="polite">
                {pct > 0 ? "+" : ""}
                {pct}%
              </output>
            </span>
            <input
              type="range"
              className="traj-slider"
              min={SLIDER_MIN}
              max={SLIDER_MAX}
              step={5}
              value={pct}
              aria-label={insightsStockTrajectoryPanelStockPriceChangePercent()}
              onChange={(e) => setPct(Number(e.target.value))}
            />
          </label>
          <div className="traj-reset-row">
            {pct !== 0 && (
              <Button variant="link" onClick={() => setPct(0)}>
                {insightsStockTrajectoryPanelResetToToday()}
              </Button>
            )}
          </div>
      </InsightHero>

      {data.public.length > 0 && (
        <div className="panel chart-panel chart-panel-wide">
          <div className="chart-panel-head">
            <div>
              <span className="eyebrow">{insightsStockTrajectoryPanelEquityShockwave()}</span>
              <h3>
                {insightsStockTrajectoryPanelWhoMovesWhenTheStock()}
                <InfoTip label={insightsStockTrajectoryPanelHowToReadEquitySensitivity()}>
                  {insightsStockTrajectoryPanelSensitivityExplained({ move: sign })}
                </InfoTip>
              </h3>
            </div>
            <span className={`chart-insight ${sign === "up" ? "good" : sign === "down" ? "bad" : ""}`}>
              {insightsStockTrajectoryPanelScenario({ move: sign, pct })}
            </span>
          </div>
          <TrajectoryShockChart companies={data.public} priceChange={pct === 0 ? SENSITIVITY : d} />
        </div>
      )}

      <div className="panel">
        <h3>
          <Msg of={insightsStockTrajectoryPanelPublicCompanies} args={{ move: sign }} elems={{ pct: pct }} />
          <InfoTip label={insightsStockTrajectoryPanelAboutPublicCompanyProjections()}>
            {insightsStockTrajectoryPanelSortedByEquityExposureOnly()}
          </InfoTip>
        </h3>
        {data.public.length === 0 ? (
          <div className="empty-hint">{insightsStockTrajectoryPanelNoOpenRolesAtPublicYet()}</div>
        ) : (
          <table className="traj-table">
            <thead>
              <tr>
                <th scope="col">{insightsCommonCompany()}</th>
                <th scope="col">{insightsStockTrajectoryPanelTicker()}</th>
                <th scope="col">{insightsStockTrajectoryPanelEquity()}</th>
                <th scope="col" className="num">{insightsStockTrajectoryPanelEquityShare()}</th>
                <th scope="col" className="num">{insightsStockTrajectoryPanelToday()}</th>
                <th scope="col" className="num">{insightsStockTrajectoryPanelProjected()}</th>
                <th scope="col" className="num">{insightsStockTrajectoryPanelChange()}</th>
              </tr>
            </thead>
            <tbody>
              {data.public.map((c) => {
                const proj = projectTc(c, d);
                const ch = projectedDelta(c, d);
                // A listed company can still be immune to its own stock price:
                // one that pays a cash election has an equity share of 0.
                const immovable = c.equity_pct === 0;
                return (
                  <tr key={c.company} className={immovable ? "traj-immovable" : undefined}>
                    <th scope="row">{companyName(c.company)}</th>
                    <td className="traj-ticker">{c.ticker}</td>
                    <td className="traj-vehicle">
                      {c.equity_vehicle ? VEHICLE_LABEL[c.equity_vehicle] ?? c.equity_vehicle : "—"}
                      <SplitSource source={c.split_source} />
                    </td>
                    <td className="num">{fmtPct(c.equity_pct)}</td>
                    <td className="num">{fmtComp(c.median_tc)}</td>
                    <td className="num">{fmtComp(proj)}</td>
                    <td className={`num ${ch > 0 ? "good" : ch < 0 ? "bad" : ""}`}>
                      {immovable ? (
                        <span title={insightsStockTrajectoryPanelPaidInCashUnaffectedBy()}>
                          {insightsStockTrajectoryPanelNoExposure()}
                        </span>
                      ) : ch === 0 ? (
                        "—"
                      ) : (
                        fmtSigned(ch)
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {data.private.length > 0 && (
        <div className="panel">
          <h3>
            {insightsStockTrajectoryPanelPrivateCompanies()}
            <InfoTip label={insightsStockTrajectoryPanelWhyPrivateCompaniesDoNot()}>
              {insightsStockTrajectoryPanelPreIpoEquityIsIlliquid()}
            </InfoTip>
          </h3>
          <table className="traj-table">
            <thead>
              <tr>
                <th scope="col">{insightsCommonCompany()}</th>
                <th scope="col" className="num">{insightsStockTrajectoryPanelEquityShare()}</th>
                <th scope="col" className="num"><Abbr short={insightsStockTrajectoryPanelMedianTc()} full={insightsStockTrajectoryPanelMedianTcFull()} /></th>
              </tr>
            </thead>
            <tbody>
              {data.private.map((c) => (
                <tr key={c.company}>
                  <th scope="row">{companyName(c.company)}</th>
                  <td className="num">{fmtPct(c.equity_pct)}</td>
                  <td className="num">{fmtComp(c.median_tc)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
