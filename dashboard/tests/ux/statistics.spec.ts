import type { Locator, Page } from "@playwright/test";
import type { ClusterDetail, ClusterList } from "../../src/api";
import { expect, test } from "./fixtures";
import {
  companyCardFixture,
  facetsFixture,
  hiringFixture,
  jobFixture,
  jobListFixture,
  levelGuideFixture,
  notificationsFixture,
  overviewFixture,
  statsFixture,
  statusFixture,
} from "../../src/test/fixtures";
import { msg } from "../../src/test/msg";
import { installJobDetailRoutes } from "./boardHarness";
import { showAdvancedInsights } from "./insightsView";

// The Statistics sub-tab lives in the path (`/statistics/:tab`) and the period in
// `?window=`, so the whole view is deep-linkable and shareable. These specs pin
// that: direct links, index redirect, push-on-tab, replace-on-window, invalid
// fallback, and reload persistence.

const velocityFixture = {
  days: 30,
  kpis: {
    open_total: 12, opened: 5, updated: 3, closed: 1, net: 4, reposted: 0, first_scan: 0,
    median_days_open: 20, employer_dated_share: 0.5,
    median_observed_listing_duration_days: null, closed_sample: 1, closed_employer_dated_share: 1,
  },
  aging: [{ lo: 0, hi: 30, label: "0–30d", count: 8 }],
  posted: [{ lo: 0, hi: 30, label: "0–30d", count: 1 }],
  by_company: [
    { company: "google", open: 6, opened: 3, updated: 2, closed: 1, median_days_open: 18, median_observed_listing_duration_days: null },
  ],
};

test.beforeEach(async ({ page }) => {
  await showAdvancedInsights(page);
  await page.route("/api/profile", (route) => route.fulfill({ json: {
    profile: null, scope_configured: true,
  } }));
  await page.route("/api/stats", (route) => route.fulfill({ json: statsFixture }));
  await page.route("/api/status", (route) => route.fulfill({ json: statusFixture }));
  await page.route("/api/facets", (route) => route.fulfill({ json: facetsFixture }));
  await page.route("/api/notifications**", (route) => route.fulfill({ json: notificationsFixture }));
  await page.route("/api/jobs/101", (route) => route.fulfill({ json: jobFixture }));
  await page.route("/api/jobs/*/similar**", (route) => route.fulfill({ json: { scope: "cross", items: [] } }));
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: jobListFixture }));
  await page.route("/api/statistics/overview**", (route) => route.fulfill({ json: overviewFixture }));
  await page.route("/api/statistics/velocity**", (route) => route.fulfill({ json: velocityFixture }));
});

test("a direct link to a sub-tab renders it selected, with the breadcrumb", async ({ page }) => {
  await page.goto("/statistics/velocity");

  await expect(page).toHaveURL(/\/statistics\/velocity$/);
  await expect(page.getByRole("tab", { name: "Pace" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { level: 2, name: "5 opened" })).toBeVisible();
  // The breadcrumb's second segment is derived from the route, not pushed imperatively.
  await expect(page.getByRole("banner", { name: "Application navigation" })).toContainText("Insights/Pace");
});

test("Pace's age bands name their clock and the share the employer dated", async ({ page, isMobile }) => {
  await page.goto("/statistics/velocity");
  const ages = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Age of open roles" }) });
  const note = ages.locator(".trends-note");
  await expect(note).toHaveText("Counted from when each role was first listed · 50% dated by the employer");
  // One line under the bands, like its neighbour's note, never wrapped to two.
  // A phone's narrow panel wraps any sentence, so the check is desktop's.
  if (isMobile) return;
  expect(await note.evaluate((el) => {
    const range = document.createRange();
    range.selectNodeContents(el);
    return new Set([...range.getClientRects()].map((rect) => Math.round(rect.top))).size;
  })).toBe(1);
});

test("the section index redirects to Overview", async ({ page }) => {
  await page.goto("/statistics");
  await expect(page).toHaveURL(/\/statistics\/overview$/);
  await expect(page.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".insight-hero .eyebrow")).toHaveText("Overview");
});

test("an unknown sub-tab falls back to Overview", async ({ page }) => {
  await page.goto("/statistics/bogus");
  await expect(page).toHaveURL(/\/statistics\/overview$/);
  await expect(page.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
});

test("switching tabs pushes, so Back returns to the prior tab", async ({ page }) => {
  await page.goto("/statistics/overview");
  await page.getByRole("tab", { name: "Pace" }).click();
  await expect(page).toHaveURL(/\/statistics\/velocity$/);

  await page.goBack();
  await expect(page).toHaveURL(/\/statistics\/overview$/);
  await expect(page.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
});

test("the window lens replaces, so it does not pollute the back button", async ({ page }) => {
  // Establish a real prior page (the board) before entering Statistics, so Back
  // has somewhere to return to.
  await page.goto("/");
  await page.goto("/statistics/overview");
  await expect(page).toHaveURL(/\/statistics\/overview$/);

  const period = page.getByRole("group", { name: "Time range" });
  await period.getByRole("button", { name: "90d" }).click();
  await expect(page).toHaveURL(/window=90/);
  await period.getByRole("button", { name: "7d" }).click();
  await expect(page).toHaveURL(/window=7/);

  // Each window change replaced the entry, so a single Back lands on the board —
  // not on window=90 then window=30.
  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
});

test("a deep link with a window lens survives reload", async ({ page }) => {
  await page.goto("/statistics/overview?window=90");
  await expect(page.getByRole("button", { name: "90d" })).toHaveAttribute("aria-pressed", "true");

  await page.reload();
  await expect(page).toHaveURL(/\/statistics\/overview\?window=90$/);
  await expect(page.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("button", { name: "90d" })).toHaveAttribute("aria-pressed", "true");
});

/* The cluster card is a whole-card control that also carries company chips, and
   a chip is a control of its own — its keyboard path to the company profile is
   the accessible half of a hover card that is otherwise pointer-only.
   One <button> wrapping the chips is invalid HTML, so the card's own control
   stretches over the card and the chips are lifted above it. Both halves need
   a real browser: jsdom has no layout, so a component test can prove there is
   no nesting but not that a click on a chip still reaches the chip. */
const clusterFixture = {
  id: 7,
  // Named by the dashboard from its strongest skills: "LLMs · RAG".
  family_hint: null,
  size: 9,
  top_terms: [{ term: "llm", weight: 42.5 }, { term: "rag", weight: 30.1 }],
};
const clustersFixture = {
  model_version: "v1",
  items: [{ ...clusterFixture, companies: { google: 4 } }],
} satisfies ClusterList;
const clusterDetailFixture = { ...clusterFixture, items: [] } satisfies ClusterDetail;

test.describe("cluster cards", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("/api/clusters", (route) => route.fulfill({ json: clustersFixture }));
    await page.route("/api/clusters/7", (route) =>
      route.fulfill({ json: clusterDetailFixture }));
    await page.route("/api/companies/google/card", (route) =>
      route.fulfill({ json: companyCardFixture }));
    /* The chip NAVIGATES, and the screen it lands on reads its own roster the
       moment its lazy chunk arrives. The test's last assertion is the URL, so
       whether that read lands inside the test is a race, and the fixtures guard
       turns a lost race into "Unmocked API request: GET /api/company-profiles". A spec that sends the user to a
       screen owns that screen's reads. */
    await page.route("/api/company-profiles**", (route) =>
      route.fulfill({ json: { items: [], attribution: null } }));
  });

  /* EVERY TAB FILLS THE PAGE. A tab wrapped in a nested `.main` gets the
     shell's 1200px cap and sits centred inside the page at 1440 while the
     other tabs fill it. */
  test("Groups fills the page between the title's edges, like every Insights tab", async ({ page, isMobile }) => {
    test.skip(isMobile, "a phone has one edge to edge");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/statistics/clusters");
    const title = (await page.getByRole("heading", { level: 1, name: "Insights" }).boundingBox())!;
    // The tab's hero card starts at the title's edge, as on every tab.
    await expect(page.getByRole("heading", { level: 2, name: /role group/ })).toBeVisible();
    const own = (await page.locator(".insight-hero").boundingBox())!;
    expect(Math.abs(own.x - title.x)).toBeLessThan(1);
    await expect(page.getByRole("main")).toHaveCount(1);
  });

  test("a company chip inside a card goes to the company, not into the cluster", async ({ page }) => {
    await page.goto("/statistics/clusters");

    const card = page.getByRole("button", { name: "LLMs · RAG", exact: true });
    await expect(card).toHaveAttribute("aria-pressed", "false");

    // The chip sits inside the card's box, so this click lands on top of the
    // card control's stretched hit area. It must reach the chip: without the
    // chips' own stacking position the card would swallow it, however the
    // controls are nested.
    await page.getByRole("button", { name: msg("shared-company-chip-aria", { company: "Google" }) }).click();

    await expect(page).toHaveURL(/\/company\/google/);
  });

  test("the card itself still selects the cluster, from anywhere in its box", async ({ page }) => {
    await page.goto("/statistics/clusters");

    // A real hit test at a point far from the title: the term row, which is
    // inert content the card control's stretched ::after covers. `page.mouse`
    // rather than a locator click on purpose — a locator click on the term
    // would either be refused as intercepted (which is the correct behaviour
    // being asserted here) or forced, and a forced click dispatches on the
    // element directly, so it would pass with no overlay at all.
    // page.mouse takes VIEWPORT coordinates and does not scroll for you; the
    // card grid sits below the landscape chart, so the box has to be read after
    // the card is on screen.
    await page.locator(".cluster-card").scrollIntoViewIfNeeded();
    const terms = await page.locator(".cluster-terms").boundingBox();
    if (!terms) throw new Error("cluster terms not rendered");
    await page.mouse.click(terms.x + terms.width / 2, terms.y + terms.height / 2);

    await expect(page.getByRole("button", { name: "LLMs · RAG", exact: true }))
      .toHaveAttribute("aria-pressed", "true");
  });

  test("the card control is one keyboard stop, and the chip is another", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name === "mobile", "Tab order is a keyboard flow; a phone has no Tab key.");

    await page.goto("/statistics/clusters");
    const card = page.getByRole("button", { name: "LLMs · RAG", exact: true });
    const chip = page.getByRole("button", { name: msg("shared-company-chip-aria", { company: "Google" }) });

    await card.focus();
    await page.keyboard.press("Tab");
    await expect(chip).toBeFocused();

    // Back the other way, with a real key press: the card control's ring is
    // painted on the CARD (`:has`), and `all: unset` has already thrown away
    // the platform's own outline — so if that rule ever stops matching, the
    // card has no focus indicator at all (2.4.7) and nothing else would say so.
    // Programmatic .focus() cannot prove it: :focus-visible follows the input
    // modality, and only a key press sets it.
    await page.keyboard.press("Shift+Tab");
    await expect(card).toBeFocused();
    // The COMPUTED outline, not `matches(":has(...)")`: the DOM matches that
    // selector whether or not any stylesheet uses it, so such an assertion
    // passes with the rule deleted.
    const ring = await page.evaluate(() => {
      const style = getComputedStyle(document.querySelector(".cluster-card")!);
      return { style: style.outlineStyle, width: style.outlineWidth };
    });
    expect(ring.style, "the focused card paints no ring").not.toBe("none");
    expect(parseFloat(ring.width)).toBeGreaterThan(0);
  });
});

/* Every tab opens with one hero whose eyebrow IS its tab label,
 * one level-2 figure, and two to four KPI tiles; nothing sits above it. */
test("every Insights tab opens with the same hero, named by its tab", async ({ page }) => {
  const summary = (p50: number) => ({ count: 4, min: p50 - 100_000, max: p50 + 200_000, p25: p50 - 50_000, p50, p75: p50 + 50_000, p90: p50 + 150_000 });
  const routes: Record<string, unknown> = {
    "/api/demand": hiringFixture,
    "/api/statistics/compensation**": {
      currency: "USD", min_roles: 5, coverage: { with_comp: 4, total_open: 12, pct: 0.333 }, overall: summary(500_000), histogram: [],
      by_level: [], by_company: [], by_family: [], by_skill: [],
      disclosed: { bands: [], reqs: 0, companies: 0, excluded: { unclear: 0, total: 0, not_usd: 0, not_yearly: 0, implausible: 0 }, truncated: false },
      disclosure: { overall: { open: 12, checked: 0, disclosed: 0, rate: null }, by_company: [], by_level: [] },
      base_estimates: { min_roles: 5, coverage: { with_base: 0, total_open: 12 }, overall: null, by_level: [], by_company: [], by_family: [] },
    },
    "/api/statistics/comp-trends**": { dim: "overall", days: 30, dates: [], series: [] },
    "/api/statistics/disclosure-trends**": { dim: "overall", days: 30, basis: "base", dates: [], series: [], cohort: null },
    "/api/statistics/comp-trajectory": {
      currency: "USD", assumptions: { bonus_pct: 0.12, equity_by_band: { senior: 0.35 } },
      overall: { count: 3, median_tc: 600_000, base: 300_000, bonus: 60_000, equity: 240_000, equity_pct: 0.4, split_source: "measured" },
      public: [{ company: "google", ticker: "GOOGL", equity_vehicle: "rsu", split_source: "measured", count: 3, median_tc: 600_000, base: 300_000, bonus: 60_000, equity: 240_000, equity_pct: 0.4 }],
      private: [],
    },
    "/api/skills/top**": {
      items: [
        { term: "python", category: "language", job_count: 9, share: 0.3, market_share: 0.3, lift: 1, distinctiveness: 0 },
        { term: "sql", category: "language", job_count: 5, share: 0.17, market_share: 0.17, lift: 1, distinctiveness: 0 },
      ],
      competencies: [], roles: 30, market_roles: 30, narrowed: false,
    },
    "/api/skills/trends**": { days: 30, dates: ["2026-07-12", "2026-07-13"], set_changes: [], series: [
      { term: "python", current: 9, delta: 1, current_share: 0.09, share_delta: 0.01,
        points: [{ date: "2026-07-12", job_count: 8, share: 0.08 }, { date: "2026-07-13", job_count: 9, share: 0.09 }] },
    ] },
    "/api/skills/overlap**": { min_jobs: 2, companies: [
      { company: "google", skill_count: 9, open: 12 }, { company: "openai", skill_count: 7, open: 5 },
    ], pairs: [{ a: "google", b: "openai", shared: 4, union: 12, similarity: 0.333, top_shared: ["Python"] }] },
    "/api/statistics/levels": levelGuideFixture,
    "/api/companies/discovery": { sectors: [], companies: [] },
    "/api/settings": { enabled_role_tracks: [] },
    "/api/clusters": { model_version: "t", items: [
      { id: 1, family_hint: "product_management", size: 7, top_terms: [], companies: { google: 7 } },
    ] },
  };
  for (const [pattern, json] of Object.entries(routes)) {
    await page.route(pattern, (route) => route.fulfill({ json }));
  }

  for (const tab of ["Overview", "Hiring", "Pace", "Compensation", "Levels", "Stock", "Skills", "Trends", "Overlap", "Groups"]) {
    await page.goto("/statistics/overview");
    await page.getByRole("tab", { name: tab, exact: true }).click();
    const hero = page.locator(".insight-hero");
    await expect(hero, tab).toHaveCount(1);
    await expect(hero.locator(".eyebrow"), tab).toHaveText(tab);
    await expect(hero.getByRole("heading", { level: 2 }), tab).toHaveCount(1);
    const tiles = await hero.locator(".kpi").count();
    expect(tiles, tab).toBeGreaterThanOrEqual(2);
    expect(tiles, tab).toBeLessThanOrEqual(4);
    // Nothing above it: the hero is the panel's first card.
    const first = await page.locator("#statistics-tabpanel .panel").first().evaluate((el) => el.classList.contains("insight-hero"));
    expect(first, tab).toBe(true);
  }
});

/* Levels is a long reference table: its toolbar and column heads stay in view
 * while the rows scroll under them, and a searched code translates. */
test("Levels keeps its search and column heads in view, and translates a searched code", async ({ page }) => {
  await page.route("/api/statistics/levels", (route) => route.fulfill({ json: levelGuideFixture }));
  await page.route("/api/companies/discovery", (route) => route.fulfill({ json: { sectors: [], companies: [] } }));
  await page.route("/api/settings", (route) => route.fulfill({ json: { enabled_role_tracks: [] } }));
  await page.setViewportSize({ width: 1440, height: 520 });
  await page.goto("/statistics/levels");

  const search = page.getByRole("searchbox", { name: "Company or level" });
  await search.fill("ICT4");
  await expect(page.getByRole("status").filter({ hasText: "Translating Apple ICT4 (Senior)" })).toBeVisible();
  await expect(page).toHaveURL(/[?&]q=ICT4/);

  // The table scrolls inside the app; the page itself never grows past the
  // window, or a scroll anywhere would slide the whole app up.
  expect(await page.evaluate(() => document.scrollingElement!.scrollHeight)).toBeLessThanOrEqual(520);
  // Scroll the app's own area, as a wheel or a swipe over the table does; a
  // wheel event does not exist on a touch device.
  await page.locator("main").evaluate((el) => el.scrollBy(0, 2000));
  await expect.poll(() => page.locator("main").evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
  const head = page.getByRole("columnheader", { name: "Senior, translating" });
  await expect(search).toBeInViewport();
  await expect(head).toBeInViewport();
  // The heads sit under the toolbar, never behind it.
  const toolbar = await page.locator(".levels-toolbar").boundingBox();
  const cell = await head.boundingBox();
  expect(cell!.y).toBeGreaterThanOrEqual(toolbar!.y + toolbar!.height - 1);
});

/* One scope bar narrows every tab but Stock, and it travels with the
 * reader from tab to tab in the address, as the window does. */
test("a scope chosen on one tab narrows the next tab's request too", async ({ page }) => {
  await page.goto("/statistics/overview");
  const overview = page.waitForRequest((r) => r.url().includes("/api/statistics/overview") && r.url().includes("side=other"));
  await page.getByRole("group", { name: "Companies" }).getByRole("button", { name: "Other companies" }).click();
  await overview;

  const pace = page.waitForRequest((r) => r.url().includes("/api/statistics/velocity") && r.url().includes("side=other"));
  await page.getByRole("tab", { name: "Pace", exact: true }).click();
  await pace;
  await expect(page).toHaveURL(/\/statistics\/velocity\?.*side=other/);
  await expect(page.getByRole("button", { name: "Other companies" })).toHaveAttribute("aria-pressed", "true");
});

/* A panel opened again paints the answer it last had while it asks again, so
 * coming back to a tab never shows a spinner for something already seen. The
 * second read is held until the panel has been checked: what shows meanwhile
 * can only be the kept answer. */
test.describe("a tab opened again", () => {
  async function holdPace(page: Page) {
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    const asked: string[] = [];
    await page.route("/api/statistics/velocity**", async (route) => {
      asked.push(route.request().url());
      await held;
      await route.fulfill({ json: { ...velocityFixture, kpis: { ...velocityFixture.kpis, opened: 6 } } });
    });
    return { asked, release };
  }

  test("paints its last answer from another tab, then the fresh one", async ({ page }) => {
    await page.goto("/statistics/velocity");
    await expect(page.getByRole("heading", { level: 2, name: "5 opened" })).toBeVisible();
    await page.getByRole("tab", { name: "Overview" }).click();
    await expect(page.locator(".insight-hero .eyebrow")).toHaveText("Overview");

    const pace = await holdPace(page);
    await page.getByRole("tab", { name: "Pace" }).click();
    await expect(page.getByRole("heading", { level: 2, name: "5 opened" })).toBeVisible();
    await expect.poll(() => pace.asked.length).toBeGreaterThan(0);

    pace.release();
    await expect(page.getByRole("heading", { level: 2, name: "6 opened" })).toBeVisible();
  });

  test("paints its last answer after a visit to another screen", async ({ page }) => {
    await page.goto("/statistics/velocity");
    await expect(page.getByRole("heading", { level: 2, name: "5 opened" })).toBeVisible();
    await page.getByRole("link", { name: "Radar", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Radar", level: 1 })).toBeVisible();

    const pace = await holdPace(page);
    await page.goBack();
    await expect(page.getByRole("heading", { level: 2, name: "5 opened" })).toBeVisible();
    await expect.poll(() => pace.asked.length).toBeGreaterThan(0);
    pace.release();
    await expect(page.getByRole("heading", { level: 2, name: "6 opened" })).toBeVisible();
  });

  /** Leave Pace for the Radar, open a role there, act on it, and come back. */
  async function openARoleAndReturn(page: Page, act: (role: Locator) => Promise<void>) {
    await installJobDetailRoutes(page);
    await page.goto("/statistics/velocity");
    await expect(page.getByRole("heading", { level: 2, name: "5 opened" })).toBeVisible();
    await page.getByRole("link", { name: "Radar", exact: true }).click();
    const viewed = page.waitForResponse((r) => r.url().endsWith("/api/jobs/101/view"));
    await page.getByRole("article").filter({ hasText: "Staff Product Manager, API" })
      .getByText("Staff Product Manager, API").click();
    const role = page.getByRole("dialog", { name: /^Role:/ });
    await expect(role).toBeVisible();
    await viewed;
    await act(role);
    await role.getByRole("button", { name: "Back" }).click();
    await expect(role).toHaveCount(0);

    const pace = await holdPace(page);
    await page.goBack();
    await expect(page.getByRole("tab", { name: "Pace" })).toHaveAttribute("aria-selected", "true");
    await expect.poll(() => pace.asked.length).toBeGreaterThan(0);
    return pace;
  }

  test("paints its last answer after a role is opened, which only marks it viewed", async ({ page }) => {
    const pace = await openARoleAndReturn(page, async () => {});
    await expect(page.getByRole("heading", { level: 2, name: "5 opened" })).toBeVisible();
    pace.release();
    await expect(page.getByRole("heading", { level: 2, name: "6 opened" })).toBeVisible();
  });

  test("shows no answer after a role is saved, which may change it", async ({ page }) => {
    await page.route("/api/jobs/101/favorite", (route) => route.fulfill({ json: { job_id: 101, is_favorite: true } }));
    const pace = await openARoleAndReturn(page, async (role) => {
      const saved = page.waitForResponse((r) => r.url().endsWith("/api/jobs/101/favorite"));
      await role.getByRole("button", { name: msg("jobs-save") }).click();
      await saved;
    });
    await expect(page.getByRole("heading", { level: 2, name: /opened/ })).toHaveCount(0);
    pace.release();
    await expect(page.getByRole("heading", { level: 2, name: "6 opened" })).toBeVisible();
  });

  test("a first visit with the read held shows no answer", async ({ page }) => {
    const pace = await holdPace(page);
    await page.goto("/statistics/velocity");
    await expect.poll(() => pace.asked.length).toBeGreaterThan(0);
    await expect(page.getByRole("heading", { level: 2, name: /opened/ })).toHaveCount(0);
    pace.release();
    await expect(page.getByRole("heading", { level: 2, name: "6 opened" })).toBeVisible();
  });
});
