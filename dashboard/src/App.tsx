import { CommandPalette } from "./shell/CommandPalette";
import { readTheme, shownTheme, writeTheme, type Theme } from "./shell/theme";
import {
  shellBreadcrumbAria,
  shellLoadPageFailed,
  shellLoadRoleFailed,
  shellLoadingPage,
  shellLoadingRole,
  shellPaletteOpenAria,
  shellPaletteOpenTitle,
  shellRouteCompare,
  shellRouteDashboard,
  shellRouteWelcome,
  shellSkipToContent,
  shellStatNew,
  shellStatNewAria,
  shellStatNewTitle,
  shellStatOpen,
  shellStatOpenAria,
  shellStatOpenAriaUnknown,
  shellStatOpenTitle,
  shellStatReposted,
  shellStatRepostedAria,
  shellStatRepostedTitle,
  shellStatSaved,
  shellStatSavedAria,
  shellStatSavedAriaUnknown,
  shellStatSavedTitle,
  shellStatUnknown,
  shellStatsAria,
  shellTopbarAria,
} from "./copy/gen/shell";
import { ToastProvider } from "./ui/Toast";
import { ResourceLoadState } from "./ui/ResourceLoadState";
import { ErrorBoundary } from "./ui/ErrorBoundary";
import { recordClientError } from "./diagnostics/clientErrors";
import { Suspense, lazy, memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import type { Location } from "react-router-dom";
import { shellApi, type UsageState } from "./api/shell";
import { FreshnessBadge } from "./shell/FreshnessBadge";
import { NavRail } from "./shell/NavRail";
import { CompareChip } from "./shell/CompareChip";
import { ModelSwitchChip } from "./shell/ModelSwitchChip";
import { CompareSaveAlert } from "./shell/CompareSaveAlert";
import { StatChip } from "./shell/StatChip";
import { NotificationBell } from "./features/notifications/NotificationBell";
import { SyncButton } from "./shell/SyncButton";
import { POSITION_ROUTE, positionKey } from "./routing/paths";
import { ScreenProvider } from "./routing/screen";
import { readUnconfigured, useSetupMode } from "./routing/setupMode";
import { NAV_TABS } from "./navigation";
import { CompareRoute, PositionRoute, ROUTE_COMPONENTS, SettingsItemRoute, WelcomeRoute, preloadProfile, preloadScreens } from "./routeRegistry";
import { AppProviders } from "./context/AppProviders";
import { CopyBoundary } from "./copy/CopyBoundary";
import { useMissionActions, useMissionState, useMissionStats } from "./context/MissionState";
import { modeFromParam } from "./features/opportunities/boardMode";
import { BEHIND_COVER } from "./ui/Overlay";
import { BrandMark } from "./ui/BrandMark";

// Usage sharing asks a configured install once (docs/architecture.md); lazy,
// so its words stay out of the startup chunk.
const UsageConsentGate = lazy(() => import("./shell/UsageConsentGate"));

/** How long after the first screen draws the other screens start loading:
 *  past the first screen's own data reads. */
const SCREENS_AHEAD_MS = 1000;

/** Start (or stop) the browser side of usage sharing. Loaded only when the
 *  user shares something, so an install that does not loads none of it. */
function startSharing(state: UsageState): void {
  if (!state.groups.some((group) => group.status === "shared")) return;
  void import("./diagnostics/sharing").then((sharing) => sharing.applySharing(state));
}

/* The routed screen. Memoized on its location, so what only the chrome reads
   (the counts, the theme, an open palette) re-renders the chrome and stops
   here, never re-rendering the open screen. */
const RoutedScreens = memo(function RoutedScreens({ location }: { location: Location }) {
  return (
    <Routes location={location}>
      {NAV_TABS.map((t) => {
        const Screen = ROUTE_COMPONENTS[t.path];
        return t.tabs ? (
          // Multi-tab section: the index redirects to the default sub-tab;
          // `:tab` mounts the section shell, which reads the slug.
          <Route key={t.path} path={t.path}>
            <Route index element={<Navigate to={t.indexRedirect!} replace />} />
            <Route path=":tab" element={<Screen />} />
          </Route>
        ) : t.entityParam ? (
          // Entity section: bare list plus a deep-linkable `${path}/:param`,
          // as ONE route with an optional segment. Two sibling routes
          // (index + `:param`) would remount the screen on its first
          // pick, dropping the list's scroll and which groups were open.
          <Route key={t.path} path={`${t.path}/:${t.entityParam}?`} element={<Screen />} />
        ) : (
          <Route key={t.path} path={t.path} element={<Screen />} />
        );
      })}
      {/* Direct link / refresh on a position renders the detail standalone.
          The canonical URL nests under the company; /job/:id is the short
          form that self-canonicalizes once the job loads. */}
      <Route path={POSITION_ROUTE} element={<PositionRoute />} />
      <Route path="/job/:id" element={<PositionRoute />} />
      {/* The comparison by URL: the same body as the cover, as the
          page. Also what renders UNDER a role opened from a column. */}
      <Route path="/compare" element={<CompareRoute />} />
      {/* The scope surface lives in Profile; its Settings addresses
          (/settings/scope, /settings/roles) still land there. Static
          segments outrank /settings/:tab in route rank. */}
      <Route path="/settings/scope" element={<Navigate to="/profile/direction" replace />} />
      <Route path="/settings/roles" element={<Navigate to="/profile/direction" replace />} />
      {/* /settings/integrations lands on Settings > Plugins, where pay sources are set. */}
      <Route path="/settings/integrations" element={<Navigate to="/settings/plugins" replace />} />
      {/* One plugin's settings: the Settings shell on the Plugins tab,
          which reads `:pluginId` (any other tab sends it back). */}
      <Route path="/settings/:tab/:pluginId" element={<SettingsItemRoute />} />
      <Route path="/welcome" element={<WelcomeRoute />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
});

function Shell() {
  // Values and verbs from different contexts on purpose: the shell reads no
  // query, so it must not re-render on a keystroke.
  const stats = useMissionStats();
  const { newSignalsOnly, repostsOnly } = useMissionState();
  const { boardSearchRef, showNewSignals, showReposts, clearLenses } = useMissionActions();
  const [theme, setTheme] = useState<Theme>(readTheme);
  const [navExpanded, setNavExpanded] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const initialPath = useRef(location.pathname).current;
  const firstRunChecked = useRef(false);
  // First-run setup has the window to itself (routing/setupMode.ts): no rail
  // and no top bar, and the palette and the global keys do not open, so its
  // only ways out are its own (the intro's button, the walk's "Set up later").
  // The chrome stays away while the install is probed too, so it never shows
  // for a moment before setup starts.
  const setupMode = useSetupMode();
  const muted = setupMode === "on";
  // A launch at "/" asks whether the install is set up before it draws
  // anything, so a fresh install goes to the welcome without the board and
  // its chrome showing first. The hold ends when the answer says "set up", or
  // when the route has left "/": the router moves a frame after the answer.
  const [launching, setLaunching] = useState(initialPath === "/");
  const holding = launching && location.pathname === "/";
  // The plain ground (no ambient wash) holds through the launch hold and on
  // the welcome; public/theme-boot.js sets it before the first paint.
  const plainGround = holding || location.pathname === "/welcome";
  useLayoutEffect(() => {
    if (plainGround) document.documentElement.setAttribute("data-ground", "plain");
    else document.documentElement.removeAttribute("data-ground");
  }, [plainGround]);
  // Once the route has left "/" (the redirect to the welcome), the launch is
  // over: a later visit to the board is not held.
  useEffect(() => {
    if (launching && location.pathname !== "/") setLaunching(false);
  }, [launching, location.pathname]);
  const room = setupMode !== "off" || holding;
  // Usage sharing may ask once the install is known to be configured: at once
  // on a deep link, after the first-run check on "/" (a fresh install is asked
  // inside the welcome walk instead, never by a dialog over it).
  const [mayAskSharing, setMayAskSharing] = useState(initialPath !== "/");
  // Usage sharing's state, read once: it starts the browser side when something
  // is shared, and is what the question for a configured install is asked from.
  const [sharingState, setSharingState] = useState<UsageState | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    shellApi.usage?.(controller.signal)
      ?.then((state) => {
        setSharingState(state);
        startSharing(state);
      })
      .catch(() => { /* unreadable: nothing is shared, and it is asked next launch */ });
    return () => controller.abort();
  }, []);
  // The welcome leads into Profile's walk: its screen is fetched while the
  // welcome is read, so setup does not open on a load state. Not at once: the
  // welcome's own first frame comes first.
  useEffect(() => {
    if (location.pathname !== "/welcome") return;
    const later = window.setTimeout(preloadProfile, 1000);
    return () => window.clearTimeout(later);
  }, [location.pathname]);
  // Every other screen is fetched once the first has drawn: a screen whose
  // code is fetched on the click asks for its data only once that code has
  // arrived. Setup has the window to itself and fetches only its own walk.
  useEffect(() => {
    if (holding || muted) return;
    const later = window.setTimeout(() => void preloadScreens(), SCREENS_AHEAD_MS);
    return () => window.clearTimeout(later);
  }, [holding, muted]);
  const answeredSharing = useCallback((next: UsageState) => {
    setSharingState(next);
    startSharing(next);
  }, []);

  // First run: a fresh install (no persona profile, scope never configured)
  // starts in the onboarding wizard. Configured installs are never redirected.
  // The question is setup's own probe, so the welcome and the walk read the
  // same answer without asking again; a failed read never blocks the board.
  //
  // ONCE, and the ref is what says so. The dependencies are the real ones,
  // and `navigate` from react-router v7 does not keep one identity across
  // navigations, so without the ref the check re-runs after the wizard's own
  // navigation to "/", reads a profile the mock has not yet flipped, and
  // throws the user back into the wizard they just finished. The dependencies
  // stay honest; the guard states the "first run".
  useEffect(() => {
    if (initialPath !== "/" || firstRunChecked.current) return;
    firstRunChecked.current = true;
    void readUnconfigured().then((unconfigured) => {
      if (unconfigured) {
        navigate("/welcome", { replace: true });
        return;
      }
      setMayAskSharing(true);
      setLaunching(false);
    });
  }, [initialPath, navigate]);
  // The detail route renders as a full-screen overlay over the page the user
  // came from; that page is stashed in history state as backgroundLocation.
  const backgroundLocation = (location.state as { backgroundLocation?: Location } | null)?.backgroundLocation;
  const routedLocation = backgroundLocation ?? location;

  /* Recovering a dead route chunk means RELOADING THE DOCUMENT, and that is not
     defeatism — it is the only thing that works. Two caches sit in the way, and
     clearing either alone changes nothing:

       1. `React.lazy` memoizes its payload including the rejection, so the same
          lazy object re-throws forever. A factory handing back fresh components
          fixes this half.
       2. The browser's MODULE MAP also records the failed fetch, keyed by URL,
          for the lifetime of the document. A brand-new `lazy()` importing the
          same specifier therefore never reaches the network again.

     With the boundary and a fresh lazy set in place, a retry after an aborted
     chunk issues no request for the module at all. Only a new document clears
     (2), so that is what the button does. */
  const reloadDocument = useCallback(() => window.location.reload(), []);
  const activeTab = NAV_TABS.find((tab) =>
    tab.end ? routedLocation.pathname === tab.path : routedLocation.pathname.startsWith(tab.path)
  );
  // The route error boundary below remounts on this key. An entity section's
  // list and its `/:param` are ONE screen picking a row, so they share a key:
  // keyed on the whole path, every company pick would remount /company,
  // refetching the roster and dropping the list's scroll and open groups.
  // Anything deeper (a position under a company: a third segment) is another
  // screen, keyed by the position whichever URL names it (`positionKey`).
  const boundaryKey =
    positionKey(routedLocation.pathname) ??
    (activeTab?.entityParam && !routedLocation.pathname.split("/")[3] ? activeTab.path : routedLocation.pathname);
  // /welcome is the one route outside the tab table; it is not the dashboard.
  const routeLabel =
    activeTab?.label ??
    (routedLocation.pathname.startsWith("/welcome")
      ? shellRouteWelcome()
      : routedLocation.pathname.startsWith("/compare")
        ? shellRouteCompare()
        : shellRouteDashboard());
  // The breadcrumb's second segment is derived from the route: for a multi-tab
  // section, look up the active sub-tab's label from the registry. Entity routes
  // (company/:slug, job/:id) show nothing here — the detail panel names the
  // entity itself.
  const headerDetail = activeTab?.tabs
    ? activeTab.tabs.find((s) => s.slug === routedLocation.pathname.split("/")[2])?.label ?? null
    : null;

  /* Which of the top bar's counts is lit: at most one, and it is what the page
     shows. Asked of the page ON SCREEN, not the routed one — a cover is its own
     screen, so a role opened from the board lights none of them. */
  const onBoard = location.pathname === "/";
  const boardView = !onBoard
    ? null
    : newSignalsOnly
      ? "new"
      : repostsOnly
        ? "reposted"
        : modeFromParam(new URLSearchParams(location.search).get("show") ?? "") === "open"
          ? "open"
          : null;

  // While setup may be running (the welcome page, or the setup flag while the
  // install is probed) the page is dark; the saved choice is the person's own.
  const shown = shownTheme(theme, location.pathname === "/welcome" || setupMode !== "off");
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", shown);
  }, [shown]);
  useEffect(() => {
    writeTheme(theme);
  }, [theme]);

  const toggleTheme = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);

  // Global keyboard surface: ⌘K/Ctrl-K opens the palette anywhere; "/" focuses
  // the board search when not already typing in a field. The input itself
  // lives in the Board's own toolbar (the settings idiom) and reaches the
  // shell only through the context ref — null on every other route, where "/"
  // falls back to the palette.
  useEffect(() => {
    if (muted) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
        return;
      }
      const target = e.target as HTMLElement;
      const typing = target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
      if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        if (boardSearchRef.current) boardSearchRef.current.focus();
        else setPaletteOpen(true);
        return;
      }
      // "?" lists every key the app answers to (docs/ui.md "Keys").
      // Not while typing: a "?" in a field is text.
      if (e.key === "?" && !typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        setShortcutsOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [boardSearchRef, muted]);

  return (
    <div className={`app${navExpanded ? " nav-expanded" : ""}${room ? " in-setup" : ""}`}>
      {/* First in the tab order, invisible until focused. Every route begins
          with the rail and the top bar, so without it reaching the page by
          keyboard means tabbing past the whole chrome on every navigation.
          The target is the routed region rather than any one screen's <main>,
          because which screen is mounted changes. */}
      {/* The skip link, the rail and the workspace are the page a cover is laid
          over: inert while one is open (ui/Overlay, BEHIND_COVER). */}
      <a className="skip-link" href="#main-content" {...{ [BEHIND_COVER]: "" }}>
        {shellSkipToContent()}
      </a>
      {!room && (
        <NavRail
          expanded={navExpanded}
          onToggleExpanded={() => setNavExpanded((open) => !open)}
          theme={theme}
          onToggleTheme={toggleTheme}
        />
      )}

      <div className="workspace" {...{ [BEHIND_COVER]: "" }}>
        {!room && <header className="topbar" data-design-system="app" data-selection="chrome" aria-label={shellTopbarAria()}>
          <div className="mobile-brand" aria-hidden="true">
            <span className="brand-mark"><BrandMark /></span>
          </div>

          {/* A landmark, not a div: `aria-label` on a plain div is prohibited
              ARIA (axe `aria-prohibited-attr`) — a generic element
              has no role for the name to hang on, so readers dropped it. The
              breadcrumb is the APG's navigation landmark, distinguished from
              the rail's "Primary" by its own name. */}
          <nav className="route-breadcrumb" aria-label={shellBreadcrumbAria()}>
            <span aria-current={headerDetail ? undefined : "page"}>{routeLabel}</span>
            {headerDetail && (
              <>
                <span className="route-slash" aria-hidden="true">/</span>
                <strong aria-current="page">{headerDetail}</strong>
              </>
            )}
          </nav>

          {/* One topbar on every route: breadcrumb, telemetry, sync, bell.
              The board's search lives in the board's own toolbar (the
              settings idiom — search leads the screen it filters); what stays
              in chrome is the one genuinely global instrument, the palette. */}
          <div className="route-spacer" />
          <button
            className="tb-cmdk"
            onClick={() => setPaletteOpen(true)}
            aria-label={shellPaletteOpenAria()}
            title={shellPaletteOpenTitle()}
          >
            <span data-copy="glyph">⌘ K</span>
          </button>

          {/* `group`, for the same reason as the breadcrumb: the name needs a
              role to be announced on. */}
          <div className="top-stats" role="group" aria-label={shellStatsAria()}>
            {/* The count IS the way back to the board it counts, so no chip
                in this strip of lenses and links is inert. `/` with no query
                is the open board by definition, which is why the mode lives in
                `?show=`. The lenses do not, so the link takes them off itself. */}
            <StatChip
              kind="link"
              to="/"
              active={boardView === "open"}
              onClick={clearLenses}
              n={stats?.open_total ?? "—"}
              label={shellStatOpen()}
              ariaLabel={stats ? shellStatOpenAria({ count: stats.open_total }) : shellStatOpenAriaUnknown()}
              title={shellStatOpenTitle()}
            />
            <StatChip
              kind="lens"
              good
              n={stats?.new_today ?? "—"}
              label={shellStatNew()}
              onClick={showNewSignals}
              pressed={boardView === "new"}
              ariaLabel={shellStatNewAria({ count: stats?.new_today ?? shellStatUnknown() })}
              title={shellStatNewTitle()}
            />
            {(stats?.reposted_today ?? 0) > 0 && (
              <StatChip
                kind="lens"
                n={stats?.reposted_today ?? "—"}
                label={shellStatReposted()}
                onClick={showReposts}
                pressed={boardView === "reposted"}
                ariaLabel={shellStatRepostedAria({ count: stats?.reposted_today ?? 0 })}
                title={shellStatRepostedTitle()}
              />
            )}
            <StatChip
              kind="link"
              to="/favorites"
              n={stats?.saved_total ?? "—"}
              label={shellStatSaved()}
              ariaLabel={stats ? shellStatSavedAria({ count: stats.saved_total }) : shellStatSavedAriaUnknown()}
              title={shellStatSavedTitle()}
            />
            <CompareChip />
            <ModelSwitchChip />
            <CompareSaveAlert />
          </div>

          <FreshnessBadge />
          <SyncButton />
          <NotificationBell />
        </header>}

        <div className="body" id="main-content" tabIndex={-1}>
          {!holding && (<>
          {/* One boundary for every lazy screen. It is announced,
              because a route chunk arriving over a slow link is exactly when a
              screen reader is told nothing at all — and it reuses the app's one
              load state rather than inventing a router-shaped spinner. */}
          <ErrorBoundary
            /* Keyed on the path so navigating away clears a stuck boundary:
               without it, one dead chunk would blank every later route too.
               An entity section keeps one key across its picks (boundaryKey). */
            key={boundaryKey}
            onError={(error, info) => recordClientError(error, "route", info.componentStack)}
            fallback={(error) => (
              <ResourceLoadState error={error} loading={shellLoadingPage()} failed={shellLoadPageFailed()} onRetry={reloadDocument} />
            )}
          >
          <Suspense fallback={<ResourceLoadState error={null} loading={shellLoadingPage()} failed={shellLoadPageFailed()} />}>
            <RoutedScreens location={routedLocation} />
          </Suspense>
          </ErrorBoundary>
          </>)}
        </div>
      </div>

      {/* In-app navigation: a cover — a role, or the comparison — floats over the
          preserved background page. Which slot a route renders in decides its
          shell: here it is a modal dialog, above it is the page. */}
      {backgroundLocation && (
        <ErrorBoundary
          key={`overlay:${positionKey(location.pathname) ?? location.pathname}`}
          onError={(error, info) => recordClientError(error, "overlay", info.componentStack)}
          fallback={(error) => (
            <ResourceLoadState error={error} loading={shellLoadingRole()} failed={shellLoadRoleFailed()} onRetry={reloadDocument} />
          )}
        >
        <Suspense fallback={<ResourceLoadState error={null} loading={shellLoadingPage()} failed={shellLoadPageFailed()} />}>
          <Routes>
            <Route path={POSITION_ROUTE} element={<PositionRoute asOverlay />} />
            <Route path="/job/:id" element={<PositionRoute asOverlay />} />
            <Route path="/compare" element={<CompareRoute asOverlay />} />
          </Routes>
        </Suspense>
        </ErrorBoundary>
      )}

      <CommandPalette
        open={paletteOpen && !muted}
        onClose={() => setPaletteOpen(false)}
        theme={theme}
        onToggleTheme={toggleTheme}
        onShowShortcuts={() => setShortcutsOpen(true)}
      />

      {shortcutsOpen && (
        <ErrorBoundary
          onError={(error, info) => recordClientError(error, "overlay", info.componentStack)}
          fallback={() => null}
        >
          <Suspense fallback={null}>
            <KeyboardShortcuts onClose={() => setShortcutsOpen(false)} />
          </Suspense>
        </ErrorBoundary>
      )}

      {mayAskSharing && sharingState && !muted && !location.pathname.startsWith("/welcome") && (
        <ErrorBoundary
          onError={(error, info) => recordClientError(error, "overlay", info.componentStack)}
          fallback={() => null}
        >
          <Suspense fallback={null}>
            <UsageConsentGate state={sharingState} onAnswered={answeredSharing} />
          </Suspense>
        </ErrorBoundary>
      )}
    </div>
  );
}

/* Lazy: the sheet is read on demand, so its list and styles stay out of the
   startup chunk; only this loader and the "?" branch above are shell. The
   command palette stays eager on purpose: loaded on Cmd-K, the keys typed
   before its input mounts are lost ("api product" arrives as "product";
   palette.spec.ts holds this). */
const KeyboardShortcuts = lazy(() =>
  import("./shell/KeyboardShortcuts").then((m) => ({ default: m.KeyboardShortcuts })),
);

export default function App() {
  return (
    <ScreenProvider>
      <ToastProvider>
        <AppProviders>
          <CopyBoundary>
            <Shell />
          </CopyBoundary>
        </AppProviders>
      </ToastProvider>
    </ScreenProvider>
  );
}
