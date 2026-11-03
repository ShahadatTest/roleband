import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { useState } from "react";
import { InsightsScope, TopSkill, TopSkills, api } from "../../api";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { companyName } from "../../format";
import { SkillsConstellationChart } from "./charts/StatisticsCharts";
import { InfoTip } from "../../ui/InfoTip";
import { FilterSelect, type FilterSelectOption } from "../../ui";
import { skillCategory } from "../../copy/skills";
import { InsightHero, n } from "./InsightHero";
import {
  insightsSkillsViewANarrowedViewRanksSkills,
  insightsSkillsViewAboveTheLineNamedMore,
  insightsSkillsViewAgainstTheMarket,
  insightsSkillsViewAnyCompany,
  insightsSkillsViewCategory,
  insightsSkillsViewExpected,
  insightsSkillsViewExpectedOfTheRole,
  insightsSkillsViewHowSkillsAreRanked,
  insightsSkillsViewLeadSkill,
  insightsSkillsViewLift,
  insightsSkillsViewLoadFailed,
  insightsSkillsViewLoading,
  insightsSkillsViewNamingASkill,
  insightsSkillsViewNoSkillsExtractedForThis,
  insightsSkillsViewOfEveryRole,
  insightsSkillsViewOfRolesNameIt,
  insightsSkillsViewPickACompanyADiscipline,
  insightsSkillsViewProcessLeadershipAndCollaborationAsks,
  insightsSkillsViewRankedHere,
  insightsSkillsViewRoles,
  insightsSkillsViewShareOrLift,
  insightsSkillsViewShareOfRoles,
  insightsSkillsViewSkill,
  insightsSkillsViewSkillsOrder,
  insightsSkillsViewWhatExpectedOfTheRole,
  insightsSkillsViewWhatSetsTheseRolesApart,
  insightsCommonMarket,
  insightsCommonSkills,
} from "../../copy/gen/insights";
import { skillName } from "../../copy/vocab";

/* The Skills tab: a slice's skills by how characteristic they are of it
 * against the market (`skills.analytics.rank_skills`), the competencies a role
 * is expected to have listed apart, and one company picker beside the scope
 * bar, offering the scope's side (`companyPicker.ts`). Ranking by how many
 * roles name a concept would lead every slice with the same competencies. The
 * whole market, which nothing distinguishes, ranks by share. */

const pct = (x: number) => `${Math.round(x * 100)}%`;
const lift = (x: number | null) => (x == null ? "" : `×${x >= 10 ? Math.round(x) : x.toFixed(1)}`);

export function SkillsView({ scope, companies = [] }: { scope?: InsightsScope; companies?: FilterSelectOption[] } = {}) {
  const [company, setCompany] = useState<string | null>(null);

  /* The ordering failure `useAsyncResource` exists to prevent: with a bare
     `.then(setSkills)` keyed on two filters, no cancellation and no
     generation, pick a slow company, then a fast one, and the slow response
     lands last and paints ITS skills under the new heading, silently, because
     both responses are valid. The hook's generation ref makes
     the newest start win, and its request key stops the previous query's rows
     being shown under the new one for a frame. */
  const skillsResource = useAsyncResource<TopSkills>(
    (signal) => api.skillsTop({ company: company ? [company] : undefined, limit: 30 }, signal, scope),
    [company, scope],
    { keep: "stats/skills" },
  );
  const data = skillsResource.data;

  const skills = data?.items ?? [];
  const lead = skills[0];
  const shareMax = Math.max(0.01, ...skills.map((s) => s.share));
  const view = data?.narrowed ? "narrowed" : "market";

  return (
    <div className="stats-view">
      {data && lead && (
        <InsightHero
          tab="skills"
          figure={insightsSkillsViewLeadSkill({ view, skill: skillName(lead.term) })}
          line={
            <>
              {insightsSkillsViewOfRolesNameIt({ view, share: pct(lead.share), market_share: pct(lead.market_share) })}
              {company ? ` · ${companyName(company)}` : ""}
              <InfoTip label={insightsSkillsViewHowSkillsAreRanked()}>
                {insightsSkillsViewANarrowedViewRanksSkills()}
              </InfoTip>
            </>
          }
          kpis={[
            { label: insightsSkillsViewRoles(), value: n(data.roles), sub: insightsSkillsViewNamingASkill() },
            { label: insightsSkillsViewShareOrLift({ view }), value: data.narrowed ? lift(lead.lift) : pct(lead.share), sub: skillName(lead.term) },
            { label: insightsCommonSkills(), value: n(skills.length), sub: insightsSkillsViewRankedHere() },
            { label: insightsSkillsViewExpected(), value: n(data.competencies.length), sub: insightsSkillsViewOfEveryRole() },
          ]}
        />
      )}

      <div className="skills-pick">
        <FilterSelect
          label={company ? companyName(company) : insightsSkillsViewAnyCompany()}
          options={companies}
          selected={company ? [company] : []}
          onChange={(next) => setCompany(next[0] ?? null)}
          multiple={false}
          searchable
        />
      </div>

      {!data ? (
        <ResourceLoadState error={skillsResource.error} loading={insightsSkillsViewLoading()} failed={insightsSkillsViewLoadFailed()} onRetry={skillsResource.retry} />
      ) : skills.length === 0 && data.competencies.length === 0 ? (
        <div className="panel" style={{ color: "var(--app-text-faint)" }}>
          {insightsSkillsViewNoSkillsExtractedForThis()}
        </div>
      ) : (
        <>
          {data.competencies.length > 0 && (
            <div className="panel skills-expected">
              <h3>
                {insightsSkillsViewExpectedOfTheRole()}
                <InfoTip label={insightsSkillsViewWhatExpectedOfTheRole()}>
                  {insightsSkillsViewProcessLeadershipAndCollaborationAsks()}
                </InfoTip>
              </h3>
              <p className="skills-expected-list">
                {data.competencies.slice(0, 6).map((c, i) => (
                  <span key={c.term}>
                    {i > 0 ? " · " : ""}
                    {skillName(c.term)} <span className="skills-expected-share">{pct(c.share)}</span>
                  </span>
                ))}
              </p>
            </div>
          )}

          {data.narrowed ? (
            <div className="panel chart-panel chart-panel-wide">
              <div className="chart-panel-head">
                <div>
                  <span className="eyebrow">{insightsSkillsViewAgainstTheMarket()}</span>
                  <h3>{insightsSkillsViewWhatSetsTheseRolesApart()}</h3>
                </div>
                <span className="chart-insight">{insightsSkillsViewAboveTheLineNamedMore()}</span>
              </div>
              <SkillsConstellationChart skills={skills} />
            </div>
          ) : (
            <p className="hiring-note">
              {insightsSkillsViewPickACompanyADiscipline()}
            </p>
          )}

          <div className="panel skills-ranked">
            <h3>{insightsSkillsViewSkillsOrder({ view })}</h3>
            <table className="data-table">
              <thead>
                <tr>
                  <th>{insightsSkillsViewSkill()}</th>
                  <th>{insightsSkillsViewCategory()}</th>
                  <th className="num">{insightsSkillsViewShareOfRoles()}</th>
                  {data.narrowed && <th className="num">{insightsCommonMarket()}</th>}
                  {data.narrowed && <th className="num">{insightsSkillsViewLift()}</th>}
                </tr>
              </thead>
              <tbody>
                {skills.map((s: TopSkill) => (
                  <tr key={s.term}>
                    <td>{skillName(s.term)}</td>
                    <td className="dim">{skillCategory(s.category)}</td>
                    <td className="num">
                      <span className="vel-open">
                        <span className="bar-track">
                          <span className="bar-fill" style={{ width: `${(s.share / shareMax) * 100}%` }} />
                        </span>
                        <span>{pct(s.share)}</span>
                      </span>
                    </td>
                    {data.narrowed && <td className="num dim">{pct(s.market_share)}</td>}
                    {data.narrowed && <td className="num">{lift(s.lift)}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
