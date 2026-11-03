import { useMemo, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import type { CompanyDiscoveryState, InsightsScope, LevelGuide, LevelGuideCompany } from "../../api";
import { compare } from "../../copy/format";
import { jobsCareerTrack } from "../../copy/gen/jobs";
import {
  insightsCommonCompanies,
  insightsCommonCompany,
  insightsLevelsAmbiguous,
  insightsLevelsClear,
  insightsLevelsEmpty,
  insightsLevelsEngineering,
  insightsLevelsEngineeringTitle,
  insightsLevelsFigure,
  insightsLevelsFigureTranslating,
  insightsLevelsFlat,
  insightsLevelsFlatTitle,
  insightsLevelsFollowedWithoutGuide,
  insightsLevelsKpiFlat,
  insightsLevelsKpiFlatSub,
  insightsLevelsKpiGuided,
  insightsLevelsKpiSkipped,
  insightsLevelsKpiSkippedSub,
  insightsLevelsLine,
  insightsLevelsLineTranslating,
  insightsLevelsLoadFailed,
  insightsLevelsLoading,
  insightsLevelsNoGuide,
  insightsLevelsReset,
  insightsLevelsSameAs,
  insightsLevelsSearch,
  insightsLevelsSearchExample,
  insightsLevelsSector,
  insightsLevelsSkipped,
  insightsLevelsSkippedClosest,
  insightsLevelsTranslateFrom,
  insightsLevelsTranslating,
  insightsLevelsTranslatingColumn,
  insightsLevelsYourAim,
  insightsLevelsYourLevel,
} from "../../copy/gen/insights";
import {
  profileWalkModelHandsOnAsTheExpert,
  profileWalkModelLeadingATeam,
  profileWalkModelOwningAProductOrProgram,
  profileWalkModelWorkingWithCustomers,
} from "../../copy/gen/profile";
import { levelName, sectorName } from "../../copy/vocab";
import { companyName } from "../../format";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { useMeasuredCssSize } from "../../hooks/useMeasuredCssSize";
import { useSearchParamList } from "../../routing/useSearchParamList";
import { Button, EmptyState, FilterSelect, SearchField } from "../../ui";
import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { ResultsSummary } from "../../patterns/ResultsSummary";
import { otherCompanies } from "./companyPicker";
import { InsightHero, n, type HeroKpi } from "./InsightHero";
import {
  LEVELS,
  closestLevel,
  defaultTrack,
  engineeringOnly,
  hiddenSpelling,
  levelHits,
  parseFrom,
  type From,
  type Hit,
} from "./levelsModel";
import { resolveCell } from "../../patterns/levels/levelGuide";

/* The Levels tab: how each company names each level, every reviewed ladder,
 * followed or not.
 *
 * Two modes over one table. Reading lights the person's own level and aim
 * from Profile. Translating starts from one company's level (a click, or a
 * search only one cell answers): that row pins on top and its column lights
 * across every row, so "ICT4 at Apple" reads off as L5 at Google.
 *
 * Search and the career track never drop a row: a company with engineering
 * levels only stays, its names marked, and a flat ladder says its titles
 * state no level rather than showing blanks that read as missing data. */

/** The tab's own address keys; the Insights shell drops them on a tab switch. */
export const LEVELS_PARAMS = ["q", "from", "track", "sector"] as const;

/** Profile's career track answers, in its order and words. */
const TRACKS = [
  { value: "technical", get label() { return profileWalkModelHandsOnAsTheExpert(); } },
  { value: "management", get label() { return profileWalkModelLeadingATeam(); } },
  { value: "product_program", get label() { return profileWalkModelOwningAProductOrProgram(); } },
  { value: "business_customer", get label() { return profileWalkModelWorkingWithCustomers(); } },
] as const;
const TRACK_ORDER = TRACKS.map((track) => track.value);

export function LevelsPanel({ scope, onResetSide }: { scope: InsightsScope; onResetSide: () => void }) {
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const [sectors, setSectors] = useSearchParamList("sector");
  const rootRef = useRef<HTMLDivElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  useMeasuredCssSize({ rootRef, elementRef: toolbarRef, property: "--levels-toolbar-h", ignoreZero: true });

  const guide = useAsyncResource<LevelGuide>((signal) => api.levelGuide(signal), [], { keep: "stats/levels" });
  const discovery = useAsyncResource<CompanyDiscoveryState>(() => api.companyDiscovery(), [], { keep: "stats/levels-discovery" }).data;
  const profile = useAsyncResource(() => api.profile(), [], { keep: "stats/levels-profile" }).data;
  const settings = useAsyncResource(() => api.scopeSettings(), [], { keep: "stats/levels-settings" }).data;
  const narrowed = scope.side !== "all";
  const other = useAsyncResource<ReadonlySet<string> | null>(
    () => (narrowed ? api.companies().then(otherCompanies) : Promise.resolve(null)),
    [narrowed],
    { keep: "stats/other-companies" },
  ).data;

  const track = TRACK_ORDER.find((value) => value === params.get("track"))
    ?? defaultTrack(settings?.enabled_role_tracks, TRACK_ORDER);

  const write = (change: (next: URLSearchParams) => void) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      change(next);
      return next;
    }, { replace: true });
  const setQuery = (value: string) => write((next) => {
    next.delete("from");
    if (value) next.set("q", value);
    else next.delete("q");
  });
  const translateFrom = (from: From) => write((next) => {
    next.delete("q");
    next.set("from", `${from.slug}:${from.level}`);
  });
  const clear = () => write((next) => { next.delete("q"); next.delete("from"); });
  const setTrack = (value: string) => write((next) => {
    if (value === defaultTrack(settings?.enabled_role_tracks, TRACK_ORDER)) next.delete("track");
    else next.set("track", value);
  });
  const resetAll = () => {
    write((next) => LEVELS_PARAMS.forEach((key) => next.delete(key)));
    onResetSide();
  };

  const byCompany = useMemo(
    () => new Map((discovery?.companies ?? []).map((company) => [company.slug, company])),
    [discovery],
  );
  // The startup names cover every catalog company; a company added by
  // address is named by its own discovery row.
  const nameOf = (slug: string) => {
    const name = companyName(slug);
    return name === slug ? byCompany.get(slug)?.display ?? name : name;
  };
  const followed = (slug: string) => byCompany.get(slug)?.enabled === true;
  const onSide = (slug: string) => {
    if (scope.side === "all") return true;
    if (!followed(slug) || other === null) return false;
    return other.has(slug) === (scope.side === "other");
  };
  const inSector = (slug: string) =>
    sectors.length === 0 || (byCompany.get(slug)?.sectors ?? []).some((sector) => sectors.includes(sector));
  const nameMatches = (slug: string, text: string) => {
    const needle = text.trim().toLowerCase();
    if (!needle) return false;
    if (nameOf(slug).toLowerCase().includes(needle)) return true;
    return (byCompany.get(slug)?.aliases ?? []).some((alias) => alias.toLowerCase() === needle);
  };

  if (!guide.data) {
    return <ResourceLoadState error={guide.error} loading={insightsLevelsLoading()} failed={insightsLevelsLoadFailed()} onRetry={guide.retry} />;
  }

  const companies = guide.data.companies;
  const pool = companies.filter((company) => onSide(company.slug) && inSector(company.slug));
  const hits: Hit[] = query ? levelHits(pool, track, query) : [];
  const named = query ? pool.filter((company) => nameMatches(company.slug, query)) : [];
  const hitCompanies = new Set(hits.map((hit) => hit.slug));
  const from = parseFrom(params.get("from"), companies)
    ?? (hits.length === 1 && named.length === 0 ? { slug: hits[0].slug, level: hits[0].level } : null);
  const ambiguous = !from && hitCompanies.size > 1;

  let rows: LevelGuideCompany[];
  if (from) rows = pool.filter((company) => company.slug !== from.slug);
  else if (query) rows = pool.filter((company) => hitCompanies.has(company.slug) || named.some((n) => n.slug === company.slug));
  else rows = pool;
  rows = [...rows].sort((a, b) => compare(nameOf(a.slug), nameOf(b.slug)));
  const pinned = from ? companies.find((company) => company.slug === from.slug) ?? null : null;
  if (pinned) rows = [pinned, ...rows];

  // A company the person can name with no guide of its own still answers a
  // search: a catalog company, or one they follow.
  const guided = new Set(companies.map((company) => company.slug));
  const unguided = new Map(guide.data.unguided.map((row) => [row.slug, row.same_as]));
  for (const company of discovery?.companies ?? []) {
    if (company.enabled && !guided.has(company.slug) && !unguided.has(company.slug)) unguided.set(company.slug, null);
  }
  const unguidedRows = query && !from
    ? [...unguided].filter(([slug]) => onSide(slug) && nameMatches(slug, query))
    : [];
  for (const [, sameAs] of unguidedRows) {
    const shared = sameAs ? companies.find((company) => company.slug === sameAs) : undefined;
    if (shared && !rows.includes(shared)) rows.push(shared);
  }
  const followedWithoutGuide = scope.side === "yours" && !query && !from
    ? [...unguided.keys()].filter((slug) => onSide(slug)).length
    : 0;

  const experience = profile?.profile?.experience_stage ?? null;
  const target = profile?.profile?.target_stage ?? null;
  const lit = new Set(from ? [from.level] : [experience, target].filter((level): level is string => Boolean(level)));
  const allowed = new Set(guide.data.tracks[track] ?? LEVELS);
  // Intern folds away unless a row shows one: most ladders name none.
  const levels = LEVELS.filter((level) => level !== "intern" || rows.some((row) => resolveCell(row.levels[level], track)));

  const heading = (level: string) => {
    const name = levelName(level);
    if (from) return level === from.level ? insightsLevelsTranslatingColumn({ level: name }) : name;
    if (level === experience) return insightsLevelsYourLevel({ level: name });
    if (level === target) return insightsLevelsYourAim({ level: name });
    return name;
  };

  const fromEntry = pinned && from ? resolveCell(pinned.levels[from.level], track)?.entry ?? null : null;
  const figure = pinned && from && fromEntry
    ? insightsLevelsFigureTranslating({ company: nameOf(pinned.slug), code: fromEntry.label, level: levelName(from.level) })
    : insightsLevelsFigure();

  // The level the tiles count gaps at: the translated one, else the aim,
  // else the person's level. A flat ladder states no level, so it skips none.
  const focus = from?.level ?? target ?? experience;
  const kpis: HeroKpi[] = [
    { label: insightsCommonCompanies(), value: n(pool.length), sub: insightsLevelsKpiGuided() },
    { label: insightsLevelsKpiFlat(), value: n(pool.filter((company) => company.flat).length), sub: insightsLevelsKpiFlatSub() },
  ];
  if (focus && allowed.has(focus)) {
    const skipping = pool.filter((company) => !company.flat && !resolveCell(company.levels[focus], track)).length;
    kpis.push({ label: insightsLevelsKpiSkipped({ level: levelName(focus) }), value: n(skipping), sub: insightsLevelsKpiSkippedSub() });
  }

  const sectorOptions = (discovery?.sectors ?? [])
    .map((sector) => ({ value: sector.slug, label: sectorName(sector.slug) }));
  const active = Boolean(query || params.get("from") || params.get("track") || sectors.length || narrowed);

  return (
    <div className="levels" ref={rootRef}>
      <InsightHero
        tab="levels"
        figure={figure}
        line={from ? insightsLevelsLineTranslating() : insightsLevelsLine()}
        kpis={kpis}
      />
      <div className="panel levels-panel">
        <div className="levels-toolbar" ref={toolbarRef}>
          <SearchField
            className="levels-search"
            label={insightsLevelsSearch()}
            placeholder={insightsLevelsSearchExample()}
            value={query}
            onChange={setQuery}
          />
          <FilterSelect
            className="levels-track"
            label={jobsCareerTrack()}
            options={TRACKS.map((option) => ({ value: option.value, label: option.label }))}
            selected={[track]}
            onChange={(next) => next[0] && setTrack(next[0])}
            multiple={false}
          />
          <FilterSelect
            className="levels-sector"
            label={insightsLevelsSector()}
            options={sectorOptions}
            selected={sectors}
            onChange={setSectors}
          />
        </div>
        <ResultsSummary
          count={rows.length}
          total={pool.length}
          noun="company"
          reset={active ? <Button variant="link" onClick={resetAll}>{insightsLevelsReset()}</Button> : undefined}
        />
        {pinned && from && fromEntry ? (
          <p className="levels-status" role="status">
            {insightsLevelsTranslating({ company: nameOf(pinned.slug), code: fromEntry.label, level: levelName(from.level) })}
            {" "}<Button variant="link" onClick={clear}>{insightsLevelsClear()}</Button>
          </p>
        ) : ambiguous ? (
          <p className="levels-status" role="status">{insightsLevelsAmbiguous({ code: query.trim(), count: hitCompanies.size })}</p>
        ) : null}

        {rows.length === 0 && unguidedRows.length === 0 ? (
          <EmptyState title={insightsLevelsEmpty()} variant="inline">
            {[query && `“${query.trim()}”`, ...sectors.map(sectorName)].filter(Boolean).join(" · ")}
            {" "}<Button variant="link" onClick={resetAll}>{insightsLevelsReset()}</Button>
          </EmptyState>
        ) : (
          <table className="levels-table">
            <thead>
              <tr>
                <th scope="col">{insightsCommonCompany()}</th>
                {levels.map((level) => (
                  <th
                    scope="col"
                    key={level}
                    className={`${lit.has(level) ? "lit" : ""}${allowed.has(level) ? "" : " gated"}`}
                  >
                    {heading(level)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((company) => (
                <LevelRow
                  key={company.slug}
                  company={company}
                  levels={levels}
                  track={track}
                  lit={lit}
                  allowed={allowed}
                  from={from}
                  hits={ambiguous ? hits : []}
                  linked={byCompany.get(company.slug)?.tracked === true}
                  name={nameOf(company.slug)}
                  onTranslate={translateFrom}
                />
              ))}
              {unguidedRows.map(([slug, sameAs]) => (
                <tr key={`unguided-${slug}`} className="levels-unguided">
                  <th scope="row">{nameOf(slug)}</th>
                  <td colSpan={levels.length}>
                    {sameAs ? insightsLevelsSameAs({ company: nameOf(sameAs) }) : insightsLevelsNoGuide({ company: nameOf(slug) })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {followedWithoutGuide > 0 && (
          <p className="levels-foot">{insightsLevelsFollowedWithoutGuide({ count: followedWithoutGuide })}</p>
        )}
      </div>
    </div>
  );
}

function LevelRow({ company, levels, track, lit, allowed, from, hits, linked, name, onTranslate }: {
  company: LevelGuideCompany;
  levels: readonly string[];
  track: string;
  lit: ReadonlySet<string>;
  allowed: ReadonlySet<string>;
  from: From | null;
  hits: readonly Hit[];
  linked: boolean;
  name: string;
  onTranslate: (from: From) => void;
}) {
  const engineering = track !== "technical" && engineeringOnly(company, track);
  const present = levels.map((level) => resolveCell(company.levels[level], track) !== null);
  // A flat ladder's titles state nothing past its last rung: one cell says so.
  const lastPresent = present.lastIndexOf(true);
  const flatFrom = company.flat && lastPresent < levels.length - 1 ? lastPresent + 1 : -1;
  const pinned = from?.slug === company.slug;

  return (
    <tr className={pinned ? "pinned" : undefined}>
      <th scope="row">
        <span className="levels-company">
          {linked ? <Link to={`/company/${company.slug}`}>{name}</Link> : name}
        </span>
        {engineering && <span className="levels-tag" title={insightsLevelsEngineeringTitle()}>{insightsLevelsEngineering()}</span>}
      </th>
      {levels.map((level, index) => {
        if (flatFrom >= 0 && index > flatFrom) return null;
        const classes = `${lit.has(level) ? "lit" : ""}${allowed.has(level) ? "" : " gated"}`;
        if (index === flatFrom) {
          return (
            <td key={level} colSpan={levels.length - flatFrom} className="levels-flat" title={insightsLevelsFlatTitle()}>
              {insightsLevelsFlat()}
            </td>
          );
        }
        const resolved = resolveCell(company.levels[level], track);
        if (!resolved) {
          const closest = lit.has(level) ? closestLevel(company, level, track) : null;
          return (
            <td key={level} className={`levels-skip ${classes}`} data-level={levelName(level)}>
              <span className="sr-only">{insightsLevelsSkipped({ company: name, level: levelName(level) })}</span>
              {closest && (
                <span aria-hidden="true">{insightsLevelsSkippedClosest({ level: levelName(level), code: closest })}</span>
              )}
            </td>
          );
        }
        const hit = hits.find((h) => h.slug === company.slug && h.level === level);
        const also = hit ? hiddenSpelling(resolved.entry.label, hit.spelling) : null;
        const chosen = pinned && from?.level === level;
        return (
          <td key={level} className={`${classes}${hit ? " hit" : ""}${resolved.engineering ? " muted" : ""}`} data-level={levelName(level)}>
            <button
              type="button"
              className="levels-cell"
              aria-pressed={chosen}
              aria-label={insightsLevelsTranslateFrom({ company: name, code: resolved.entry.label })}
              onClick={() => onTranslate({ slug: company.slug, level })}
            >
              {resolved.entry.label}
              {also && <span className="levels-also">, {also}</span>}
            </button>
          </td>
        );
      })}
    </tr>
  );
}
