import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PROFILE_TABS } from "../../navTabs";
import { useTabRoute } from "../../routing/useTabRoute";
import { SETUP_PATH, useSetupMode, type SetupCompaniesProps } from "../../routing/setupMode";
import { useInstallSetUp } from "../../routing/installSetUp";
import { ScopeDraftProvider } from "./useScopeDraft";
import { Walk } from "./walk/Walk";
import { SettingsDesignSystemRoot } from "../../ui/SettingsDesignSystemRoot";
import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { PageHeader } from "../../patterns/PageHeader";
import { ScopeGuideButton } from "./ScopeGuide";
import { ExperiencePage } from "./ExperiencePage";
import { radarLoading } from "../../copy/gen/radar";
import { shellNavProfile } from "../../copy/gen/shell";
import { profileSetupFinish, profileSetupUnfinished } from "../../copy/gen/profile";

const PROFILE_SLUGS = PROFILE_TABS.map((tab) => tab.slug) as [string, ...string[]];

/* The Profile area. It has no Overview, Background or Activity — those
   would be display-only surfaces whose facts live where the user acts — so
   Direction, the radar's steering wheel, is all that renders here. Your
   experience is reached through the Summary's CV action; no tabbar is needed.
   `useTabRoute` owns the `/profile/:tab` slug, which redirects any other
   `/profile/...` deep link here instead of dead-ending.

   Direction is the walk: five screens, one question each, and a
   sheet that writes the answer back. It owns its own two-column layout and
   folds it at the settings shell's breakpoint, so the shell here is only the
   head. Rendered inside the settings design scope, which owns the
   select-card and rail families.

   First-run setup is this same walk (routing/setupMode.ts): it starts blank,
   ends on the companies step the route hands in, and draws its own header,
   which says how far along setup is; that header's one action is the way
   out. */
export function ProfileView({
  setupCompanies,
}: {
  setupCompanies?: (props: SetupCompaniesProps) => ReactNode;
} = {}) {
  const { tab } = useTabRoute({ base: "/profile", slugs: PROFILE_SLUGS, fallback: "direction" });
  const navigate = useNavigate();
  const setup = useSetupMode();
  const inSetup = setup === "on" && tab === "direction";
  const setUp = useInstallSetUp();
  /* No material: the walk paints the app's own action set, so a chosen card is
     gold. A `data-material` here would need its stylesheet loaded by this
     chunk, or the page would change colour whenever another chunk loads it. */

  const actions = tab === "direction" ? <ScopeGuideButton variant="walk" compact /> : undefined;

  return (
    <SettingsDesignSystemRoot>
      {!inSetup && <PageHeader title={shellNavProfile()} actions={actions} />}
      {/* Left for later, setup is unfinished: the radar runs on starter
          settings, which Direction shows as if they were answers. */}
      {!inSetup && tab === "direction" && setUp === false && (
        <p className="scope-notice profile-setup-unfinished">
          {profileSetupUnfinished()}{" "}
          <Link className="ui-btn ui-btn-link" to={SETUP_PATH}>{profileSetupFinish()}</Link>
        </p>
      )}
      <div className="settings-shell">
        <div id="profile-tabpanel" className="settings-content">
          {/* The experience placeholder does not consume a scope draft. The
              route boundary remounts on navigation; keeping its provider on
              Direction lets the existing unmount stash carry unsaved picks
              back, without a second provider clearing it in between. Setup's
              draft starts blank and keeps no stash; it is keyed apart so the
              two never share a mount. */}
          {tab === "experience" ? (
            <ExperiencePage />
          ) : setup === "pending" ? (
            <ResourceLoadState error={null} loading={radarLoading()} />
          ) : (
            <ScopeDraftProvider key={inSetup ? "setup" : "profile"} initialSelection={inSetup ? "empty" : "saved"}>
              <Walk setup={inSetup ? { companies: setupCompanies, onLater: () => navigate("/", { replace: true }) } : undefined} />
            </ScopeDraftProvider>
          )}
        </div>
      </div>
    </SettingsDesignSystemRoot>
  );
}
