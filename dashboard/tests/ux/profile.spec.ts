import { expect, test } from "./fixtures";
import {
  emptyScopeCellsFixture, facetsFixture, jobListFixture, notificationsFixture, profileSuggestionFixture, settingsSaveFixture,
  statsFixture, statusFixture, usageStateFixture,
} from "../../src/test/fixtures";
import { companyList, scopeCatalog, scopePreview } from "./scopeFixtures";
import { companyDiscovery, companyOpenCounts } from "./settingsHarness";
import type { ProfileSuggestion, ScopeSettingsPayload } from "../../src/api";

/* Profile: the first-class home for the candidate. Direction is the whole
   section, and Direction is the walk: five
   screens, one question each, a Summary, and a progress rail. The retired
   slugs must still land somewhere real; that is asserted below. */

test.beforeEach(async ({ page }) => {
  await page.route("/api/**", async (route) => {
    await route.abort("blockedbyclient");
    throw new Error(`Unmocked profile API request: ${route.request().url()}`);
  });
  // The page-level guard outranks context fixtures; repeat the two shared
  // bootstrap reads so both stay mocked before Profile mounts.
  await page.route("/api/companies/names", (route) => route.request().method() === "GET" ? route.fulfill({ json: { names: {} } }) : route.fallback());
  await page.route("/api/compare-selection", (route) => route.request().method() === "GET" ? route.fulfill({ json: { job_ids: [] } }) : route.fallback());
  await page.route("/api/settings/locale", (route) => route.request().method() === "GET" ? route.fulfill({ json: { language: "en", region: null } }) : route.fallback());
  await page.route("/api/usage", (route) => route.request().method() === "GET" ? route.fulfill({ json: usageStateFixture("declined") }) : route.fallback());
  await page.route("/api/scope/rules", (route) => route.fulfill({ json: { rules: [] } }));
  await page.route("/api/stats", (route) => route.fulfill({ json: statsFixture }));
  await page.route("/api/status", (route) => route.fulfill({ json: statusFixture }));
  await page.route("/api/companies/directory/status", (route) => route.fulfill({ json: { size: 0, following: false, since: null, checked: 0, to_check: 0, with_roles: 0, waiting_for_power: false } }));
  await page.route("/api/facets", (route) => route.fulfill({ json: facetsFixture }));
  await page.route("/api/notifications**", (route) => route.fulfill({ json: notificationsFixture }));
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: jobListFixture }));
  await page.route("/api/scope/catalog", (route) => route.fulfill({ json: scopeCatalog }));
  await page.route("/api/scope/preview", (route) => route.fulfill({ json: scopePreview }));
  // The location search. Empty by default: the catalog's own
  // places answer; a test that needs a city routes its own answer.
  await page.route("/api/scope/places?**", (route) => route.fulfill({ json: { places: [], unions: [] } }));
  await page.route("/api/profile", (route) => route.fulfill({
    json: { profile: null, scope_configured: true },
  }));
  await page.route("/api/profile/suggestions", (route) => route.fulfill({
    json: { suggestions: [] },
  }));
  // The optional pay floor: unset, and a save echoes what it saved.
  await page.route("/api/profile/pay-floor", (route) => route.fulfill({
    json: { pay_floor: route.request().method() === "PUT" ? route.request().postDataJSON() : null },
  }));
  await page.route("/api/companies", (route) => route.fulfill({ json: companyList }));
});

const offSuggestion: ProfileSuggestion = {
  ...profileSuggestionFixture,
  world: "logistics_fulfillment",
  
};

type Page = import("./fixtures").Page;
const rail = (page: Page) => page.getByRole("complementary", { name: "Your progress" });
const strip = (page: Page) => page.getByRole("tablist", { name: "Steps" });
const stripButton = (page: Page, name: string) => strip(page).getByRole("tab", { name, exact: true });
const review = (page: Page) => page.getByRole("region", { name: "Review changes" });
/** One rendered line: the element's box is no taller than one line of its own type. */
const oneLine = (locator: import("@playwright/test").Locator) => locator.evaluate((el) => {
  const range = document.createRange();
  range.selectNodeContents(el);
  return range.getClientRects().length > 0
    && new Set([...range.getClientRects()].map((rect) => Math.round(rect.top))).size === 1;
});

test("the labelled funnel shows the pool, live effect and stable desktop frame", async ({ page, isMobile }) => {
  // Marginal catalog totals cannot price this funnel. Supply real joint
  // cells: five roles, three at Staff, one after excluding logistics.
  await page.route("/api/scope/catalog", (route) => route.fulfill({ json: {
    ...scopeCatalog,
    scope_cells: {
      ...emptyScopeCellsFixture, ready: true, companies: ["google"],
      roles: ["software_engineering"], bands: ["staff", "entry"], tracks: ["technical"],
      location_sets: [["silicon_valley", "united_states"]],
      domain_sets: [["ai_ml"], ["logistics_fulfillment"]],
      cells: [[0, 0, 0, 0, 0, 1], [0, 0, 0, 0, 1, 2], [0, 1, 0, 0, 0, 2]],
    },
  } }));
  if (!isMobile) await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/profile/direction");
  const progress = page.getByRole("region", { name: "Focus your radar" });
  await expect(progress.locator(".walk-progress-source")).toHaveText("All roles100%");
  await expect(progress.getByText(/roles counted/)).toHaveCount(0);
  await expect(progress.locator(".walk-pyramid-caption").filter({ hasText: "Level" })).toHaveText("Level60%");
  const outcome = progress.locator(".walk-progress-outcome");
  await expect(outcome.locator("strong")).toHaveText("3");
  await expect(outcome.locator("span")).toHaveText("roles match");
  await expect(progress.locator(".walk-progress-line")).toHaveText("60% of all roles");
  // The count's label sits on one line beside the numeral, never wrapped.
  expect(await oneLine(outcome.locator("span"))).toBe(true);
  expect(await outcome.locator("strong").evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThan(
    await outcome.locator("span").evaluate((el) => parseFloat(getComputedStyle(el).fontSize)),
  );
  const rows = progress.getByRole("group", { name: "What each answer keeps" });
  for (const name of ["Career track", "Level", "Location", "Discipline", "World"]) {
    await expect(rows.getByRole("button", { name, exact: true })).toBeVisible();
    await expect(progress.locator(".walk-pyramid-caption").filter({ hasText: name }).first()).toBeVisible();
  }
  for (const row of await progress.locator(".walk-pyramid-caption").all()) {
    const label = (await row.locator("strong").boundingBox())!, metric = (await row.locator("span").boundingBox())!;
    expect(Math.abs((label.y + label.height / 2) - (metric.y + metric.height / 2))).toBeLessThan(2);
    expect(metric.x).toBeGreaterThanOrEqual(label.x + label.width);
  }
  for (const name of ["Career track", "Level", "Location"]) {
    await stripButton(page, name).click();
    await expect(rows.getByRole("button", { name, exact: true })).toHaveAttribute("aria-current", "step");
    if (!isMobile) {
      const card = (await page.locator(".walk-card").boundingBox())!;
      const funnel = (await progress.boundingBox())!;
      expect(Math.abs(card.y - funnel.y)).toBeLessThan(1);
      expect(Math.abs(card.height - funnel.height)).toBeLessThan(1);
    }
  }
  // Keyboard navigation works on the labelled row, not just the narrow shape.
  await rows.getByRole("button", { name: "World", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(stripButton(page, "World")).toHaveAttribute("aria-selected", "true");
  await page.getByRole("radio", { name: "Not interested in", exact: true }).check();
  await page.getByRole("group", { name: "Not interested in", exact: true }).getByLabel("Logistics & Fulfillment").check();
  await expect(progress.locator(".walk-pyramid-caption").filter({ hasText: "World" })).toHaveText("World20%");
  await expect(outcome.locator("strong")).toHaveText("1");
  await expect(outcome.locator("span")).toHaveText("role matches");
  await expect(progress.locator(".walk-progress-line")).toHaveText("20% of all roles");
  await expect(stripButton(page, "World")).toHaveAccessibleName("World");
  await expect(stripButton(page, "Discipline")).toHaveAccessibleName("Discipline");
  await expect(page.getByRole("region", { name: "Your picks" })).toHaveCount(0);
  await stripButton(page, "Summary").click();
  await expect(rows.locator('[aria-current="step"]')).toHaveCount(0);
  // The Summary's first funnel row names the pool in one line, never wrapped.
  const pool = page.getByRole("region", { name: "What it keeps" }).locator(".walk-funnel-row").first();
  await expect(pool.locator(".walk-funnel-label")).toHaveText("All roles");
  await expect(pool.locator(".walk-funnel-value")).toHaveText("5");
  expect(await oneLine(pool.locator(".walk-funnel-label"))).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("a world suggestion explains itself, applies on accept, and the Summary reads the pick it produced", async ({ page }) => {
  await page.unroute("/api/profile/suggestions");
  await page.route("/api/profile/suggestions", (route) =>
    route.fulfill({ json: { suggestions: [offSuggestion] } }));
  let accepted = false;
  await page.route("/api/profile/suggestions/7/accept", async (route) => {
    accepted = true;
    await route.fulfill({ json: {
      suggestion: { ...offSuggestion, status: "accepted" },
      enabled_domain_groups: ["ai_ml"],
      excluded_domain_groups: [],
      in_scope_changed: 12,
      promoted: 0,
      promotion_pending: false,
    } });
  });
  await page.goto("/profile/direction");
  await stripButton(page, "Summary").click();

  const inbox = page.getByRole("region", { name: "Suggested adjustments" });
  await expect(inbox.getByText("Turn off Logistics & Fulfillment?")).toBeVisible();
  // The basis is the user's own history in plain language, never a bare score.
  await expect(inbox.getByText(/you marked 2 roles there Not for me: wrong world/)).toBeVisible();

  await inbox.getByRole("button", { name: /Accept: turn off Logistics & Fulfillment/ }).click();
  await expect.poll(() => accepted).toBe(true);
  await expect(inbox.getByText(/Logistics & Fulfillment turned off · 12 roles on your radar updated/)).toBeVisible();
  // The server's authoritative set reads back as the pick that produces it,
  // with nothing to save: the accept already persisted.
  // The World row names it.
  await expect(page.getByRole("region", { name: "Tuned for" }).getByText("AI & Machine Learning")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);
});

test("dismissing a suggestion changes nothing about the radar", async ({ page }) => {
  await page.unroute("/api/profile/suggestions");
  await page.route("/api/profile/suggestions", (route) =>
    route.fulfill({ json: { suggestions: [offSuggestion] } }));
  let dismissed = false;
  await page.route("/api/profile/suggestions/7/dismiss", async (route) => {
    dismissed = true;
    await route.fulfill({ json: { suggestion: { ...offSuggestion, status: "dismissed" } } });
  });
  await page.goto("/profile/direction");
  await stripButton(page, "Summary").click();

  const inbox = page.getByRole("region", { name: "Suggested adjustments" });
  await inbox.getByRole("button", { name: /Dismiss suggestion about Logistics & Fulfillment/ }).click();
  await expect.poll(() => dismissed).toBe(true);
  await expect(inbox).toHaveCount(0);
  // Untouched: every world still on, so there is no pick to read.
  await expect(page.getByRole("region", { name: "Tuned for" }).getByText("Any world", { exact: true })).toBeVisible();
});

test("the profile index redirects to Direction", async ({ page }) => {
  await page.goto("/profile");
  await expect(page).toHaveURL(/\/profile\/direction$/);
  await expect(page.getByRole("region", { name: "What your radar looks for" })).toBeVisible();
  // One surface, so no tabbar: the section head is not a menu of one.
  await expect(page.getByRole("tablist", { name: "Profile sections" })).toHaveCount(0);
});

test("the old Settings scope paths land on Profile › Direction", async ({ page }) => {
  await page.goto("/settings/scope");
  await expect(page).toHaveURL(/\/profile\/direction$/);
  await expect(page.getByRole("banner", { name: "Application navigation" })).toContainText("Profile/Looking for");

  // /settings/roles is a scope deep link too.
  await page.goto("/settings/roles");
  await expect(page).toHaveURL(/\/profile\/direction$/);
});

test("the retired profile tabs redirect instead of dead-ending", async ({ page }) => {
  for (const slug of ["overview", "background", "activity"]) {
    await page.goto(`/profile/${slug}`);
    await expect(page).toHaveURL(/\/profile\/direction$/);
    await expect(page.getByRole("region", { name: "What your radar looks for" })).toBeVisible();
  }
  // The redirect replaces, so a retired link leaves no history entry to fall
  // back into.
  await page.goBack();
  await expect(page).not.toHaveURL(/\/profile\/(overview|background|activity)/);
});

/* A returning user lands on the walk itself, with every step complete and
   every step in the strip a button: there is no second layout for coming
   back, so nothing new to learn. */
test("a returning user lands on the walk with every step live and the Summary already written", async ({ page }) => {
  await page.goto("/profile/direction");

  for (const name of ["Career track", "Level", "Location", "Discipline", "World", "Summary"]) {
    await expect(stripButton(page, name)).toBeEnabled();
  }
  await expect(stripButton(page, "Career track")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "What kind of role are you looking for?" })).toBeVisible();
  // Any number of kinds can be picked, so the note never caps it at two.
  await expect(page.getByText("Pick one or more.", { exact: true })).toBeVisible();
  // No material: a chosen card is the app's gold (see the test below).
  await expect(page.locator("body")).not.toHaveAttribute("data-material", /.+/);

  // The Summary reads the saved answers back as rows, and no pick yet.
  await stripButton(page, "Summary").click();
  const tuned = page.getByRole("region", { name: "Tuned for" });
  // The kinds on the Role row; what narrows them on its own row.
  await expect(tuned).toContainText("Leading a team, owning a product, or hands-on");
  await expect(tuned.locator(".persona-fact", { hasText: "Discipline" })).toContainText("Software");
  await expect(tuned).toContainText("In Silicon Valley or anywhere in the UK or Singapore");
  await expect(page.getByRole("region", { name: "Tuned for" }).getByText("Any world", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);
  // No step ordinals as headings, no region list, no browser of every role card.
  await expect(page.getByLabel("Technical Program Management (TPM)")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Include all of Europe" })).toHaveCount(0);
});

test("a fresh user walks the three answers, lands on the Summary, sharpens from there and saves on the rail", async ({ page, isMobile }) => {
  await page.unroute("/api/scope/catalog");
  await page.route("/api/scope/catalog", (route) => route.fulfill({ json: {
    ...scopeCatalog,
    settings: {
      ...scopeCatalog.settings,
      enabled_role_groups: [], enabled_role_tracks: [], enabled_location_groups: [],
      enabled_seniority_bands: ["staff"], role_answers: [],
    },
  } }));
  let saved: Record<string, unknown> | undefined;
  await page.route("/api/settings", async (route) => {
    saved = route.request().postDataJSON();
    await route.fulfill({ json: settingsSaveFixture(saved as ScopeSettingsPayload, { in_scope_changed: 5, on_board: 2 }) });
  });
  await page.goto("/profile/direction");

  await expect(stripButton(page, "Discipline")).toBeDisabled();
  await expect(stripButton(page, "Summary")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled();
  // The first step has nowhere to go back to: Back holds its place unseen.
  await expect(page.getByRole("button", { name: "Back" })).toBeHidden();

  // Why Continue is shut is on screen, on the buttons' footer, and is the
  // button's description. Beside Continue on a wide card, above both buttons
  // on a narrow one; Continue stands where it stands once it opens.
  const advance = page.getByRole("button", { name: "Continue" });
  const reason = page.getByText("Pick at least one career track to continue.");
  await expect(reason).toBeVisible();
  await expect(advance).toHaveAccessibleDescription("Pick at least one career track to continue.");
  const shut = (await advance.boundingBox())!;
  const said = (await reason.boundingBox())!;
  // Back's held place: the foot's first button, unseen on this step.
  const back = await page.locator(".walk-step-foot .ui-btn").first()
    .evaluate((el) => { const { x, y, width, height } = el.getBoundingClientRect(); return { x, y, width, height }; });
  if (isMobile) {
    expect(said.y + said.height).toBeLessThanOrEqual(Math.min(back.y, shut.y));
  } else {
    expect(said.x).toBeGreaterThanOrEqual(back.x + back.width);
    expect(said.x + said.width).toBeLessThanOrEqual(shut.x);
    expect(said.y).toBeGreaterThanOrEqual(shut.y - 1);
    expect(said.y + said.height).toBeLessThanOrEqual(shut.y + shut.height + 1);
  }

  await page.getByLabel("Leading a team").check();
  await expect(reason).toHaveCount(0);
  await expect(advance).toHaveAccessibleDescription("");
  if (!isMobile) {
    const opened = (await advance.boundingBox())!;
    expect(Math.abs(opened.x - shut.x)).toBeLessThan(2);
    expect(Math.abs(opened.y - shut.y)).toBeLessThan(2);
  }
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Your level" })).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Where do you want to work?" })).toBeVisible();
  await page.getByLabel("Where are you based?").fill("silicon");
  await page.getByRole("button", { name: "Add Silicon Valley" }).click();
  const reach = page.getByRole("group", { name: "How far from Silicon Valley" });
  await expect(reach.getByRole("button", { name: "Silicon Valley" })).toHaveAttribute("aria-pressed", "true");
  await reach.getByRole("button", { name: "United States" }).click();

  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Summary" })).toBeVisible();
  // The Summary reads the answers back as rows, at most two lines each,
  // never as one long radar sentence.
  await expect(page.getByText("Change any answer and this page shows what it costs or gains.")).toHaveCount(0);
  const choices = page.getByRole("region", { name: "Tuned for" });
  await expect(choices).toContainText("Leading a team");
  await expect(choices).toContainText("Anywhere in the US");
  await expect(stripButton(page, "Discipline")).toBeEnabled();
  // The Summary's leave is the one primary on screen; the rail's Save steps back.
  await expect(page.locator(".ui-btn-primary:visible")).toHaveCount(1);

  await page.getByRole("button", { name: "Adjust discipline" }).click();
  // Each answer starts with nothing ticked (every role of the kind); ticking a
  // card keeps only what it names.
  await expect(page.getByLabel("Engineers (Leading a team)")).not.toBeChecked();
  await expect(page.getByLabel("Designers (Leading a team)")).not.toBeChecked();
  await page.getByLabel("Engineers (Leading a team)").check();
  await expect(page.getByLabel("Engineers (Leading a team)")).toBeChecked();
  await review(page).getByRole("button", { name: "Save" }).click();

  await expect.poll(() => saved).toBeTruthy();
  expect(saved).toMatchObject({
    enabled_role_tracks: ["management"],
    enabled_location_groups: ["united_states"],
    enabled_seniority_bands: ["staff"],
    // The answer itself travels: leading a team of engineers.
    role_answers: [{
      track: "management",
      roles: ["data_engineering", "engineering_management", "hardware_engineering", "infrastructure_sre", "security_engineering", "software_engineering"],
    }],
  });
  expect(saved?.enabled_role_groups).toEqual(expect.arrayContaining(["software_engineering"]));
  // The confirmation says what the Board holds now, not how many rows moved.
  await expect(rail(page).getByText(/Saved\. 2 roles are on your radar now/)).toBeVisible();
});

test("where is a base and a reach: removing a base and widening one both save as slugs", async ({ page }) => {
  let saved: Record<string, unknown> | undefined;
  await page.route("/api/settings", async (route) => {
    saved = route.request().postDataJSON();
    await route.fulfill({ json: settingsSaveFixture(saved as ScopeSettingsPayload, { in_scope_changed: 12, on_board: 7 }) });
  });
  await page.goto("/profile/direction");

  await stripButton(page, "Location").click();
  const bases = page.getByRole("list", { name: "Your bases" });
  await expect(bases.getByText("Singapore", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Remove Singapore" }).click();
  await expect(bases.getByText("Singapore", { exact: true })).toHaveCount(0);
  // Joint counts cannot price a location change: the review says so instead of a number.
  await expect(review(page)).toContainText("Updates when you save");

  await page.getByRole("group", { name: "How far from Silicon Valley" }).getByRole("button", { name: "United States" }).click();
  await review(page).getByRole("button", { name: "Save" }).click();
  await expect.poll(() => saved).toBeTruthy();
  const groups = saved?.enabled_location_groups as string[];
  expect(groups).toEqual(expect.arrayContaining(["united_states", "uk"]));
  expect(groups).not.toContain("singapore");
  expect(groups).not.toContain("silicon_valley");
  await expect(rail(page).getByText(/Saved\. 7 roles are on your radar now/)).toBeVisible();
});

test("where: a region is whole by default, and a country inside it can be excepted", async ({ page, isMobile }) => {
  const country = (slug: string, display: string) => ({
    slug, display, default_enabled: false, selected: false, count: 0, kind: "country" as const, parent: "europe",
  });
  await page.unroute("/api/scope/catalog");
  await page.route("/api/scope/catalog", (route) => route.fulfill({
    json: { ...scopeCatalog, locations: [...scopeCatalog.locations, country("germany", "Germany"), country("france", "France")] },
  }));
  let saved: Record<string, unknown> | undefined;
  await page.route("/api/settings", async (route) => {
    saved = route.request().postDataJSON();
    await route.fulfill({ json: settingsSaveFixture(saved as ScopeSettingsPayload, { in_scope_changed: 3 }) });
  });
  await page.goto("/profile/direction");
  await stripButton(page, "Location").click();

  // Widen the UK to Europe: the whole region, every country in it, by default.
  await page.getByRole("group", { name: "How far from United Kingdom" }).getByRole("button", { name: "Europe" }).click();
  const bases = page.getByRole("list", { name: "Your bases" });
  await expect(bases.getByText("Anywhere in Europe")).toBeVisible();
  const before = await page.getByRole("button", { name: "Continue" }).boundingBox();

  await page.getByRole("button", { name: "Choose countries in Europe" }).click();
  const chooser = page.getByRole("region", { name: "Countries in Europe" });
  for (const name of ["United Kingdom", "Germany", "France"]) {
    await expect(chooser.getByRole("checkbox", { name })).toBeChecked();
  }
  // One task at a time: the other bases and the search step aside. The frame
  // is snug to the closed answer, so the chooser may push Continue down, never
  // up, and never out of a desktop screen.
  await expect(bases.getByText("Silicon Valley only")).toHaveCount(0);
  await expect(page.getByRole("searchbox", { name: "Add another place" })).toHaveCount(0);
  if (!isMobile) {
    expect((await page.getByRole("button", { name: "Continue" }).boundingBox())!.y).toBeGreaterThanOrEqual(before!.y);
    await expect(page.getByRole("button", { name: "Continue" })).toBeInViewport();
  }

  // Unticking excepts it: Europe stays whole, so roles filed at
  // Europe itself stay too, where spelling it out as the other countries
  // would drop them.
  await chooser.getByRole("checkbox", { name: "Germany" }).uncheck();
  await expect(bases.getByText("Anywhere in Europe except Germany")).toBeVisible();
  await page.getByRole("button", { name: "Done choosing countries in Europe" }).click();
  await expect(chooser).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Choose countries in Europe" })).toBeFocused();
  await expect(bases.getByText("Silicon Valley only")).toBeVisible();

  await review(page).getByRole("button", { name: "Save" }).click();
  await expect.poll(() => saved).toBeTruthy();
  const groups = saved?.enabled_location_groups as string[];
  expect(new Set(groups)).toEqual(new Set(["europe", "silicon_valley", "singapore"]));
  expect(saved?.excluded_location_groups).toEqual(["germany"]);

  // One click puts the whole region back.
  await page.getByRole("button", { name: "Include all of Europe" }).click();
  await expect(bases.getByText("Anywhere in Europe", { exact: true })).toBeVisible();
});

test("where: the search, Go worldwide and every base stay inside the step's card", async ({ page }) => {
  await page.goto("/profile/direction");
  await stripButton(page, "Location").click();
  const card = page.locator(".walk-card");
  const bases = page.getByRole("list", { name: "Your bases" });
  await expect(bases.getByText("Silicon Valley only")).toBeVisible();

  // A search field's natural width, or a reach switch wider than a phone's
  // row, once stretched the whole step past the card's edge, clipping Go
  // worldwide and every base's Remove.
  const edge = (await card.boundingBox())!;
  const outside = await card.evaluate((el) => {
    const right = el.getBoundingClientRect().right;
    return [...el.querySelectorAll<HTMLElement>(".walk-add-row, .walk-add-row *, .walk-bases > li, .walk-bases .settings-row-trailing")]
      .filter((node) => node.getBoundingClientRect().right > right + 0.5)
      .map((node) => node.className || node.tagName);
  });
  expect(outside).toEqual([]);
  for (const control of [
    page.getByRole("searchbox", { name: "Add another place" }),
    page.getByRole("button", { name: "Go worldwide" }),
    ...(await bases.getByRole("button", { name: /^Remove / }).all()),
  ]) {
    // A phone scrolls the step down to it; nothing should need scrolling across.
    await control.scrollIntoViewIfNeeded();
    await expect(control).toBeInViewport({ ratio: 1 });
    const box = (await control.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(edge.x + edge.width);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width);
});

test("where: any city in the world is found by name, or by the name people still use, and saved as itself", async ({ page }) => {
  await page.unroute("/api/scope/places?**");
  await page.route("/api/scope/places?**", (route) => {
    const q = new URL(route.request().url()).searchParams.get("q") ?? "";
    const places = q.toLowerCase().startsWith("bangal")
      ? [{ slug: "city_1277333", display: "Bengaluru", kind: "city", parent: "india", context: "Karnataka, India", matched_by: "Bangalore" }]
      : q.toLowerCase().startsWith("stock")
        ? [{ slug: "city_2673730", display: "Stockholm", kind: "city", parent: "sweden", context: "Sweden", matched_by: null }]
        : [];
    return route.fulfill({ json: { places, unions: [] } });
  });
  const country = (slug: string, display: string, parent: string) => ({
    slug, display, default_enabled: false, selected: false, count: 0, kind: "country" as const, parent,
  });
  const withCountries = {
    ...scopeCatalog,
    locations: [...scopeCatalog.locations, country("sweden", "Sweden", "europe"), country("india", "India", "south_asia"),
      { slug: "south_asia", display: "South Asia", default_enabled: false, selected: false, count: 0, kind: "region", parent: null }],
  };
  await page.unroute("/api/scope/catalog");
  await page.route("/api/scope/catalog", (route) => route.fulfill({ json: withCountries }));
  // A city named before saving is counted by a read that names it.
  const citiesAsked: string[][] = [];
  await page.route("/api/scope/catalog?**", (route) => {
    const cities = new URL(route.request().url()).searchParams.getAll("cities");
    citiesAsked.push(cities);
    return route.fulfill({ json: { ...withCountries, scope_cells: { ...emptyScopeCellsFixture, cities } } });
  });
  let saved: Record<string, unknown> | undefined;
  await page.route("/api/settings", async (route) => {
    saved = route.request().postDataJSON();
    await route.fulfill({ json: settingsSaveFixture(saved as ScopeSettingsPayload, { in_scope_changed: 2 }) });
  });
  await page.goto("/profile/direction");
  await stripButton(page, "Location").click();

  const search = page.getByRole("searchbox", { name: "Add another place" });
  await search.fill("Bangalore");
  // The city goes by its name today; the old one says why it was found.
  await expect(page.getByRole("list", { name: "Places" })).toContainText("“Bangalore” · Karnataka, India");
  await search.fill("stockholm");
  await page.getByRole("button", { name: "Add Stockholm, Sweden" }).click();

  const bases = page.getByRole("list", { name: "Your bases" });
  await expect(bases.getByText("Stockholm only")).toBeVisible();
  await expect(page.getByRole("group", { name: "How far from Stockholm" }).getByRole("button", { name: "Sweden" })).toBeVisible();
  await expect.poll(() => citiesAsked).toContainEqual(["city_2673730"]);
  // Before Save, the review says what the save does to the Board.
  await expect(review(page)).toContainText("Your radar keeps its 0 roles.");

  await review(page).getByRole("button", { name: "Save" }).click();
  await expect.poll(() => saved).toBeTruthy();
  expect(saved?.enabled_location_groups).toEqual(expect.arrayContaining(["city_2673730"]));
  expect(saved?.enabled_location_groups).not.toContain("sweden");

  await stripButton(page, "Summary").click();
  // Four places: named two, counted the rest, Stockholm among the named.
  await expect(page.getByRole("region", { name: "Tuned for" })).toContainText("Silicon Valley, Stockholm, or 2 more");
});

test("interests: the verb leads, a card is one tap, and the pick saves the worlds set it means", async ({ page }) => {
  let saved: Record<string, unknown> | undefined;
  // Seven roles carry no subject, but only three of them are Staff: the
  // untagged line counts the draft, never the market.
  await page.route("/api/scope/catalog", (route) => route.fulfill({ json: {
    ...scopeCatalog,
    scope_cells: {
      ...emptyScopeCellsFixture, ready: true, companies: ["google"],
      roles: ["software_engineering"], bands: ["staff", "entry"], tracks: ["technical"],
      location_sets: [["silicon_valley", "united_states"]],
      domain_sets: [[], ["ai_ml"]],
      cells: [[0, 0, 0, 0, 0, 3], [0, 1, 0, 0, 0, 4], [0, 0, 0, 0, 1, 2]],
    },
  } }));
  await page.route("/api/settings", async (route) => {
    saved = route.request().postDataJSON();
    await route.fulfill({ json: settingsSaveFixture(saved as ScopeSettingsPayload) });
  });
  await page.goto("/profile/direction");

  await stripButton(page, "World").click();
  // The list is chosen first; the picker is named by the list it fills.
  await expect(page.getByRole("group", { name: "Not interested in" })).toHaveCount(0);
  await page.getByRole("radio", { name: "Not interested in" }).check();
  const picker = page.getByRole("group", { name: "Not interested in" });
  // What the list does is its radio's description (a phone hides the sentence).
  await expect(page.getByRole("radio", { name: "Not interested in" })).toHaveAccessibleDescription(/Roles about these drop off/);
  await picker.getByLabel("Filter worlds").fill("logist");
  await expect(picker.getByLabel("AI & Machine Learning")).toHaveCount(0);
  await picker.getByLabel("Logistics & Fulfillment").check();
  await expect(picker.getByLabel("Logistics & Fulfillment")).toBeChecked();

  await expect(page.getByRole("region", { name: "Your picks" })).toHaveCount(0);
  await expect(stripButton(page, "World")).toHaveAccessibleName("World");
  // The fail-open volume is disclosed, never hidden by narrowing.
  await expect(page.getByText("3 of your 5 roles aren't sorted into a world yet. They stay on your radar whatever you pick.")).toBeVisible();
  await review(page).getByRole("button", { name: "Save" }).click();
  await expect.poll(() => saved).toBeTruthy();
  expect(saved?.enabled_domain_groups).toEqual(["ai_ml"]);
});

test("the aim sentence is not on the Profile, and a save never carries it", async ({ page }) => {
  let saved: Record<string, unknown> | undefined;
  await page.route("/api/settings", async (route) => {
    saved = route.request().postDataJSON();
    await route.fulfill({ json: settingsSaveFixture(saved as ScopeSettingsPayload) });
  });
  await page.goto("/profile/direction");

  await stripButton(page, "Summary").click();
  await expect(page.getByRole("region", { name: "Tuned for" })).toBeVisible();
  await expect(page.getByLabel(/your aim, in one sentence/i)).toHaveCount(0);

  await stripButton(page, "Location").click();
  await page.getByRole("button", { name: "Remove Singapore" }).click();
  await review(page).getByRole("button", { name: "Save" }).click();
  await expect.poll(() => saved).toBeTruthy();
  // Settings > Intelligence owns it; sending even "" here would erase it.
  expect(saved).not.toHaveProperty("intent_statement");
});

/* The preview of what a save does answers after the change that asked for it,
   often while the person is already tapping Save. Text that lands above the
   button pushes it out from under the finger and the tap is lost. */
test("the save preview arriving late never moves Save under a tap", async ({ page }) => {
  let release!: () => void;
  const answered = new Promise<void>((resolve) => { release = resolve; });
  await page.route("/api/scope/preview", async (route) => {
    await answered;
    await route.fulfill({ json: scopePreview });
  });
  await page.goto("/profile/direction");

  await stripButton(page, "Location").click();
  await page.getByRole("button", { name: "Remove Singapore" }).click();
  const save = review(page).getByRole("button", { name: "Save" });
  await expect(save).toBeVisible();
  const before = await save.boundingBox();

  release();
  await expect(review(page).getByText(/^Your radar (goes from|keeps)/)).toBeVisible();
  expect(await save.boundingBox()).toEqual(before);
});

test("the level step decodes corporate levels and saves the stretched profile range", async ({ page, isMobile }) => {
  let saved: Record<string, unknown> | undefined;
  await page.route("/api/profile", (route) => route.fulfill({ json: {
    profile: { experience_stage: "staff", target_stage: "staff" },
    scope_configured: true, intent_statement: "",
  } }));
  // The one save path: the scope and both level markers.
  await page.route("/api/settings", async (route) => {
    if (route.request().method() !== "PUT") return route.fallback();
    saved = route.request().postDataJSON();
    await route.fulfill({ json: settingsSaveFixture(saved as ScopeSettingsPayload, { in_scope_changed: 4, on_board: 1 }) });
  });
  await page.goto("/profile/direction");
  await stripButton(page, "Level").click();

  if (!isMobile) {
    // The grading table is reference-on-demand: collapsed on load, so the
    // step opens with the rail it explains, not a 12-row matrix.
    const decoder = page.getByRole("button", { name: /What this means at each company/ });
    await expect(decoder).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByText("L6", { exact: true })).toHaveCount(0);
    // The reference companies only, each by its own name ("OpenAI", never
    // the capitalised slug "Openai").
    await expect(decoder).toContainText("2 companies");
    await decoder.click();
    await expect(page.getByText("L6", { exact: true })).toBeVisible();
    await expect(page.locator("#stage-decoder-table").getByText("OpenAI", { exact: true })).toBeVisible();
    await expect(page.locator("#stage-decoder-table").getByText("Openai", { exact: true })).toHaveCount(0);
    await expect(page.getByText("you are here")).toBeVisible();
  }

  // Move the aim down to Junior via the keyboard slider; the marker stays put.
  const edge = page.getByRole("slider", { name: "Level you're aiming for" });
  await edge.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(edge).toHaveAttribute("aria-valuetext", "Entry / Junior");
  await expect(page.getByRole("slider", { name: "Your level today" }))
    .toHaveAttribute("aria-valuetext", "Staff");

  await review(page).getByRole("button", { name: "Save" }).click();
  await expect.poll(() => saved).toBeTruthy();
  expect(saved).toEqual({
    experience_stage: "staff",
    target_stage: "entry",
    enabled_seniority_bands: expect.arrayContaining(["entry", "staff"]),
    enabled_role_tracks: expect.arrayContaining(["management", "product_program", "technical"]),
    enabled_role_groups: ["software_engineering"],
    enabled_location_groups: expect.arrayContaining(["silicon_valley", "uk", "singapore"]),
    enabled_domain_groups: ["ai_ml", "logistics_fulfillment"],
    // Nothing is "not interested in": the veto list travels, empty.
    excluded_domain_groups: [],
    // No place is excepted: that list travels empty too.
    excluded_location_groups: [],
    // The box was never touched: it saves the default, which is on.
    include_unstated_level: true,
    // The answers read off the saved lists travel too: each kind, holding software engineering.
    role_answers: expect.arrayContaining([{ track: "technical", roles: ["software_engineering"] }]),
  });
  await expect(rail(page).getByText(/Saved\. 1 role is on your radar now/)).toBeVisible();
  // The Summary reads the stretched range back.
  await stripButton(page, "Summary").click();
  await expect(page.getByRole("region", { name: "Tuned for" })).toContainText(/from Entry \/ Junior to Staff/i);
});

/* A role whose posting names no level sits on no rung. The Level
   step counts it apart, the funnel leaves it out until the person ticks the
   choice, and the save carries that choice. */
test("roles whose level isn't stated are counted apart and included only while ticked", async ({ page }) => {
  let saved: Record<string, unknown> | undefined;
  await page.route("/api/scope/catalog", (route) => route.fulfill({ json: {
    ...scopeCatalog,
    unstated_level_count: 2,
    scope_cells: {
      ...emptyScopeCellsFixture, ready: true, companies: ["google"],
      roles: ["software_engineering"], bands: ["staff", "unstated"], tracks: ["technical"],
      location_sets: [["silicon_valley", "united_states"]], domain_sets: [["ai_ml"]],
      cells: [[0, 0, 0, 0, 0, 3], [0, 1, 0, 0, 0, 2]],
    },
  } }));
  await page.route("/api/settings", async (route) => {
    if (route.request().method() !== "PUT") return route.fallback();
    saved = route.request().postDataJSON();
    await route.fulfill({ json: settingsSaveFixture(saved as ScopeSettingsPayload, { in_scope_changed: 2 }) });
  });
  await page.goto("/profile/direction");
  await stripButton(page, "Level").click();

  // Ticked by default: the 2 unstated roles count in.
  const choice = page.getByRole("checkbox", { name: "Include roles with an unknown level" });
  await expect(choice).toBeChecked();
  await expect(page.locator("label").filter({ has: choice })).toContainText("2 roles");
  const outcome = page.getByRole("region", { name: "Focus your radar" }).locator(".walk-pyramid-caption").filter({ hasText: "Level" });
  await expect(outcome).toHaveText("Level100%");

  await choice.uncheck();
  await expect(outcome).toHaveText("Level60%");
  await review(page).getByRole("button", { name: "Save" }).click();
  await expect.poll(() => saved).toBeTruthy();
  expect(saved).toMatchObject({ include_unstated_level: false });
});

/* A returning install's Level control must reach the axis: nothing may skip
   the stage->band sync, or the control cannot dirty the draft or offer a
   Save. */
test("a returning install saves the level it picks", async ({ page }) => {
  let savedAxes: Record<string, unknown> | undefined;
  await page.route("/api/profile", (route) => route.fulfill({
    json: {
      profile: {
        experience_stage: "staff", target_stage: "staff",
        crafts: ["management", "product_program", "technical"],
        disciplines: ["software_engineering"],
        locations: ["silicon_valley", "uk", "singapore"],
        domains: ["ai_ml", "logistics_fulfillment"],
      },
      scope_configured: true, intent_statement: "",
    },
  }));
  await page.route("/api/settings", async (route) => {
    savedAxes = route.request().postDataJSON();
    await route.fulfill({ json: settingsSaveFixture(savedAxes as ScopeSettingsPayload, { in_scope_changed: 9 }) });
  });
  await page.goto("/profile/direction");
  await stripButton(page, "Level").click();

  // Loads clean: the stored axis agrees with the persona, so the Save below can
  // only have come from the level edit.
  const edge = page.getByRole("slider", { name: "Level you're aiming for" });
  await expect(edge).toBeVisible();
  await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);

  await edge.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(edge).toHaveAttribute("aria-valuetext", "Entry / Junior");

  await review(page).getByRole("button", { name: "Save" }).click();
  await expect.poll(() => savedAxes).toBeTruthy();
  expect(savedAxes).toMatchObject({
    enabled_seniority_bands: ["entry", "staff"],
    experience_stage: "staff",
    target_stage: "entry",
  });
});

test("direction remains usable at a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/profile/direction");
  await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);
  await page.getByLabel("Working with customers").check();
  // The rail folds under the step and still offers the Save.
  await expect(review(page).getByRole("button", { name: "Save" })).toBeVisible();
});

/* An unsaved answer outlives leaving the page. A draft held in the route is
   lost on any navigation, and coming back shows the saved scope with no word
   said. Kept in memory until Save, so a full reload starts from the saved
   scope. */
test("an unsaved answer survives leaving Profile and coming back, and nothing saves on the way", async ({ page }) => {
  let saves = 0;
  await page.route("/api/settings", (route) => {
    if (route.request().method() !== "GET") saves += 1;
    return route.fallback();
  });
  await page.goto("/profile/direction");
  const customers = page.getByLabel("Working with customers");
  await expect(customers).not.toBeChecked();
  await customers.check();
  await expect(review(page).getByRole("button", { name: "Save" })).toBeVisible();

  const nav = page.getByRole("navigation", { name: /primary|main/i }).first();
  await nav.getByRole("link", { name: "Radar", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await nav.getByRole("link", { name: "Profile", exact: true }).click();
  await expect(page.getByLabel("Working with customers")).toBeChecked();
  await expect(review(page).getByRole("button", { name: "Save" })).toBeVisible();

  // The browser's own Back leaves and returns the same way.
  await nav.getByRole("link", { name: "Radar", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goBack();
  await expect(page.getByLabel("Working with customers")).toBeChecked();

  // In memory, not autosaved: a reload is a fresh start from the saved scope.
  await page.reload();
  await expect(page.getByLabel("Working with customers")).not.toBeChecked();
  expect(saves).toBe(0);
});

test("the guide is an icon on the Profile title's row, on the side its sheet opens from", async ({ page }) => {
  await page.goto("/profile/direction");

  const guide = page.getByRole("button", { name: "How your radar works" });
  // On the title's row, at its far end: the sheet slides in from the right.
  const title = (await page.getByRole("heading", { level: 1, name: "Profile" }).boundingBox())!;
  const trigger = (await guide.boundingBox())!;
  expect(trigger.y).toBeLessThan(title.y + title.height);
  expect(trigger.y + trigger.height).toBeGreaterThan(title.y);
  expect(trigger.x).toBeGreaterThan(page.viewportSize()!.width / 2);
  await guide.click();
  await expect(page.getByRole("dialog", { name: "How your radar works" })).toBeVisible();

  /* `ui/Sheet` freezes the page behind, closes from Escape wherever focus is,
     and names its backdrop. */
  await expect
    .poll(() => page.evaluate(() => getComputedStyle(document.body).overflow))
    .toBe("hidden");
  await expect(page.getByRole("button", { name: "Close guide" })).toBeVisible();

  await page.locator("body").click({ position: { x: 4, y: 4 } });
  await expect(page.getByRole("dialog", { name: "How your radar works" })).toHaveCount(0);
  await expect
    .poll(() => page.evaluate(() => getComputedStyle(document.body).overflow))
    .not.toBe("hidden");

  await guide.click();
  await expect(page.getByRole("dialog", { name: "How your radar works" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "How your radar works" })).toHaveCount(0);
  await expect(guide).toBeFocused();
});

test("the rail says no count yet instead of a zero, and offers the count there", async ({ page }) => {
  await page.unroute("/api/scope/catalog");
  await page.route("/api/scope/catalog", (route) => route.fulfill({ json: {
    ...scopeCatalog,
    joint_counts_ready: false,
    companies: [{ ...scopeCatalog.companies[0], role_catalog_status: "partial" }],
  } }));
  await page.route("/api/scope/refresh", (route) => route.fulfill({ json: { status: "started", max_list: 600 } }));
  await page.goto("/profile/direction");

  const progress = rail(page);
  await expect(progress).toContainText("No count yet");
  await expect(progress).not.toContainText(/\b0%/);
  await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);
  await progress.getByRole("button", { name: "Count now" }).click();
  await expect(progress).toContainText(/Counting roles again/i);
});

/* THE APP'S TAB BAR. Settings and Insights show their parts as ui/TabBar
   between the title and the content; Profile's steps are the same control,
   in three runs set apart by a rule (the three that decide, the two that
   sharpen, Summary), above the question on every width. */
test("the steps are the app's tab bar, in three runs, above the question", async ({ page }) => {
  await page.goto("/profile/direction");
  const tabs = strip(page);
  await expect(tabs.getByRole("tab")).toHaveCount(6);
  expect(await tabs.evaluate((bar) => [...bar.children].map((child) => child.getAttribute("role") ?? "rule"))).toEqual(
    ["tab", "tab", "tab", "rule", "tab", "tab", "rule", "tab"],
  );
  await expect(stripButton(page, "Career track")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "walk-tab-accountable");

  const bar = (await tabs.boundingBox())!;
  const card = (await page.getByRole("heading", { name: "What kind of role are you looking for?" }).locator("xpath=ancestor::section[1]").boundingBox())!;
  expect(bar.y + bar.height).toBeLessThanOrEqual(card.y);
  // Keyboard: the tablist pattern moves between steps.
  await stripButton(page, "Career track").focus();
  await page.keyboard.press("ArrowRight");
  await expect(stripButton(page, "Level")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "Your level" })).toBeVisible();
});

/* NOTHING JUMPS. The three answers that decide share one frame, so Back and
   Continue land in the same place on each; only a browser can measure it. */
test("Back and Continue stay put across the three answers that decide", async ({ page, isMobile }) => {
  test.skip(isMobile, "the frame is a minimum height on a phone, which scrolls anyway");
  await page.goto("/profile/direction");
  const box = async () => (await page.getByRole("button", { name: "Continue" }).boundingBox())!;
  const first = await box();
  for (const name of ["Level", "Location"]) {
    await stripButton(page, name).click();
    await expect(page.getByRole("button", { name: "Continue" })).toBeVisible();
    const next = await box();
    expect(Math.abs(next.y - first.y)).toBeLessThan(2);
    expect(Math.abs(next.x - first.x)).toBeLessThan(2);
  }
  // What lets two bases fit that frame: the whole world is a button on the
  // search's row, not a row of its own under it.
  const search = (await page.getByRole("searchbox", { name: "Add another place" }).boundingBox())!;
  const worldwide = (await page.getByRole("button", { name: "Go worldwide" }).boundingBox())!;
  expect(Math.abs(worldwide.y + worldwide.height / 2 - (search.y + search.height / 2))).toBeLessThan(2);
  expect(worldwide.x).toBeGreaterThan(search.x + search.width);
});

/* A CHOSEN CARD IS GOLD, AND STAYS GOLD. Profile sets the register material,
   whose stylesheet the Companies chunk also imports: if Profile does not load
   it itself, a chosen card renders gold and turns ink whenever that chunk
   arrives later. Here it arrives for certain (a visit to Settings, then back),
   and the card must not change. */
test("a chosen card keeps the app's gold after another screen's styles load", async ({ page }) => {
  await page.route("/api/companies/discovery", (route) => route.fulfill({ json: companyDiscovery }));
  await page.route("/api/companies/open-counts", (route) => route.fulfill({ json: companyOpenCounts }));
  await page.route("/api/companies/directory/status", (route) => route.fulfill({
    json: { size: 0, following: false, since: null, checked: 0, to_check: 0, with_roles: 0, waiting_for_power: false },
  }));
  await page.route("/api/sync/targets", (route) => route.fulfill({ json: { companies: [], freshness_max_hours: 24 } }));
  await page.goto("/profile/direction");
  const chosen = page.locator(".walk-cards .select-card:has(> input:checked)").first();
  await expect(chosen).toBeVisible();
  const paint = () => chosen.evaluate((node) => getComputedStyle(node).borderTopColor);
  const gold = await page.evaluate(() => {
    const probe = document.createElement("div");
    probe.style.color = "var(--app-chosen-line)";
    document.querySelector("main")!.appendChild(probe);
    const value = getComputedStyle(probe).color;
    probe.remove();
    return value;
  });
  await expect.poll(paint).toBe(gold);

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await page.goBack();
  await expect(chosen).toBeVisible();
  await expect.poll(paint).toBe(gold);
  // And gold is not ink: the probe read the app's action colour, not white.
  expect(gold).not.toMatch(/^rgba?\(236, 234, 228/);
});

/* ONE CARD, ONE SHAPE. The select-card means the same thing on Career track,
   Discipline and World (tick it to include it), so it is one size on all
   three: the size is the card's, never a result of how many siblings share
   its row or how long its hint runs, so no step states its own grid. */
test("a pick card is one width and one height on every step that shows one", async ({ page, isMobile }) => {
  if (!isMobile) await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/profile/direction");
  const sizes = async () => {
    const cards = page.locator(".walk-cards label.select-card:visible");
    await expect(cards.first()).toBeVisible();
    return (await cards.evaluateAll((nodes) => nodes.map((node) => {
      const box = node.getBoundingClientRect();
      // The text block (name to hint) and the air on each side of it.
      const parts = [...node.querySelectorAll(".select-card-label, small")].map((part) => part.getBoundingClientRect());
      const top = Math.min(...parts.map((part) => part.top));
      const bottom = Math.max(...parts.map((part) => part.bottom));
      return {
        w: Math.round(box.width), h: Math.round(box.height), y: Math.round(box.top),
        above: Math.round(top - box.top), below: Math.round(box.bottom - bottom),
      };
    })));
  };
  const role = await sizes();
  expect(role).toHaveLength(4);
  // Four across on a desktop step card: the four answers are peers, one row.
  if (!isMobile) expect(new Set(role.map((card) => card.y)).size).toBe(1);
  await stripButton(page, "Discipline").click();
  const roles = await sizes();
  await stripButton(page, "World").click();
  const world = await sizes();
  const seen = [...role, ...roles, ...world];
  expect(seen.length).toBeGreaterThan(role.length + 3);
  expect(new Set(seen.map((card) => card.w))).toEqual(new Set([role[0].w]));
  expect(new Set(seen.map((card) => card.h))).toEqual(new Set([role[0].h]));
  // The name and its hint sit centred as one unit: equal air above and below,
  // whether a card uses two lines or four. Where cards share a row, Discipline
  // pins its names to one line instead (welcome.spec.ts holds it); a phone's
  // single column centres it again.
  const lopsided = (isMobile ? seen : [...role, ...world]).filter((card) => Math.abs(card.above - card.below) > 2);
  expect(lopsided, JSON.stringify(lopsided.slice(0, 3))).toEqual([]);
});

/* THE LIST IS ALWAYS IN SIGHT. On World the first decision is which list
   a tick lands in, so the chooser is the step's largest object and never
   scrolls away: scrolled to the picks at the bottom, both lists are still on
   screen, the chosen one still says so, and a ticked card wears the chosen
   list's colour. A segmented switch in its place reads as chrome and
   scrolls off with the first card row. */
test("interests: both lists stay in sight while ticking, and a tick wears the chosen list's colour", async ({ page }) => {
  await page.setViewportSize({ width: page.viewportSize()!.width, height: 560 });
  await page.goto("/profile/direction");
  await stripButton(page, "World").click();
  const lists = page.getByRole("group", { name: "Choose a list, then tick what goes in it" });
  const avoid = lists.getByRole("radio", { name: "Not interested in" });
  await avoid.check();
  const option = (name: string) => lists.locator("label").filter({ has: page.getByRole("radio", { name, exact: true }) });
  const chosen = option("Not interested in");
  await expect(chosen).toContainText("Not interested in");
  await page.getByRole("group", { name: "Not interested in" }).getByLabel("Logistics & Fulfillment").check();

  // Scroll to the bottom of the step: the first group has passed beneath.
  await page.getByRole("button", { name: "Done", exact: true }).scrollIntoViewIfNeeded();
  // The step's own heading has scrolled off: without the stick, the chooser
  // above the cards would have gone with it.
  await expect(page.getByRole("heading", { name: "Anything you care about, or want to avoid?" })).not.toBeInViewport();
  await expect(lists.getByRole("radio", { name: "Interested in", exact: true })).toBeInViewport();
  await expect(avoid).toBeInViewport();
  await expect(avoid).toBeChecked();
  await expect(chosen).toContainText("1 picked");
  // Nothing paints over the chooser where it sticks.
  const box = (await chosen.boundingBox())!;
  const top = await page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.closest("label")?.textContent ?? "", [box.x + box.width / 2, box.y + box.height / 2]);
  expect(top).toContain("Not interested in");

  // The chosen list's colour is the tick's colour, and it is not the other list's.
  // Read after the cards' colour transition has settled.
  const tick = page.locator(".walk-cards .select-card:has(> input:checked)").first();
  const border = (locator: typeof tick) => locator.evaluate((node) => getComputedStyle(node).borderTopColor);
  await expect.poll(async () => (await border(tick)) === (await border(chosen))).toBe(true);
  const avoidInk = await border(tick);
  await lists.getByRole("radio", { name: "Interested in", exact: true }).check();
  const interested = option("Interested in");
  await expect(interested).toContainText("Picking now");
  await expect.poll(() => border(interested)).not.toBe(avoidInk);
});

/* EVERY STEP OPENS IN ONE PLACE. World is the one step taller than the
   screen, and bringing its card "into view" would align its top and scroll
   the Profile header away on that step alone. */
test("opening World leaves the page where every other step leaves it", async ({ page }) => {
  await page.setViewportSize({ width: page.viewportSize()!.width, height: 560 });
  await page.goto("/profile/direction");
  const header = page.getByRole("heading", { level: 1, name: "Profile" });
  for (const name of ["Discipline", "World", "Career track", "World"]) {
    await stripButton(page, name).click();
    await expect(page.getByRole("heading", { level: 2 }).first()).toBeFocused();
    await expect(header).toBeInViewport();
  }
});

/* PRIMARY RANK. A count is the only honest test of scarcity, and it
   belongs in a browser: how many primaries are VISIBLE at once is a rendering
   fact, not a source one. The walk has two candidates — the rail's Save and
   the Summary's leave — and never shows both. */
test("Direction offers at most one primary action on every screen of the walk", async ({ page }) => {
  await page.goto("/profile/direction");
  await expect(page.getByRole("region", { name: "What your radar looks for" })).toBeVisible();
  await expect(page.locator(".ui-btn-primary:visible")).toHaveCount(0);

  await page.getByLabel("Working with customers").check();
  await expect(page.locator(".ui-btn-primary:visible")).toHaveCount(1);

  for (const name of ["Level", "Location", "Discipline", "World"]) {
    await stripButton(page, name).click();
    await expect(page.locator(".ui-btn-primary:visible")).toHaveCount(1);
  }
  // The Summary, reached from Where with the draft dirty: its own primary only.
  await stripButton(page, "Location").click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Summary" })).toBeVisible();
  const names = await page.locator(".ui-btn-primary:visible").allInnerTexts();
  expect(names).toEqual(["Save and see your radar"]);
});

/* A category added since the last save arrives OFF and says "New". */
test("categories added since the last save are marked New on every opt-in axis", async ({ page }, testInfo) => {
  const flagged = {
    ...scopeCatalog,
    categories: scopeCatalog.categories.map((c) => ({
      ...c,
      groups: c.groups.map((g) => ({ ...g, new: g.slug === "software_engineering" })),
    })),
    levels: scopeCatalog.levels.map((l) => (l.slug === "entry" ? { ...l, new: true } : { ...l, new: false })),
    tracks: scopeCatalog.tracks.map((t) =>
      t.slug === "business_customer" ? { ...t, selected: false, new: true } : { ...t, new: false }),
    // A new place arrives off, so it is listed among the places you can add.
    locations: [
      ...scopeCatalog.locations.map((l) => ({ ...l, new: false })),
      { slug: "canada", display: "Canada", default_enabled: false, selected: false, new: true,
        count: 3, kind: "country", parent: null },
    ],
  };
  await page.unroute("/api/scope/catalog");
  await page.route("/api/scope/catalog", (route) => route.fulfill({ json: flagged }));
  await page.goto("/profile/direction");

  // The walk carries every mark, each where its step
  // shows the category: the answer card, the level rail, the place search
  // and the "which roles" card.
  await stripButton(page, "Career track").click();
  const track = page.locator("label.select-card", { has: page.getByLabel("Working with customers") });
  await expect(track.getByText("New", { exact: true })).toBeVisible();
  await expect(track.getByRole("checkbox")).not.toBeChecked();
  await track.screenshot({ path: testInfo.outputPath("new-track.png") });

  await stripButton(page, "Level").click();
  const newLevel = page.locator("button.stage-cell", { hasText: "Entry / Junior" });
  await expect(newLevel.getByText("New", { exact: true })).toBeVisible();
  await newLevel.screenshot({ path: testInfo.outputPath("new-level.png") });

  // A new place arrives off, so it is found where places are added.
  await stripButton(page, "Location").click();
  await page.getByRole("searchbox", { name: "Add another place" }).fill("cana");
  const canada = page.getByRole("list", { name: "Places" }).getByRole("button", { name: /Canada/ });
  await expect(canada.getByText("New", { exact: true })).toBeVisible();
  await canada.screenshot({ path: testInfo.outputPath("new-location.png") });

  await stripButton(page, "Discipline").click();
  const role = page.locator("label.select-card", { hasText: "New" }).first();
  await expect(role).toBeVisible();
  await role.screenshot({ path: testInfo.outputPath("new-role.png") });
});

/* Every answer given at once. Each row still reads in at most two lines
   (a Role row can otherwise run to five). At a laptop's width no
   line is cut either; narrower, the clamp is the net and the line's title
   still says it all. */
for (const [width, cutAllowed] of [[1440, false], [1280, true]] as const) {
  test(`the Summary says the longest answers in two lines at ${width}px`, async ({ page, isMobile }) => {
    test.skip(isMobile, "The two-line rule is measured at desktop column widths.");
    await page.setViewportSize({ width, height: 900 });
    // Real world names, the longest the catalog has; eighteen, nine on.
    const names = [
      "Media & Entertainment", "Logistics & Fulfillment", "AI & Machine Learning", "Cloud & Infrastructure",
      "Financial Services & Fintech", "Healthcare & Life Sciences", "Retail & Commerce", "Security & Identity",
      "Climate & Energy", "Education & Learning", "Gaming & Interactive", "Government & Public Sector",
      "Hardware & Devices", "Marketing & Advertising", "Real Estate & Property", "Telecommunications",
      "Travel & Hospitality", "Transportation & Mobility",
    ];
    const worlds = names.map((display, i) => ({ slug: `world_${i}`, display }));
    const on = worlds.slice(0, 9).map((world) => world.slug);
    await page.route("/api/scope/catalog", (route) => route.fulfill({ json: {
      ...scopeCatalog,
      settings: {
        ...scopeCatalog.settings,
        enabled_role_tracks: ["management", "product_program", "technical", "business_customer"],
        role_answers: [
          { track: "management", roles: ["engineering_management", "software_engineering", "design_ux", "data_science", "ml_ai_research"] },
          { track: "product_program", roles: ["product_management", "technical_program_management"] },
          { track: "technical", roles: ["software_engineering", "infrastructure_sre", "security_engineering"] },
          { track: "business_customer", roles: ["sales_business_development", "customer_success"] },
        ],
        // Every top-level place would read "Anywhere"; three say the longest sentence.
        enabled_location_groups: ["united_states", "uk", "singapore"],
        enabled_domain_groups: on,
      },
      domains: worlds.map((world) => ({ ...world, selected: on.includes(world.slug), count: 3, examples: [], hint: "", kind: "function" })),
    } }));
    await page.goto("/profile/direction");
    await stripButton(page, "Summary").click();
    const tuned = page.getByRole("region", { name: "Tuned for" });
    await expect(tuned).toBeVisible();
    for (const label of ["Career track", "Level", "Location", "Discipline", "World"]) {
      const row = tuned.locator(".persona-fact", { has: page.getByText(label, { exact: true }) });
      const measured = await row.locator(".walk-fact-text").evaluate((text) => {
        const lineHeight = parseFloat(getComputedStyle(text).lineHeight);
        const lines = [...text.querySelectorAll<HTMLElement>(".walk-fact-line")];
        return {
          lines: text.getBoundingClientRect().height / lineHeight,
          cut: lines.filter((line) => line.scrollHeight > line.clientHeight + 1).map((line) => line.textContent),
          untitled: lines.filter((line) => line.title !== line.textContent).length,
        };
      });
      expect(measured.lines, `${label} row height in lines`).toBeLessThanOrEqual(2.1);
      expect(measured.untitled, `${label} lines whose title does not say them in full`).toBe(0);
      if (!cutAllowed) expect(measured.cut, `${label} lines cut by the clamp`).toEqual([]);
    }
  });
}

/* The pay floor is an optional answer on the Summary, saved on its
   own; the CV action opens its future page. */
test("the Summary takes an optional pay floor and links to the CV page", async ({ page }) => {
  const saved: unknown[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/api/profile/pay-floor") && request.method() === "PUT") saved.push(request.postDataJSON());
  });
  await page.goto("/profile/direction");
  await stripButton(page, "Summary").click();
  await expect(page.getByRole("heading", { name: "Summary" })).toBeVisible();

  // The way back sits beside the answer, never on a line of its own below it,
  // which would add a line to every row.
  const roleRow = page.getByRole("region", { name: "Tuned for" }).locator(".persona-fact").first();
  const firstLine = await roleRow.locator(".walk-fact-line").first().boundingBox();
  const adjust = await roleRow.getByRole("button", { name: "Adjust career track" }).boundingBox();
  expect(adjust!.y).toBeLessThan(firstLine!.y + firstLine!.height);
  expect(adjust!.x).toBeGreaterThan(firstLine!.x + 40);

  await page.getByRole("button", { name: "Add a minimum base" }).click();
  await page.getByLabel("Lowest yearly base salary").fill("250000");
  await page.getByRole("button", { name: "Save minimum base" }).click();
  await expect(page.getByText("$250,000 a year")).toBeVisible();
  expect(saved).toEqual([{ amount: 250000, currency: "USD" }]);
  // The note speaks of the funnel; with no count yet there is nothing for
  // "this" to name (the unit test sees it beside a counted funnel).
  await expect(page.getByRole("region", { name: "What it keeps" }).getByText(/No count yet/)).toBeVisible();
  await expect(page.getByText("The pay floor never narrows this.")).toHaveCount(0);

  const hint = page.getByRole("region", { name: "Your experience" });
  await expect(hint).toContainText("Coming soon");
  await expect(hint.getByRole("link", { name: "Add your CV" })).toHaveAttribute("href", "/profile/experience");
  await expect(page.locator(".ui-btn-primary:visible")).toHaveCount(1);
});

test("Summary actions are full-width controls and the CV page returns to Summary", async ({ page, isMobile }) => {
  if (!isMobile) await page.setViewportSize({ width: 1440, height: 1000 });
  let saves = 0;
  await page.route("/api/settings", (route) => {
    if (route.request().method() !== "GET") saves += 1;
    return route.fallback();
  });
  await page.goto("/profile/direction");
  await page.getByLabel("Working with customers").check();
  await stripButton(page, "Summary").click();
  const floor = page.getByRole("region", { name: "Minimum base" });
  const experience = page.getByRole("region", { name: "Your experience" });
  const opener = floor.getByRole("button", { name: "Add a minimum base" });
  const cv = experience.getByRole("link", { name: "Add your CV" });
  for (const [region, action] of [[floor, opener], [experience, cv]]) {
    const box = (await action.boundingBox())!;
    const container = (await region.boundingBox())!;
    expect(box.width).toBeGreaterThanOrEqual(container.width - 2);
    expect(box.height).toBeGreaterThanOrEqual(72);
    // Desktop keyboard and mobile touch exercise their native input modes.
    if (!isMobile) {
      await action.focus();
      await page.keyboard.press("Tab");
      await page.keyboard.press("Shift+Tab");
      await expect(action).toBeFocused();
      expect(await action.evaluate((el) => getComputedStyle(el).outlineStyle)).toBe("solid");
    }
  }
  if (!isMobile) {
    const a = (await opener.boundingBox())!, b = (await cv.boundingBox())!;
    expect(Math.abs(a.y - b.y)).toBeLessThan(2);
    expect(b.x).toBeGreaterThan(a.x + a.width);
  }
  if (isMobile) {
    await opener.tap();
    await expect(floor.getByRole("textbox", { name: "Lowest yearly base salary" })).toBeVisible();
    await floor.getByRole("button", { name: "Cancel", exact: true }).tap();
    await cv.tap();
  } else {
    await page.keyboard.press("Enter");
  }
  await expect(page).toHaveURL(/\/profile\/experience$/);
  await expect(page.getByRole("heading", { name: "Your experience" })).toBeVisible();
  await expect(page.getByText(/CV upload isn't available yet/)).toBeVisible();
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  await page.getByRole("link", { name: "Back to Summary" }).click();
  await expect(page.getByRole("heading", { name: "Summary" })).toBeVisible();
  await stripButton(page, "Career track").click();
  await expect(page.getByLabel("Working with customers")).toBeChecked();
  expect(saves).toBe(0);
});

for (const count of [1, 50]) {
  test(`company exclusions stay compact with ${count} entries`, async ({ page, isMobile }) => {
    if (!isMobile) await page.setViewportSize({ width: 1440, height: 1000 });
    await page.route("/api/scope/rules", (route) => route.fulfill({ json: {
      rules: Array.from({ length: count }, (_, i) => ({ id: i + 1, company: "google", kind: "department", value: `Software Engineering Infrastructure ${i + 1}`, created_at: "2026-10-04T00:00:00Z" })),
    } }));
    await page.goto("/profile/direction");
    await stripButton(page, "Summary").click();
    const list = page.getByRole("region", { name: "Company exclusions" });
    const toggle = list.getByRole("button", { name: `Company exclusions ${count}` });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(list.getByRole("button", { name: /Remove exclusion/ })).toHaveCount(0);
    expect((await list.boundingBox())!.height).toBeLessThan(80);
    await toggle.click();
    await expect(list.getByRole("button", { name: /Remove exclusion/ })).toHaveCount(Math.min(count, 5));
    if (count > 5) {
      await expect(list.getByText("Page 1 of 10")).toBeVisible();
      await list.getByRole("button", { name: "Next" }).click();
      await expect(list.getByText("Page 2 of 10")).toBeVisible();
      await expect(list.getByRole("button", { name: /Remove exclusion Software Engineering Infrastructure 6 / })).toBeVisible();
      expect((await list.boundingBox())!.height).toBeLessThan(650);
    } else {
      await expect(list.getByRole("button", { name: "Next" })).toHaveCount(0);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await toggle.click();
    await expect(list.getByRole("button", { name: /Remove exclusion/ })).toHaveCount(0);
  });
}
