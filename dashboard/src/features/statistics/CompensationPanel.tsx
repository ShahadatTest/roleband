import { CompensationStats, CompSummary, InsightsScope, api } from "../../api";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { useSourceSwitch } from "../../context/SyncState";
import { fmtComp, companyName, BAND_LABEL } from "../../format";
import { CompTrendChart } from "./CompTrendChart";
import { DisclosurePanel } from "./DisclosurePanel";
import { PayBands } from "./PayBands";
import { exclusionNote } from "./charts/compBands";
import { InfoTip } from "../../ui/InfoTip";
import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { InsightHero, n } from "./InsightHero";
import {
  insightsCompensationPanelAboutPublishedSalaryBands,
  insightsCompensationPanelBandsFromEmployers,
  insightsCompensationPanelBaseOnly,
  insightsCompensationPanelBaseOnlyLead,
  insightsCompensationPanelBaseSalaryQuotedFromThe,
  insightsCompensationPanelCompensation,
  insightsCompensationPanelCoverage,
  insightsCompensationPanelEstimatedBaseByLevel,
  insightsCompensationPanelEstimatedCompDistribution,
  insightsCompensationPanelEstimatedTotalCompensationIsImputed,
  insightsCompensationPanelGroupsOfRolesOrMore,
  insightsCompensationPanelHowASkillSPay,
  insightsCompensationPanelHowCompensationIsEstimated,
  insightsCompensationPanelLoadFailed,
  insightsCompensationPanelLoading,
  insightsCompensationPanelMedian,
  insightsCompensationPanelMedianPay,
  insightsCompensationPanelMedianCompByLevel,
  insightsCompensationPanelMedianPayByDiscipline,
  insightsCompensationPanelMiddle50,
  insightsCompensationPanelMinMax,
  insightsCompensationPanelNoOpenRolesWithA,
  insightsCompensationPanelNotEnoughPricedRolesPer,
  insightsCompensationPanelOpenRolesNowCoverage,
  insightsCompensationPanelPublishedBands,
  insightsCompensationPanelRange,
  insightsCompensationPanelRoles,
  insightsCompensationPanelPricedRoles,
  insightsCompensationPanelRolesNamingTheSkillAgainst,
  insightsCompensationPanelSpread,
  insightsCompensationPanelTopDecile,
  insightsCompensationPanelTopPayingCompanies,
  insightsCompensationPanelWhatASkillAddsAt,
  insightsCompensationPanelWhatEmployersActuallyPrint,
} from "../../copy/gen/insights";
import { Msg } from "../../ui/Msg";
import { roleName, skillName } from "../../copy/vocab";

// One ranked "name | median-bar | value | roles" row, scaled against the group
// max. Every row says how many roles it rests on.
function CompBar({
  label,
  s,
  max,
  title,
}: {
  label: string;
  s: CompSummary;
  max: number;
  title?: string;
}) {
  const median = s.p50 ?? 0;
  return (
    <div className="bar-row comp-row" title={title}>
      <span>{label}</span>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${(median / max) * 100}%` }} />
      </div>
      <span className="val">{fmtComp(median)}</span>
      <span className="comp-n">{roles(s.count)}</span>
    </div>
  );
}

const roles = (count: number) => insightsCompensationPanelRoles({ count });
const iqr = (s: CompSummary) =>
  insightsCompensationPanelSpread({ low: String(fmtComp(s.p25)), high: String(fmtComp(s.p75)), roles: roles(s.count) });
const signed = (x: number) => (x === 0 ? "$0" : `${x > 0 ? "+" : "−"}${fmtComp(Math.abs(x))}`);
// The two lists in a pair show the same number of rows.
const PAIR_ROWS = 8;

/* Roles whose pay estimate is a base alone. No total exists for them, so they
   have their own panel and their own axis: a base drawn beside totals reads as
   a lower-paying role. The payload may omit the block, so it is read
   optionally. */
function BaseEstimatesPanel({ base }: { base: CompensationStats["base_estimates"] | undefined }) {
  if (!base?.overall) return null;
  const max = Math.max(1, ...base.by_level.map((l) => l.p50 ?? 0));
  const heading = insightsCompensationPanelEstimatedBaseByLevel();
  return (
    <section className="panel" aria-label={heading}>
      <span className="eyebrow">{insightsCompensationPanelBaseOnly()}</span>
      <h3>{heading}</h3>
      <p className="hiring-note">{insightsCompensationPanelBaseOnlyLead({ count: base.coverage.with_base })}</p>
      {base.by_level.map((l) => (
        <CompBar key={l.level_band} label={BAND_LABEL[l.level_band] ?? l.level_band} s={l} max={max} title={iqr(l)} />
      ))}
      <p className="hiring-note">{insightsCompensationPanelGroupsOfRolesOrMore({ min_roles: base.min_roles })}</p>
    </section>
  );
}

export function CompensationPanel({
  days,
  scope,
  advanced = false,
}: {
  days: number;
  scope?: InsightsScope;
  /** The basic view keeps the median and its middle half, and pay by level,
   *  company and discipline; the advanced view adds every other panel. */
  advanced?: boolean;
}) {
  // The roles open now: the window moves the trend charts, never this
  // population.
  const { data, error, retry, refresh } = useAsyncResource<CompensationStats>(
    () => api.compensation(scope), [scope], { keep: "stats/compensation" });
  // Pay statistics follow the source answering pay.
  useSourceSwitch(refresh);

  if (!data) return <ResourceLoadState error={error} loading={insightsCompensationPanelLoading()} failed={insightsCompensationPanelLoadFailed()} onRetry={retry} />;
  if (!data.overall) {
    return (
      <>
        {advanced && <CompTrendChart days={days} scope={scope} />}
        <div className="panel">
          <h3>{insightsCompensationPanelCompensation()}</h3>
          <div className="empty-hint">{insightsCompensationPanelNoOpenRolesWithA()}</div>
        </div>
        {/* Disclosure is read off the postings, not the estimate: a missing
            comp_median must not hide what employers actually published. */}
        {advanced && <DisclosurePanel rates={data.disclosure} days={days} scope={scope} minRoles={data.min_roles} />}
        {/* With no total to show, the base estimates are the only pay figures,
            so both views keep them. */}
        <BaseEstimatesPanel base={data.base_estimates} />
      </>
    );
  }

  const o = data.overall;
  const cov = data.coverage;
  const pct = Math.round(cov.pct * 100);
  const histMax = Math.max(1, ...data.histogram.map((b) => b.count));
  const levelMax = Math.max(1, ...data.by_level.map((l) => l.p50 ?? 0));
  const companies = data.by_company.slice(0, PAIR_ROWS);
  const families = data.by_family.slice(0, PAIR_ROWS);
  const companyMax = Math.max(1, ...companies.map((c) => c.p50 ?? 0));
  const familyMax = Math.max(1, ...families.map((f) => f.p50 ?? 0));
  const premiumMax = Math.max(1, ...data.by_skill.map((s) => Math.abs(s.premium)));
  const atLeast = insightsCompensationPanelGroupsOfRolesOrMore({ min_roles: data.min_roles });
  const disclosedExplanation = [
    insightsCompensationPanelBaseSalaryQuotedFromThe(),
    exclusionNote(data.disclosed.excluded),
  ].filter(Boolean).join(" ");
  const distribution = (
    <div className="panel">
      <h3>{insightsCompensationPanelEstimatedCompDistribution()}</h3>
      {data.histogram.map((b) => (
        <div className="bar-row comp-hist-row" key={b.lo}>
          <span>{fmtComp(b.lo)}–{fmtComp(b.hi)}</span>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${(b.count / histMax) * 100}%` }} />
          </div>
          <span className="val">{b.count}</span>
        </div>
      ))}
    </div>
  );
  const byLevel = (
    <div className="panel">
      <h3>{insightsCompensationPanelMedianCompByLevel()}</h3>
      {data.by_level.map((l) => (
        <CompBar
          key={l.level_band}
          label={BAND_LABEL[l.level_band] ?? l.level_band}
          s={l}
          max={levelMax}
          title={iqr(l)}
        />
      ))}
      <p className="hiring-note">{atLeast}</p>
    </div>
  );

  return (
    <>
      {/* The answer first, as on every tab; the trend under it. */}
      <InsightHero
        tab="compensation"
        figure={insightsCompensationPanelMedianPay({ p50: fmtComp(o.p50) })}
        line={
          <>
            <Msg of={insightsCompensationPanelOpenRolesNowCoverage} elems={{ with_comp: n(cov.with_comp), total_open: n(cov.total_open), pct: pct }} />
            <InfoTip label={insightsCompensationPanelHowCompensationIsEstimated()}>
              {insightsCompensationPanelEstimatedTotalCompensationIsImputed()}
            </InfoTip>
          </>
        }
        kpis={[
          { label: insightsCompensationPanelCoverage(), value: `${pct}%`, sub: insightsCompensationPanelPricedRoles({ with_comp: n(cov.with_comp) }) },
          { label: insightsCompensationPanelMiddle50(), value: `${fmtComp(o.p25)}–${fmtComp(o.p75)}`, sub: "p25–p75", wide: true },
          ...(advanced
            ? [
                { label: insightsCompensationPanelTopDecile(), value: fmtComp(o.p90), sub: "p90", tone: "good" as const },
                { label: insightsCompensationPanelRange(), value: `${fmtComp(o.min)}–${fmtComp(o.max)}`, sub: insightsCompensationPanelMinMax(), wide: true },
              ]
            : []),
        ]}
      />

      {advanced && <CompTrendChart days={days} scope={scope} />}

      {advanced && data.disclosed.bands.length > 0 && (
        <div className="panel chart-panel chart-panel-wide">
          <div className="chart-panel-head">
            <div>
              <span className="eyebrow">{insightsCompensationPanelPublishedBands()}</span>
              <h3>
                {insightsCompensationPanelWhatEmployersActuallyPrint()}
                <InfoTip label={insightsCompensationPanelAboutPublishedSalaryBands()}>{disclosedExplanation}</InfoTip>
              </h3>
            </div>
            <span className="chart-insight">
              {insightsCompensationPanelBandsFromEmployers({ bands: data.disclosed.bands.length, employers: data.disclosed.companies })}
            </span>
          </div>
          <PayBands disclosed={data.disclosed} />
        </div>
      )}

      {/* What employers print (above) vs. how many of them print anything (here). */}
      {advanced && <DisclosurePanel rates={data.disclosure} days={days} scope={scope} minRoles={data.min_roles} />}

      {/* Equal pairs: each row of the grid holds two cards of one kind and
          length. The basic view has no distribution, so pay by level stands
          alone above the next pair. */}
      {advanced ? (
        <div className="demand-grid pay-pair">
          {distribution}
          {byLevel}
        </div>
      ) : byLevel}

      <div className="demand-grid pay-pair">
        <div className="panel">
          <h3>{insightsCompensationPanelTopPayingCompanies()}</h3>
          {companies.map((c) => (
            <CompBar key={c.company} label={companyName(c.company)} s={c} max={companyMax} title={iqr(c)} />
          ))}
          <p className="hiring-note">{atLeast}</p>
        </div>

        <div className="panel">
          <h3>{insightsCompensationPanelMedianPayByDiscipline()}</h3>
          {families.map((f) => (
            <CompBar key={f.family ?? "none"} label={roleName(f.family)} s={f} max={familyMax} title={iqr(f)} />
          ))}
          <p className="hiring-note">{atLeast}</p>
        </div>
      </div>

      {advanced && <BaseEstimatesPanel base={data.base_estimates} />}

      {advanced && <div className="panel">
        <h3>
          {insightsCompensationPanelWhatASkillAddsAt()}
          <InfoTip label={insightsCompensationPanelHowASkillSPay()}>
            {insightsCompensationPanelRolesNamingTheSkillAgainst()}
          </InfoTip>
        </h3>
        {data.by_skill.length === 0 ? (
          <div className="empty-hint">{insightsCompensationPanelNotEnoughPricedRolesPer()}</div>
        ) : (
          data.by_skill.map((s) => (
            <div className="bar-row comp-row" key={s.term} title={insightsCompensationPanelMedian({ roles: roles(s.count), p50: fmtComp(s.p50) })}>
              <span className="pay-skill">{skillName(s.term)}</span>
              <div className="bar-track">
                <div
                  className={`bar-fill${s.premium < 0 ? " is-below" : ""}`}
                  style={{ width: `${(Math.abs(s.premium) / premiumMax) * 100}%` }}
                />
              </div>
              <span className={`val${s.premium > 0 ? " pay-premium" : ""}`}>{signed(s.premium)}</span>
              <span className="comp-n">{roles(s.count)}</span>
            </div>
          ))
        )}
      </div>}
    </>
  );
}
