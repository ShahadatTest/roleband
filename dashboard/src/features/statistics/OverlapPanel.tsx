import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { InsightsScope, OverlapPair, SkillsOverlap, api } from "../../api";
import { useState } from "react";
import { FilterSelect, type FilterSelectOption } from "../../ui";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { companyName } from "../../format";
import { OverlapHeatmapChart } from "./charts/StatisticsCharts";
import { InfoTip } from "../../ui/InfoTip";
import { InsightHero, n } from "./InsightHero";
import {
  insightsOverlapPanelAlike,
  insightsOverlapPanelCellsShowHowAlikeTwo,
  insightsOverlapPanelClosestPair,
  insightsOverlapPanelCompaniesCompared,
  insightsOverlapPanelCompared,
  insightsOverlapPanelComparison,
  insightsOverlapPanelCrossCompanySkillOverlapMatrix,
  insightsOverlapPanelEachCompanyIsItsOpen,
  insightsOverlapPanelExactMatrix,
  insightsOverlapPanelFurthestPair,
  insightsOverlapPanelHowAlikeTheirRolesAre,
  insightsOverlapPanelHowSkillOverlapIsCalculated,
  insightsOverlapPanelLoadFailed,
  insightsOverlapPanelLoading,
  insightsOverlapPanelMedianPair,
  insightsOverlapPanelCompaniesPicked,
  insightsOverlapPanelNoSharedSkills,
  insightsOverlapPanelNoSharedSkillsYet,
  insightsOverlapPanelNotEnoughCompaniesWithSkills,
  insightsOverlapPanelSharedVocabulary,
  insightsOverlapPanelSkills,
  insightsOverlapPanelSkillsOpen,
  insightsCommonCompanies,
  insightsCommonDistinctSkills,
  insightsOverlapPanelMostAlikeOf,
  insightsOverlapPanelPairAlike,
  insightsOverlapPanelPairNames,
} from "../../copy/gen/insights";
import { Msg } from "../../ui/Msg";
import { skillName } from "../../copy/vocab";

// Intensity ramp for the exact-value ledger; chart owns its own matching ramp.
function cellBg(similarity: number): string {
  const pct = Math.round(Math.min(1, similarity) * 82) + 4;
  return /* not copy: CSS */ `color-mix(in srgb, var(--app-data-2) ${pct}%, var(--app-surface-sunken))`;
}

/** The most companies one matrix compares (the route's own ceiling is 50). */
const MAX_COMPANIES = 12;

export function OverlapPanel({ scope, companies = [] }: { scope?: InsightsScope; companies?: FilterSelectOption[] } = {}) {
  // Which companies to compare: the reader's choice among the scope's side
  // (`companyPicker.ts`), else the ten with the most open roles in the scope.
  // The choice exists because volume alone can set unrelated firms beside the
  // companies the reader follows.
  const [chosen, setChosen] = useState<string[]>([]);
  const chosenKey = chosen.join(",");
  const { data, error, retry } = useAsyncResource<SkillsOverlap>(
    (signal) => api.skillsOverlap(2, chosen.length ? MAX_COMPANIES : 10, signal, scope, chosen),
    [scope, chosenKey],
    { keep: "stats/overlap" },
  );
  const picker = (
    <div className="skills-pick">
      <FilterSelect
        label={insightsOverlapPanelCompaniesPicked({ picker: chosen.length ? "chosen" : "default", picked: chosen.length })}
        options={companies}
        selected={chosen}
        onChange={(next) => setChosen(next.slice(0, MAX_COMPANIES))}
        searchable
      />
    </div>
  );

  if (!data) return <ResourceLoadState error={error} loading={insightsOverlapPanelLoading()} failed={insightsOverlapPanelLoadFailed()} onRetry={retry} />;

  const cos = data.companies;
  if (cos.length < 2) {
    return (
      <>
        {picker}
        <div className="panel">
          <h3>{insightsOverlapPanelHowAlikeTheirRolesAre()}</h3>
          <div className="empty-hint">{insightsOverlapPanelNotEnoughCompaniesWithSkills()}</div>
        </div>
      </>
    );
  }

  // Lookup both orderings so cell (row, col) resolves regardless of pair direction.
  const pairMap = new Map<string, OverlapPair>();
  for (const p of data.pairs) {
    pairMap.set(`${p.a}|${p.b}`, p);
    pairMap.set(`${p.b}|${p.a}`, p);
  }

  const closest = data.pairs.reduce<OverlapPair | null>((best, p) => (!best || p.similarity > best.similarity ? p : best), null);
  const sorted = data.pairs.map((p) => p.similarity).sort((a, b) => a - b);
  const median = sorted.length ? sorted[Math.floor((sorted.length - 1) / 2)] : 0;
  const pct = (x: number) => `${Math.round(x * 100)}%`;
  return (
    <>
      <InsightHero
        tab="overlap"
        figure={closest ? insightsOverlapPanelPairNames({ a: companyName(closest.a), b: companyName(closest.b) }) : insightsOverlapPanelNoSharedSkillsYet()}
        line={
          closest
            ? insightsOverlapPanelMostAlikeOf({ companies: n(cos.length), similarity: pct(closest.similarity) })
            : insightsOverlapPanelCompaniesCompared({ companies: n(cos.length) })
        }
        kpis={[
          { label: insightsCommonCompanies(), value: n(cos.length), sub: insightsOverlapPanelCompared() },
          { label: insightsOverlapPanelClosestPair(), value: closest ? pct(closest.similarity) : "0%", sub: insightsOverlapPanelAlike() },
          { label: insightsOverlapPanelMedianPair(), value: pct(median), sub: insightsOverlapPanelAlike() },
          { label: insightsOverlapPanelFurthestPair(), value: pct(sorted[0] ?? 0), sub: insightsOverlapPanelAlike() },
        ]}
      />
      {picker}
    <div className="panel overlap-panel">
      <div className="overlap-head chart-panel-head">
        <div>
          <span className="eyebrow">{insightsOverlapPanelSharedVocabulary()}</span>
          <h3>
            {insightsOverlapPanelHowAlikeTheirRolesAre()}
            <InfoTip label={insightsOverlapPanelHowSkillOverlapIsCalculated()}>
              <Msg of={insightsOverlapPanelEachCompanyIsItsOpen} elems={{ min_jobs: data.min_jobs }} />
            </InfoTip>
          </h3>
        </div>
        <span className="chart-insight"><Msg of={insightsOverlapPanelComparison} elems={{ companies: cos.length }} /></span>
      </div>

      <OverlapHeatmapChart data={data} />

      <details className="chart-ledger">
        <summary>{insightsOverlapPanelExactMatrix()}</summary>
        <div className="overlap-scroll">
          <div
            className="overlap-matrix"
            style={{ gridTemplateColumns: `minmax(96px, max-content) repeat(${cos.length}, 44px)` }}
            role="table"
            aria-label={insightsOverlapPanelCrossCompanySkillOverlapMatrix()}
          >
          <div className="ovl-corner" role="columnheader" />
          {cos.map((c) => (
            <div className="ovl-colhead" role="columnheader" key={c.company}>
              <span title={insightsOverlapPanelSkillsOpen({ company: String(companyName(c.company)), skill_count: c.skill_count, open: c.open })}>
                {companyName(c.company)}
              </span>
            </div>
          ))}

          {cos.map((row) => (
            <div className="ovl-row" role="row" key={row.company} style={{ display: "contents" }}>
              <div className="ovl-rowhead" role="rowheader" title={insightsCommonDistinctSkills({ count: row.skill_count })}>
                {companyName(row.company)}
              </div>
              {cos.map((col) => {
                if (row.company === col.company) {
                  return (
                    <div className="ovl-cell diag" role="cell" key={col.company} title={insightsOverlapPanelSkills({ skill_count: row.skill_count })}>
                      {row.skill_count}
                    </div>
                  );
                }
                const p = pairMap.get(`${row.company}|${col.company}`);
                const j = p ? p.similarity : 0;
                const a = companyName(row.company);
                const b = companyName(col.company);
                const title = p
                  ? insightsOverlapPanelPairAlike({
                      a,
                      b,
                      percent: Math.round(p.similarity * 100),
                      shared: p.shared,
                      union: p.union,
                      listed: p.top_shared.length ? "some" : "none",
                      skills: p.top_shared.map(skillName).join(", "),
                    })
                  : insightsOverlapPanelNoSharedSkills({ a, b });
                return (
                  <div
                    className="ovl-cell"
                    role="cell"
                    key={col.company}
                    style={{ background: cellBg(j) }}
                    title={title}
                  >
                    {j > 0 ? Math.round(j * 100) : ""}
                  </div>
                );
              })}
            </div>
          ))}
          </div>
        </div>
        <div className="overlap-foot">
          {insightsOverlapPanelCellsShowHowAlikeTwo()}
        </div>
      </details>
    </div>
    </>
  );
}
