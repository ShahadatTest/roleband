import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import * as shell from "../copy/gen/shell";
import { NAV_TABS } from "../navigation";
import { ROUTE_COMPONENTS } from "../routeRegistry";

/* Every tab of the rail wears ONE page header, titled by its rail label, so
 * the title never jumps or vanishes on a tab switch. The geometry is pinned
 * in the browser (`tests/ux/page-header.spec.ts`). A new tab lands here
 * unlisted and fails by name.
 */

const src = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (path: string) => readFileSync(join(src, path), "utf8");

/** The file that renders each tab's page header. */
const PAGE_HEADER: Record<string, string> = {
  "/": "features/opportunities/BoardScreen.tsx",
  "/favorites": "features/saved/SavedScreen.tsx",
  "/profile": "features/scope/ProfileView.tsx",
  "/statistics": "features/statistics/StatisticsView.tsx",
  "/company": "features/company-profiles/CompanyProfilesView.tsx",
  "/review": "routes/ReviewRoute.tsx",
  "/notifications": "features/notifications/NotificationScreen.tsx",
  "/settings": "routes/SettingsRoute.tsx",
};

describe("PageHeader adoption", () => {
  it("accounts for every tab in the route table, and only those", () => {
    expect(Object.keys(PAGE_HEADER).sort()).toEqual(Object.keys(ROUTE_COMPONENTS).sort());
  });

  it.each(Object.entries(PAGE_HEADER))("%s renders the shared page header, titled by its rail label", (path, file) => {
    const source = read(file);
    const label = NAV_TABS.find((tab) => tab.path === path)!.label;
    expect(source).toMatch(/from ["'][^"']*patterns\/PageHeader["']/);
    // Titled by the rail's own label: the literal, or the nav message that
    // says the same words (the copy catalog).
    const named = source.match(/<PageHeader title=\{(shellNav\w+)\(\)\}/)?.[1];
    if (named) expect((shell as unknown as Record<string, () => string>)[named](), file).toBe(label);
    else expect(source).toContain(`<PageHeader title="${label}"`);
    // No second head of its own, and no title only a screen reader could see.
    expect(source).not.toMatch(/settings-head|<h1 className="sr-only"/);
  });
});
