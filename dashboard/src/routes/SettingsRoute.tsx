import { Navigate, useParams } from "react-router-dom";
import { SETTINGS_TABS } from "../navTabs";
import { TabBar } from "../ui/TabBar";
import { useTabRoute } from "../routing/useTabRoute";
import { CompaniesSection } from "../features/companies/CompaniesSection";
import { CompaniesDataProvider } from "../features/companies/CompaniesData";
import { IntelligenceTab } from "../features/intelligence/IntelligenceSection";
import { ScheduleSection } from "../features/settings/ScheduleSection";
import { RecipesSection } from "../features/settings/RecipesSection";
import { RetentionSection } from "../features/settings/RetentionSection";
import { LanguageSection } from "../features/settings/LanguageSection";
import { PrivacySection } from "../features/settings/PrivacySection";
import { PluginsSection } from "../features/settings/PluginsSection";
import { PluginSettings } from "../features/settings/PluginSettings";
import { PriceFeedSection } from "../features/settings/PriceFeedSection";
import { SettingsDesignSystemRoot } from "../ui/SettingsDesignSystemRoot";
import { PageHeader } from "../patterns/PageHeader";
import {
  settingsRouteSettingsSections,
} from "../copy/gen/settings";
import { shellNavSettings } from "../copy/gen/shell";

const SETTINGS_SLUGS = SETTINGS_TABS.map((tab) => tab.slug) as [string, ...string[]];

/* Settings keeps the machinery: companies, intelligence, schedule, recipes,
   language, privacy, plugins, retention. The candidate scope surface is
   Profile › Direction; /settings/scope redirects there in App.tsx.

   It lives in `routes/`, not in `features/settings/`, because what it does is
   COMPOSE two other features: Companies and Intelligence are whole features
   whose only consumer is this tab shell. Under `features/` that is a
   feature reaching into two siblings. `routes/` is the tier above `features/` and may import it, so
   here the same composition is simply legal. Its siblings BoardRoute,
   StatisticsRoute and ReviewRoute are the same shape, one feature lighter. */
export function SettingsRoute() {
  const { tab, setTab } = useTabRoute({
    base: "/settings",
    slugs: SETTINGS_SLUGS,
    fallback: "companies",
  });
  // `/settings/plugins/:pluginId` is one plugin's settings; no other tab has items.
  const { pluginId } = useParams();
  if (pluginId != null && tab !== "plugins") return <Navigate to={`/settings/${tab}`} replace />;
  // No tab has a rail column: on Companies the sector index navigates, so a
  // rail would only restate numbers the board shows.
  const shell = (
    <div className="settings-shell">
      <div
        id="settings-tabpanel"
        className="settings-content"
        role="tabpanel"
        aria-labelledby={`settings-tab-${tab}`}
      >
        {tab === "companies" && <CompaniesSection />}
        {tab === "intelligence" && <IntelligenceTab />}
        {tab === "schedule" && <ScheduleSection />}
        {tab === "recipes" && <RecipesSection />}
        {tab === "retention" && <RetentionSection />}
        {tab === "language" && <LanguageSection />}
        {tab === "privacy" && <PrivacySection />}
        {tab === "plugins" && (pluginId != null ? <PluginSettings pluginId={pluginId} /> : (
          <>
            <PluginsSection />
            {/* Not a plugin: the price feed is the core's, keyed by the user. */}
            <PriceFeedSection />
          </>
        ))}
      </div>
    </div>
  );

  return (
    <SettingsDesignSystemRoot>
      <PageHeader title={shellNavSettings()} />

      <TabBar
        className="settings-tabbar"
        label={settingsRouteSettingsSections()}
        idPrefix="settings"
        controls="settings-tabpanel"
        value={tab}
        onChange={setTab}
        tabs={SETTINGS_TABS.map((item) => ({ id: item.slug, label: item.label }))}
      />

      {tab === "companies" ? <CompaniesDataProvider>{shell}</CompaniesDataProvider> : shell}
    </SettingsDesignSystemRoot>
  );
}
