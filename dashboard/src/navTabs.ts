// Sub-tab definitions for multi-view sections. This is a LEAF module: it imports
// no components, so section components (StatisticsView, Settings) can read these
// constants without forming an import cycle with tabs.tsx (which imports those
// same components to build the route table).

// Labels are getters over the copy catalog (docs/copy.md):
// a module-level table is evaluated once, a getter reads the active language
// on every access.
import {
  shellTabInsightsOverview,
  shellTabInsightsHiring,
  shellTabInsightsPace,
  shellTabInsightsPay,
  shellTabInsightsLevels,
  shellTabInsightsStock,
  shellTabInsightsSkills,
  shellTabInsightsTrends,
  shellTabInsightsOverlap,
  shellTabInsightsGroups,
  shellTabSettingsCompanies,
  shellTabSettingsAi,
  shellTabSettingsSchedule,
  shellTabSettingsRecipes,
  shellTabSettingsRetention,
  shellTabSettingsPlugins,
  shellTabSettingsPrivacy,
  shellTabSettingsLanguage,
  shellTabProfileLookingFor,
  shellTabProfileExperience,
} from "./copy/gen/shell";

// A path sub-tab within a section. The slug is the URL segment
// (`/statistics/velocity`); the label is what the tabbar/breadcrumb/palette show.
export interface SubTabDef {
  slug: string;
  label: string;
}

// Statistics sub-tabs. Canonical source — StatisticsView, the breadcrumb, and
// the command palette all import this rather than re-declaring the list.
export const STATISTICS_TABS: SubTabDef[] = [
  { slug: "overview", get label() { return shellTabInsightsOverview(); } },
  { slug: "demand", get label() { return shellTabInsightsHiring(); } },
  { slug: "velocity", get label() { return shellTabInsightsPace(); } },
  { slug: "compensation", get label() { return shellTabInsightsPay(); } },
  { slug: "levels", get label() { return shellTabInsightsLevels(); } },
  { slug: "trajectory", get label() { return shellTabInsightsStock(); } },
  { slug: "skills", get label() { return shellTabInsightsSkills(); } },
  { slug: "trends", get label() { return shellTabInsightsTrends(); } },
  { slug: "overlap", get label() { return shellTabInsightsOverlap(); } },
  { slug: "clusters", get label() { return shellTabInsightsGroups(); } },
];

// Settings sub-tabs. The section shell switch-renders these; each is a
// deep-linkable `/settings/:tab`. Settings keeps machinery only; the candidate
// scope surface lives under Profile (`/settings/scope` redirects there).
// Order is how often a person comes back to a tab: what RoleBand reads and
// how (companies, matching, when it scans, plugins that add data, then
// recipes for a board no built-in reader covers), then the set-once
// preferences, ending on the two about the person's own data.
export const SETTINGS_TABS: SubTabDef[] = [
  { slug: "companies", get label() { return shellTabSettingsCompanies(); } },
  { slug: "intelligence", get label() { return shellTabSettingsAi(); } },
  { slug: "schedule", get label() { return shellTabSettingsSchedule(); } },
  { slug: "plugins", get label() { return shellTabSettingsPlugins(); } },
  { slug: "recipes", get label() { return shellTabSettingsRecipes(); } },
  { slug: "language", get label() { return shellTabSettingsLanguage(); } },
  { slug: "retention", get label() { return shellTabSettingsRetention(); } },
  { slug: "privacy", get label() { return shellTabSettingsPrivacy(); } },
];

// Profile sub-tabs: Direction, which steers the radar, and Your experience,
// which holds the CV action. No display-only surfaces: the slugs overview,
// background and activity are not valid, so `useTabRoute` redirects those deep
// links to Direction.
export const PROFILE_TABS: SubTabDef[] = [
  { slug: "direction", get label() { return shellTabProfileLookingFor(); } },
  { slug: "experience", get label() { return shellTabProfileExperience(); } },
];
