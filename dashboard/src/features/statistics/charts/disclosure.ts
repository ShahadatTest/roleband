import type { EChartsCoreOption } from "echarts/core";
import type {
  DisclosureRates,
  DisclosureTrendDim,
  DisclosureTrendSeries,
  DisclosureTrends,
} from "../../../api";
import { companyName, fmtComp } from "../../../format";
import { levelLabel } from "./levelLabel";
import { BORDER, DATA_2, FAINT, MUTED, SIGNAL, compactGrid, valueAxis } from "./options";
import {
  insightsDisclosureMedianCeiling,
  insightsDisclosureMedianFloor,
  insightsDisclosureMedianPublishedSalaryBandAcross,
  insightsDisclosureNoBandPosted,
  insightsDisclosureNoOpenRolesHaveBeen,
  insightsDisclosureNoPayTransparencyHistoryRecorded,
  insightsDisclosureNoPublishedPayBandHas,
  insightsDisclosureNoRolesCheckedYet,
  insightsDisclosureOfCheckedOpenRoles,
  insightsDisclosureOfCheckedRolesStatePay,
  insightsDisclosureOfRoles,
  insightsDisclosureShareOfCheckedOpenRoles,
  insightsDisclosureShareOfOpenRolesStating,
  insightsSeriesSameCompanies,
  insightsDisclosureUnclassified,
  insightsCommonMarket,
  insightsDisclosureNotChecked,
  insightsDisclosureRatePercent,
  insightsDisclosureRateStatesPay,
} from "../../../copy/gen/insights";
import { payBasisName } from "../../../copy/vocab";
import { tooltipHtml } from "./tooltip";

/**
 * Pay-transparency chart options (pure — no canvas, unit-testable).
 *
 * Two quantities, deliberately never on one axis:
 *
 * - The RATE (%): how many open roles state pay at all. Its denominator is the
 *   roles the disclosure pass has read, so a group whose `rate` is null has not
 *   been checked yet and is dropped rather than drawn at 0% — "we have not
 *   looked" and "this employer publishes nothing" are different findings.
 * - The published BAND ($): the median floor and ceiling employers print, pooled
 *   within one pay basis. Charted at the market grain as a range, matching the
 *   floating-bar treatment of the current-state bands.
 */

export const pct = (rate: number) => `${Math.round(rate * 100)}%`;

export interface DisclosureRateRow {
  key: string;
  label: string;
  rate: number;
  disclosed: number;
  checked: number;
}

/** Rows for the current-state rate chart, unchecked groups dropped. Lowest
 * rate first: the employers that post no range are what a reader looks for here. */
export function disclosureRateRows(
  rates: DisclosureRates,
  dim: "company" | "level",
): DisclosureRateRow[] {
  const source =
    dim === "company"
      ? rates.by_company.map((c) => ({ ...c, key: c.company, label: companyName(c.company) }))
      : rates.by_level.map((l) => ({
          ...l,
          key: l.level_band,
          label: l.level_band ? levelLabel(l.level_band) : insightsDisclosureUnclassified(),
        }));
  return source
    .filter((row): row is typeof row & { rate: number } => row.rate !== null)
    .map(({ key, label, rate, disclosed, checked }) => ({ key, label, rate, disclosed, checked }))
    .sort((a, b) => a.rate - b.rate || b.checked - a.checked);
}

/** Groups whose rate cannot be stated yet, so the panel can say so out loud. */
export function unratedCount(rates: DisclosureRates, dim: "company" | "level"): number {
  const source = dim === "company" ? rates.by_company : rates.by_level;
  return source.filter((row) => row.rate === null).length;
}

export function disclosureRateSummary(rows: DisclosureRateRow[], unrated: number): string {
  if (!rows.length) return insightsDisclosureNoOpenRolesHaveBeen();
  const rates = rows.map((r) => insightsDisclosureOfRoles({ label: r.label, rate: pct(r.rate), disclosed: r.disclosed, checked: r.checked })).join(". ");
  return insightsDisclosureShareOfCheckedOpenRoles({ rates, unrated });
}

export function buildDisclosureRateOption(rows: DisclosureRateRow[]): EChartsCoreOption {
  // ECharts draws category 0 at the bottom, so the rows go in reversed to put
  // the first on top; every index the chart hands back is into this order.
  const drawn = [...rows].reverse();
  return {
    // The EChart wrapper supplies a concise aria-label plus an sr-only summary;
    // echarts' own generated label would replace it with a robot paragraph.
    aria: { enabled: false },
    grid: { ...compactGrid, left: 14, right: 96, top: 12, bottom: 22 },
    tooltip: {
      trigger: "item",
      formatter: (p: { dataIndex: number }) => {
        const r = drawn[p.dataIndex];
        if (!r) return "";
        return tooltipHtml(r.label, [
          insightsDisclosureRateStatesPay({ rate: pct(r.rate) }),
          insightsDisclosureOfCheckedOpenRoles({ disclosed: r.disclosed, checked: r.checked }),
        ]);
      },
    },
    // A share is always read against 0-100%, never against the leader — an
    // auto-scaled axis would make 12% look like a full bar.
    xAxis: {
      ...valueAxis,
      min: 0,
      max: 100,
      axisLabel: { color: FAINT, fontSize: 9, formatter: (v: number) => `${v}%` },
    },
    yAxis: {
      type: "category",
      data: drawn.map((r) => r.label),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: MUTED, fontSize: 10, interval: 0 },
    },
    series: [
      {
        type: "bar",
        barMaxWidth: 14,
        itemStyle: { color: SIGNAL, borderRadius: [0, 3, 3, 0] },
        data: drawn.map((r) => Math.round(r.rate * 1000) / 10),
        label: {
          show: true,
          position: "right",
          color: MUTED,
          fontFamily: "var(--app-font-mono)",
          fontSize: 9,
          formatter: (p: { dataIndex: number }) => {
            const r = drawn[p.dataIndex];
            return r ? `${pct(r.rate)} · ${r.disclosed}/${r.checked}` : "";
          },
        },
      },
    ],
  };
}

/** The trend as drawn: the same-companies line only while its latest reading
 *  rests on `minRoles` checked roles or more, the floor every other pay
 *  figure keeps. A thinner one is a company or two, not the market held
 *  still, and its rate jumps whole steps with each role. */
export function withSteadyCohort(trend: DisclosureTrends, minRoles: number): DisclosureTrends {
  const cohort = trend.series.find((s) => s.key === "cohort");
  if (!cohort || cohort.checked >= minRoles) return trend;
  return { ...trend, cohort: null, series: trend.series.filter((s) => s !== cohort) };
}

function trendLabel(dim: DisclosureTrendDim, series: DisclosureTrendSeries): string {
  if (dim === "company") return companyName(series.key);
  if (dim === "level") return levelLabel(series.key);
  return series.key === "cohort" ? insightsSeriesSameCompanies() : insightsCommonMarket();
}

export function disclosureTrendSummary(
  dim: DisclosureTrendDim,
  dates: string[],
  series: DisclosureTrendSeries[],
): string {
  if (!series.length || !dates.length) return insightsDisclosureNoPayTransparencyHistoryRecorded();
  const lines = series.map((s) => {
    const rated = s.points.filter((p) => p.rate !== null);
    const first = rated[0];
    const last = rated[rated.length - 1];
    if (!last) return insightsDisclosureNoRolesCheckedYet({ dim: trendLabel(dim, s) });
    return insightsDisclosureOfCheckedRolesStatePay({
      series: trendLabel(dim, s),
      pct: pct(last.rate as number),
      checked: last.checked,
      readings: rated.length > 1 ? "several" : "single",
      from: pct(first.rate as number),
    });
  });
  return insightsDisclosureShareOfOpenRolesStating({
    dim,
    span: dates.length > 1 ? "range" : "day",
    first: dates[0],
    last: dates[dates.length - 1],
    lines: lines.join(". "),
  });
}

const LINE_COLORS = [SIGNAL, DATA_2, "var(--app-data-3)", "var(--app-data-4)", "var(--app-positive)", MUTED];

export function buildDisclosureRateTrendOption(
  dim: DisclosureTrendDim,
  dates: string[],
  series: DisclosureTrendSeries[],
): EChartsCoreOption {
  return {
    aria: { enabled: false },
    grid: { ...compactGrid, left: 34, right: 16, top: 28, bottom: 22 },
    // The market alone needs no legend; beside its fixed cohort it does.
    legend:
      dim === "overall" && series.length < 2
        ? { show: false }
        : { top: 0, right: 0, itemHeight: 8, itemWidth: 8, textStyle: { color: MUTED, fontSize: 10 } },
    tooltip: {
      trigger: "axis",
      valueFormatter: (v: number | null) => (v == null ? insightsDisclosureNotChecked() : insightsDisclosureRatePercent({ rate: v })),
    },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: dates,
      axisLine: { lineStyle: { color: BORDER } },
      axisTick: { show: false },
      axisLabel: { color: FAINT, fontSize: 9, hideOverlap: true },
    },
    yAxis: {
      ...valueAxis,
      min: 0,
      max: 100,
      axisLabel: { color: FAINT, fontSize: 9, formatter: (v: number) => `${v}%` },
    },
    series: series.map((s, i) => ({
      name: trendLabel(dim, s),
      type: "line" as const,
      smooth: true,
      showSymbol: dates.length === 1,
      symbolSize: 5,
      lineStyle: {
        width: 2,
        color: LINE_COLORS[i % LINE_COLORS.length],
        type: s.key === "cohort" ? ("dashed" as const) : ("solid" as const),
      },
      itemStyle: { color: LINE_COLORS[i % LINE_COLORS.length] },
      // A day with nothing checked is a gap, not a 0% reading.
      connectNulls: false,
      data: s.points.map((p) => (p.rate === null ? null : Math.round(p.rate * 1000) / 10)),
    })),
  };
}

export function bandTrendSummary(basis: string, series: DisclosureTrendSeries | undefined): string {
  const points = (series?.points ?? []).filter((p) => p.low_p50 !== null && p.high_p50 !== null);
  if (!points.length) return insightsDisclosureNoPublishedPayBandHas();
  const last = points[points.length - 1];
  const first = points[0];
  return insightsDisclosureMedianPublishedSalaryBandAcross({
    basis: payBasisName(basis),
    bands: last.bands,
    roles: last.reqs,
    low_p50: fmtComp(last.low_p50),
    high_p50: fmtComp(last.high_p50),
    readings: points.length > 1 ? "several" : "single",
    start_low: fmtComp(first.low_p50),
    start_high: fmtComp(first.high_p50),
  });
}

export function buildBandTrendOption(
  dates: string[],
  series: DisclosureTrendSeries | undefined,
): EChartsCoreOption {
  const points = series?.points ?? [];
  const lows = points.map((p) => p.low_p50);
  const highs = points.map((p) => p.high_p50);

  return {
    aria: { enabled: false },
    grid: { ...compactGrid, left: 48, right: 16, top: 28, bottom: 22 },
    legend: {
      top: 0,
      right: 0,
      itemHeight: 8,
      itemWidth: 8,
      textStyle: { color: MUTED, fontSize: 10 },
      data: [insightsDisclosureMedianCeiling(), insightsDisclosureMedianFloor()],
    },
    tooltip: {
      trigger: "axis",
      valueFormatter: (v: number | null) => (v == null ? insightsDisclosureNoBandPosted() : fmtComp(v)),
    },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: dates,
      axisLine: { lineStyle: { color: BORDER } },
      axisTick: { show: false },
      axisLabel: { color: FAINT, fontSize: 9, hideOverlap: true },
    },
    yAxis: {
      ...valueAxis,
      scale: true,
      axisLabel: { color: FAINT, fontSize: 9, formatter: (v: number) => fmtComp(v) },
    },
    series: [
      {
        // Floor first, invisible, so the ceiling series can stack a shaded span on
        // top of it — the same offset trick the current-state bands chart uses to
        // draw a range without leaving the tree-shaken BarChart/LineChart runtime.
        name: "floor-offset",
        type: "line" as const,
        stack: "band",
        symbol: "none",
        lineStyle: { opacity: 0 },
        silent: true,
        tooltip: { show: false },
        data: lows,
      },
      {
        name: "span",
        type: "line" as const,
        stack: "band",
        symbol: "none",
        lineStyle: { opacity: 0 },
        areaStyle: { color: SIGNAL, opacity: 0.13 },
        silent: true,
        tooltip: { show: false },
        data: points.map((p) =>
          p.low_p50 === null || p.high_p50 === null ? null : p.high_p50 - p.low_p50,
        ),
      },
      {
        name: insightsDisclosureMedianCeiling(),
        type: "line" as const,
        smooth: true,
        showSymbol: dates.length === 1,
        symbolSize: 5,
        lineStyle: { width: 2, color: SIGNAL },
        itemStyle: { color: SIGNAL },
        data: highs,
      },
      {
        name: insightsDisclosureMedianFloor(),
        type: "line" as const,
        smooth: true,
        showSymbol: dates.length === 1,
        symbolSize: 5,
        lineStyle: { width: 2, color: DATA_2 },
        itemStyle: { color: DATA_2 },
        data: lows,
      },
    ],
  };
}
