/* The opportunity detail: what the full-screen cover shows, how it is reached,
   and what it writes. The shell is full-screen, so its entry paths (row
   click, /job/:id, company-scoped URL, back/forward) are the contract. */

import type { Locator, Page } from "@playwright/test";
import { msg } from "../../src/test/msg";
import { expect, mockGet, test, watchReads } from "./fixtures";
import { hiringFixture, jobFixture } from "../../src/test/fixtures";
import { appleJobFixture, comparison, detail, installBoardRoutes, jobFixture2 } from "./boardHarness";
import { showAdvancedInsights } from "./insightsView";
import { expectOnTop, pointAndClick, strangersOver } from "./paint";

test.beforeEach(async ({ page }) => {
  await installBoardRoutes(page);
});

test("opening an opportunity shows a full-screen detail that fills the viewport", async ({ page }) => {
  await page.goto("/");

  const mission = page.getByRole("banner", { name: "Application navigation" });
  await expect(mission).toContainText("Radar");
  await expect(mission.locator(".stat-chip").nth(0)).toHaveAttribute("aria-label", msg("shell-stat-open-aria", { count: 1 }));
  await expect(mission.locator(".stat-chip").nth(1)).toHaveAttribute("aria-label", "1 new in the last 2 days");
  await expect(mission.getByRole("status", { name: /Last scan/ })).toContainText("Last scan");
  await expect(page.getByRole("main")).toContainText("2 roles");
  await expect(page.getByRole("status", { name: /Last scan/ })).toContainText(msg("shell-freshness-checked", { age: msg("format-age-hours", { count: 2 }) }));
  await expect(page.getByText("Staff Product Manager, API")).toBeVisible();
  // The row's pay is the base: the fixture posts no base range, so its estimate.
  await expect(page.locator(`[data-job-id="${jobFixture.id}"] .comp`)).toHaveText(/^\$400K /);

  await page.getByText("Staff Product Manager, API").click();

  const panel = detail(page);
  await expect(panel).toBeVisible();
  await expect(panel.getByRole("heading", { name: "Staff Product Manager, API" })).toBeVisible();
  await expect(panel).toContainText("Lead API product strategy.");
  await expect(panel.getByRole("link", { name: /view & apply/i })).toHaveAttribute("href", jobFixture.url);

  // Full-screen: the detail covers the whole viewport, not a narrow side panel.
  const viewport = page.viewportSize()!;
  const box = await panel.boundingBox();
  expect(box!.width).toBeGreaterThan(viewport.width - 2);
  expect(box!.height).toBeGreaterThan(viewport.height - 2);
});

test("an open role cover leaves one h1 and an inert page behind it", async ({ page }) => {
  // Fail-first: the list stayed in the accessibility tree under the cover,
  // so the document had two h1s and a virtual cursor read the list.
  await page.goto("/");
  await page.getByText("Staff Product Manager, API").click();
  const panel = detail(page);
  await expect(panel).toBeVisible();

  const reachable = () => page.locator("h1").evaluateAll((hs) => hs.filter((h) => !h.closest("[inert]")).length);
  await expect.poll(reachable).toBe(1);
  await expect(page.locator(".workspace")).toHaveAttribute("inert", "");
  await expect(page.locator(".nav-rail")).toHaveAttribute("inert", "");
  await expect(panel).not.toHaveAttribute("inert", "");

  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();
  await expect(page.locator(".workspace")).not.toHaveAttribute("inert", "");
  await expect(page.locator(".nav-rail")).not.toHaveAttribute("inert", "");
});

// Sources publish a run of cities in one string, then each again on its own:
// "San Francisco, CA | New York City, NY" and then "New York City, NY" a
// second time.
test("a posting that names a city twice lists each place once", async ({ page }) => {
  await mockGet(page, "/api/jobs/101", (route) => route.fulfill({ json: {
    ...jobFixture, locations: ["San Francisco, CA | New York City, NY", "New York City, NY"],
  } }));
  await page.goto("/job/101");

  const meta = detail(page).locator(".job-meta");
  await expect(meta.getByText("San Francisco, CA", { exact: true })).toHaveCount(1);
  await expect(meta.getByText("New York City, NY", { exact: true })).toHaveCount(1);
  await expect(meta).not.toContainText("|");
});

// The place line already says the country, and the region follows from it:
// only the metro area is news.
test("the place tags add only what the place line does not say", async ({ page }) => {
  await mockGet(page, "/api/jobs/101", (route) => route.fulfill({ json: {
    ...jobFixture,
    locations: ["Sunnyvale, CA, USA"],
    location_groups: ["silicon_valley", "united_states", "north_america", "city_5400075"],
  } }));
  await page.goto("/job/101");

  const meta = detail(page).locator(".job-meta");
  await expect(meta.getByText("Sunnyvale, CA, USA", { exact: true })).toBeVisible();
  await expect(meta.getByText("Silicon Valley", { exact: true })).toBeVisible();
  await expect(meta.getByText("United States", { exact: true })).toHaveCount(0);
  await expect(meta.getByText("North America", { exact: true })).toHaveCount(0);
});

test("Apple detail preserves source sections and Pay & Benefits", async ({ page }) => {
  await page.goto("/job/303");

  const panel = detail(page);
  await expect(panel.getByRole("heading", { name: "Summary" })).toBeVisible();
  await expect(panel.getByRole("heading", { name: "Minimum Qualifications" })).toBeVisible();
  await expect(panel.getByRole("heading", { name: "Pay & Benefits" })).toBeVisible();
  await expect(panel.getByText(/\$250,800 and \$376,300/)).toBeVisible();
  await expect(panel.getByText("10+ years of product management experience")).toBeVisible();
  await expect(panel.getByText("Legacy fallback should not replace structured sections.")).toHaveCount(0);
});

const readyRequirements = {
  state: "ready",
  extractor_version: "test",
  qualifications: [],
  required_years: null,
  skills: [
    {
      concept_id: 1,
      slug: "python",
      facet: "technology",
      category: "Languages",
      importance_band: "core",
      importance_score: 1,
      confidence: "high",
      modality: "required",
      evidence: [],
    },
  ],
};

// The description is the column's main text, so it spans the column exactly
// as the requirements card above it does, at the base and the wide layout.
//
// The measuring tests below open the company-scoped URL. A short /job/:id
// rewrites itself once the job loads, which remounts the whole detail, so a
// one-shot measurement taken after the first paint can land on nodes the
// remount has already detached: `boundingBox()` answers null and a query
// finds nothing.
for (const width of [1440, 1600]) {
  test(`the description spans the same width as the requirements card at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockGet(page, "/api/jobs/303", (route) =>
      route.fulfill({ json: { ...appleJobFixture, requirements: readyRequirements } }),
    );
    await page.goto("/company/apple/job/303");

    const panel = detail(page);
    const card = panel.locator(".req-panel");
    await expect(card).toBeVisible();
    const cardBox = (await card.boundingBox())!;

    for (const heading of ["Summary", "Minimum Qualifications"]) {
      const section = panel.locator(".jd-section").filter({ has: page.getByRole("heading", { name: heading }) });
      const box = (await section.boundingBox())!;
      expect(Math.abs(box.x - cardBox.x), `${heading} left edge`).toBeLessThanOrEqual(1);
      expect(Math.abs(box.width - cardBox.width), `${heading} width`).toBeLessThanOrEqual(1);
    }
  });
}

test("a plain-text description spans the same width as the requirements card", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockGet(page, "/api/jobs/101", (route) =>
    route.fulfill({ json: { ...jobFixture, requirements: readyRequirements } }),
  );
  await page.goto("/company/openai/job/101");

  const panel = detail(page);
  const card = panel.locator(".req-panel");
  const text = panel.locator(".jd-fallback");
  await expect(card).toBeVisible();
  await expect(text).toContainText("Lead API product strategy.");
  const cardBox = (await card.boundingBox())!;
  const box = (await text.boundingBox())!;
  expect(Math.abs(box.x - cardBox.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(box.width - cardBox.width)).toBeLessThanOrEqual(1);
});

// Justified text is only acceptable with hyphenation, and hyphenation only
// works when the page names its language. A phone line holds too few words.
const descriptionSetting = (page: import("@playwright/test").Page) =>
  detail(page).locator(".jd-section p, .jd-section li").evaluateAll((els) =>
    els.map((el) => {
      const s = getComputedStyle(el);
      return { align: s.textAlign, hyphens: s.hyphens || s.getPropertyValue("-webkit-hyphens") };
    }),
  );

test("the description is justified with hyphenation on a wide screen", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/company/apple/job/303");
  await expect(detail(page).getByRole("heading", { name: "Summary" })).toBeVisible();

  expect(await page.evaluate(() => document.documentElement.lang)).toBe("en");
  const settings = await descriptionSetting(page);
  expect(settings.length).toBeGreaterThan(2);
  for (const setting of settings) expect(setting).toEqual({ align: "justify", hyphens: "auto" });
});

test("the description stays left-aligned on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/company/apple/job/303");
  await expect(detail(page).getByRole("heading", { name: "Summary" })).toBeVisible();

  const settings = await descriptionSetting(page);
  expect(settings.length).toBeGreaterThan(2);
  for (const setting of settings) expect(setting).toEqual({ align: "start", hyphens: "manual" });
});

test("a role with no twins never asks for them", async ({ page }) => {
  const twins = watchReads(page, "GET", "/api/jobs/101/twins");
  const placeSet = watchReads(page, "GET", "/api/jobs/101/place-set");
  await page.goto("/job/101");
  await expect(page.getByText("View & apply")).toBeVisible();
  // Its sibling section asks as the page opens, so by its answer the deck would have asked too.
  await expect.poll(() => placeSet.answered).toBeGreaterThan(0);
  expect(twins.started).toBe(0);
  await expect(page.getByRole("button", { name: /Has a related role/ })).toHaveCount(0);
});

test("a confirmed twin opens as a paper stack and compares full descriptions", async ({ page }) => {
  await page.route("/api/jobs/101", (route) => route.fulfill({ json: { ...jobFixture, twin_count: 1 } }));
  await page.route("/api/jobs/101/twins", (route) => route.fulfill({ json: {
    job_id: 101,
    size: 3,
    direct_count: 1,
    members: [
      { job: jobFixture, direct: false, link: null },
      { job: jobFixture2, direct: true, link: { proposal_kind: "twin", id: 8 } },
      { job: appleJobFixture, direct: false, link: null },
    ],
  } }));

  await page.goto("/job/101");
  await page.getByRole("button", { name: /Has a related role/ }).click();
  await expect(page.getByText("Principal Engineer, Platform")).toBeVisible();
  await expect(page.getByText(/Head of Product, Global AI Learning Platform/)).toBeVisible();
  await expect(page.getByText(/not directly related/)).toBeVisible();

  /* One primary per surface. Job detail's is "View & apply" — the
     one thing that page exists for — so opening this disclosure must not put a
     second filled button beside it. A rank rule of "primary = commits state"
     cannot express this: neither of these two commits anything. */
  const primaries = await page.locator(".ui-btn-primary:visible").allInnerTexts();
  expect(
    primaries.map((t) => t.trim()),
    "more than one primary is visible on Job detail",
  ).toEqual(["View & apply"]);

  await page.getByRole("button", { name: "Compare with related roles" }).click();
  await expect(page).toHaveURL(/\/compare$/);
  /* Compare folds each description pair behind its own line, so the
     comparison is one click in, and each region is named for the ROLE it reads
     against the baseline rather than all sharing one name. */
  /* The comparison covers the role page it opened from. Each
     twin's description sits under its role, and what only one posting says
     is on screen at once — no baseline, nothing to unfold. */
  const cover = comparison(page);
  await expect(cover.locator(".cmp-prose").filter({ hasText: "Lead API product strategy." })).toHaveCount(1);
  await expect(cover.locator(".cmp-prose").filter({ hasText: "Own core platform reliability." })).toHaveCount(1);
});

test("each opportunity's URL nests it under its company", async ({ page }) => {
  await page.goto("/");

  // A position is a sub-resource of its company: /company/<slug>/job/<id>.
  await page.getByText("Staff Product Manager, API").click();
  await expect(page).toHaveURL(/\/company\/openai\/job\/101$/);
  await expect(detail(page).getByRole("heading", { name: "Staff Product Manager, API" })).toBeVisible();

  await page.getByRole("button", { name: "Back" }).click();
  await expect(page).toHaveURL(/\/$/);

  await page.getByText("Principal Engineer, Platform").click();
  await expect(page).toHaveURL(/\/company\/openai\/job\/202$/);
  await expect(detail(page).getByRole("heading", { name: "Principal Engineer, Platform" })).toBeVisible();
});

test("a short /job/:id link canonicalizes to the company-scoped URL and reloads", async ({ page }) => {
  await page.goto("/job/202");

  // The flat /job/:id link still resolves, then rewrites itself to the nested form.
  await expect(page).toHaveURL(/\/company\/openai\/job\/202$/);
  const panel = detail(page);
  await expect(panel.getByRole("heading", { name: "Principal Engineer, Platform" })).toBeVisible();
  await expect(panel.getByRole("link", { name: /view & apply/i })).toHaveAttribute("href", jobFixture2.url);

  // Refresh on the canonical URL keeps the same opportunity.
  await page.reload();
  await expect(page).toHaveURL(/\/company\/openai\/job\/202$/);
  await expect(detail(page).getByRole("heading", { name: "Principal Engineer, Platform" })).toBeVisible();

  // From a direct link there is no in-app history, so Back returns to the board.
  await page.getByRole("button", { name: "Back" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("main")).toContainText("2 roles");
});

// Rewriting the URL is not a new page: the role drawn from the first URL is the
// one still on screen, not a second copy drawn after a reload of the detail.
for (const entry of ["/job/202", "/company/not-openai/job/202"]) {
  test(`${entry} rewrites its URL without drawing the role twice`, async ({ page }) => {
    await page.addInitScript(() => {
      const drawn = new Set<Element>();
      new MutationObserver(() => {
        for (const title of document.querySelectorAll(".jd-hero h1")) drawn.add(title);
      }).observe(document, { childList: true, subtree: true });
      (window as unknown as { roleTitlesDrawn: () => number }).roleTitlesDrawn = () => drawn.size;
    });
    const drawn = () => page.evaluate(() => (window as unknown as { roleTitlesDrawn: () => number }).roleTitlesDrawn());

    await page.goto(entry);
    await expect(page).toHaveURL(/\/company\/openai\/job\/202$/);
    await expect(detail(page).getByRole("heading", { name: "Principal Engineer, Platform" })).toBeVisible();
    // Past every fetch a remount would make again.
    await page.waitForLoadState("networkidle");
    expect(await drawn()).toBe(1);
  });
}

test("browser back and forward move between the board and an opportunity", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Staff Product Manager, API").click();
  await expect(page).toHaveURL(/\/company\/openai\/job\/101$/);
  await expect(detail(page)).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
  await expect(detail(page)).toHaveCount(0);
  await expect(page.getByRole("main")).toContainText("2 roles");

  await page.goForward();
  await expect(page).toHaveURL(/\/company\/openai\/job\/101$/);
  await expect(detail(page).getByRole("heading", { name: "Staff Product Manager, API" })).toBeVisible();
});

/* ---- one scroll ---------------------------------------------------------- *
 *
 * The Board scrolls the way Settings > Companies scrolls: `.main`
 * is the ONE scroller, the hero slides away like any page content, the
 * toolbar docks at the top through the shared `.app-toolbar` recipe, and the
 * column head and the filter register pin beneath it at the toolbar's
 * measured height. A page of roles is rendered IN FULL in the flow — no inner
 * scroll windows anywhere — and the list wears the register's ledger
 * treatment (no floating-card frame), which is what makes rows sliding under
 * an opaque pinned band drawable at all.
 *
 * The register renders as the left rail from 1360px; below that the toolbar
 * carries a "Filters · N" opener over the same component.
 */

test("opening a job over a nested Statistics tab returns to that exact tab", async ({ page }) => {
  // The job overlay works over a nested background route. Opening a job from
  // /statistics/demand and pressing Back lands on /statistics/demand with the
  // Demand tab still selected, never on the board.
  const demandFixture = {
    ...hiringFixture,
    most_updated_open: [{ ...jobFixture2, update_count: 3, last_updated_at: "2026-07-12T16:00:00Z" }],
  };
  await page.route("/api/demand", (route) => route.fulfill({ json: demandFixture }));
  // The role lists are the advanced view's.
  await showAdvancedInsights(page);

  await page.goto("/statistics/demand");
  await expect(page.getByRole("tab", { name: "Hiring", exact: true })).toHaveAttribute("aria-selected", "true");

  await page.getByText("Principal Engineer, Platform").click();
  await expect(page).toHaveURL(/\/company\/openai\/job\/202$/);
  await expect(detail(page).getByRole("heading", { name: "Principal Engineer, Platform" })).toBeVisible();

  await page.getByRole("button", { name: "Back" }).click();
  await expect(page).toHaveURL(/\/statistics\/demand$/);
  await expect(page.getByRole("tab", { name: "Hiring", exact: true })).toHaveAttribute("aria-selected", "true");
});

test("the stage select starts a pursuit, which also saves the role", async ({ page }) => {
  let putBody: Record<string, unknown> | null = null;
  await page.route("/api/jobs/101/pursuit", async (route) => {
    putBody = route.request().postDataJSON();
    await route.fulfill({ json: { pursuit: {
      id: 7, job_id: 101, stage: "researching", priority: 3, notes: null,
      next_action: null, next_action_due: null,
      created_at: "2026-08-08T19:00:00Z", updated_at: "2026-08-08T19:00:00Z",
    } } });
  });
  await page.goto("/company/openai/job/101");
  const panel = detail(page);

  // Not pursuing yet: the select doubles as the entry point, and says what it does first.
  await expect(panel.getByText("Not started")).toBeVisible();
  await expect(panel.getByText(msg("role-job-detail-tracking-explainer"))).toBeVisible();
  await panel.getByLabel("Stage").selectOption("researching");

  await expect.poll(() => putBody).not.toBeNull();
  expect(putBody).toEqual({ stage: "researching" });
  await expect(panel.getByText("Stage", { exact: true })).toBeVisible();
  // Pursuing implies saved — the star reflects the server rule immediately.
  await expect(panel.getByRole("button", { name: msg("jobs-save"), pressed: true })).toBeVisible();
  // Once tracking, the explanation has done its job.
  await expect(panel.getByText(msg("role-job-detail-tracking-explainer"))).toHaveCount(0);
});

/* The stage popup is native: the OS draws it, in whatever appearance the page
   declares. A dark page on a light Mac must still open a dark menu, and the
   reverse; the OS setting is the opposite of the theme in both cases here. */
for (const [theme, os] of [["dark", "light"], ["light", "dark"]] as const) {
  test(`the stage select's native popup takes the ${theme} theme on a ${os} system`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: os });
    await page.addInitScript((t) => localStorage.setItem("theme", t), theme);
    await page.goto("/company/openai/job/101");

    const stage = detail(page).getByLabel("Stage");
    await expect(stage).toBeVisible();
    await expect(stage).toHaveCSS("color-scheme", theme);
    // The app's own select, so it wears the app's chevron rather than the platform's.
    await expect(stage).toHaveCSS("appearance", "none");
    await expect(stage.locator("option").first()).toHaveText(msg("role-job-detail-set-a-stage"));
  });
}

test("Saved shows each tracked role's stage on its row", async ({ page }) => {
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: {
    items: [{ ...jobFixture, id: 101, is_favorite: true }, { ...jobFixture, id: 102, title: "Untracked role", is_favorite: true }],
    total: 2, related: [], related_total: 0, ranked_by: "date",
  } }));
  await page.route("/api/pursuits**", (route) => route.fulfill({ json: { pursuits: [{
    id: 7, job_id: 101, stage: "applied", priority: 3, notes: null, next_action: null, next_action_due: null,
    created_at: "2026-08-08T19:00:00Z", updated_at: "2026-08-08T19:00:00Z",
    opportunity: { company: "openai", status: "open", title: jobFixture.title, url: jobFixture.url },
  }] } }));
  await page.goto("/favorites");
  const rows = page.locator(".job-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText(msg("saved-screen-progress", { stage: "Applied" }));
  await expect(rows.nth(1)).not.toContainText("Your progress");
});

/* Radar's read is a hint for the reader. The stored rationale, model id and
   confidence are bench material: none of them may reach the screen, and the
   world appears by its name, never its slug. Fixtures carry what the anchor
   classifier really stores. */
const ANCHOR_REVIEW = {
  tracked_worlds: ["ai_ml"], prompt_version: "relevance_review/emb-v1",
  provider: "builtin", model_id: "lightonai/DenseOn", reviewed_at: "2026-08-07T12:00:00Z",
};

async function openWithReview(page: Page, review: Record<string, unknown>) {
  await page.route("/api/jobs/101", (route) => route.fulfill({ json: {
    ...jobFixture, relevance_review: { ...ANCHOR_REVIEW, ...review },
  } }));
  await page.goto("/company/openai/job/101");
  const box = detail(page).locator(".jd-advisory");
  await expect(box).toBeVisible();
  return box;
}

async function expectNoInternals(box: Locator) {
  for (const internal of [/cosine/i, /margin/i, /anchor/i, /DenseOn/, /builtin/, /%/, /_/]) {
    await expect(box).not.toContainText(internal);
  }
}

test("a placed role's read names the world and its basis, never the score or model", async ({ page }) => {
  const box = await openWithReview(page, {
    domain: "payments_fintech", relevance: "irrelevant", confidence: 0.63,
    rationale: "Nearest world anchor: 'Payments & Fintech' (cosine 0.30, margin 0.020 over 'Customer Support & Service').",
  });

  await expect(box).toContainText(msg("role-job-detail-likely-outside-your-worlds"));
  await expect(box).toContainText(msg("vocab-domain-payments-fintech"));
  await expect(box).toContainText(msg("role-job-detail-advisory-basis"));
  // The "between worlds" line belongs to a role it could not place.
  await expect(box).not.toContainText(msg("role-job-detail-advisory-unclear"));
  await expectNoInternals(box);
});

test("a role it cannot place says so plainly, with no world named", async ({ page }) => {
  const box = await openWithReview(page, {
    domain: null, relevance: "uncertain", confidence: 0.25,
    rationale: "No world is clearly nearest: 'AI & Machine Learning' at cosine 0.25 is only 0.001 ahead of 'Cloud & Infrastructure'.",
  });

  await expect(box).toContainText(msg("role-job-detail-hard-to-place"));
  await expect(box).toContainText(msg("role-job-detail-advisory-unclear"));
  await expect(box).toContainText(msg("role-job-detail-advisory-basis"));
  await expect(box).not.toContainText(msg("vocab-domain-ai-ml"));
  await expectNoInternals(box);
});

test("no advisory, no card — the aside stays quiet for unreviewed roles", async ({ page }) => {
  await page.goto("/company/openai/job/101");
  await expect(detail(page).getByRole("heading", { name: jobFixture.title })).toBeVisible();
  await expect(detail(page).getByText("Radar's read")).toHaveCount(0);
});

/* What applying asks, read from the posting's own page. Absent until
   read: a form we never read is not a form that asks nothing. */
test("Details says what applying asks once the posting page has been read", async ({ page }) => {
  await page.goto("/company/openai/job/101");
  await expect(detail(page).getByRole("heading", { name: jobFixture.title })).toBeVisible();
  await expect(detail(page).locator("dl.kv").getByText("To apply", { exact: true })).toHaveCount(0);

  await page.route("/api/jobs/101", (route) => route.fulfill({ json: {
    ...jobFixture,
    application_form: { required: 9, written: 1, choices: 8, asks_expected_pay: true, read_at: "2026-09-28T12:00:00Z" },
  } }));
  await page.reload();
  const details = detail(page).locator("dl.kv");
  await expect(details.getByText("To apply", { exact: true })).toBeVisible();
  await expect(details.getByText("9 questions, 1 written answer, asks your expected compensation", { exact: true })).toBeVisible();
});

/* Opening a posting whose form is unread asks for it once,
   after the page is shown, and the row appears when the answer arrives. A
   posting the server marks unreadable is never asked about. */
test("opening an unread posting reads what applying asks, once", async ({ page }) => {
  const reads: string[] = [];
  const form = { required: 5, written: 1, choices: 2, asks_expected_pay: false, read_at: "2026-09-29T09:00:00Z" };
  let stored = false;
  await page.route("/api/jobs/101/posting-page", (route) => {
    reads.push(route.request().method());
    stored = true;
    return route.fulfill({ json: { outcome: "read", application_form: form } });
  });
  // As the server answers: unread until the read, then the form and no flag.
  // The detail is read again after a read, since the page may state pay:
  // twice in all, counted as answered (dev StrictMode re-issues the first).
  const detailReads = watchReads(page, "GET", "/api/jobs/101");
  await page.route("/api/jobs/101", (route) => route.fulfill({ json: stored
    ? { ...jobFixture, application_form: form, application_form_readable: false }
    : { ...jobFixture, application_form: null, application_form_readable: true } }));
  await page.goto("/company/openai/job/101");
  const details = detail(page).locator("dl.kv");
  await expect(details.getByText("5 questions, 1 written answer", { exact: true })).toBeVisible();
  await expect.poll(() => detailReads.answered).toBe(2);
  expect(reads).toEqual(["POST"]);

  // A posting the server marks unreadable is never asked about. Absence is
  // asserted once the page has gone quiet, not at first paint, when the
  // effect that would ask may not have run yet.
  await page.unroute("/api/jobs/101");
  await page.route("/api/jobs/101", (route) => route.fulfill({ json: {
    ...jobFixture, application_form: null, application_form_readable: false,
  } }));
  await page.reload();
  await expect(detail(page).getByRole("heading", { name: jobFixture.title })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expect(details.getByText("To apply", { exact: true })).toHaveCount(0);
  expect(reads).toEqual(["POST"]);
});

/* One age in Details, with where it counts from, in place of separate Posted,
   First seen and Listed for; the history opens on demand, is read once, and
   marks the start. */
test("Details says one age with its basis, and the history opens on demand", async ({ page }) => {
  const reads = watchReads(page, "GET", "/api/jobs/101/history");
  const event = { from_at: null, to_at: null, field: null, count: null, job_id: null, req_id: null, title: null, until: null, link: null };
  await page.route("/api/jobs/101", (route) => route.fulfill({ json: {
    ...jobFixture, listed_since: "2026-04-12T00:00:00Z", listed_days: 170, listed_basis: "employer",
  } }));
  await page.route("/api/jobs/101/history", (route) => route.fulfill({ json: {
    headline: { since: "2026-04-12T00:00:00Z", days: 170, basis: "employer" },
    role: null,
    events: [
      { ...event, at: "2026-04-12T00:00:00Z", kind: "employer_published" },
      { ...event, at: "2026-07-23T00:00:00Z", kind: "first_seen" },
      { ...event, at: "2026-09-02T00:00:00Z", kind: "redated", from_at: "2026-04-12T00:00:00Z", to_at: "2026-09-02T00:00:00Z" },
    ],
    unconfirmed: [],
  } }));
  await page.goto("/company/openai/job/101");
  const details = detail(page).locator("dl.kv");
  await expect(details.getByText("170 days", { exact: true })).toBeVisible();
  await expect(details.getByText(/, the employer's date$/)).toBeVisible();
  for (const gone of ["Posted", "First seen"]) await expect(details.getByText(gone, { exact: true })).toHaveCount(0);
  expect(reads.started).toBe(0);

  await details.getByRole("button", { name: "History" }).click();
  const panel = page.getByRole("dialog", { name: "Listing history" });
  const events = panel.getByRole("list", { name: "Events" });
  await expect(events).toContainText("Published by the employer · the start");
  await expect(events).toContainText(/Employer changed its date to .* · never the start/);
  await expect.poll(() => reads.answered).toBe(1);
});

/* The history opens in the side column it belongs to, edge to edge with the
   stage select above it, under its button; it may cover what follows. */
test("the listing history opens across the side column, under its button", async ({ page }) => {
  const event = { from_at: null, to_at: null, field: null, count: null, job_id: null, req_id: null, title: null, until: null, link: null };
  await page.route("/api/jobs/101/history", (route) => route.fulfill({ json: {
    headline: { since: "2026-10-24T00:00:00Z", days: 9, basis: "sighting" },
    role: null,
    events: [
      { ...event, at: "2026-10-24T00:00:00Z", kind: "first_seen" },
      { ...event, at: "2026-11-02T00:00:00Z", kind: "last_seen" },
    ],
    unconfirmed: [],
  } }));
  await page.goto("/company/openai/job/101");
  const cover = detail(page);
  const button = cover.locator("dl.kv").getByRole("button", { name: "History" });
  await button.click();
  const panel = page.getByRole("dialog", { name: "Listing history" }).locator(".ui-popover-inner");
  await expect(panel).toBeVisible();
  // The pop-in scales the panel; measure where it settles.
  await panel.evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)));

  const box = (await panel.boundingBox())!;
  const column = (await cover.locator(".jd-aside").boundingBox())!;
  const stage = (await cover.getByLabel("Stage").boundingBox())!;
  const opener = (await button.boundingBox())!;
  expect(Math.abs(box.x - column.x), "left edge on the column's").toBeLessThanOrEqual(1);
  expect(Math.abs(box.x + box.width - (column.x + column.width)), "right edge on the column's").toBeLessThanOrEqual(1);
  expect(Math.abs(box.x - stage.x), "left edge on the stage select's").toBeLessThanOrEqual(1);
  expect(box.y).toBeGreaterThan(opener.y + opener.height);
});

/* A posting showing two of three standing signs says which, and
   states its own limit. One sign, or none, says nothing at all. The
   screen states ONE age, in Details, from the employer's earlier date; the
   standing section names the sign without repeating the figure. */
test("a posting with two standing signs names them, and one without says nothing", async ({ page }) => {
  await page.route("/api/jobs/101", (route) => route.fulfill({ json: {
    ...jobFixture,
    days_open: 62,
    listed_since: "2026-04-30T00:00:00Z",
    listed_days: 150,
    posting_reality: {
      level: "possible", met: ["long_open", "relisted"], criteria_total: 3, listings: 3,
    },
  } }));
  await page.goto("/company/openai/job/101");
  const standing = detail(page).getByRole("region", { name: "May be an always-open posting" });
  await expect(standing).toBeVisible();
  await expect(standing).toContainText("Listed for a long time");
  const details = detail(page).locator("dl.kv");
  await expect(details.getByText("Listed for", { exact: true })).toBeVisible();
  await expect(details.getByText("150 days", { exact: true })).toBeVisible();
  await expect(detail(page).getByText("Days open")).toHaveCount(0);
  await expect(detail(page).getByText("62 days")).toHaveCount(0);
  await expect(standing).toContainText("Listed 3 times");
  await expect(standing).toContainText("2 of 3 signs");

  await page.unroute("/api/jobs/101");
  await page.route("/api/jobs/101", (route) => route.fulfill({ json: {
    ...jobFixture,
    posting_reality: {
      level: "none", met: ["long_open"], criteria_total: 3, listings: 1,
    },
  } }));
  await page.reload();
  await expect(detail(page).getByRole("heading", { name: jobFixture.title })).toBeVisible();
  await expect(detail(page).getByRole("region", { name: "May be an always-open posting" })).toHaveCount(0);
});


/* Opened from a list, the detail covers a page that stays MOUNTED underneath.
   As a bare <section> (no dialog role, no aria-modal, no focus capture, no
   trap, no restore, no scroll lock) a keyboard user lands on the covered row,
   tabs through every control of a page they cannot see to reach "View & apply", and gets
   nothing back on close. Reached by a direct link
   there is nothing underneath, and it must NOT claim to be a dialog. */
test("opened over a list, the detail is a modal dialog that owns focus", async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto("/");
  const row = page.getByRole("article").first();
  await row.getByRole("heading").click();

  const dialog = page.getByRole("dialog", { name: /^Role:/ });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");

  // The page behind is locked, so the cover does not scroll a list nobody sees.
  await expect(page.locator("body")).toHaveCSS("overflow", "hidden");

  // Focus moved INTO the cover, and stays there however long you tab.
  await expect(dialog).toContainText("View & apply");
  for (let i = 0; i < 40; i += 1) {
    await page.keyboard.press("Tab");
    // WebKit's Tab skips buttons and can step out; the overlay brings focus
    // back one task later (ui/Overlay, which covers use), so
    // focus is judged once that task has run, as palette.spec does.
    await page.evaluate(() => new Promise<void>((resolve) => setTimeout(resolve, 0)));
    const inside = await dialog.evaluate((el) => el.contains(document.activeElement));
    expect(inside, `focus left the dialog after ${i + 1} tabs`).toBe(true);
  }

  // And it comes back to the row that opened it.
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  const restored = await row.evaluate((el) => el.contains(document.activeElement));
  expect(restored, "focus was not restored to the opening row").toBe(true);
});

test("reached by a direct link, the detail is the page, not a dialog", async ({ page }) => {
  await page.goto("/company/google/job/101");
  // The page's one main landmark (a cover reached by URL IS the page).
  await expect(page.getByRole("main", { name: /^Role:/ })).toBeVisible();
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  // Nothing is covered, so nothing is locked.
  await expect(page.locator("body")).not.toHaveCSS("overflow", "hidden");
});

/* Similar positions: two categories, three rows each, visibly two blocks.
   More rows, at body size under small labels, read as one wall. The
   source is answered with FIVE per scope on purpose: the cap must hold on
   the page even when the request's `limit` is ignored. */
test("similar positions show at most three per category, fetched as three, and the categories are set apart", async ({ page }) => {
  const similar = (scope: string) =>
    Array.from({ length: 5 }, (_, i) => ({
      ...jobFixture,
      id: (scope === "within" ? 900 : 950) + i,
      company: scope === "within" ? "openai" : "anthropic",
      title: `${scope === "within" ? "Same" : "Other"} similar role ${i + 1}`,
      score: 0.9 - i * 0.05,
    }));
  const requested: string[] = [];
  await page.route("/api/jobs/101/similar**", (route) => {
    const url = new URL(route.request().url());
    requested.push(url.search);
    return route.fulfill({ json: { scope: url.searchParams.get("scope"), items: similar(url.searchParams.get("scope")!) } });
  });

  await page.goto("/job/101");
  const panel = detail(page);
  const groups = panel.locator(".similar-group");
  await expect(groups).toHaveCount(2);
  await expect(groups.nth(0)).toContainText("Other companies");
  await expect(groups.nth(1)).toContainText("Same company · OpenAI");
  await expect(groups.nth(0).locator(".similar-row")).toHaveCount(3);
  await expect(groups.nth(1).locator(".similar-row")).toHaveCount(3);
  await expect(panel.getByText("Other similar role 4")).toHaveCount(0);
  await expect(panel.getByText("Same similar role 4")).toHaveCount(0);

  // Fetched as three, per scope: nothing is requested only to be hidden.
  // (The COUNT of requests is not asserted: dev StrictMode doubles every
  // mount, so the same pair is issued more than once there.)
  expect(requested.length).toBeGreaterThanOrEqual(2);
  for (const scope of ["within", "cross"]) expect(requested).toContain(`?scope=${scope}&limit=3`);
  for (const query of requested) expect(query).toMatch(/(\?|&)limit=3(&|$)/);

  // Set apart on the page, not only in the DOM: each category opens with a
  // hairline, and its head and its rows are on different type steps, with
  // the rows stepped below the body size of the prose.
  const metrics = await groups.nth(1).evaluate((group) => {
    const px = (el: Element | null, prop: string) => parseFloat(getComputedStyle(el!).getPropertyValue(prop));
    return {
      hairline: px(group, "border-top-width"),
      head: px(group.querySelector(".similar-label"), "font-size"),
      row: px(group.querySelector(".mj-title"), "font-size"),
      body: parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--app-type-body")),
    };
  });
  expect(metrics.hairline).toBeGreaterThan(0);
  expect(metrics.head).not.toBe(metrics.row);
  expect(metrics.row).toBeLessThan(metrics.body);
});

/* The eyebrow modifier's cascade.
 *
 * `.req-eyebrow` changes ONE property of the shared `.eyebrow` recipe: it is a
 * single-declaration modifier worn beside the shared class, which means it
 * wins on SOURCE ORDER at equal specificity, and
 * source order here spans two sheets: `.eyebrow` is in the always-loaded
 * `design/surfaces.css`, `.req-eyebrow` arrives in the job-detail route chunk.
 * That is precisely the shape not to reason about
 * ("specificity is relative, so relocating one silently inverts it"), so it is
 * measured in a browser instead: the eyebrow must paint the ACTION ink, and
 * must not have fallen back to the shared faint.
 */
test("the requirements eyebrow keeps its ink after folding into the shared recipe", async ({ page }) => {
  // The board harness's job carries no requirements, so the panel that owns
  // this eyebrow never mounts. Give it one.
  await page.route("/api/jobs/101", (route) =>
    route.fulfill({
      json: {
        ...jobFixture,
        requirements: {
          state: "ready",
          extractor_version: "test",
          qualifications: [],
          required_years: null,
          skills: [
            {
              concept_id: 1,
              slug: "python",
              facet: "technology",
              category: "Languages",
              importance_band: "core",
              importance_score: 1,
              confidence: "high",
              modality: "required",
              evidence: [],
            },
          ],
        },
      },
    }),
  );
  await page.goto("/");
  await page.getByRole("article").first().click();

  const eyebrow = page.getByText("Role requirements", { exact: true });
  await expect(eyebrow).toBeVisible();
  // It wears both: the shared recipe and the one-property modifier.
  await expect(eyebrow).toHaveClass(/(^|\s)eyebrow(\s|$)/);
  await expect(eyebrow).toHaveClass(/(^|\s)req-eyebrow(\s|$)/);

  const paint = await eyebrow.evaluate((el) => {
    const s = getComputedStyle(el);
    const root = getComputedStyle(document.documentElement);
    const probe = (token: string) => {
      const d = document.createElement("span");
      d.style.color = `var(${token})`;
      document.body.append(d);
      const v = getComputedStyle(d).color;
      d.remove();
      return v;
    };
    return {
      color: s.color,
      action: probe("--app-action-text"),
      faint: probe("--app-text-faint"),
      transform: s.textTransform,
      family: s.fontFamily,
      rootOk: Boolean(root),
    };
  });

  // The modifier won: action ink, not the shared faint it would inherit if the
  // cascade had gone the other way.
  expect(paint.color).toBe(paint.action);
  expect(paint.color).not.toBe(paint.faint);
  // And the shared recipe is still doing its half of the job.
  expect(paint.transform).toBe("uppercase");
  expect(paint.family).toMatch(/Plex Mono/i);
});

/* Picking for comparison while reading. With only Back, the star and "View &
   apply" on the cover, and the twin deck as the only compare entry, a reader
   who decides while reading has to close, find the row again and hit its
   icon. The selection is server state, so
   a pick made here is still standing when the cover closes — and the beacon
   that would say so does not raise until the second role, which is why the
   cover states the waiting half itself. */

test("a role is picked for comparison while reading it, and the pick is still standing on return", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Staff Product Manager, API").click();

  const panel = detail(page);
  const toggle = panel.getByRole("button", { name: "Compare", exact: true });
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  // Nothing is claimed about a selection that does not exist yet.
  await expect(panel.getByText(/in compare/i)).toHaveCount(0);

  await toggle.click();
  await expect(panel.getByRole("button", { name: "In compare", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  // The waiting half, said where the gesture was made — and no promise of a
  // comparison that cannot be read yet.
  await expect(panel.getByText("1 in compare · pick one more")).toBeVisible();
  await expect(panel.getByRole("button", { name: /Compare 1 position/ })).toHaveCount(0);

  await page.getByRole("button", { name: "Back" }).click();
  await expect(page).toHaveURL(/\/$/);

  // Back on the board the role is already selected, waiting for its other half.
  const first = page.getByRole("article").filter({ hasText: "Staff Product Manager, API" });
  await expect(first.getByRole("button", { name: msg("jobs-compare") })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByRole("button", { name: /in compare/ })).toHaveCount(0);

  // The second role raises the beacon, exactly as if both had been picked here.
  const second = page.getByRole("article").filter({ hasText: "Principal Engineer, Platform" });
  await second.getByRole("button", { name: msg("jobs-compare") }).click();
  await expect(page.getByRole("button", { name: "2 in compare. Compare 2 roles" })).toBeVisible();
});

test("the second role picked while reading offers the comparison from the cover", async ({ page }) => {
  await page.goto("/");
  const first = page.getByRole("article").filter({ hasText: "Staff Product Manager, API" });
  await first.getByRole("button", { name: msg("jobs-compare") }).click();

  await page.getByText("Principal Engineer, Platform").click();
  const panel = detail(page);
  // The standing selection is stated even for a role that is not in it.
  await expect(panel.getByText("1 in compare · pick one more")).toBeVisible();

  await panel.getByRole("button", { name: "Compare", exact: true }).click();
  await expect(panel.getByRole("button", { name: "In compare", exact: true })).toBeVisible();
  await expect(panel.getByText("1 in compare · pick one more")).toHaveCount(0);

  const onward = panel.getByRole("button", { name: "Compare 2 roles" });
  await expect(onward).toBeVisible();
  await onward.click();
  await expect(page).toHaveURL(/\/compare$/);
  await expect(comparison(page)).toContainText("Comparing 2 roles");
});

test("the pick survives a reload of the cover itself", async ({ page }) => {
  // The gesture writes through to the store, not to the tab: a selection held
  // only in memory is lost on reload, and a cover reached by a direct link is
  // the case that would lose it silently.
  await page.goto("/job/202");
  const panel = detail(page);
  await panel.getByRole("button", { name: "Compare", exact: true }).click();
  await expect(panel.getByRole("button", { name: "In compare", exact: true })).toBeVisible();

  await page.reload();
  await expect(detail(page).getByRole("button", { name: "In compare", exact: true })).toBeVisible();
});

/* The cover's other occupant, on its failure path. A save that the
   server refuses rolls the star back and says so in a toast. Opened over a
   list, a toast rendered UNDER the cover would leave the star dark again with
   nothing on screen saying why. Both halves, as on the comparison: painted where it sits
   and reachable by a pointer there, and on the cover's Tab ring.

   The helper returns once the failure is ON SCREEN. The notice exists only
   after the server answers, and the cover reads its Tab ring at the keypress,
   so a Shift+Tab pressed before the notice arrives rightly goes round the
   cover alone, and the Tab-ring test would race it. The refusal also arrives a beat after the click, as a real
   server's does, so a helper that stops waiting fails every run, not some.
   */
async function openFailingSave(page: import("./fixtures").Page) {
  await page.route("/api/jobs/*/favorite", async (route) => {
    await new Promise((settle) => setTimeout(settle, 250));
    await route.fulfill({ status: 500, json: { detail: "unavailable" } });
  });
  await page.goto("/");
  await page.getByRole("article").first().getByRole("heading").click();
  const cover = page.getByRole("dialog", { name: /^Role:/ });
  await expect(cover).toHaveAttribute("aria-modal", "true");
  await expect.poll(() => strangersOver(cover)).toEqual([]);
  await cover.getByRole("button", { name: "Save", exact: true }).click();
  const toast = page.getByRole("status").filter({ hasText: "Couldn't save this role" });
  const close = toast.getByRole("button", { name: "Dismiss" });
  await expect(close).toBeVisible();
  return { cover, toast, close };
}

test("a failed save inside the cover is painted on top, and a pointer there clears it", async ({ page }) => {
  const { toast, close } = await openFailingSave(page);
  await expectOnTop(toast.getByText("Couldn't save this role"), "the failure notice");
  await expectOnTop(close, "its Dismiss");
  await pointAndClick(page, close);
  await expect(toast).toHaveCount(0);
});

test("a failed save inside the cover is on the cover's Tab ring", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "Tab order is a keyboard flow; a phone has no Tab key.");
  const { cover, toast, close } = await openFailingSave(page);
  await cover.getByRole("button", { name: "Back" }).focus();
  await page.keyboard.press("Shift+Tab");
  await expect(close).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(toast).toHaveCount(0);
});

/* A role RoleBand has dropped (removed after it stopped being listed) is
   said as that, with no Try again that cannot help; any other failure keeps
   Try again. Neither names the API or the service. */
test("a role that is gone says so, and a failed load offers Try again in the person's words", async ({ page }) => {
  await page.route("/api/jobs/9999", (route) => route.fulfill({ status: 404, json: { detail: "job not found" } }));
  await page.goto("/job/9999");
  const gone = page.getByRole("alert");
  await expect(gone).toContainText("Couldn't load this role");
  await expect(gone).toContainText("This role no longer exists.");
  await expect(gone.getByRole("button", { name: "Try again" })).toHaveCount(0);
  await expect(page.getByText(/API|service/)).toHaveCount(0);

  await page.route("/api/jobs/9998", (route) => route.fulfill({ status: 500, json: { detail: "boom" } }));
  await page.goto("/job/9998");
  const failed = page.getByRole("alert");
  await expect(failed).toContainText("Couldn't get it just now.");
  await expect(failed.getByRole("button", { name: "Try again" })).toBeVisible();
  await expect(page.getByText(/API|service/)).toHaveCount(0);
});
