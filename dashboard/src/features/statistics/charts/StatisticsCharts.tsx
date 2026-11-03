import type { EChartsCoreOption } from "echarts/core";
import type {
  ClusterSummary,
  CompTrajectoryCompany,
  OverviewSkill,
  SkillSeries,
  SkillsOverlap,
  TopSkill,
  VelocityCompany,
} from "../../../api";
import { companyName, fmtComp } from "../../../format";
import { EChart } from "../../../ui/EChart";
import {
  BORDER,
  DANGER,
  DATA_2,
  FAINT,
  MUTED,
  SIGNAL,
  SUNKEN,
  WARN,
  categoryAxis,
  compactGrid,
  valueAxis,
} from "./options";
import {
  insightsStatisticsChartsClosed,
  insightsStatisticsChartsClosedCount,
  insightsStatisticsChartsCrossCompanySkillOverlapHeatmap,
  insightsStatisticsChartsEquityShockwaveByCompany,
  insightsStatisticsChartsHiringFlowByCompany,
  insightsStatisticsChartsLessAlike,
  insightsStatisticsChartsLiftTheMarketSRate,
  insightsStatisticsChartsMarketDemandField,
  insightsStatisticsChartsMoreAlike,
  insightsStatisticsChartsMoreSignals,
  insightsStatisticsChartsNewClosedToday,
  insightsStatisticsChartsNewCount,
  insightsStatisticsChartsNoChange,
  insightsStatisticsChartsOfTheseRolesTheMarket,
  insightsStatisticsChartsOpenNewClosed,
  insightsStatisticsChartsOpenRolesByCompany,
  insightsStatisticsChartsOpened,
  insightsStatisticsChartsOpenedClosedUpdated,
  insightsStatisticsChartsPair,
  insightsStatisticsChartsRoleClusterLandscape,
  insightsStatisticsChartsRoles,
  insightsStatisticsChartsSetChanged,
  insightsStatisticsChartsShareOfTheseRoles,
  insightsStatisticsChartsSkillDemandTrends,
  insightsStatisticsChartsTheMarketSRate,
  insightsStatisticsChartsWhatSetsTheseRolesApart,
  insightsCommonDistinctSkills,
  insightsCommonOpenRoles,
  insightsCommonOpenRolesUnit,
  insightsCommonUpdated,
  insightsStatisticsChartsClusterRoles,
  insightsStatisticsChartsClusterSize,
  insightsStatisticsChartsCompanyOpenRoles,
  insightsStatisticsChartsEquityChange,
  insightsStatisticsChartsOverlapCell,
  insightsStatisticsChartsPairAlike,
  insightsStatisticsChartsPairSimilarity,
  insightsStatisticsChartsShareAgainstMarket,
  insightsStatisticsChartsSkillMentionsChange,
  insightsStatisticsChartsSkillMentionsShare,
  insightsStatisticsChartsSkillOpenRoles,
} from "../../../copy/gen/insights";
import { roleName, skillName } from "../../../copy/vocab";
import { clusterLabel } from "../names";
import { tooltipHtml, withParts } from "./tooltip";

const mono = "var(--app-font-mono)";

const direction = (amount: number) => (amount > 0 ? "up" : amount < 0 ? "down" : "flat");

export function OverviewSignalChart({ skills }: { skills: OverviewSkill[] }) {
  const ordered = skills.slice(0, 10).reverse();
  const values = ordered.map((s) => s.job_count);
  const option: EChartsCoreOption = {
    grid: { ...compactGrid, right: 48 },
    tooltip: {
      trigger: "item",
      formatter: (p: { dataIndex: number }) => {
        const skill = ordered[p.dataIndex];
        return tooltipHtml(skillName(skill.term), [
          insightsStatisticsChartsSkillOpenRoles({ job_count: skill.job_count, category: skill.category ?? "uncategorized" }),
        ]);
      },
    },
    xAxis: { ...valueAxis, name: insightsCommonOpenRolesUnit(), nameTextStyle: { color: FAINT, fontSize: 9 } },
    yAxis: { ...categoryAxis, data: ordered.map((s) => skillName(s.term)) },
    series: [
      {
        type: "bar",
        data: values,
        barMaxWidth: 2,
        silent: true,
        itemStyle: { color: DATA_2, opacity: 0.5 },
      },
      {
        type: "scatter",
        data: values,
        symbolSize: (value: number) => Math.max(8, Math.min(18, 7 + value * 0.32)),
        itemStyle: { color: SIGNAL, borderColor: "var(--app-surface-raised)", borderWidth: 2 },
        label: {
          show: true,
          position: "right",
          color: MUTED,
          fontFamily: mono,
          fontSize: 9,
          formatter: ({ value }: { value: number }) => String(value),
        },
      },
    ],
  };

  return (
    <EChart
      ariaLabel={insightsStatisticsChartsMarketDemandField()}
      className="chart-overview"
      height={292}
      option={option}
      summary={ordered.map((s) => `${skillName(s.term)}: ${s.job_count}`).join(", ")}
    />
  );
}

/** One bar of the Hiring company chart: a company, or the folded rest. */
export interface HiringBar {
  label: string;
  open: number;
  fresh: number;
  closed: number;
}

/** Open roles by company, leaders first. The caller bounds the rows
 *  (`hiring.topCompanies`): this draws what it is given, never a bar per company. */
export function HiringCompaniesChart({ bars }: { bars: readonly HiringBar[] }) {
  const rows = bars.slice().reverse();
  const option: EChartsCoreOption = {
    grid: { ...compactGrid, right: 118, top: 24 },
    tooltip: {
      trigger: "item",
      formatter: (p: { dataIndex: number }) => {
        const row = rows[p.dataIndex];
        return tooltipHtml(row.label, [
          insightsStatisticsChartsCompanyOpenRoles({ open: row.open }),
          withParts(insightsStatisticsChartsNewClosedToday, {
            new_roles: { text: insightsStatisticsChartsNewCount({ fresh: row.fresh }), tone: "new" },
            closed_roles: { text: insightsStatisticsChartsClosedCount({ closed: row.closed }), tone: "closed" },
          }),
        ]);
      },
    },
    xAxis: valueAxis,
    yAxis: { ...categoryAxis, data: rows.map((row) => row.label) },
    series: [
      {
        name: insightsCommonOpenRoles(),
        type: "bar",
        data: rows.map((row) => ({ value: row.open })),
        barMaxWidth: 13,
        itemStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 1,
            y2: 0,
            colorStops: [{ offset: 0, color: SIGNAL }, { offset: 1, color: DATA_2 }],
          },
          borderRadius: [0, 5, 5, 0],
        },
        label: {
          show: true,
          position: "right",
          distance: 8,
          fontFamily: mono,
          fontSize: 9,
          formatter: (p: { dataIndex: number }) => {
            const row = rows[p.dataIndex];
            return `{open|${row.open}}  {new|+${row.fresh}} {closed|−${row.closed}}`;
          },
          rich: {
            open: { color: MUTED, fontFamily: mono, fontWeight: 700 },
            new: { color: DATA_2, fontFamily: mono },
            closed: { color: DANGER, fontFamily: mono },
          },
        },
      },
    ],
  };
  return (
    <EChart
      ariaLabel={insightsStatisticsChartsOpenRolesByCompany()}
      className="chart-demand"
      height={Math.max(220, 54 + rows.length * 30)}
      option={option}
      summary={bars.map((b) => insightsStatisticsChartsOpenNewClosed({ label: String(b.label), open: b.open, fresh: b.fresh, closed: b.closed })).join("; ")}
    />
  );
}

export function VelocityFlowChart({ companies }: { companies: VelocityCompany[] }) {
  const rows = companies.slice().sort((a, b) => a.opened + a.closed - (b.opened + b.closed));
  const option: EChartsCoreOption = {
    grid: { ...compactGrid, right: 34, top: 34 },
    legend: {
      top: 0,
      right: 4,
      itemWidth: 9,
      itemHeight: 5,
      textStyle: { color: MUTED, fontSize: 9 },
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      valueFormatter: (value: number) => String(Math.abs(value)),
    },
    xAxis: {
      ...valueAxis,
      axisLabel: { color: FAINT, fontSize: 9, formatter: (v: number) => String(Math.abs(v)) },
    },
    yAxis: { ...categoryAxis, data: rows.map((c) => companyName(c.company)) },
    series: [
      {
        name: insightsStatisticsChartsClosed(),
        type: "bar",
        stack: "flow",
        data: rows.map((c) => -c.closed),
        barMaxWidth: 14,
        itemStyle: { color: DANGER, opacity: 0.74, borderRadius: [4, 0, 0, 4] },
      },
      {
        name: insightsStatisticsChartsOpened(),
        type: "bar",
        stack: "flow",
        data: rows.map((c) => c.opened),
        barMaxWidth: 14,
        itemStyle: { color: SIGNAL, borderRadius: [0, 4, 4, 0] },
      },
      {
        name: insightsCommonUpdated(),
        type: "scatter",
        data: rows.map((c) => c.updated),
        symbol: "diamond",
        symbolSize: 8,
        itemStyle: { color: DATA_2 },
      },
    ],
  };
  return (
    <EChart
      ariaLabel={insightsStatisticsChartsHiringFlowByCompany()}
      className="chart-velocity"
      height={Math.max(260, 64 + rows.length * 32)}
      option={option}
      summary={rows.map((c) => insightsStatisticsChartsOpenedClosedUpdated({ company: String(companyName(c.company)), opened: c.opened, closed: c.closed, updated: c.updated })).join("; ")}
    />
  );
}

export function TrajectoryShockChart({
  companies,
  priceChange,
}: {
  companies: CompTrajectoryCompany[];
  priceChange: number;
}) {
  const rows = companies
    .map((c) => ({ ...c, change: Math.round(c.equity * priceChange) }))
    .sort((a, b) => a.change - b.change);
  const zeroScenario = rows.every((row) => row.change === 0);
  const option: EChartsCoreOption = {
    grid: { ...compactGrid, right: zeroScenario ? 88 : 58, top: 22 },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      valueFormatter: (value: number | unknown[]) => {
        const amount = Number(Array.isArray(value) ? value[0] : value);
        return insightsStatisticsChartsEquityChange({ direction: direction(amount), amount: fmtComp(Math.abs(amount)) });
      },
    },
    xAxis: {
      ...valueAxis,
      min: zeroScenario ? -1 : undefined,
      max: zeroScenario ? 1 : undefined,
      interval: zeroScenario ? 1 : undefined,
      axisLabel: {
        color: FAINT,
        fontSize: 9,
        formatter: (v: number) => zeroScenario
          ? (v === 0 ? "$0" : "")
          : (v === 0 ? "$0" : `${v > 0 ? "+" : "−"}${fmtComp(Math.abs(v))}`),
      },
    },
    yAxis: { ...categoryAxis, data: rows.map((c) => companyName(c.company)) },
    series: [
      {
        type: "bar",
        data: rows.map((c) => ({
          value: c.change,
          itemStyle: {
            color: c.change > 0 ? SIGNAL : c.change < 0 ? DANGER : MUTED,
            opacity: c.change === 0 ? 0.28 : 0.86,
            borderRadius: c.change >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4],
          },
        })),
        barMaxWidth: 14,
        label: {
          show: !zeroScenario,
          position: "right",
          color: MUTED,
          fontFamily: mono,
          fontSize: 9,
          formatter: ({ value }: { value: number }) => value === 0 ? "—" : `${value > 0 ? "+" : "−"}${fmtComp(Math.abs(value))}`,
        },
        markLine: { silent: true, symbol: "none", lineStyle: { color: BORDER }, data: [{ xAxis: 0 }] },
      },
      ...(zeroScenario ? [{
        name: insightsStatisticsChartsNoChange(),
        type: "scatter" as const,
        data: rows.map((c) => [0, companyName(c.company)]),
        symbolSize: 9,
        itemStyle: { color: DATA_2, borderColor: "var(--app-surface-raised)", borderWidth: 2 },
        label: {
          show: true,
          position: "right" as const,
          color: MUTED,
          fontFamily: mono,
          fontSize: 9,
          formatter: insightsStatisticsChartsNoChange(),
        },
        tooltip: { show: false },
      }] : []),
    ],
  };
  return (
    <EChart
      ariaLabel={insightsStatisticsChartsEquityShockwaveByCompany()}
      className="chart-trajectory"
      height={Math.max(zeroScenario ? 220 : 250, 58 + rows.length * 34)}
      option={option}
      summary={rows.map((c) => `${companyName(c.company)}: ${c.change >= 0 ? "+" : "−"}${fmtComp(Math.abs(c.change))}`).join(", ")}
    />
  );
}

/** A narrowed slice's skills: how much of the slice names each (x) against how
 *  much more than the market it does (y, log; the line is the market's own
 *  rate). */
export function SkillsConstellationChart({ skills }: { skills: TopSkill[] }) {
  const rows = skills.filter((s) => s.lift != null && s.lift > 0).slice(0, 18);
  const option: EChartsCoreOption = {
    grid: { ...compactGrid, left: 48, right: 32, bottom: 42, top: 28 },
    tooltip: {
      formatter: (p: { dataIndex: number }) => {
        const skill = rows[p.dataIndex];
        return tooltipHtml(skillName(skill.term), [
          insightsStatisticsChartsShareAgainstMarket({ share: Math.round(skill.share * 100), market_share: Math.round(skill.market_share * 100) }),
          insightsStatisticsChartsLiftTheMarketSRate({ lift: String(skill.lift) }),
        ]);
      },
    },
    xAxis: {
      ...valueAxis,
      name: insightsStatisticsChartsShareOfTheseRoles(),
      nameLocation: "middle",
      nameGap: 28,
      nameTextStyle: { color: FAINT, fontSize: 9 },
      axisLabel: { color: FAINT, fontSize: 10, formatter: (v: number) => `${v}%` },
    },
    yAxis: {
      type: "log",
      logBase: 2,
      min: 0.25,
      name: insightsStatisticsChartsTheMarketSRate(),
      nameTextStyle: { color: FAINT, fontSize: 9 },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: FAINT, fontSize: 10, formatter: (v: number) => `×${v}` },
      splitLine: { lineStyle: { color: BORDER, type: "dashed" } },
    },
    series: [
      {
        type: "scatter",
        data: rows.map((s, index) => ({
          name: skillName(s.term),
          value: [Math.round(s.share * 1000) / 10, s.lift],
          label: { show: index < 5, position: index % 2 ? "bottom" : "top" },
        })),
        symbolSize: 14,
        itemStyle: { color: SIGNAL, opacity: 0.74, borderColor: DATA_2, borderWidth: 1.5 },
        label: { show: false, color: MUTED, fontSize: 10, distance: 7, formatter: "{b}" },
        labelLayout: { hideOverlap: true, moveOverlap: "shiftY" },
        markLine: {
          silent: true,
          symbol: "none",
          label: { show: false },
          lineStyle: { color: BORDER, type: "dashed", opacity: 0.85 },
          data: [{ yAxis: 1 }],
        },
        emphasis: {
          itemStyle: { opacity: 1, borderWidth: 2 },
          label: { show: true, color: "var(--app-text)", fontWeight: 700 },
          scale: 1.08,
        },
      },
    ],
  };
  return (
    <EChart
      ariaLabel={insightsStatisticsChartsWhatSetsTheseRolesApart()}
      className="chart-skills"
      height={350}
      option={option}
      summary={rows.map((s) => insightsStatisticsChartsOfTheseRolesTheMarket({ skill: skillName(s.term), share: Math.round(s.share * 100), lift: String(s.lift) })).join(", ")}
    />
  );
}

/** Each skill's share of the day's skill mentions, with the days the
 *  measured set changed marked: a raw count steps up whenever companies join
 *  the set, and would read as demand. */
export function SkillTrendChart({
  dates,
  series,
  setChanges = [],
}: {
  dates: string[];
  series: SkillSeries[];
  setChanges?: readonly string[];
}) {
  const visibleSeries = series.slice(0, 6);
  const colors = [SIGNAL, DATA_2, WARN, DANGER, MUTED, "color-mix(in srgb, var(--app-data-2) 58%, var(--app-text-muted))"];
  const option: EChartsCoreOption = {
    color: colors,
    grid: { left: 40, right: 18, top: 48, bottom: dates.length > 18 ? 52 : 30 },
    legend: {
      type: "scroll",
      top: 0,
      left: 0,
      right: 0,
      itemWidth: 10,
      itemHeight: 5,
      textStyle: { color: MUTED, fontSize: 9 },
    },
    tooltip: { trigger: "axis", axisPointer: { type: "line" } },
    dataZoom: dates.length > 18 ? [{ type: "inside" }, { type: "slider", height: 14, bottom: 2, borderColor: BORDER, fillerColor: "rgba(111,201,230,.12)" }] : [],
    xAxis: {
      ...categoryAxis,
      boundaryGap: false,
      data: dates,
      axisLabel: { color: FAINT, fontSize: 9, hideOverlap: true },
    },
    yAxis: { ...valueAxis, minInterval: 0, axisLabel: { color: FAINT, fontSize: 10, formatter: (v: number) => `${v}%` } },
    series: visibleSeries.map((s, index) => ({
      name: skillName(s.term),
      type: "line",
      data: s.points.map((p, pointIndex) => {
        const value = Math.round(p.share * 1000) / 10;
        return pointIndex === s.points.length - 1 ? { value, symbol: "circle", symbolSize: 6 } : value;
      }),
      markLine: index === 0 && setChanges.length
        ? {
            silent: true,
            symbol: "none",
            lineStyle: { color: WARN, type: "dashed", opacity: 0.7 },
            label: { show: true, formatter: insightsStatisticsChartsSetChanged(), color: FAINT, fontSize: 9, position: "insideEndTop" },
            data: setChanges.filter((d) => dates.includes(d)).map((d) => ({ xAxis: d })),
          }
        : undefined,
      smooth: 0.28,
      showSymbol: dates.length <= 6,
      symbolSize: 5,
      lineStyle: { width: index < 3 ? 2.2 : 1.5, opacity: index < 5 ? 1 : 0.72 },
      areaStyle: index === 0 ? { color: SIGNAL, opacity: 0.07 } : undefined,
      emphasis: { focus: "series" },
    })),
  };
  return (
    <EChart
      ariaLabel={insightsStatisticsChartsSkillDemandTrends()}
      className="chart-trends"
      height={390}
      option={option}
      // A change is said only across a window that measured one set
      // throughout (`TrendsPanel`).
      summary={series
        .map((s) => setChanges.length
          ? insightsStatisticsChartsSkillMentionsShare({ skill: skillName(s.term), share: Math.round(s.current_share * 100) })
          : insightsStatisticsChartsSkillMentionsChange({
              direction: s.share_delta >= 0 ? "up" : "down",
              skill: skillName(s.term),
              share: Math.round(s.current_share * 100),
              points: (s.share_delta * 100).toFixed(1),
            }))
        .join("; ")}
    />
  );
}

export function OverlapHeatmapChart({ data }: { data: SkillsOverlap }) {
  const names = data.companies.map((c) => companyName(c.company));
  const bySlug = new Map(data.companies.map((c, index) => [c.company, index]));
  const pairCells = data.pairs.flatMap((pair) => {
    const a = bySlug.get(pair.a);
    const b = bySlug.get(pair.b);
    if (a == null || b == null) return [];
    const value = Math.round(pair.similarity * 100);
    return [
      { value: [a, b, value], shared: pair.shared, terms: pair.top_shared.map(skillName) },
      { value: [b, a, value], shared: pair.shared, terms: pair.top_shared.map(skillName) },
    ];
  });
  const diagonalCells = data.companies.map((company, index) => ({
    value: [index, index, 0],
    diagonal: true,
    skillCount: company.skill_count,
    shared: company.skill_count,
    terms: [] as string[],
    itemStyle: { color: SUNKEN },
  }));
  const cells = [...pairCells, ...diagonalCells];
  const option: EChartsCoreOption = {
    grid: { left: 92, right: 24, top: 18, bottom: 52 },
    tooltip: {
      formatter: (p: { value: [number, number, number]; data: { diagonal?: boolean; skillCount?: number; shared: number; terms: string[] } }) =>
        p.data.diagonal
          ? tooltipHtml(names[p.value[0]], [
              insightsCommonDistinctSkills({ count: p.data.skillCount ?? 0 }),
            ])
          : tooltipHtml(insightsStatisticsChartsPair({ a: names[p.value[0]], b: names[p.value[1]] }), [
              insightsStatisticsChartsPairAlike({ similarity: p.value[2], shared: p.data.shared }),
              p.data.terms.join(", "),
            ]),
    },
    xAxis: {
      ...categoryAxis,
      data: names,
      splitArea: { show: true },
      axisLabel: { color: MUTED, fontSize: 9, interval: 0, rotate: names.length > 4 ? 28 : 0 },
    },
    // The route orders companies so similar ones sit together; the y axis reads
    // top-down in that order, so the diagonal runs top-left to bottom-right.
    yAxis: { ...categoryAxis, data: names, inverse: true, splitArea: { show: true } },
    visualMap: {
      min: 0,
      max: 100,
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemWidth: 7,
      itemHeight: 110,
      text: [insightsStatisticsChartsMoreAlike(), insightsStatisticsChartsLessAlike()],
      textStyle: { color: FAINT, fontSize: 9 },
      inRange: { color: [SUNKEN, DATA_2, SIGNAL] },
    },
    series: [
      {
        type: "heatmap",
        data: cells,
        label: {
          show: true,
          color: "var(--app-text)",
          fontFamily: mono,
          fontSize: 9,
          formatter: (p: { value: [number, number, number]; data: { diagonal?: boolean; skillCount?: number } }) =>
            insightsStatisticsChartsOverlapCell({
              cell: p.data.diagonal ? "self" : p.value[2] ? "pair" : "empty",
              skillCount: p.data.skillCount ?? 0,
              similarity: p.value[2],
            }),
        },
        itemStyle: { borderColor: "var(--app-surface-raised)", borderWidth: 1, borderRadius: 3 },
        emphasis: { itemStyle: { borderColor: "var(--app-text)", borderWidth: 1 } },
      },
    ],
  };
  return (
    <EChart
      ariaLabel={insightsStatisticsChartsCrossCompanySkillOverlapHeatmap()}
      className="chart-overlap"
      height={Math.max(340, 160 + names.length * 30)}
      option={option}
      summary={data.pairs.map((p) => insightsStatisticsChartsPairSimilarity({ a: companyName(p.a), b: companyName(p.b), percent: Math.round(p.similarity * 100) })).join("; ")}
    />
  );
}

export function ClusterLandscapeChart({
  clusters,
  onSelect,
  selectedId,
}: {
  clusters: ClusterSummary[];
  onSelect: (id: number) => void;
  selectedId?: number | null;
}) {
  const palette = [
    "color-mix(in srgb, var(--app-data-1) 52%, var(--app-surface-sunken))",
    "color-mix(in srgb, var(--app-data-2) 46%, var(--app-surface-sunken))",
    "color-mix(in srgb, var(--app-data-1) 32%, var(--app-surface-sunken))",
    "color-mix(in srgb, var(--app-data-2) 28%, var(--app-surface-sunken))",
  ];
  const option: EChartsCoreOption = {
    tooltip: {
      formatter: (p: { data: { name: string; value: number; family: string; terms: string } }) =>
        tooltipHtml(p.data.name, [insightsStatisticsChartsClusterRoles({ size: p.data.value, family: p.data.family }), p.data.terms]),
    },
    series: [
      {
        type: "treemap",
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        squareRatio: 1.25,
        visibleMin: 2,
        upperLabel: { show: false },
        label: {
          show: true,
          color: "var(--app-text)",
          fontSize: 11,
          fontWeight: 650,
          lineHeight: 16,
          formatter: (params: { name: string; value: number }) => {
            const terms = params.name.split(" · ");
            const more = terms.length > 2 ? `\n${insightsStatisticsChartsMoreSignals({ count: terms.length - 2 })}` : "";
            return `${terms.slice(0, 2).join("\n")}${more}\n${insightsStatisticsChartsClusterSize({ size: params.value })}`;
          },
          overflow: "truncate",
        },
        itemStyle: { borderColor: "var(--app-surface-raised)", borderWidth: 3, gapWidth: 2 },
        data: clusters.map((c, index) => {
          const itemColor = c.id === selectedId
            ? "color-mix(in srgb, var(--app-action) 54%, var(--app-surface-sunken))"
            : palette[index % palette.length];
          return {
            id: c.id,
            name: clusterLabel(c),
            value: c.size,
            family: roleName(c.family_hint),
            terms: c.top_terms.slice(0, 4).map((t) => skillName(t.term)).join(", "),
            itemStyle: { color: itemColor },
            emphasis: {
              itemStyle: { color: itemColor, borderColor: "var(--app-action)", borderWidth: 2 },
            },
          };
        }),
      },
    ],
  };
  return (
    <EChart
      ariaLabel={insightsStatisticsChartsRoleClusterLandscape()}
      className="chart-clusters"
      height={390}
      onEvents={{
        click: (params) => {
          const id = (params as { data?: { id?: number } }).data?.id;
          if (id != null) onSelect(id);
        },
      }}
      option={option}
      summary={clusters.map((c) => insightsStatisticsChartsRoles({ label: String(clusterLabel(c)), size: c.size })).join(", ")}
    />
  );
}
