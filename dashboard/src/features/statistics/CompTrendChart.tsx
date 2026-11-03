import { useMemo, useState } from "react";
import { useSyncEpoch } from "../../context/SyncState";
import { EmptyState, ResourceLoadState, Segmented } from "../../ui";
import { CompTrends, CompTrendDim, CompTrendPoint, CompTrendSeries, InsightsScope, api } from "../../api";
import { useAsyncResource, useRefetchOn } from "../../hooks/useAsyncResource";
import { fmtComp, companyName, BAND_LABEL } from "../../format";
import {
  insightsCompTrendChartBreakdown,
  insightsCompTrendChartByFamily,
  insightsCompTrendChartCompensationOverTime,
  insightsCompTrendChartCompensationPercentileTrend,
  insightsCompTrendChartHistoryIsStillAccruingOne,
  insightsCompTrendChartLoadFailed,
  insightsCompTrendChartLoading,
  insightsCompTrendChartMedianTotalPay,
  insightsCompTrendChartNoCompHistoryYet,
  insightsCompTrendChartRoles,
  insightsCompTrendChartReferenceChanged,
  insightsCompTrendChartReferenceMarker,
  insightsCommonByCompany,
  insightsCommonByLevel,
  insightsCommonMarket,
} from "../../copy/gen/insights";
import { Msg } from "../../ui/Msg";
import { calendarDay } from "../../copy/format";
import { roleName } from "../../copy/vocab";

const W = 100;
const H = 46;
const PAD = 3;

const DIMS: { key: CompTrendDim; label: string }[] = [
  { key: "overall", get label() { return insightsCommonMarket(); } },
  { key: "level", get label() { return insightsCommonByLevel(); } },
  { key: "company", get label() { return insightsCommonByCompany(); } },
  { key: "family", get label() { return insightsCompTrendChartByFamily(); } },
];

// Series stroke palette (cycled). CSS vars so it stays theme-aware.
const COLORS = [
  "var(--app-action)",
  "var(--app-data-1)",
  "var(--app-data-2)",
  "var(--app-positive)",
  "var(--app-data-3)",
  "var(--app-data-4)",
];

// Every series is its key, named here.
function label(dim: CompTrendDim, s: CompTrendSeries): string {
  if (dim === "company") return companyName(s.key);
  if (dim === "level") return BAND_LABEL[s.key] ?? s.key;
  if (dim === "family") return roleName(s.key);
  return insightsCommonMarket();
}

export function CompTrendChart({ days, scope }: { days: number; scope?: InsightsScope }) {
  const [dim, setDim] = useState<CompTrendDim>("overall");
  const { data, error, retry, refresh } = useAsyncResource<CompTrends>(
    () => api.compTrends(dim, days, scope),
    [dim, days, scope],
    { keep: "stats/comp-trends" },
  );
  // A reference change adds a marker and moves today's point.
  const { referenceVersion } = useSyncEpoch();
  useRefetchOn(referenceVersion, refresh);

  const plot = useMemo(() => {
    if (!data) return null;
    const vals: number[] = [];
    for (const s of data.series)
      for (const p of s.points)
        for (const v of [p.p25, p.p50, p.p75, p.p90]) if (v != null) vals.push(v);
    if (!vals.length) return { lo: 0, hi: 1, empty: true };
    let lo = Math.min(...vals);
    let hi = Math.max(...vals);
    if (lo === hi) { lo -= lo * 0.1 || 1; hi += hi * 0.1 || 1; }
    return { lo, hi, empty: false };
  }, [data]);

  if (!data) return <ResourceLoadState error={error} loading={insightsCompTrendChartLoading()} failed={insightsCompTrendChartLoadFailed()} onRetry={retry} />;

  const n = data.dates.length;
  const single = data.series.length === 1;
  const accruing = n <= 1;
  const xAt = (i: number) => (n > 1 ? (i / (n - 1)) * W : W);
  const yAt = (v: number) =>
    H - PAD - ((v - plot!.lo) / (plot!.hi - plot!.lo)) * (H - 2 * PAD);

  const linePath = (pts: CompTrendPoint[], get: (p: CompTrendPoint) => number | null) => {
    const cs: [number, number][] = [];
    pts.forEach((p, i) => { const v = get(p); if (v != null) cs.push([i, v]); });
    if (!cs.length) return "";
    if (cs.length === 1) { const cy = yAt(cs[0][1]); return `M0,${cy.toFixed(1)} L${W},${cy.toFixed(1)}`; }
    return cs.map(([i, v], k) => `${k ? "L" : "M"}${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`).join(" ");
  };

  // Reference changes inside the axis, at the first day on or after each one.
  const markers = n > 1
    ? (data.reference_changes ?? []).flatMap((change) => {
        const day = change.at.slice(0, 10);
        const i = data.dates.findIndex((d) => d >= day);
        return i < 0 ? [] : [{ id: change.id, x: xAt(i), date: calendarDay(day) }];
      })
    : [];

  // p25–p75 band polygon: only meaningful for a single series with a real time axis.
  const bandPath = (pts: CompTrendPoint[]) => {
    if (n <= 1) return "";
    const top: [number, number][] = [];
    const bot: [number, number][] = [];
    pts.forEach((p, i) => {
      if (p.p75 != null) top.push([i, p.p75]);
      if (p.p25 != null) bot.push([i, p.p25]);
    });
    if (top.length < 2 || bot.length < 2) return "";
    const fwd = top.map(([i, v], k) => `${k ? "L" : "M"}${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`).join(" ");
    const back = bot.reverse().map(([i, v]) => `L${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`).join(" ");
    return `${fwd} ${back} Z`;
  };

  return (
    <div className="panel comp-trend">
      <div className="comp-trend-head">
        <div>
          <h3>{insightsCompTrendChartCompensationOverTime()}</h3>
          <div className="sub">{insightsCompTrendChartMedianTotalPay({ series: single ? "single" : "several", period: days <= 0 ? "all" : "days", days })}</div>
        </div>
        <Segmented
          className="chart-seg"
          label={insightsCompTrendChartBreakdown()}
          value={dim}
          onChange={setDim}
          options={DIMS.map((d) => ({ value: d.key, label: d.label }))}
        />
      </div>

      {accruing && (
        <div className="trends-note">
          {insightsCompTrendChartHistoryIsStillAccruingOne()}
        </div>
      )}

      {plot!.empty || data.series.length === 0 ? (
        <EmptyState variant="preview" art="chart" title={insightsCompTrendChartNoCompHistoryYet()} />
      ) : (
        <>
          <div className="comp-trend-plot">
            <div className="comp-trend-yaxis" aria-hidden="true">
              <span>{fmtComp(plot!.hi)}</span>
              <span>{fmtComp((plot!.lo + plot!.hi) / 2)}</span>
              <span>{fmtComp(plot!.lo)}</span>
            </div>
            <svg
              className="comp-trend-svg"
              viewBox={`0 0 ${W} ${H}`}
              preserveAspectRatio="none"
              role="img"
              aria-label={insightsCompTrendChartCompensationPercentileTrend()}
            >
              {single && (
                <path className="comp-trend-band" d={bandPath(data.series[0].points)} />
              )}
              {markers.map((m) => (
                <line key={m.id} className="comp-trend-marker" x1={m.x} x2={m.x} y1={0} y2={H}
                      data-testid="comp-trend-marker">
                  <title>{insightsCompTrendChartReferenceMarker({ date: m.date })}</title>
                </line>
              ))}
              {data.series.map((s, i) => (
                <path
                  key={s.key}
                  className="comp-trend-line"
                  style={{ stroke: COLORS[i % COLORS.length] }}
                  d={linePath(s.points, (p) => p.p50)}
                  fill="none"
                />
              ))}
            </svg>
          </div>

          {markers.length > 0 && (
            <div className="trends-note" data-testid="comp-trend-reference-note">
              {insightsCompTrendChartReferenceChanged({ count: markers.length })}
            </div>
          )}
          {single ? (
            <div className="comp-trend-single">
              <Msg of={insightsCompTrendChartRoles} elems={{ dim: label(data.dim, data.series[0]), count: data.series[0].count }} />
            </div>
          ) : (
            <div className="comp-trend-legend">
              {data.series.map((s, i) => (
                <span key={s.key} className="ct-legend-item">
                  <i style={{ background: COLORS[i % COLORS.length] }} />
                  {label(data.dim, s)}
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
