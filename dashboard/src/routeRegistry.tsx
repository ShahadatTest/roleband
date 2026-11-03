import { createElement, lazy } from "react";
import type { ComponentProps, ComponentType } from "react";
import { COMPARE_ROUTE, positionKey } from "./routing/paths";

/**
 * Route COMPONENTS, one lazy chunk per screen.
 *
 * Imported eagerly by the route table, every screen and all of its CSS would be
 * evaluated before the Board rendered a single row. Only the screen a launch
 * opens on is fetched before the first render (`preloadRoute`); the rest follow
 * once it has drawn (`preloadScreens`).
 *
 * The bundler names each chunk after the module it loads, so the build report reads
 * as a list of screens.
 */

/** A lazy screen that can be fetched ahead of its route. Once fetched it
    renders straight away: React.lazy would still suspend on its first render,
    and React holds a fallback it has shown for a moment, so a screen already
    in hand would open on a load state. */
/** React.lazy's own bound: a component of any props. */
type AnyComponent = ComponentType<any>;

export type Screen<T extends AnyComponent = ComponentType> = ComponentType<ComponentProps<T>> & {
  load: () => Promise<{ default: T }>;
  preload: () => void;
};

export function preloadable<T extends AnyComponent>(factory: () => Promise<{ default: T }>): Screen<T> {
  let loaded: T | null = null;
  let loading: Promise<{ default: T }> | null = null;
  const load = () => (loading ??= factory().then((module) => {
    loaded = module.default;
    return module;
  }));
  const Lazy = lazy(load);
  const Shown = (props: ComponentProps<T>) => createElement(loaded ?? Lazy, props);
  // A fetch that fails ahead of its route is reported when the route renders:
  // the lazy rethrows it to the route's error boundary.
  return Object.assign(Shown, { load, preload: () => { load().catch(() => undefined); } });
}

const ProfileScreen = preloadable(() => import("./routes/ProfileRoute").then((m) => ({ default: m.ProfileRoute })));

/** Fetch Profile's screen ahead of its route: the welcome leads into its walk. */
export const preloadProfile = (): void => ProfileScreen.preload();

/** Keyed by the `path` in `navigation.ts`. Both are checked against each other
 *  by `route-registry.test.ts`: a tab with no loader is a blank screen, and a
 *  loader with no tab is a chunk nothing can reach. */
export const ROUTE_COMPONENTS: Record<string, Screen> = {
  "/": preloadable(() =>
    import("./routes/BoardRoute").then((m) => ({ default: m.BoardRoute })),
  ),
  "/favorites": preloadable(() =>
    import("./features/saved/SavedScreen").then((m) => ({ default: m.SavedScreen })),
  ),
  "/profile": ProfileScreen,
  "/statistics": preloadable(() =>
    import("./routes/StatisticsRoute").then((m) => ({ default: m.StatisticsRoute })),
  ),
  "/company": preloadable(() =>
    import("./features/company-profiles/CompanyProfilesView").then((m) => ({
      default: m.CompanyProfilesView,
    })),
  ),
  "/review": preloadable(() => import("./routes/ReviewRoute").then((m) => ({ default: m.ReviewRoute }))),
  "/notifications": preloadable(() =>
    import("./features/notifications/NotificationScreen").then((m) => ({
      default: m.NotificationScreen,
    })),
  ),
  "/settings": preloadable(() => import("./routes/SettingsRoute").then((m) => ({ default: m.SettingsRoute }))),
};

/** The two routes outside the tab table. The position overlay is lazy too — it
 *  is the largest single screen (comp panels, requirements, lineage, twins) and
 *  it opens over a page that is already painted, so its chunk arrives during a
 *  transition the reader is already watching. */
export const WelcomeRoute = preloadable(() =>
  import("./features/scope/Welcome").then((m) => ({ default: m.Welcome })),
);

export const PositionRoute = preloadable(() =>
  import("./routes/JobRoute").then((m) => ({ default: m.JobRoute })),
);

/** The comparison cover. Like the position overlay it is not in the
 *  tab table: it opens OVER the list the roles were picked on, and by URL it
 *  is a standalone page — the same two shells Job detail has. */
export const CompareRoute = preloadable(() =>
  import("./routes/CompareRoute").then((m) => ({ default: m.CompareRoute })),
);

/** One plugin's settings (`/settings/plugins/:pluginId`): the same Settings
 *  screen and chunk, mounted on the two-segment address it reads. */
export const SettingsItemRoute = ROUTE_COMPONENTS["/settings"];

/** The screen a launch at `pathname` opens on, fetched before the first render
 *  so its code arrives while the app reads names, language and setup. */
export function preloadRoute(pathname: string): void {
  if (positionKey(pathname)) return PositionRoute.preload();
  if (pathname === COMPARE_ROUTE) return CompareRoute.preload();
  const path = Object.keys(ROUTE_COMPONENTS).find((tab) =>
    tab === "/" ? pathname === "/" : pathname === tab || pathname.startsWith(`${tab}/`),
  );
  if (path) ROUTE_COMPONENTS[path].preload();
}

/** Every screen a configured install reaches, fetched one after another once
 *  the first screen has drawn, so a tab or a cover opens on itself and asks for
 *  its data at once. One at a time, so each module's evaluation is its own
 *  task and the screen on show keeps the main thread between them. */
export async function preloadScreens(): Promise<void> {
  for (const screen of [...Object.values(ROUTE_COMPONENTS), PositionRoute, CompareRoute]) {
    await screen.load().catch(() => undefined);
  }
}
