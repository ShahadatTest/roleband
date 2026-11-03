import { expect, test } from "./fixtures";
import { expectMeasuredToolbar } from "./measuredToolbar";
import { installCompanyRegisterRoutes, installSettingsRoutes } from "./settingsHarness";
import { msg } from "../../src/test/msg";
import type { CompanyPrices, CompanyProfileDetail, CompanyProfileList } from "../../src/api";
import {
  companyCardFixture,
  companyProfileFieldsFixture,
  facetsFixture,
  jobFixture,
  jobListFixture,
  levelGuideFixture,
  notificationsFixture,
  profileFieldFixture,
  profileSectorOrderFixture,
  statsFixture,
  statusFixture,
  PLUGIN_SOURCE,
  PLUGIN_ATTRIBUTION,
  PLUGIN_NAME,
  OUR_SECTION,
  PLUGIN_SECTION,
} from "../../src/test/fixtures";

// Company Profiles: resolved values must be shown WITH their provenance, and a
// disagreement between sources must surface as a conflict — not be silently
// dropped. The Reddit fixture is that case: one source gives a ticker while
// another still says private (identity disputes are among RoleBand's own
// sources).
// Both outside the dataset, so they share the one group that opens on landing:
// these specs are about a profile, and the roster's folds have their own below.
const listFixture = {
  attribution: PLUGIN_ATTRIBUTION,
  sectors: profileSectorOrderFixture,
  items: [
    {
      slug: "google", display_name: "Google", logo_url: null, brand_color: null, is_public: true, ticker: "GOOG",
      equity_vehicle: "rsu", headcount: 258750,
      data_health: "ok", conflict_fields: [], mapped_levels: 5, sectors: [], in_dataset: false,
      price: 213.95, change_pct: -0.48, currency: "USD", price_as_of: "2026-07-13",
    },
    {
      slug: "reddit", display_name: "Reddit", logo_url: null, brand_color: null, is_public: true, ticker: "RDDT",
      equity_vehicle: "options", headcount: 1820,
      data_health: "conflict", conflict_fields: ["ticker", "is_public"],
      mapped_levels: 3, sectors: [], in_dataset: false,
      price: 168.4, change_pct: 1.21, currency: "USD", price_as_of: "2026-07-13",
    },
  ],
} satisfies CompanyProfileList;

const prices = (slug: string, ticker: string, price: number, change: number) => ({
  slug, range: "3m", currency: "USD",
  latest: { ticker, price, currency: "USD", change_abs: Math.sign(change), change_pct: change, as_of: "2026-07-13" },
  bars: [
    { date: "2026-07-10", open: price - 3, high: price + 1, low: price - 4, close: price - 2, volume: 1 },
    { date: "2026-07-13", open: price - 2, high: price + 2, low: price - 3, close: price, volume: 1 },
  ],
  attribution: "Price data: Tiingo",
  feed_configured: true,
} satisfies CompanyPrices);

const field = profileFieldFixture;

const googleDetail = {
  slug: "google", display_name: "Google", logo_url: null, brand_color: null, data_health: "ok", needs_review: [],
  fields: companyProfileFieldsFixture({ is_public: field(true), ticker: field("GOOG"), headcount: field(258750) }),
  comp_levels: [{
    level_label: "L7", band: "principal", currency: "USD", tc_median: 907556,
    base_amount: 315444, stock_amount: 499333, bonus_amount: 92778,
    base_pct: 0.3476, stock_pct: 0.5502, bonus_pct: 0.1022,
    source: PLUGIN_SOURCE, source_url: "https://pay.example/x",
  }],
  benefits: [{ category: "retirement_financial", items: [
    { name: "401k", benefit_type: "retirement_plan", value_usd: 9750, value_text: null, description: null,
      source: PLUGIN_SOURCE, provider: PLUGIN_SOURCE, builtin: false, kind: "provider", country: null,
      reviewed: false, mentions: 0, wordings: [] },
  ]}],
  level_base: [],
  benefit_notes: [],
  offer_policy: {
    verified_on: "2026-10-09",
    facts: [
      { fact: "equity_rule", value: "dollar_grant_by_level", stated_by: "estimated" },
      { fact: "bonus_rule", value: "pct_of_base", stated_by: "employer" },
      { fact: "annual_refresh", value: null, stated_by: null },
    ],
    unknown_fields: [],
  },
  comp_notes: null, open_roles: 3,
  /* Five US cities rather than one, and under TOP_N (6) so no section
     collapses. A single-item list cannot exercise the offices list's COLUMNS:
     one item is one column at every width, so a column regression would be
     invisible here. */
  locations: [
    {
      city: "Mountain View, CA", open_count: 2, groups: ["silicon_valley", "united_states"],
      is_hq: true, country: "united_states",
    },
    {
      city: "Sunnyvale, CA", open_count: 2, groups: ["silicon_valley", "united_states"],
      is_hq: false, country: "united_states",
    },
    {
      city: "New York, NY", open_count: 1, groups: ["new_york", "united_states"],
      is_hq: false, country: "united_states",
    },
    {
      city: "Seattle, WA", open_count: 1, groups: ["seattle", "united_states"],
      is_hq: false, country: "united_states",
    },
    {
      city: "Austin, TX", open_count: 1, groups: ["austin", "united_states"],
      is_hq: false, country: "united_states",
    },
    { city: "London, UK", open_count: 1, groups: ["london", "uk"], is_hq: false, country: "uk" },
  ],
  attribution: PLUGIN_ATTRIBUTION,
  source_names: { [PLUGIN_SOURCE]: PLUGIN_NAME },
  // The plugin answers pay and benefits, never identity.
  sources: { pay: PLUGIN_SECTION, benefits: PLUGIN_SECTION, company_size: OUR_SECTION },
  // A followed company.
  unfollowed: false,
} satisfies CompanyProfileDetail;

const SEC_TICKER = {
  source: "sec_edgar", rank: 80,
  value: "RDDT", observed_at: "2026-07-14T00:00:00Z",
};
const AGG_TICKER = {
  source: "reported", rank: 55,
  value: null, observed_at: "2026-07-14T00:00:00Z",
};

const redditDetail = {
  slug: "reddit", display_name: "Reddit", logo_url: null, brand_color: null, data_health: "conflict",
  fields: companyProfileFieldsFixture({
    is_public: field(true, {
      source: "sec_edgar", 
      conflicts: [{ source: "reported", value: false, observed_at: "2026-07-14T00:00:00Z" }],
    }),
    ticker: field("RDDT", {
      source: "sec_edgar", 
      conflicts: [{ source: "reported", value: null, observed_at: "2026-07-14T00:00:00Z" }],
    }),
  }),
  comp_levels: [{
    level_label: "IC5", band: "staff", currency: "USD", tc_median: 567618,
    base_amount: 296000, stock_amount: 271618, bonus_amount: 0,
    base_pct: 0.522, stock_pct: 0.478, bonus_pct: 0,
    source: PLUGIN_SOURCE, source_url: "https://pay.example/y",
  }],
  benefits: [], level_base: [], benefit_notes: [], offer_policy: null, comp_notes: null, open_roles: 2, locations: [],
  // A company whose health is "conflict" has a worklist to match — the two
  // sources above, offered as the choice that settles the field.
  needs_review: [{
    field: "ticker", reason: "conflict", current: "RDDT",
    suggestion: SEC_TICKER,
    candidates: [SEC_TICKER, AGG_TICKER],
  }],
  attribution: PLUGIN_ATTRIBUTION,
  source_names: { [PLUGIN_SOURCE]: PLUGIN_NAME },
  // The plugin answers pay and benefits, never identity.
  sources: { pay: PLUGIN_SECTION, benefits: PLUGIN_SECTION, company_size: OUR_SECTION },
  // A followed company.
  unfollowed: false,
} satisfies CompanyProfileDetail;

test.beforeEach(async ({ page }) => {
  await page.route("/api/stats", (r) => r.fulfill({ json: statsFixture }));
  await page.route("/api/status", (r) => r.fulfill({ json: statusFixture }));
  await page.route("/api/facets", (r) => r.fulfill({ json: facetsFixture }));
  await page.route("/api/notifications**", (r) => r.fulfill({ json: notificationsFixture }));
  await page.route("/api/jobs/*/similar**", (r) => r.fulfill({ json: { scope: "cross", items: [] } }));
  await page.route("/api/jobs/101", (r) => r.fulfill({ json: jobFixture }));
  await page.route("/api/jobs?**", (r) => r.fulfill({ json: jobListFixture }));
  await page.route("/api/company-profiles", (r) => r.fulfill({ json: listFixture }));
  await page.route("/api/statistics/levels", (r) => r.fulfill({ json: levelGuideFixture }));
  await page.route("/api/company-profiles/google/prices**", (r) =>
    r.fulfill({ json: prices("google", "GOOG", 213.95, -0.48) }));
  await page.route("/api/company-profiles/reddit/prices**", (r) =>
    r.fulfill({ json: prices("reddit", "RDDT", 168.4, 1.21) }));
  await page.route("/api/company-profiles/google", (r) => r.fulfill({ json: googleDetail }));
  await page.route("/api/company-profiles/reddit", (r) => r.fulfill({ json: redditDetail }));
  await page.route("/api/companies/*/card", (r) =>
    r.fulfill({ json: companyCardFixture }));
});

test("a profile toolbar arriving after loading measures CSS-only reflow in both themes", async ({ page }) => {
  for (const theme of ["light", "dark"]) {
    let release!: () => void;
    const loaded = new Promise<void>((resolve) => { release = resolve; });
    await page.route("/api/company-profiles", async (route) => {
      await loaded;
      await route.fulfill({ json: listFixture });
    });
    await page.goto("/company/google");
    await expect(page.locator(".prof-main")).toBeVisible();
    await expect(page.locator(".prof-toolbar")).toHaveCount(0);
    release();
    await expect(page.getByRole("heading", { name: "Offices & open roles" })).toBeVisible();
    await page.locator("html").evaluate((node, value) => node.setAttribute("data-theme", value), theme);
    await expect(page.getByRole("heading", { name: "Companies", exact: true, level: 1 })).toHaveCount(1);
    await expectMeasuredToolbar(page, ".prof-main", ".prof-toolbar", "--prof-toolbar-h");
  }
});

/* One screen, one empty voice.
 *
 * Left to each part, `/company` makes three claims about this single state:
 * the selector rail says "Nothing needs review right now" (it renders
 * whenever the filtered list is empty and the query is blank, false here),
 * the profile pane "No company profiles yet", and the toolbar "0 companies ·
 * all profiles current" over a search box with nothing to search. An empty
 * roster means exactly one thing, so the screen says exactly one thing. */
test("an untracked roster says the one true thing, and routes to the fix", async ({ page }) => {
  await page.route("/api/company-profiles", (r) =>
    r.fulfill({ json: { items: [], attribution: listFixture.attribution } }));

  await page.goto("/company");

  await expect(page.getByText("You don't follow any company yet")).toBeVisible();
  await expect(page.getByText(/Nothing needs review/)).toHaveCount(0);
  await expect(page.getByText(/No company profiles yet/)).toHaveCount(0);
  await expect(page.getByLabel("Search companies")).toHaveCount(0);

  // The link's destination loads its own data, and those requests land after
  // the URL changes. Serve them, and hold the test until the register renders
  // from them: a URL alone would end the test mid-load, and "routes to the
  // fix" means arriving at a screen that works.
  await installCompanyRegisterRoutes(page);
  await page.getByRole("link", { name: "Settings › Companies" }).click();
  await expect(page).toHaveURL(/\/settings\/companies$/);
  await expect(page.getByRole("region", { name: "FAANG", exact: true })
    .getByRole("checkbox", { name: "Google" })).toBeChecked();
});

test("company profile lists offices observed from open postings", async ({ page }) => {
  await page.goto("/company/google");

  await expect(page.getByRole("heading", { name: "Offices & open roles" })).toBeVisible();

  // Each country is its own section, busiest first.
  const us = page.getByRole("list", { name: "Offices in United States" });
  await expect(us.getByRole("listitem")).toHaveCount(5);
  await expect(us).toContainText("Mountain View, CA");
  await expect(us).toContainText("HQ");

  const uk = page.getByRole("list", { name: "Offices in UK" });
  await expect(uk).toContainText("London, UK");

  // The country filter narrows to one section.
  await page.getByRole("button", { name: "Filter by country" }).click();
  await page.getByRole("option", { name: /^UK/ }).click();
  await expect(page.getByRole("list", { name: "Offices in United States" })).toHaveCount(0);
  await expect(page.getByRole("list", { name: "Offices in UK" })).toBeVisible();
  // Multi-select stays open on pick; close it before touching the page behind.
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Close Country filter" })).toHaveCount(0);

  // A profile whose postings carry no resolvable city shows no empty shell.
  await page.getByRole("button", { name: /Reddit/ }).click();
  await expect(page.getByRole("heading", { name: "Offices & open roles" })).toHaveCount(0);
});

/* The offices list must never answer "how many columns" with the viewport.
 *
 * The profile's OWN 900 arm drops `.prof-shell`'s 260px company-selector
 * column, so `.prof-body` gets much WIDER at that pixel. A list that drops to
 * one column under a `@media (max-width: 900px)` arm would go a column poorer
 * exactly as it got wider: the viewport standing in for a width the viewport
 * has just changed.
 *
 * The property is monotonicity, not a count: a wider list may never have FEWER
 * columns. Asserting exact counts would pin the chosen column width instead,
 * which is a tuning number and not the contract. The premise is asserted too —
 * a list that failed to get wider, or that renders one column at both widths,
 * would make this pass while measuring nothing. */
test("the offices list gains columns as it widens, never loses them", async ({ page }) => {
  const list = page.locator(".office-list").first();
  const measure = async (width: number) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/company/google");
    await expect(list).toBeVisible();
    return list.evaluate((ol) => ({
      width: Math.round(ol.getBoundingClientRect().width),
      // Distinct left edges IS the rendered column count; `column-count`
      // computes to `auto` whenever the width is what decides.
      columns: new Set(
        [...ol.children].map((li) => Math.round(li.getBoundingClientRect().left)),
      ).size,
      // A column too narrow for its rows shows up as a taller row, not as a
      // count — so the ellipsis contract is checked here rather than by eye.
      tallestRow: Math.max(...[...ol.children].map((li) => Math.round(li.getBoundingClientRect().height))),
    }));
  };

  // Straddle the profile's own breakpoint: the selector column is present at
  // 901 and gone at 899, which is what makes the list jump wider.
  const narrow = await measure(901);
  const wide = await measure(899);

  expect(
    wide.width,
    `premise failed: the list did not get wider when the selector column went (${narrow.width} -> ${wide.width})`,
  ).toBeGreaterThan(narrow.width);
  expect(
    narrow.columns,
    "premise failed: one column at the narrow width means this test cannot see a loss",
  ).toBeGreaterThanOrEqual(2);

  expect(
    wide.columns,
    `the list is ${wide.width}px wide in ${wide.columns} column(s) but was ${narrow.width}px in ${narrow.columns} — it lost a column by growing`,
  ).toBeGreaterThanOrEqual(narrow.columns);

  // Single-line rows at both widths: the city label ellipsises, it never wraps.
  expect(narrow.tallestRow).toBeLessThan(40);
  expect(wide.tallestRow).toBeLessThan(40);
});

test("company profiles show provenance, and surface conflicting signals", async ({ page }) => {
  await page.goto("/company");

  // The screen leads with the same page header as every other route.
  await expect(page.getByRole("heading", { level: 1, name: "Companies" })).toBeVisible();

  // The toolbar owns the counts and flags how many need attention, of the
  // companies SHOWN: not the roster's own totals over a list the search box
  // and the review lens have already narrowed.
  await expect(page.getByText(/1 needs review/)).toBeVisible();
  // The screen wears the register material, like settings/companies — without
  // it the shared action set falls back to gold and the register look is gone.
  await expect(page.locator("body")).toHaveAttribute("data-material", "register");

  // Companies are reachable by accessible name — the conflict is part of it, so a
  // screen-reader user learns of it without seeing the colour.
  const google = page.getByRole("button", { name: "Google", exact: true });
  await expect(google).toBeVisible();
  const reddit = page.getByRole("button", { name: /Reddit — Conflicting signals/ });
  await expect(reddit).toBeVisible();

  // Identity is RoleBand's own: a field never names the plugin the
  // footer credits for the ladder and benefits. Provenance display is proven on
  // Reddit below, where two of RoleBand's own sources disagree.
  const ticker = page.locator(".prof-field", { hasText: "Ticker" });
  await expect(ticker).toContainText("GOOG");
  await expect(ticker).not.toContainText(PLUGIN_NAME);
  await expect(page.getByText(PLUGIN_ATTRIBUTION)).toBeVisible();

  // Comp baseline splits cash from equity.
  const row = page.getByRole("row", { name: /Principal/ });
  await expect(row).toContainText("$908K");
  await expect(row).toContainText("55%");

  // Switch to the company with disagreeing sources.
  await reddit.click();
  // The hero keeps the health signal as a compact dot next to the name.
  await expect(page.locator(".prof-name-row .health-dot.health-conflict")).toBeVisible();

  // The higher-trust source wins the value...
  const rTicker = page.locator(".prof-field", { hasText: "Ticker" });
  await expect(rTicker).toContainText("RDDT");
  await expect(rTicker).toContainText("SEC EDGAR");
  // ...and the dissenting claim is stated explicitly, not swallowed.
  await expect(rTicker).toContainText(/Conflicting signal:\s*Estimated says\s*none/);
  const listed = page.locator(".prof-field", { hasText: "Listed" });
  await expect(listed).toContainText(/Conflicting signal:\s*Estimated says\s*No/);

  // A company with no benefits data says it was not collected, never that there are none or $0.
  await expect(page.getByText(msg("profiles-benefits-not-collected"))).toBeVisible();

  // Attribution is a license condition of using this data.
  await expect(page.getByText(PLUGIN_ATTRIBUTION)).toBeVisible();
});

test("the toolbar filter narrows the list to companies needing review", async ({ page }) => {
  await page.goto("/company");
  await expect(page.getByRole("button", { name: "Google", exact: true })).toBeVisible();

  await page.getByLabel("Needs review only").check();
  await expect(page.getByRole("button", { name: "Google", exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /Reddit — Conflicting signals/ }),
  ).toBeVisible();

  // Unchecking restores the full roster.
  await page.getByLabel("Needs review only").uncheck();
  await expect(page.getByRole("button", { name: "Google", exact: true })).toBeVisible();
});

test("enrichment arrives with the button, not with the page", async ({ page }) => {
  await page.goto("/company/reddit");

  // At rest the flagged field SAYS it is flagged...
  const ticker = page.locator(".prof-field", { hasText: "Ticker" });
  await expect(ticker).toContainText("Sources disagree");
  // ...and offers no way to change the value: the dossier opens to be read.
  await expect(page.getByLabel(/Custom value for Ticker/i)).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /Set Ticker to RDDT from SEC EDGAR/i }),
  ).toHaveCount(0);

  // The decision is the button, in the toolbar's action slot.
  const enrich = page.locator(".prof-toolbar").getByRole("button", { name: "Enrich fields" });
  await expect(enrich).toHaveAttribute("aria-pressed", "false");
  await enrich.click();

  await expect(enrich).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel(/Custom value for Ticker/i)).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Set Ticker to RDDT from SEC EDGAR/i }),
  ).toBeVisible();

  // ...and it is a mode, so it can be put away again.
  await enrich.click();
  await expect(page.getByLabel(/Custom value for Ticker/i)).toHaveCount(0);
});

test("a public company shows its stock price and history", async ({ page }) => {
  await page.goto("/company");
  // Google is selected by default (first, public) — its price panel renders.
  await expect(page.getByRole("heading", { name: "Stock price" })).toBeVisible();
  await expect(page.locator(".prof-price-quote")).toHaveText("$213.95");
  await expect(page.getByTestId("stock-day-move")).toHaveText("-$1.00 (-0.48%)");
  await expect(page.getByTestId("stock-ticker")).toHaveText("GOOG");
});

test("a company profile deep-links from the URL and jumps to its open roles", async ({ page }) => {
  // The job→company hover card lands here: /company/reddit selects Reddit.
  await page.goto("/company/reddit");
  const reddit = page.getByRole("button", { name: /Reddit — Conflicting signals/ });
  await expect(reddit).toHaveAttribute("aria-current", "true");

  // The company→jobs cross-link (beige open-roles pill) carries the company into
  // the board filter.
  const pill = page.getByRole("button", { name: /See 2 open roles at Reddit/i });
  await expect(pill).toHaveAttribute("title", "See open roles");
  await pill.click();
  await expect(page).toHaveURL(/\/\?company=reddit/);
  // The board requested only Reddit's jobs.
  await expect(page.getByRole("heading", { name: "Radar" })).toBeVisible();
});

test("a ?slug= query link redirects to the /company/:slug path form", async ({ page }) => {
  // Shared or bookmarked query-string links must keep working beside the path form.
  await page.goto("/company?slug=reddit");
  await expect(page).toHaveURL(/\/company\/reddit$/);
  await expect(page.getByRole("button", { name: /Reddit — Conflicting signals/ })).toHaveAttribute(
    "aria-current",
    "true",
  );
});

test("picking a company writes its slug into the URL path", async ({ page }) => {
  await page.goto("/company");
  // Google is the default (first, public); pick Reddit and the path follows.
  await page.getByRole("button", { name: /Reddit — Conflicting signals/ }).click();
  await expect(page).toHaveURL(/\/company\/reddit$/);
});

/* --- Master–detail geometry ------------------------------------------------
 *
 * Statements about the rendered page that hold however the CSS is written, so
 * they can falsify it: a wide void between the selector and the profile fails
 * here. An invariant derived from the implementation cannot falsify the
 * implementation. */

const GUTTER_MAX = 24;

for (const width of [1440, 2300, 3440]) {
  test(`the company selector sits beside the profile it selects at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/company/google");
    await expect(page.getByRole("heading", { name: "Offices & open roles" })).toBeVisible();

    const panelOf = (name: string) =>
      page
        .getByRole("heading", { name, exact: true })
        .locator("xpath=ancestor::div[contains(concat(' ', @class, ' '), ' panel ')][1]");

    // The list has no panel box or heading: the selector column is the flat
    // index itself.
    const selector = await page.locator(".prof-list").boundingBox();
    const profile = await panelOf("Google").boundingBox();
    expect(selector).not.toBeNull();
    expect(profile).not.toBeNull();

    // One gutter between the list and the profile it drives — they are one
    // block, not two floating cards.
    const gap = profile!.x - (selector!.x + selector!.width);
    expect(gap).toBeGreaterThanOrEqual(0);
    expect(gap).toBeLessThanOrEqual(GUTTER_MAX);

    // ...and closing that gap must not be paid for by shrinking the profile.
    expect(profile!.width).toBeGreaterThanOrEqual(width >= 2300 ? 1200 : 900);
  });
}

test("nothing on the company route renders outside the block that holds it", async ({ page }) => {
  await page.setViewportSize({ width: 2300, height: 1000 });
  await page.goto("/company/google");
  await expect(page.getByRole("heading", { name: "Offices & open roles" })).toBeVisible();

  const escapees = await page.evaluate(() => {
    const root = document.querySelector(".prof-main");
    if (!root) return ["no .prof-main"];
    const bounds = root.getBoundingClientRect();
    const out: string[] = [];
    for (const el of Array.from(root.querySelectorAll("*"))) {
      const b = el.getBoundingClientRect();
      if (b.width === 0 || b.height === 0) continue;
      const over = Math.max(b.right - bounds.right, bounds.left - b.left);
      if (over > 1) out.push(`${el.tagName}.${el.className} by ${Math.round(over)}px`);
    }
    return out.slice(0, 8);
  });
  expect(escapees).toEqual([]);
});

test("the company route settles on a single pair of outer edges", async ({ page }) => {
  await page.setViewportSize({ width: 2300, height: 1000 });
  await page.goto("/company/google");
  await expect(page.getByRole("heading", { name: "Offices & open roles" })).toBeVisible();

  // Every card on the route is either in the selector column or the profile
  // column, so the route shows two left edges and two right edges — no more.
  const edges = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll(".prof-main .panel"));
    const round = (n: number) => Math.round(n);
    return {
      left: [...new Set(cards.map((c) => round(c.getBoundingClientRect().left)))].sort((a, b) => a - b),
      right: [...new Set(cards.map((c) => round(c.getBoundingClientRect().right)))].sort((a, b) => a - b),
    };
  });
  expect(edges.left.length).toBeLessThanOrEqual(2);
  expect(edges.right.length).toBeLessThanOrEqual(2);
});

/* The roster: the dataset first, folded by the sectors Settings lists, then
 * every other followed company; and a list that scrolls on its own, so
 * reaching a name never means scrolling the page, and the profile with it, to
 * the bottom of a long roster. */
test.describe("the company roster", () => {
  const row = (slug: string, name: string, over: Partial<CompanyProfileList["items"][number]> = {}) => ({
    ...listFixture.items[0], slug, display_name: name, ticker: null, price: null, change_pct: null,
    currency: null, price_as_of: null, ...over,
  });
  const ROSTER = {
    ...listFixture,
    items: [
      row("amazon", "Amazon", { in_dataset: true, sectors: ["faang"] }),
      row("google", "Google", { in_dataset: true, sectors: ["faang"] }),
      row("openai", "OpenAI", { in_dataset: true, sectors: ["ai"] }),
      row("stripe", "Stripe", { in_dataset: true, sectors: ["fintech"] }),
      // A long tail, as the wider-market set makes it: 400 rows.
      ...Array.from({ length: 400 }, (_, i) =>
        row(`other-${String(i).padStart(3, "0")}`, `Other ${String(i).padStart(3, "0")}`)),
    ],
  } satisfies CompanyProfileList;

  test.beforeEach(async ({ page }) => {
    await page.route("/api/company-profiles", (r) => r.fulfill({ json: ROSTER }));
    await page.route("/api/company-profiles/*", (r) => {
      const slug = new URL(r.request().url()).pathname.split("/").pop()!;
      const name = ROSTER.items.find((c) => c.slug === slug)?.display_name ?? slug;
      return r.fulfill({ json: { ...googleDetail, slug, display_name: name } });
    });
    await page.route("/api/company-profiles/*/prices**", (r) =>
      r.fulfill({ json: prices("google", "GOOG", 213.95, -0.48) }));
  });

  test("lands on the dataset with only the selected company's sector open", async ({ page }) => {
    await page.goto("/company");
    const list = page.locator(".prof-list");
    await expect(list.getByRole("button", { name: "Amazon" })).toHaveAttribute("aria-current", "true");
    await expect(list.getByRole("button", { name: msg("vocab-sector-faang"), expanded: true })).toBeVisible();
    for (const folded of [msg("vocab-sector-ai"), msg("vocab-sector-fintech"), msg("companies-model-other-companies")]) {
      await expect(list.getByRole("button", { name: folded, expanded: false })).toBeVisible();
    }
    await expect(list.getByRole("button", { name: "Other 000" })).toHaveCount(0);

    // A search reaches into a fold; clearing it folds the group again.
    await page.getByLabel("Search companies").fill("strip");
    await expect(list.getByRole("button", { name: "Stripe" })).toBeVisible();
    await page.getByLabel("Search companies").fill("");
    await expect(list.getByRole("button", { name: "Stripe" })).toHaveCount(0);
  });

  test("picking companies keeps the screen mounted: no roster re-read, folds kept", async ({ page }) => {
    let reads = 0;
    await page.route("/api/company-profiles", (r) => { reads += 1; return r.fulfill({ json: ROSTER }); });
    await page.goto("/company");
    const list = page.locator(".prof-list");
    await expect(list.getByRole("button", { name: "Amazon" })).toBeVisible();
    // Counted after load: the dev server's StrictMode mounts twice on purpose.
    const atLoad = reads;
    expect(atLoad).toBeGreaterThan(0);
    await list.getByRole("button", { name: msg("vocab-sector-ai"), expanded: false }).click();
    await list.getByRole("button", { name: "OpenAI" }).click();
    await expect(page).toHaveURL(/\/company\/openai$/);
    await list.getByRole("button", { name: "Google" }).click();
    await expect(page).toHaveURL(/\/company\/google$/);
    await expect(page.locator(".prof-body").getByRole("heading", { name: "Google", exact: true })).toBeVisible();
    // A remount would refetch the roster and fold AI again.
    await expect(list.getByRole("button", { name: msg("vocab-sector-ai"), expanded: true })).toBeVisible();
    expect(reads).toBe(atLoad);
  });

  test("a link to a company far down the list shows its row, scrolling only the list", async ({ page }) => {
    await page.goto("/company/other-350");
    const row = page.locator(".prof-list").getByRole("button", { name: "Other 350" });
    await expect(row).toHaveAttribute("aria-current", "true");
    await expect(row).toBeInViewport();
    expect(await page.locator(".prof-main").evaluate((el) => el.scrollTop)).toBe(0);
  });

  /* Same content, same type. The list's left column is
   * the same substance as Settings' left Sectors index, so its section label
   * and sector folds wear the INDEX (`.ledger-index-label`, `.ledger-index
   * button`: name, count, height), never the register's wide sector heads in
   * the middle of the page. Company rows
   * wear the register's rows. Both screens are measured in one run, so the
   * comparison holds whatever either stylesheet is changed to. */
  test("the company list wears the Settings register's type and rows", async ({ page, isMobile }) => {
    test.skip(isMobile, "the register's phone layout has its own row height and columns");
    await page.setViewportSize({ width: 1440, height: 900 });
    await installSettingsRoutes(page);
    const type = (el: Element | null) => {
      if (!el) return null;
      const c = getComputedStyle(el);
      return [c.fontFamily, c.fontSize, c.fontWeight, c.letterSpacing, c.textTransform, c.color,
        c.borderBottomColor].join(" | ");
    };
    type Sample = Record<string, string | number | null>;

    await page.goto("/settings/companies");
    await expect(page.locator(".ledger-sector-title").first()).toBeVisible();
    const settings: Sample = await page.evaluate(`(${((t: typeof type) => {
      const followed = document.querySelector(".ledger-row:has(.ui-switch-track:checked)");
      const sector = document.querySelector(".ledger-index button:not([aria-current])")!;
      return {
        sectionLabel: t(document.querySelector(".ledger-index-label")),
        sectionLabelHeight: Math.round(document.querySelector(".ledger-index-label")!.getBoundingClientRect().height),
        sectorName: t(sector.querySelector(".ledger-index-row > span")),
        sectorCount: t(sector.querySelector(".ledger-index-row > b")),
        sectorHeight: Math.round(sector.getBoundingClientRect().height),
        name: t(followed?.querySelector(".ledger-name > span:first-child") ?? null),
        rowHeight: Math.round(followed!.getBoundingClientRect().height),
        markSize: Math.round(followed!.querySelector(".ledger-mark")!.getBoundingClientRect().width),
      };
    }).toString()})(${type.toString()})`);

    await page.goto("/company/amazon");
    await expect(page.locator('.prof-nav button[aria-current="true"]')).toBeVisible();
    const list: Sample = await page.evaluate(`(${((t: typeof type) => {
      const row = document.querySelector('.prof-nav li:not(:has([aria-current="true"])) button') ?? document.querySelector(".prof-nav button");
      // A folded sector, as the index's sectors are, and one whose name fits one line.
      const fold = [...document.querySelectorAll(".prof-group-fold > .prof-group-head")]
        .find((h) => h.querySelector('[aria-expanded="false"]') && (h.textContent ?? "").length < 16)!;
      return {
        sectionLabel: t(document.querySelector(".prof-section-head")),
        sectionLabelHeight: Math.round(document.querySelector(".prof-section-head")!.getBoundingClientRect().height),
        sectorName: t(fold.querySelector(".prof-group-disclose")),
        sectorCount: t(fold.querySelector(".prof-group-count")),
        sectorHeight: Math.round(fold.getBoundingClientRect().height),
        name: t(row!.querySelector(".prof-nav-name")),
        rowHeight: Math.round(row!.getBoundingClientRect().height),
        markSize: Math.round(row!.querySelector(".company-logo, .ui-company-icon")!.getBoundingClientRect().width),
      };
    }).toString()})(${type.toString()})`);

    expect(list).toEqual(settings);
  });

  test("the list scrolls on its own: its last row is reached without moving the page", async ({ page, isMobile }) => {
    test.skip(isMobile, "one column: the list is a bounded box above the profile");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/company");
    const list = page.locator(".prof-list");
    await list.getByRole("button", { name: msg("companies-model-other-companies"), expanded: false }).click();
    const last = list.getByRole("button", { name: "Other 399" });
    await expect(last).toBeAttached();

    // The premise: 400 rows are far taller than the window.
    const sizes = await list.evaluate((el) => ({ scroll: el.scrollHeight, client: el.clientHeight }));
    expect(sizes.scroll).toBeGreaterThan(sizes.client * 4);
    // The list ends inside the window rather than running past its bottom.
    const box = (await list.boundingBox())!;
    expect(box.y + box.height).toBeLessThanOrEqual(900);

    await last.scrollIntoViewIfNeeded();
    await expect(last).toBeInViewport();
    await last.click();
    await expect(page).toHaveURL(/\/company\/other-399$/);
    expect(await list.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
    // The page never moved: the toolbar and the profile's head are where they were.
    expect(await page.locator(".prof-main").evaluate((el) => el.scrollTop)).toBe(0);
    await expect(page.locator(".prof-body").getByRole("heading", { name: "Other 399", exact: true })).toBeInViewport();
  });
});

/* How offers are built and Benefits, in a real browser at a desktop and a
 * phone width: the atlas's facts with who states them, the two offer fields
 * kept apart from the identity facts, and an estimate shown as one. */
test("a profile says how offers are built and labels a benefit estimate", async ({ page }) => {
  await page.goto("/company/google");
  const offers = page.locator(".panel").filter({ has: page.getByRole("heading", { name: msg("profiles-offer-heading") }) });
  await expect(offers).toBeVisible();
  const fact = (label: string) => offers.locator(".prof-field").filter({ has: page.getByText(label, { exact: true }) });
  const equity = fact(msg("profiles-offer-fact", { fact: "equity_rule" }));
  await expect(equity).toContainText(msg("profiles-offer-equity-rule", { rule: "dollar_grant_by_level" }));
  await expect(equity).toContainText(msg("vocab-source-reported"));
  await expect(fact(msg("profiles-offer-fact", { fact: "annual_refresh" })))
    .toContainText(msg("profiles-offer-searched-not-found"));
  await expect(offers.getByText(msg("profiles-labels-equity-vehicle"))).toBeVisible();
  await expect(page.getByText(msg("profiles-labels-equity-vehicle"), { exact: true })).toHaveCount(1);

  const benefit = page.locator(".benefit-list li").first();
  await expect(benefit).toContainText(msg("profiles-benefits-estimate", { value: "$10K" }));
  await expect(benefit.locator(".benefit-terms")).toHaveCount(0);  // no filler line under an estimate

  // A company never researched says so once.
  await page.locator(".prof-list").getByRole("button", { name: /Reddit/ }).click();
  await expect(page.getByText(msg("profiles-offer-not-researched"))).toBeVisible();
  await expect(page.getByText(msg("profiles-benefits-not-collected"))).toBeVisible();
});

/* Our dataset's benefits, one row per benefit, never one row per posting
 * mention. In a real browser at a desktop and a
 * phone width: the shared sentence once, name-only benefits on one line, other
 * wordings folded behind a toggle, and nothing wider than the page. */
test("our benefits read one row per benefit, with shared sentences said once", async ({ page }) => {
  const said = "Medical, Dental, and Vision Coverage";
  const row = (over: Record<string, unknown>) => ({
    name: null, benefit_type: "vacation", value_usd: null, value_text: null, description: null, source: "builtin",
    provider: "builtin", builtin: true, kind: "dataset" as const, country: null, reviewed: false, mentions: 0,
    wordings: [], ...over,
  });
  const amazon = {
    ...googleDetail, slug: "google", display_name: "Google", attribution: null, source_names: {},
    sources: { pay: OUR_SECTION, benefits: OUR_SECTION, company_size: OUR_SECTION },
    benefits: [
      { category: "health_wellbeing", items: [
        row({ benefit_type: "dental_insurance", kind: "employer", mentions: 73 }),
        row({ benefit_type: "onsite_clinic" }),
        row({ benefit_type: "pet_insurance" }),
      ] },
      { category: "retirement_financial", items: [row({
        benefit_type: "retirement_plan", mentions: 75,
        value_text: "Match vests only after 3 years. You can contribute up to 90% of your salary on a pre-tax basis.",
        wordings: [{ text: "401(k) Plan", kind: "employer", country: null }],
      })] },
    ],
    benefit_notes: [{ text: said, mentions: 27, benefit_types: ["dental_insurance", "medical_insurance"] }],
  } satisfies CompanyProfileDetail;
  await page.route("/api/company-profiles/google", (r) => r.fulfill({ json: amazon }));
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/company/google");
    const section = page.locator(".panel").filter({ has: page.getByRole("heading", { name: msg("profiles-company-profile-panel-benefits") }) });
    await expect(section.getByText(said)).toHaveCount(1);
    await expect(section.getByTestId("benefit-notes")).toContainText(msg("profiles-benefits-mentions", { count: 27 }));
    const names = [msg("profiles-benefits-type", { type: "onsite_clinic" }), msg("profiles-benefits-type", { type: "pet_insurance" })];
    await expect(section.locator(".benefit-also")).toHaveText(msg("profiles-benefits-also-listed", { names: `${names[0]} and ${names[1]}` }));
    const plan = section.locator(".benefit-list li").filter({ hasText: "Match vests only after 3 years." });
    await expect(plan.getByText("401(k) Plan")).toHaveCount(0);
    await plan.getByRole("button", { name: msg("profiles-benefits-other-wordings", { open: "no", count: 1 }) }).click();
    await expect(plan.getByText("401(k) Plan")).toBeVisible();
    // Nothing in the section is wider than the page: long sentences wrap.
    const overflow = await section.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  }
});

/* Our own baseline: base per level from our dataset while no pay
 * plugin is on, with what each figure rests on, and the company's own code
 * for each level from the level guide. */
test("our baseline shows base and the company's code per level and fits a phone", async ({ page }) => {
  const level = (band: string, base: number, over: Record<string, unknown> = {}) => ({
    band, base_usd: base, bonus_ratio: 0, bonus_usd: 0, below_lower: false, stock_usd: 170160,
    total_usd: base + 170160, ...over,
  });
  const ours = {
    ...googleDetail, attribution: null, source_names: {}, comp_levels: [],
    sources: { pay: OUR_SECTION, benefits: OUR_SECTION, company_size: OUR_SECTION },
    level_base: [level("entry", 129000), level("mid", 173496), level("senior", 196900),
                 level("principal", 247100), level("director_plus", 307050)],
  } satisfies CompanyProfileDetail;
  await page.route("/api/company-profiles/google", (r) => r.fulfill({ json: ours }));
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/company/google");
    const table = page.getByTestId("level-base");
    await expect(table.locator("tbody tr")).toHaveCount(5);
    await expect(table.getByRole("columnheader", { name: msg("profiles-company-profile-panel-level") })).toBeVisible();
    // The engineering ladder's code: Google's L8 sits with Principal there.
    const principal = table.locator("tbody tr").filter({ hasText: msg("taxonomy-band-principal") });
    await expect(principal.locator("td").first()).toHaveText("L7–L8");
    await expect(principal.locator("td").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Comp bands" })).toBeVisible();
    await expect(table).not.toContainText(/reported|pay filings|posted ranges/i);
    await expect(table.getByRole("columnheader", { name: "From", exact: true })).toHaveCount(0);
    const estimated = table.locator("tbody tr").filter({ hasText: msg("taxonomy-band-senior") });
    await expect(estimated).toContainText("$197K");
    await expect(estimated).toContainText("$170K");
    await expect(page.locator(".split-legend")).toHaveCount(0);
    const panel = page.locator(".panel").filter({ has: table });
    expect(await panel.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(0);
  }
});
