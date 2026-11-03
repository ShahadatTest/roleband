import type { Page } from "./fixtures";
import { installBoardRoutes } from "./boardHarness";
import { overviewFixture } from "../../src/test/fixtures";
import { companyDiscovery, companyOpenCounts } from "./settingsHarness";
import { companyList, scopeCatalog, scopePreview } from "./scopeFixtures";

/* Enough of the API for every tab of the rail to render its whole chrome,
   answered from fixtures. Shared by the sweeps that visit every route
   (`a11y.spec.ts`, `page-header.spec.ts`). */
export async function installEveryRoute(page: Page) {
  await page.route("/api/profile", (route) => route.fulfill({
    json: { profile: null, scope_configured: true },
  }));
  await page.route("/api/companies/discovery", (route) =>
    route.fulfill({ json: companyDiscovery }));
  await page.route("/api/companies/open-counts", (route) =>
    route.fulfill({ json: companyOpenCounts }));
  await page.route("/api/companies/directory/status", (route) =>
    route.fulfill({ json: { size: 0, following: false, since: null, checked: 0, to_check: 0, with_roles: 0, waiting_for_power: false } }));
  await page.route("/api/companies",(route) => route.fulfill({ json: companyList }));
  await page.route("/api/scope/catalog", (route) => route.fulfill({ json: scopeCatalog }));
  await page.route("/api/scope/preview", (route) => route.fulfill({ json: scopePreview }));
  await page.route("/api/scope/rules", (route) => route.fulfill({ json: { rules: [] } }));
  await page.route("/api/profile/suggestions", (route) =>
    route.fulfill({ json: { suggestions: [] } }));
  await page.route("/api/statistics/overview**", (route) =>
    route.fulfill({ json: overviewFixture }));
  /* These two are answered EMPTY rather than populated, deliberately. Their
     rich fixtures live inside `companies.spec.ts` and `review.spec.ts`, and the
     lineage one is a function of the query string — extracting that to dress a
     floor-level scan is out of proportion. An empty queue still renders the
     route's whole chrome, and the proof-of-life assertion at the bottom is what
     stops an empty page from passing by having nothing to check. */
  await page.route("/api/company-profiles**", (route) => route.fulfill({
    json: { attribution: null, items: [] },
  }));
  await page.route("/api/lineage/review**", (route) =>
    route.fulfill({ json: { total: 0, limit: 50, offset: 0, items: [] } }));
  /* Second-order: /review only asks for twins once lineage has answered, so no
     amount of listing the FIRST wave of requests finds this one. The guard
     does, because it fails on the call rather than on a list. */
  await page.route("/api/twins/review**", (route) =>
    route.fulfill({ json: { total: 0, limit: 50, offset: 0, items: [] } }));
  await page.route("/api/sync/targets", (route) =>
    route.fulfill({ json: { companies: [], freshness_max_hours: 24 } }));
  await installBoardRoutes(page);
}
