import {
  shellNavRadar,
  shellNavSaved,
  shellNavProfile,
  shellNavInsights,
  shellNavCompanies,
  shellNavDuplicates,
  shellNavNotifications,
  shellNavSettings,
} from "./copy/gen/shell";
import type { IconName } from "./ui/Icon";
// Sub-tab constants live in a leaf module (navTabs) so section components can
// import them without forming a cycle.
import { PROFILE_TABS, SETTINGS_TABS, STATISTICS_TABS, SubTabDef } from "./navTabs";

export type { SubTabDef };

/**
 * Navigation METADATA — paths, labels, icons, sub-tabs. No components, no JSX,
 * no feature imports.
 *
 * This module and `routeRegistry.tsx` are two files because one file would
 * make a visit to any route evaluate every screen in the product: the rail,
 * the breadcrumb and the command palette all need the labels, so importing
 * the labels would import the elements, and importing the elements every
 * feature and its CSS. Nothing here reaches a screen, so the three chrome
 * consumers cost nothing but this table.
 */
export interface NavTabDef {
  path: string;
  label: string;
  icon: IconName;
  /** Exact-match the path (the Board owns "/", which prefixes everything). */
  end?: boolean;
  /** Multi-view sections declare their path sub-tabs here so the router, the
   *  section shell, the breadcrumb and the palette derive from one list. */
  tabs?: SubTabDef[];
  /** Default sub-tab a section index (`/statistics`) redirects to. */
  indexRedirect?: string;
  /** Entity sections mount `${path}/:<entityParam>?`, one route with an
   *  optional segment (e.g. company -> `/company/:slug?`), preserving deep links
   *  without remounting the screen when a pick adds the segment. */
  entityParam?: string;
}

// Single source of truth for navigation. The header, the rail, the palette and
// the router all derive from this list, so adding a tab is a line here plus a
// loader in routeRegistry.tsx.
//
// A rail entry is a PLACE with standing content — a list, a queue with a
// backlog, settings. A view of something chosen elsewhere (one role, a
// selection) is a cover opened from where the choosing happens, and is not
// listed: a Compare entry would advertise an empty room (docs/ui.md "Cover").
export const NAV_TABS: NavTabDef[] = [
  { path: "/", get label() { return shellNavRadar(); }, icon: "grid", end: true },
  { path: "/favorites", get label() { return shellNavSaved(); }, icon: "star" },
  { path: "/profile", get label() { return shellNavProfile(); }, icon: "person", tabs: PROFILE_TABS, indexRedirect: "direction" },
  {
    path: "/statistics",
    get label() { return shellNavInsights(); },
    icon: "chart",
    tabs: STATISTICS_TABS,
    indexRedirect: "overview",
  },
  { path: "/company", get label() { return shellNavCompanies(); }, icon: "building", entityParam: "slug" },
  { path: "/review", get label() { return shellNavDuplicates(); }, icon: "files" },
  { path: "/notifications", get label() { return shellNavNotifications(); }, icon: "bell" },
  {
    path: "/settings",
    get label() { return shellNavSettings(); },
    icon: "gear",
    tabs: SETTINGS_TABS,
    indexRedirect: "companies",
  },
];
