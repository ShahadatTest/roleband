import { mockApi, mockGet } from "./fixtures";
/* The board's route harness and the two extra opportunities every board spec
   needs. Every board spec installs the same routes from here, so their setup
   cannot drift apart.

   installBoardRoutes is a FUNCTION, not a fixture object, because the routes
   are per-page side effects: a shared object would be global mutable state. */

import type { Page } from "@playwright/test";
import { facetsFixture, jobFixture, jobListFixture, notificationsFixture, statsFixture, statusFixture, syncStartedFixture } from "../../src/test/fixtures";

// A second opportunity so tests can prove each has its own stable URL.
export const jobFixture2 = {
  ...jobFixture,
  id: 202,
  title: "Principal Engineer, Platform",
  url: "https://example.test/jobs/202",
  description_text: "Own core platform reliability.",
  comp_low: 900000,
  comp_high: 1100000,
  comp_median: 1000000,
};

export const twoJobList = { ...jobListFixture, total: 2, items: [jobFixture, jobFixture2] };

/** 40 rows — enough to scroll the page deeply at any tested viewport. */
export const deepList = {
  ...jobListFixture,
  total: 40,
  ranked_by: "intent",
  items: Array.from({ length: 40 }, (_, i) => ({
    ...jobFixture,
    id: 1000 + i,
    title: `Row ${i} Principal Product Manager`,
  })),
};

export const appleJobFixture = {
  ...jobFixture,
  id: 303,
  company: "apple",
  title: "Head of Product, Global AI Learning Platform",
  url: "https://jobs.apple.com/en-us/details/200646926/head-of-product-global-ai-learning-platform",
  description_text: "Legacy fallback should not replace structured sections.",
  description_sections: [
    { key: "summary", title: "Summary", content: "Lead Apple's global AI learning platform." },
    {
      key: "minimum_qualifications",
      title: "Minimum Qualifications",
      content: "10+ years of product management experience\n5+ years in senior leadership",
    },
    {
      key: "pay_and_benefits",
      title: "Pay & Benefits",
      content: "The base pay range for this role is between $250,800 and $376,300.",
    },
  ],
};

/* The opportunity detail, in EITHER of its two shells. Opened from a list it
   covers a page that is still mounted, so it is a modal `dialog`;
   reached by a direct link or a refresh it is the page itself, so it stays a
   named `region`. Same content, and which one is showing is exactly what the
   specs below assert on. */
export const detail = (page: Page) =>
  page.getByRole("dialog", { name: /^Role:/ })
    .or(page.getByRole("main", { name: /^Role:/ }));

/* The comparison, in EITHER of its two shells: a modal `dialog`
   opened over a list, the page's `main` by direct link or refresh. Exact:
   the description panels inside are regions whose names contain the word. */
export const comparison = (page: Page) =>
  page.getByRole("dialog", { name: "Comparison", exact: true })
    .or(page.getByRole("main", { name: "Comparison", exact: true }));

/** Secondary detail reads are shared by board, notification and search entry points. */
export async function installJobDetailRoutes(page: Page) {
  await mockGet(page, "/api/jobs/*/similar**", (route) => route.fulfill({ json: { scope: "cross", items: [] } }));
  await mockGet(page, "/api/jobs/*/twins", (route) => route.fulfill({ json: {
    job_id: Number(new URL(route.request().url()).pathname.split("/")[3]),
    size: 1, direct_count: 0, members: [],
  } }));
  // A posting in no place set; a spec about one routes its own.
  await mockGet(page, "/api/jobs/*/place-set", (route) => route.fulfill({ json: {
    job_id: Number(new URL(route.request().url()).pathname.split("/")[3]),
    place_set: null, rejected: false, rejected_at: null,
  } }));
  await mockApi(page, "POST", "/api/jobs/*/view", (route) => route.fulfill({ json: {
    job_id: Number(new URL(route.request().url()).pathname.split("/")[3]),
    viewed_at: "2026-09-08T12:00:00Z",
  } }));
  await mockGet(page, "/api/companies/*/card", (route) => {
    const slug = new URL(route.request().url()).pathname.split("/")[3];
    return route.fulfill({ json: {
      slug, display_name: slug, logo_url: null, brand_color: null,
      ticker: null, is_public: false, has_profile: false, open_roles: 1,
      top_cities: ["San Francisco"], price: null, change_pct: null,
      currency: null, price_as_of: null,
    } });
  });
}

export async function installBoardRoutes(page: Page) {
  await installJobDetailRoutes(page);
  // Saved reads the pursuits for each tracked role's stage; none by default.
  await page.route("/api/pursuits**", (route) => route.fulfill({ json: { pursuits: [] } }));
  // The compare selection is server state, so the harness has to be
  // a STORE and not a canned response: a reload asks for it again, and a route
  // that always answers empty would report the persistence bug as fixed while
  // reproducing it exactly. One route for both verbs, because the PUT's reply
  // IS the new state.
  let compareSelection: number[] = [];
  await mockApi(page, ["GET", "PUT"], "/api/compare-selection", async (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as { job_ids: number[] };
      // Clamped like the store: COMPARE_CAP is 3, and a harness
      // that stored more would let a spec pass on a selection the API refuses.
      compareSelection = body.job_ids.slice(0, 3);
    }
    await route.fulfill({ json: { job_ids: compareSelection } });
  });
  await mockGet(page, "/api/profile", (route) => route.fulfill({ json: {
    profile: null, scope_configured: true,
  } }));
  await mockGet(page, "/api/stats", (route) => route.fulfill({ json: statsFixture }));
  await mockGet(page, "/api/status", (route) => route.fulfill({ json: statusFixture }));
  await mockApi(page, "POST", "/api/sync", (route) => route.fulfill({ json: syncStartedFixture }));
  await mockGet(page, "/api/facets", (route) => route.fulfill({ json: facetsFixture }));
  await mockGet(page, "/api/notifications**", (route) => route.fulfill({ json: notificationsFixture }));
  await mockGet(page, "/api/jobs/101", (route) => route.fulfill({ json: jobFixture }));
  await mockGet(page, "/api/jobs/202", (route) => route.fulfill({ json: jobFixture2 }));
  await mockGet(page, "/api/jobs/303", (route) => route.fulfill({ json: appleJobFixture }));
  await mockGet(page, "/api/jobs?**", (route) => route.fulfill({ json: twoJobList }));
}
