import { DemandView } from "./Demand";
import { SkillsView } from "./SkillsView";
import { ClustersView } from "./ClustersView";
import { OverviewPanel } from "./OverviewPanel";
import { TrendsPanel } from "./TrendsPanel";
import { OverlapPanel } from "./OverlapPanel";
import { CompensationPanel } from "./CompensationPanel";
import { StockTrajectoryPanel } from "./StockTrajectoryPanel";
import { VelocityPanel } from "./VelocityPanel";
import { LEVELS_PARAMS, LevelsPanel } from "./LevelsPanel";
import { STATISTICS_TABS } from "../../navTabs";
import { useTabRoute } from "../../routing/useTabRoute";
import { useSearchParam } from "../../routing/useSearchParam";
import { useSearchParamList } from "../../routing/useSearchParamList";
import { Button, Dialog, FilterSelect, Segmented, Switch, TabBar } from "../../ui";
import { useCallback, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Facets, InsightsScope, api } from "../../api";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { companyPickerOptions, otherCompanies } from "./companyPicker";
import { ADVANCED_TABS, InsightsView, readInsightsView, writeInsightsView } from "./insightsView";
import "./statistics.css";
import { PageHeader } from "../../patterns/PageHeader";
import {
  insightsOtherCompanies,
  insightsPeriodDays,
  insightsStatisticsViewAdvancedView,
  insightsStatisticsViewAdvancedWarningBody,
  insightsStatisticsViewAdvancedWarningTitle,
  insightsStatisticsViewAllTime,
  insightsStatisticsViewDiscipline,
  insightsStatisticsViewKeepItSimple,
  insightsStatisticsViewPartOfAdvancedView,
  insightsStatisticsViewShowAdvancedView,
  insightsStatisticsViewShowMeEverything,
  insightsStatisticsViewStatisticsSections,
  insightsStatisticsViewTimeRange,
  insightsStatisticsViewWindow,
  insightsYourCompanies,
  insightsCommonAllCompanies,
  insightsCommonCompanies,
} from "../../copy/gen/insights";
import { shellNavInsights } from "../../copy/gen/shell";
import { roleName } from "../../copy/vocab";

const SUBTAB_SLUGS = STATISTICS_TABS.map((t) => t.slug) as [string, ...string[]];

// days<=0 == all-time. Overview, Velocity, Trends, and Compensation's trend chart
// honor this period lens;
// the others are current-snapshot views (demand shows its own "as of" date).
// The `?window=` lens stores readable strings; `all` maps to days<=0.
const PERIODS: { win: string; days: number; label: string }[] = [
  { win: "7", days: 7, get label() { return insightsPeriodDays({ days: 7 }); } },
  { win: "30", days: 30, get label() { return insightsPeriodDays({ days: 30 }); } },
  { win: "90", days: 90, get label() { return insightsPeriodDays({ days: 90 }); } },
  { win: "all", days: 0, get label() { return insightsStatisticsViewAllTime(); } },
];
const WINDOW_OPTIONS = PERIODS.map((p) => p.win) as [string, ...string[]];

// The scope narrows every tab but Stock, whose public/private
// split is per company already. Kept in `?side=` and `?family=` like the window.
const SIDES = ["all", "yours", "other"] as const;
const SIDE_OPTIONS = [
  { value: "all" as const, get label() { return insightsCommonAllCompanies(); } },
  { value: "yours" as const, get label() { return insightsYourCompanies(); } },
  { value: "other" as const, get label() { return insightsOtherCompanies(); } },
];
const SCOPE_AWARE = new Set<string>(SUBTAB_SLUGS.filter((slug) => slug !== "trajectory"));
// Levels is reference data: the side picks whose ladders show, and no
// discipline narrows a ladder.
const DISCIPLINE_AWARE = new Set<string>([...SCOPE_AWARE].filter((slug) => slug !== "levels"));

const PERIOD_AWARE = new Set<string>([
  "overview",
  "velocity",
  "compensation",
  "trends",
]);

export function StatisticsView({ onOpen }: { onOpen: (id: number, companySlug?: string | null) => void }) {
  // Sub-tab lives in the path (`/statistics/:tab`); the period lives in `?window=`.
  const { tab: view } = useTabRoute({
    base: "/statistics",
    slugs: SUBTAB_SLUGS,
    fallback: "overview",
  });
  const [win, setWin] = useSearchParam("window", { options: WINDOW_OPTIONS, fallback: "30" });
  // A tab switch keeps the lenses: the scope and the window are the
  // reader's question, not one tab's, so they travel with the reader.
  const navigate = useNavigate();
  const { search } = useLocation();
  const setView = useCallback(
    (tab: string) => {
      // Levels' own keys (its search, its translation) answer only Levels.
      const next = new URLSearchParams(search);
      if (tab !== "levels") LEVELS_PARAMS.forEach((key) => next.delete(key));
      const query = next.toString();
      navigate({ pathname: `/statistics/${tab}`, search: query ? `?${query}` : "" });
    },
    [navigate, search],
  );
  const days = win === "all" ? 0 : Number(win);
  // Basic until the person turns the advanced view on. The first time, a
  // dialog asks; once they have said yes, the switch just switches.
  const [stored, setStored] = useState<InsightsView | null>(readInsightsView);
  const [asking, setAsking] = useState(false);
  const advanced = stored === "advanced";
  const choose = (next: InsightsView) => {
    writeInsightsView(next);
    setStored(next);
  };
  const turnOn = () => (stored === null ? setAsking(true) : choose("advanced"));
  // A link to an advanced tab still opens it, so the basic view lists the
  // tab while it is the one on screen.
  const tabs = STATISTICS_TABS.filter((t) => advanced || !ADVANCED_TABS.has(t.slug) || t.slug === view);
  const [side, setSide] = useSearchParam("side", { options: SIDES, fallback: "all" });
  const [families, setFamilies] = useSearchParamList("family");
  const familyKey = families.join(",");
  // One object per distinct scope, so a panel's request key changes only when
  // the scope does (the list hook returns a fresh array every render).
  const scope = useMemo<InsightsScope>(
    () => ({ side, families: familyKey ? familyKey.split(",") : [] }),
    [side, familyKey],
  );
  // One read of the filter options for the screen: the discipline select and
  // the Skills and Overlap company pickers all draw from it.
  const facets = useAsyncResource<Facets>(api.facets, [], { keep: "facets" }).data;
  const familyOptions = facets
    ? Object.entries(facets.families)
        .filter(([slug]) => (facets.counts.family[slug] ?? 0) > 0)
        .map(([slug]) => ({ value: slug, label: roleName(slug), count: facets.counts.family[slug] }))
    : [];
  // A picker on a narrowed side needs to know which companies are on it; the
  // roster says, and is read only then.
  const picksCompanies = view === "skills" || view === "overlap";
  const sideRoster = picksCompanies && side !== "all";
  const other = useAsyncResource<ReadonlySet<string> | null>(
    () => (sideRoster ? api.companies().then(otherCompanies) : Promise.resolve(null)),
    [sideRoster],
    { keep: "stats/other-companies" },
  ).data;
  const companyOptions = useMemo(
    () => (picksCompanies ? companyPickerOptions(facets, side, other) : []),
    [picksCompanies, facets, side, other],
  );
  // A pick belongs to the scope it was made in: keyed on the scope, a panel
  // starts with no pick whenever the side or the disciplines change.
  const scopeKey = `${side}|${familyKey}`;
  return (
    <main className="main stats-main" data-design-system="app">
      <PageHeader title={shellNavInsights()}
        actions={
          <Switch checked={advanced} onChange={(on) => (on ? turnOn() : choose("basic"))}>
            {insightsStatisticsViewAdvancedView()}
          </Switch>
        }
      />
      <Dialog
        isOpen={asking}
        onClose={() => setAsking(false)}
        label={insightsStatisticsViewAdvancedWarningTitle()}
        width={440}
        className="app-overlay"
      >
        <div className="stats-view-dialog">
          <h2>{insightsStatisticsViewAdvancedWarningTitle()}</h2>
          <p>{insightsStatisticsViewAdvancedWarningBody()}</p>
          <div className="stats-view-dialog-actions">
            <Button onClick={() => setAsking(false)}>{insightsStatisticsViewKeepItSimple()}</Button>
            <Button
              variant="primary"
              onClick={() => {
                setAsking(false);
                choose("advanced");
              }}
            >
              {insightsStatisticsViewShowMeEverything()}
            </Button>
          </div>
        </div>
      </Dialog>
      <div className="stats-head">
        <TabBar
          className="stats-tabbar"
          label={insightsStatisticsViewStatisticsSections()}
          idPrefix="statistics"
          controls="statistics-tabpanel"
          value={view}
          onChange={setView}
          tabs={tabs.map((t) => ({ id: t.slug, label: t.label }))}
        />
        {SCOPE_AWARE.has(view) && (
          <div className="stats-scope">
            <Segmented className="stats-side" label={insightsCommonCompanies()} value={side} onChange={setSide} options={SIDE_OPTIONS} />
            {DISCIPLINE_AWARE.has(view) && <FilterSelect
              className="stats-family"
              label={insightsStatisticsViewDiscipline()}
              options={familyOptions}
              selected={scope.families as string[]}
              onChange={setFamilies}
              searchable
            />}
          </div>
        )}
        {PERIOD_AWARE.has(view) && (
          <div className="stats-period-wrap">
            <span data-selection="chrome" className="stats-period-label">{insightsStatisticsViewWindow()}</span>
            <Segmented
              className="stats-period"
              label={insightsStatisticsViewTimeRange()}
              value={win}
              onChange={setWin}
              options={PERIODS.map((p) => ({ value: p.win, label: p.label }))}
            />
          </div>
        )}
      </div>

      {!advanced && ADVANCED_TABS.has(view) && (
        <p className="stats-view-note">
          {insightsStatisticsViewPartOfAdvancedView()}{" "}
          <Button variant="link" onClick={turnOn}>{insightsStatisticsViewShowAdvancedView()}</Button>
        </p>
      )}

      <div
        id="statistics-tabpanel"
        className="stats-panel"
        role="tabpanel"
        aria-labelledby={`statistics-tab-${view}`}
      >
        {view === "overview" && <OverviewPanel days={days} scope={scope} onOpen={onOpen} advanced={advanced} />}
        {view === "demand" && <DemandView scope={scope} onOpen={onOpen} advanced={advanced} />}
        {view === "velocity" && <VelocityPanel days={days} scope={scope} />}
        {view === "compensation" && <CompensationPanel days={days} scope={scope} advanced={advanced} />}
        {view === "levels" && <LevelsPanel scope={scope} onResetSide={() => setSide("all")} />}
        {view === "trajectory" && <StockTrajectoryPanel />}
        {view === "skills" && <SkillsView key={scopeKey} scope={scope} companies={companyOptions} />}
        {view === "trends" && <TrendsPanel days={days} scope={scope} />}
        {view === "overlap" && <OverlapPanel key={scopeKey} scope={scope} companies={companyOptions} />}
        {view === "clusters" && <ClustersView scope={scope} onOpen={onOpen} />}
      </div>
    </main>
  );
}
