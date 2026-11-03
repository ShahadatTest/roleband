import { expect, test, type Page } from "./fixtures";
import { msg } from "../../src/test/msg";
import {
  facetsFixture, jobListFixture, notificationsFixture, settingsSaveFixture, statsFixture, statusFixture,
  usageStateFixture,
} from "../../src/test/fixtures";
import type { ScopeSettingsPayload } from "../../src/api";
import { scopeCatalog, scopePreview } from "./scopeFixtures";
import { companyDiscovery, installCompanyRegisterRoutes } from "./settingsHarness";

/* First-run setup: the radar intro, then Profile's own walk with the window
   to itself (no rail, no top bar), then which companies to scan, then the board. A
   configured install never enters it, whatever the URL says, and leaving it
   saves nothing and asks again on the next launch. */

const FRESH = { profile: null, scope_configured: false, intent_statement: "" };
const CONFIGURED = { profile: null, scope_configured: true, intent_statement: "" };

/** A fresh install: nothing scanned yet, so the board has no roles. The first
    scan is under way: 8 of the 35 followed companies read. */
const neverRead = (count: number) => Array.from({ length: count }, (_, index) => ({
  company: `company-${index}`, last_read_at: null, reason: "never_read" as const,
}));
const NEVER_SCANNED = {
  ...statusFixture, last_success_at: null, last_success_age_hours: null, running: true,
  scheduler: { ...statusFixture.scheduler, required: 35, ever_read: 8, fresh: 0, unread: neverRead(23), last_complete_at: null },
};

async function install(page: Page, profile: typeof FRESH) {
  const saves: ScopeSettingsPayload[] = [];
  // Setup's save configures the install, as the server would say after it.
  await page.route("/api/profile", (route) => route.fulfill({ json: saves.length > 0 ? { ...profile, scope_configured: true } : profile }));
  await page.route("/api/stats", (route) => route.fulfill({ json: statsFixture }));
  await page.route("/api/status", (route) => route.fulfill({ json: NEVER_SCANNED }));
  await page.route("/api/facets", (route) => route.fulfill({ json: facetsFixture }));
  await page.route("/api/notifications**", (route) => route.fulfill({ json: notificationsFixture }));
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: { ...jobListFixture, items: [], total: 0 } }));
  await page.route("/api/scope/catalog", (route) => route.fulfill({ json: scopeCatalog }));
  await page.route("/api/scope/preview", (route) => route.fulfill({ json: scopePreview }));
  await page.route("/api/scope/rules", (route) => route.fulfill({ json: { rules: [] } }));
  await page.route("/api/scope/places?**", (route) => route.fulfill({ json: { places: [], unions: [] } }));
  await page.route("/api/companies", (route) => route.fulfill({ json: { companies: [] } }));
  await page.route("/api/profile/suggestions", (route) => route.fulfill({ json: { suggestions: [] } }));
  await page.route("/api/profile/pay-floor", (route) => route.fulfill({ json: { pay_floor: null } }));
  await page.route("/api/settings", async (route) => {
    if (route.request().method() !== "PUT") return route.fallback();
    const body = route.request().postDataJSON() as ScopeSettingsPayload;
    saves.push(body);
    await route.fulfill({ json: settingsSaveFixture(body, { in_scope_changed: 0, on_board: 0 }) });
  });
  await installCompanyRegisterRoutes(page);
  return saves;
}

/** The pay floor's writes, in order; registered after `install`, so they are
 *  answered here before its read-only route. */
async function recordFloorWrites(page: Page) {
  const writes: { method: string; body: unknown }[] = [];
  await page.route("/api/profile/pay-floor", async (route) => {
    const method = route.request().method();
    if (method === "GET") return route.fallback();
    const body = method === "PUT" ? route.request().postDataJSON() : null;
    writes.push({ method, body });
    await route.fulfill({ json: { pay_floor: body } });
  });
  return writes;
}

const SETUP_URL = /\/profile\/direction\?setup=1$/;
const railLink = (page: Page, name: string) => page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name });

test("a fresh install goes from the intro through Profile's walk to a board that says how far its first scan has got", async ({ page, isMobile }) => {
  const saves = await install(page, FRESH);
  const floorWrites = await recordFloorWrites(page);

  await page.goto("/");
  await expect(page).toHaveURL(/\/welcome$/);
  await expect(page.getByRole("heading", { name: "Scanning careers pages for your next role" })).toBeVisible();
  // The count is what the install follows, not every company RoleBand knows.
  // The harness knows no company directory, so the intro claims no reach.
  await expect(page.locator(".welcome-intro-stats")).toHaveCount(0);
  await page.getByRole("button", { name: "Tune the radar" }).click();

  // Profile's walk with the window to itself: no rail, no top bar, no palette
  // over it, so its only ways out are its own. It says what it is and how far
  // along.
  await expect(page).toHaveURL(SETUP_URL);
  await expect(page.getByRole("heading", { name: "What kind of role are you looking for?" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);
  await expect(page.locator(".topbar")).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1, name: "Set up your radar" })).toBeVisible();
  await expect(page.getByText("Setup, step 1 of 7")).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.getByRole("dialog", { name: "Command palette" })).toHaveCount(0);

  // Three answers, two optional ones, the Summary, then Companies; nothing
  // pre-ticked. Why the later tabs are locked is said beside the bar.
  const strip = page.getByRole("tablist", { name: "Steps" });
  await expect(strip.getByRole("tab")).toHaveText(["Career track", "Level", "Location", "Discipline", "World", "Summary", "Companies"]);
  const locked = page.getByText("The other steps open once you answer the first three.");
  await expect(locked).toBeVisible();
  await expect(strip.getByRole("tab", { name: "Discipline" })).toHaveAccessibleDescription("The other steps open once you answer the first three.");
  // Seven tabs scroll inside their bar; the page itself never scrolls sideways.
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width);
  if (!isMobile) {
    const bar = (await strip.boundingBox())!;
    const said = (await locked.boundingBox())!;
    expect(said.x).toBeGreaterThanOrEqual(bar.x + bar.width);
    expect(said.y).toBeGreaterThanOrEqual(bar.y - 1);
    expect(said.y + said.height).toBeLessThanOrEqual(bar.y + bar.height + 1);
  }
  await expect(page.getByLabel("Leading a team")).not.toBeChecked();
  // The first step has nowhere to go back to.
  await expect(page.getByRole("button", { name: "Back" })).toBeHidden();
  await page.getByLabel("Hands-on, as the expert").check();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Setup, step 2 of 7")).toBeVisible();
  // Setup asks for the level alone: roles that state none pass by default,
  // and Profile is where that is changed.
  await expect(page.getByRole("heading", { name: "Your level" })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /Include roles whose level/ })).toHaveCount(0);
  // The grading table names every reference company, so it starts folded,
  // as in Profile: Continue stays in sight. The phone's vertical rail drops
  // the table altogether.
  if (!isMobile) {
    await expect(page.getByRole("button", { name: /What this means at each company/ }))
      .toHaveAttribute("aria-expanded", "false");
    await expect(page.getByText("L6", { exact: true })).toHaveCount(0);
  }
  await page.locator(".stage-cell").filter({ hasText: "Staff" }).click();
  await page.locator(".stage-cell").filter({ hasText: "Staff" }).click();
  await expect(page.getByRole("button", { name: "Continue" })).toBeInViewport();
  await page.getByRole("button", { name: "Continue" }).click();
  // Each step is its own card, so measure only once Location's has replaced Level's.
  await expect(page.getByRole("heading", { name: "Where do you want to work?" })).toBeVisible();
  const card = page.locator(".walk-card");
  const before = (await card.boundingBox())!;
  await page.getByLabel("Where are you based?").fill("silicon");
  await page.getByRole("button", { name: "Add Silicon Valley" }).click();
  await expect(locked).toHaveCount(0);
  // The reason leaves from the bar's own line, so the card does not move.
  if (!isMobile) expect(Math.abs((await card.boundingBox())!.y - before.y)).toBeLessThan(2);
  await page.getByRole("button", { name: "Continue" }).click();

  // The two that sharpen say they are optional and are skipped untouched.
  // Skip sits beside Continue, which stays at the row's end; all three
  // buttons keep one row, a phone's included.
  for (const question of ["Any particular roles?", "Anything you care about, or want to avoid?"]) {
    await expect(page.getByRole("heading", { name: question })).toBeVisible();
    await expect(page.locator(".walk-card-head").getByText("Optional", { exact: true })).toBeVisible();
    const back = (await page.getByRole("button", { name: "Back" }).boundingBox())!;
    const skip = (await page.getByRole("button", { name: "Skip" }).boundingBox())!;
    const advance = (await page.getByRole("button", { name: "Continue" }).boundingBox())!;
    expect(Math.abs(skip.y - advance.y)).toBeLessThan(2);
    expect(Math.abs(back.y - advance.y)).toBeLessThan(2);
    expect(skip.x + skip.width).toBeLessThanOrEqual(advance.x);
    expect(back.x + back.width).toBeLessThanOrEqual(skip.x);
    await page.getByRole("button", { name: "Skip" }).click();
  }
  await expect(page.getByRole("heading", { name: "Summary" })).toBeVisible();
  // The pay floor is set here but held: Start is setup's one save.
  await page.getByRole("button", { name: "Add a minimum base" }).click();
  await page.getByLabel("Lowest yearly base salary").fill("200k");
  await page.getByRole("button", { name: "Set minimum base" }).click();
  await expect(page.getByText("$200,000 a year")).toBeVisible();
  expect(saves).toEqual([]);
  expect(floorWrites).toEqual([]);
  const onward = (await page.getByRole("button", { name: "Continue" }).boundingBox())!;
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Where should your radar look?" })).toBeVisible();
  await expect(page.getByText("Setup, step 7 of 7")).toBeVisible();
  await expect(page.getByRole("radio", { name: /^Well-known companies/ })).toBeChecked();
  // Start stands where the Summary's Continue stood: the last step keeps the
  // walk's frame. A phone's steps are as tall as their content.
  if (!isMobile) {
    const start = (await page.getByRole("button", { name: "Start the radar" }).boundingBox())!;
    expect(Math.abs(start.y - onward.y)).toBeLessThan(2);
  }
  await page.getByRole("button", { name: "Start the radar" }).click();

  await expect(page).toHaveURL(/\/$/);
  expect(saves).toHaveLength(1);
  expect(saves[0]).toMatchObject({
    enabled_role_tracks: ["technical"],
    enabled_location_groups: ["silicon_valley"],
    experience_stage: "staff",
    target_stage: "staff",
  });
  expect(floorWrites).toEqual([{ method: "PUT", body: { amount: 200000, currency: "USD" } }]);
  // Nothing has been scanned: the board says how far the first scan has got
  // instead of blaming filters.
  await expect(page.getByText(msg("radar-first-scan-running-title"))).toBeVisible();
  await expect(page.getByText(msg("radar-first-scan-progress", { read: "8", total: "35" }))).toBeVisible();
  await expect(page.getByText(msg("radar-empty-filtered-title"))).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Finish setting up" })).toHaveCount(0);
  // Start saved the answers the tab kept: nothing of setup is left in it.
  expect(await page.evaluate(() => sessionStorage.getItem("roleband.setup.v1"))).toBeNull();
  // The app comes back around the board.
  await expect(railLink(page, "Settings")).toBeVisible();
});

test("Set up later leaves without saving, and the next launch offers setup again", async ({ page }) => {
  const saves = await install(page, FRESH);
  await page.goto("/");
  await page.getByRole("button", { name: "Tune the radar" }).click();
  await expect(page).toHaveURL(SETUP_URL);
  await page.getByLabel("Leading a team").check();

  await page.getByRole("button", { name: "Set up later" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(railLink(page, "Profile")).toBeVisible();
  // Not set up: the first scan's words, and the way back into setup.
  await expect(page.getByText(msg("radar-first-scan-running-title"))).toBeVisible();
  const finish = page.getByRole("link", { name: "Finish setting up" });
  await expect(finish).toBeVisible();
  expect(saves).toEqual([]);

  // Profile says its answers are starter settings, with the same way back.
  await railLink(page, "Profile").click();
  await expect(page.getByText("Setup isn't finished, so your radar is using starter settings.")).toBeVisible();
  await page.getByRole("link", { name: "Finish setting up" }).click();
  await expect(page).toHaveURL(SETUP_URL);
  await expect(page.getByText("Setup, step 1 of 7")).toBeVisible();
  // The answer given before leaving is kept for the tab until Start.
  await expect(page.getByLabel("Leading a team")).toBeChecked();

  await page.goto("/");
  await expect(page).toHaveURL(/\/welcome$/);
});

/* Setup saves nothing before Start, so its steps are the browser's history
   and its answers are the tab's: Back, the browser's or a phone's gesture,
   steps back through setup and from its first step to the welcome, never out
   of RoleBand, and a reload opens the step it left with every answer. */
test("Back steps back through setup, and a reload keeps the step and its answers", async ({ page }) => {
  const saves = await install(page, FRESH);
  await page.goto("/");
  await page.getByRole("button", { name: "Tune the radar" }).click();
  await expect(page).toHaveURL(SETUP_URL);
  await page.getByLabel("Leading a team").check();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.locator(".stage-cell").filter({ hasText: "Staff" }).click();
  await page.locator(".stage-cell").filter({ hasText: "Staff" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Where are you based?").fill("silicon");
  await page.getByRole("button", { name: "Add Silicon Valley" }).click();
  await expect(page.getByText("Setup, step 3 of 7")).toBeVisible();

  await page.reload();
  await expect(page.getByText("Setup, step 3 of 7")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Where do you want to work?" })).toBeVisible();
  await expect(page.getByText("Silicon Valley").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue" })).toBeEnabled();

  await page.goBack();
  await expect(page.getByText("Setup, step 2 of 7")).toBeVisible();
  // The level is still answered: Continue opens only on an answered level.
  await expect(page.getByRole("button", { name: "Continue" })).toBeEnabled();
  await page.goBack();
  await expect(page.getByText("Setup, step 1 of 7")).toBeVisible();
  await expect(page.getByLabel("Leading a team")).toBeChecked();
  await page.goBack();
  await expect(page).toHaveURL(/\/welcome$/);

  // Into the walk again, the answers are still there.
  await page.getByRole("button", { name: "Tune the radar" }).click();
  await expect(page.getByLabel("Leading a team")).toBeChecked();
  expect(saves).toEqual([]);
});

/* A save in Profile configures the install as setup's Start does: the notice
   that setup is unfinished goes at once, and the board says the radar is set. */
test("a save in Profile ends an unfinished setup", async ({ page }) => {
  const saves = await install(page, FRESH);
  await page.goto("/profile/direction");
  const unfinished = page.getByText("Setup isn't finished, so your radar is using starter settings.");
  await expect(unfinished).toBeVisible();
  await page.getByLabel("Working with customers").check();
  await page.getByRole("region", { name: "Review changes" }).getByRole("button", { name: "Save" }).click();
  await expect.poll(() => saves.length).toBe(1);
  await expect(unfinished).toHaveCount(0);
  await railLink(page, "Radar").click();
  await expect(page.getByText(msg("radar-first-scan-running-title"))).toBeVisible();
  await expect(page.getByRole("link", { name: "Finish setting up" })).toHaveCount(0);
});

test("a configured install never gets setup, not even from the URL", async ({ page }) => {
  await install(page, CONFIGURED);

  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await expect(page).toHaveURL(/\/$/);

  await page.goto("/profile/direction?setup=1");
  await expect(page.getByRole("tablist", { name: "Steps" }).getByRole("tab", { name: "Discipline" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Set up later" })).toHaveCount(0);
  await expect(page.getByText(/^Setup, step/)).toHaveCount(0);
  await expect(railLink(page, "Radar")).toBeVisible();
});

/* The intro is setup's front door: it has the window too, so no side door
   opens over it, and its own Escape is the way into the walk. */
test("the radar intro has the window to itself, and Escape enters the walk", async ({ page }) => {
  await install(page, FRESH);
  await page.goto("/welcome");
  await expect(page.getByRole("heading", { name: "Scanning careers pages for your next role" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);
  await expect(page.locator(".topbar")).toHaveCount(0);

  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.getByRole("dialog", { name: "Command palette" })).toHaveCount(0);

  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(SETUP_URL);
});

test("a configured install visiting the intro keeps its app open", async ({ page }) => {
  await install(page, CONFIGURED);
  await page.goto("/welcome");
  await expect(page.getByRole("heading", { name: "Scanning careers pages for your next role" })).toBeVisible();
  await expect(railLink(page, "Radar")).toBeVisible();
});

/* The intro is one screen: its button sits above the fold on a laptop. */
test("the intro's button is above the fold", async ({ page, isMobile }) => {
  test.skip(isMobile, "a phone scrolls the intro by design");
  await install(page, FRESH);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/welcome");
  const begin = page.getByRole("button", { name: "Tune the radar" });
  await expect(begin).toBeVisible();
  const box = await begin.boundingBox();
  expect(box!.y + box!.height).toBeLessThanOrEqual(900);
});

const DIRECTORY = { size: 12_500, following: false, since: null, checked: 0, to_check: 12_500, with_roles: 0, waiting_for_power: false };

/* How many companies are within reach: the directory's size rounded DOWN, so
   "more than" never overstates. On a laptop the promise, the cost and the
   reach each hold one line. */
test("the intro says how many companies are within reach", async ({ page, isMobile }) => {
  await install(page, FRESH);
  await page.route("/api/companies/directory/status", (route) => route.fulfill({ json: DIRECTORY }));
  const widths = isMobile ? [page.viewportSize()!.width] : [1440, 2000];
  for (const width of widths) {
    if (!isMobile) await page.setViewportSize({ width, height: width === 1440 ? 900 : 1100 });
    await page.goto("/welcome");
    await expect(page.locator(".welcome-intro-stats")).toHaveText("12,000+ companies within reach");
    const lines = (selector: string) => page.locator(selector).evaluateAll((items) =>
      items.map((item) => Math.round(item.getBoundingClientRect().height / parseFloat(getComputedStyle(item).lineHeight))));
    const paragraph = await lines(".welcome-intro-line");
    // The cost always starts its own line.
    expect(paragraph).toHaveLength(2);
    if (!isMobile) {
      expect(paragraph).toEqual([1, 1]);
      expect(await lines(".welcome-intro-stats")).toEqual([1]);
    }
  }
});

/* Setup is always dark: a person who chose light sees the welcome page and
   the walk dark from the first paint, and finds their own theme, still saved,
   once they leave setup. */
test("first-run setup is dark even for a light theme, and the theme comes back after it", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("theme", "light");
    // The first theme the page paints with, set by the boot script before the app runs.
    // Watched from the document: this runs before <html> is parsed.
    new MutationObserver((records, observer) => {
      (window as unknown as { firstTheme?: string }).firstTheme = (records[0].target as Element).getAttribute("data-theme") ?? "";
      observer.disconnect();
    }).observe(document, { subtree: true, attributes: true, attributeFilter: ["data-theme"] });
  });
  await install(page, FRESH);
  await page.goto("/welcome");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(() => (window as unknown as { firstTheme?: string }).firstTheme)).toBe("dark");

  await page.getByRole("button", { name: "Tune the radar" }).click();
  await expect(page).toHaveURL(SETUP_URL);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  await page.getByRole("button", { name: "Set up later" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(await page.evaluate(() => localStorage.getItem("theme"))).toBe("light");
});

/* The planet turns when the reader drags it, and only when they grab the
   planet itself. Reduced motion holds one frame, so pictures compare. */
test("the welcome planet holds still under reduced motion and turns when dragged", async ({ page, isMobile }) => {
  test.skip(isMobile, "a phone turns it by touch; this drives a mouse");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await install(page, FRESH);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/welcome");
  const globe = page.locator(".welcome-globe");
  await expect(globe).toBeVisible();
  // Settled once the world shapes have loaded and drawn.
  let before = await globe.screenshot();
  for (let i = 0; i < 20; i++) {
    await page.waitForTimeout(150);
    const next = await globe.screenshot();
    if (next.equals(before)) break;
    before = next;
  }
  await page.waitForTimeout(1000);
  expect((await globe.screenshot()).equals(before)).toBe(true);

  // The planet sits right of centre (globeView.place): grab its middle, and a
  // point above the copy and left of its edge.
  const box = (await globe.boundingBox())!;
  const r = Math.min(box.height * 0.56, box.width * 0.36);
  const centre = { x: box.x + box.width * 0.64, y: box.y + box.height * 0.57 };
  const beside = { x: centre.x - r - 40, y: box.y + 40 };
  await page.mouse.move(beside.x, beside.y);
  await page.mouse.down();
  await page.mouse.move(beside.x + 150, beside.y + 60, { steps: 6 });
  await page.mouse.up();
  expect((await globe.screenshot()).equals(before)).toBe(true);

  await page.mouse.move(centre.x, centre.y);
  await expect(globe).toHaveCSS("cursor", "grab");
  await page.mouse.down();
  await page.mouse.move(centre.x + 200, centre.y + 40, { steps: 8 });
  await page.mouse.up();
  expect((await globe.screenshot()).equals(before)).toBe(false);
});

test("the welcome page never scrolls sideways", async ({ page }) => {
  await install(page, FRESH);
  await page.goto("/welcome");
  await expect(page.locator(".welcome-globe")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width);
});

/* The sharing question is alone on its screen, so it sits in the middle of
   the page, not against its left edge; on a phone it starts on screen. */
/* The sharing question is asked in the intro's own scene: the planet stays,
   dimmed, and the question stands where the intro's words stood, whole on the
   screen. Its two answers look the same, and Escape does not skip it. */
test("the sharing question takes the intro's place over the dimmed planet", async ({ page, isMobile }) => {
  await install(page, FRESH);
  await page.route("/api/usage", (route) => route.request().method() === "GET"
    ? route.fulfill({ json: usageStateFixture("undecided") }) : route.fallback());
  const sizes = isMobile ? [page.viewportSize()!] : [{ width: 1440, height: 900 }, { width: 2000, height: 1100 }];
  for (const size of sizes) {
    if (!isMobile) await page.setViewportSize(size);
    await page.goto("/welcome");
    const words = (await page.getByRole("heading", { name: "Scanning careers pages for your next role" }).boundingBox())!;
    await page.getByRole("button", { name: "Tune the radar" }).click();
    const question = page.getByRole("region", { name: "Help us improve" });
    await expect(question).toBeVisible();
    await expect(page.getByRole("heading", { name: "Scanning careers pages for your next role" })).toHaveCount(0);

    // The same planet, still drawn, now dim behind the question.
    const planet = page.locator("canvas.welcome-globe");
    await expect(planet).toBeVisible();
    await expect.poll(async () => Number(await planet.evaluate((el) => getComputedStyle(el).opacity))).toBeLessThan(0.5);

    const box = (await question.boundingBox())!;
    expect(box.y).toBeGreaterThanOrEqual(0);
    if (!isMobile) {
      // Where the words stood, and whole on the screen.
      expect(Math.abs(box.x - words.x)).toBeLessThan(2);
      expect(box.y + box.height).toBeLessThanOrEqual(size.height);
    }

    // Two answers of one look and one size: neither is the default.
    const no = question.getByRole("button", { name: "No thanks" });
    const yes = question.getByRole("button", { name: "Happy to help" });
    const look = (button: typeof no) => button.evaluate((el) => {
      const style = getComputedStyle(el);
      const { width, height } = el.getBoundingClientRect();
      return [style.backgroundColor, style.borderColor, style.color, Math.round(width), Math.round(height)];
    });
    expect(await look(no)).toEqual(await look(yes));

    await page.keyboard.press("Escape");
    await expect(page).toHaveURL(/\/welcome$/);
    await expect(question).toBeVisible();
  }
});

/* Setup has the window, and stands in it as one column: centred and no wider
   than 1320px at the owner's width, a little below the top rather than
   against it. On a phone there is no dock under it. */
test("setup stands as one centred column below the top", async ({ page, isMobile }) => {
  await install(page, FRESH);
  for (const [width, height] of isMobile ? [[0, 0]] : [[2000, 1100], [1440, 900]]) {
    if (!isMobile) await page.setViewportSize({ width, height });
    await page.goto("/profile/direction?setup=1");
    const walk = page.getByRole("region", { name: "What your radar looks for" });
    await expect(page.getByRole("heading", { level: 1, name: "Set up your radar" })).toBeVisible();
    const box = (await walk.boundingBox())!;
    const view = page.viewportSize()!;
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(view.width);
    await expect(page.locator(".nav-rail")).toHaveCount(0);
    if (isMobile) continue;
    expect(box.width).toBeLessThanOrEqual(1320);
    expect(Math.abs(box.x + box.width / 2 - view.width / 2)).toBeLessThan(2);
    const title = (await page.getByRole("heading", { level: 1, name: "Set up your radar" }).boundingBox())!;
    expect(title.y).toBeGreaterThan(view.height * 0.08);
  }
});

/* A fresh install has read nothing yet, so every count would be zero: setup
   says what was chosen instead, and offers nothing to count. */
/* Setup counts nothing: before the first scan every count is zero, and during
   it (it starts as setup opens) most are, so the answers stand alone. */
for (const [when, levels] of [
  ["before anything is scanned", scopeCatalog.levels.map((level) => ({ ...level, count: 0 }))],
  ["while the first scan has read some roles", scopeCatalog.levels],
] as const) {
  test(`${when}, setup shows the answers, not counts`, async ({ page }) => {
    await install(page, FRESH);
    await page.unroute("/api/scope/catalog");
    await page.route("/api/scope/catalog", (route) => route.fulfill({
      json: { ...scopeCatalog, unstated_level_count: 0, levels },
    }));
    await page.goto("/profile/direction?setup=1");
    const rail = page.getByRole("complementary", { name: "Your progress" });
    await page.getByLabel("Leading a team").check();
    // Seen beside the layer, and said as the layer's description.
    await expect(rail.locator(".walk-pyramid-caption").filter({ hasText: "Career track" })).toContainText("Leading a team");
    await expect(rail.getByRole("button", { name: "Career track" })).toHaveAccessibleDescription("Leading a team");
    await expect(rail.getByText(/No count/)).toHaveCount(0);
    await expect(rail.getByRole("button", { name: /Count now/ })).toHaveCount(0);

    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("heading", { name: "Your level" })).toBeVisible();
    await expect(page.locator(".stage-cell").filter({ hasText: /roles?$/ })).toHaveCount(0);
    await expect(page.locator(".stage-count")).toHaveCount(0);
    await page.locator(".stage-cell").filter({ hasText: "Staff" }).first().click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByLabel("Where are you based?").fill("silicon");
    await page.getByRole("button", { name: "Add Silicon Valley" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("heading", { name: "Any particular roles?" })).toBeVisible();
    await expect(page.locator(".walk-roles .select-card small").filter({ hasText: /\d[\d,]* roles?\b/ })).toHaveCount(0);
  });
}

/* Until every followed company has been read once the board waits for its
   first roles with the radar mark alone, unframed and larger, a title and its
   lines: the companies read so far and when to look again while the scan
   runs, or that it is about to start. An install that left setup for later
   is offered the way back into it. */
test("before the first scan ends the board shows the radar mark, a title and the scan's lines", async ({ page }) => {
  await install(page, CONFIGURED);
  const textFor = async (status: typeof NEVER_SCANNED, title: string) => {
    await page.unroute("/api/status");
    await page.route("/api/status", (route) => route.fulfill({ json: status }));
    await page.goto("/");
    await expect(page.locator(".board-first-scan .empty .big")).toHaveText(new RegExp(`^${title}`));
    return page.locator(".board-first-scan .empty").innerText();
  };

  expect(await textFor(NEVER_SCANNED, msg("radar-first-scan-running-title")))
    .toContain(msg("radar-first-scan-progress", { read: "8", total: "35" }));
  expect(await textFor({ ...NEVER_SCANNED, scheduler: { ...NEVER_SCANNED.scheduler, seeded: false, required: 0, ever_read: 0 } },
    msg("radar-first-scan-running-title"))).toContain(msg("radar-first-scan-progress-unknown"));
  expect(await textFor({ ...NEVER_SCANNED, running: false, last_run_started_at: null, scheduler: { ...NEVER_SCANNED.scheduler, ever_read: 0 } },
    msg("radar-first-scan-starting-title"))).toContain(msg("radar-first-scan-starting"));

  // The mark alone: no frame, larger than an ordinary empty state's, and
  // nothing in the board's place but the title and the scan's two lines.
  await textFor(NEVER_SCANNED, msg("radar-first-scan-running-title"));
  const empty = page.locator(".board-first-scan .empty");
  await expect(empty).toHaveCSS("border-top-style", "none");
  expect((await empty.locator(".empty-art").boundingBox())!.width).toBeGreaterThanOrEqual(160);
  expect((await empty.innerText()).split("\n").filter((line) => line.trim())).toHaveLength(3);
  await expect(empty.getByRole("link", { name: msg("radar-empty-first-scan-finish") })).toHaveCount(0);
});

/* A fresh install's first launch at "/" goes to the welcome without the
   board, the rail or the top bar showing for a moment first: the app asks
   whether it is set up before it draws anything. */
test("a first launch shows no app chrome and no board before the welcome", async ({ page }) => {
  await install(page, FRESH);
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { __seen: string[] }).__seen = seen;
    new MutationObserver(() => {
      for (const selector of [".topbar", ".nav-rail", ".board-search-box"]) {
        if (document.querySelector(selector) && !seen.includes(selector)) seen.push(selector);
      }
    }).observe(document, { childList: true, subtree: true });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Scanning careers pages for your next role" })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __seen: string[] }).__seen)).toEqual([]);
});

/* Discipline sets hints of one line and of two side by side, and a few
   names of two lines: every name in a row still starts on the same line, its
   checkbox beside it, on every craft of the hands-on answer too. */
test("on Discipline the names of a row start on one line, whatever their hints run to", async ({ page, isMobile }) => {
  test.skip(isMobile, "a phone sets one card per row");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await install(page, FRESH);
  await page.goto("/");
  await page.getByRole("button", { name: "Tune the radar" }).click();
  for (const answer of ["Leading a team", "Owning a product", "Hands-on, as the expert", "Working with customers"]) {
    await page.getByLabel(answer).check();
  }
  await page.getByRole("button", { name: "Continue" }).click();
  await page.locator(".stage-cell").filter({ hasText: "Staff" }).click();
  await page.locator(".stage-cell").filter({ hasText: "Staff" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Where are you based?").fill("silicon");
  await page.getByRole("button", { name: "Add Silicon Valley" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Any particular roles?" })).toBeVisible();

  const rows = () => page.locator(".walk-roles .walk-cards").evaluateAll((grids) => grids.flatMap((grid) => {
    const byRow = new Map<number, { name: number; box: number; nameLines: number; hintLines: number }[]>();
    for (const card of grid.querySelectorAll("label.select-card")) {
      const name = card.querySelector(".select-card-label")!.getBoundingClientRect();
      const hint = card.querySelector("small")!.getBoundingClientRect();
      const row = Math.round(card.getBoundingClientRect().top);
      byRow.set(row, [...(byRow.get(row) ?? []), {
        name: name.top, box: card.querySelector("input")!.getBoundingClientRect().top,
        nameLines: Math.round(name.height / 16), hintLines: Math.round(hint.height / 15),
      }]);
    }
    return [...byRow.values()].filter((cards) => cards.length > 1);
  }));
  const spread = (values: number[]) => Math.max(...values) - Math.min(...values);
  let uneven = 0;
  const crafts = page.getByRole("group", { name: "Craft for Hands-on, as the expert" }).getByRole("button");
  expect(await crafts.count()).toBeGreaterThan(1);
  for (let index = 0; index < await crafts.count(); index++) {
    await crafts.nth(index).click();
    await expect(crafts.nth(index)).toHaveAttribute("aria-pressed", "true");
    for (const cards of await rows()) {
      expect(spread(cards.map((card) => card.name))).toBeLessThan(1);
      expect(spread(cards.map((card) => card.box))).toBeLessThan(1);
      if (new Set(cards.map((card) => `${card.nameLines}/${card.hintLines}`)).size > 1) uneven += 1;
    }
  }
  // The steps above held rows whose cards differ in their lines, not only
  // rows of identical cards.
  expect(uneven).toBeGreaterThan(2);
});

/* The planet's page is its own dark ground: the app's ambient wash, whose warm
   corner reads as a stray light beside the lit planet, does not show. */
test("the welcome paints its own ground over the app's ambient wash", async ({ page }) => {
  await install(page, FRESH);
  await page.goto("/welcome");
  const ground = await page.locator("main.welcome-main").evaluate((el) => {
    const style = getComputedStyle(el);
    const probe = document.createElement("div");
    probe.style.color = "var(--app-canvas)";
    document.body.append(probe);
    const canvas = getComputedStyle(probe).color;
    probe.remove();
    return { paint: style.backgroundColor, canvas };
  });
  expect(ground.paint).toBe(ground.canvas);
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundImage)).toBe("none");
});

/* Before any of the app's code runs, the launch is already on the plain
   ground, so the wash does not flash for the first frames; the board of a
   configured install gets its wash back. */
test("the wash stays off from the first paint of a launch and returns on the board", async ({ page }) => {
  await install(page, CONFIGURED);
  await page.route("**/assets/index-*.js", (route) => route.abort());
  await page.route("**/src/main.tsx", (route) => route.abort());
  await page.goto("/");
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundImage)).toBe("none");

  await page.unroute("**/assets/index-*.js");
  await page.unroute("**/src/main.tsx");
  await page.goto("/");
  await expect(page.locator(".topbar")).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => getComputedStyle(document.body).backgroundImage))
    .not.toBe("none");
});

/** Setup's three answers from the first step, both optional steps skipped:
 *  lands on the Summary. */
async function walkToSummary(page: Page) {
  await page.goto("/profile/direction?setup=1");
  await page.getByLabel("Hands-on, as the expert").check();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.locator(".stage-cell").filter({ hasText: "Staff" }).click();
  await page.locator(".stage-cell").filter({ hasText: "Staff" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Where are you based?").fill("silicon");
  await page.getByRole("button", { name: "Add Silicon Valley" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Skip" }).click();
  await page.getByRole("button", { name: "Skip" }).click();
  await expect(page.getByRole("heading", { name: "Summary" })).toBeVisible();
}

/* The follow confirmation is a consent text: in setup it wears the same form
   as in Settings, its words and buttons inside the dialog's edge. */
test("setup's follow confirmation keeps its words inside the dialog's edge", async ({ page }) => {
  await install(page, FRESH);
  await walkToSummary(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("radio", { name: /^Every listed company/ }).check();
  await page.getByRole("button", { name: "Start the radar" }).click();
  const ask = page.getByRole("dialog", { name: "Follow the whole list?" });
  await expect(ask).toBeVisible();
  const edge = (await ask.boundingBox())!;
  for (const part of [ask.getByRole("heading"), ask.getByRole("button", { name: "Keep curated list" })]) {
    const box = (await part.boundingBox())!;
    expect(box.x - edge.x).toBeGreaterThanOrEqual(12);
    expect(box.y - edge.y).toBeGreaterThanOrEqual(0);
    expect(edge.x + edge.width - (box.x + box.width)).toBeGreaterThanOrEqual(0);
  }
  const heading = (await ask.getByRole("heading").boundingBox())!;
  expect(heading.y - edge.y).toBeGreaterThanOrEqual(12);
});

/* "Plus other companies" is one choice, so it is one question: it follows the rest
   of the list and starts the wider scan on a single yes, then setup ends. */
test("Plus other companies asks one question, follows the list and the rest, then opens the board", async ({ page }) => {
  const saves = await install(page, FRESH);
  await page.route("/api/companies/directory/status", (route) => route.fulfill({ json: DIRECTORY }));
  const writes: string[] = [];
  await page.route("/api/companies/selection", async (route) => {
    writes.push("selection");
    await route.fulfill({ json: companyDiscovery });
  });
  await page.route("/api/companies/directory/follow", async (route) => {
    writes.push("directory");
    await route.fulfill({ json: { ...DIRECTORY, following: true, since: "2026-10-28T08:00:00Z" } });
  });
  await walkToSummary(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("radio", { name: /^Plus other companies/ }).check();
  await page.getByRole("button", { name: "Start the radar" }).click();

  const ask = page.getByRole("dialog", { name: "Follow the other companies too?" });
  await expect(ask).toBeVisible();
  await expect(ask).toContainText("Your radar adds the other companies");
  // The choice is the list and the other companies: the question counts nothing.
  await expect(ask).not.toContainText(/\d/);
  // No paragraph of the question ends on a word alone on its line.
  const lastLines = await ask.locator("p").evaluateAll((paragraphs) => paragraphs.map((p) => {
    const words: { top: number; word: string }[] = [];
    const texts = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
    for (let text = texts.nextNode(); text; text = texts.nextNode()) {
      for (const match of (text.textContent ?? "").matchAll(/\S+/g)) {
        const range = document.createRange();
        range.setStart(text, match.index);
        range.setEnd(text, match.index + match[0].length);
        words.push({ top: Math.round(range.getBoundingClientRect().top), word: match[0] });
      }
    }
    const last = words[words.length - 1].top;
    return words.filter((entry) => entry.top === last).map((entry) => entry.word).join(" ");
  }));
  for (const line of lastLines) expect(line.split(" ").length, line).toBeGreaterThan(1);
  expect(writes).toEqual([]);
  await ask.getByRole("button", { name: "Follow them" }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(writes).toEqual(["selection", "directory"]);
  expect(saves).toHaveLength(1);
});

/* Opened from the keyboard, the sharing question takes the keyboard to its
   safe answer, so Enter on a question that just opened never shares. */
test("the sharing question, opened by keyboard, puts focus on No thanks", async ({ page }) => {
  await install(page, FRESH);
  await page.route("/api/usage", (route) => route.request().method() === "GET"
    ? route.fulfill({ json: usageStateFixture("undecided") }) : route.fallback());
  await page.goto("/welcome");
  await page.getByRole("button", { name: "Tune the radar" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("region", { name: "Help us improve" }).getByRole("button", { name: "No thanks" })).toBeFocused();
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
});

/* On a phone a place's reach switch has a line of its own, so a metro, its
   country and its region read side by side, with Remove on the line below. */
test("on a phone a place's reach reads in full, with Remove below it", async ({ page, isMobile }) => {
  test.skip(!isMobile, "the phone's row");
  await install(page, FRESH);
  await page.unroute("/api/scope/catalog");
  await page.route("/api/scope/catalog", (route) => route.fulfill({
    json: {
      ...scopeCatalog,
      locations: [
        ...scopeCatalog.locations.map((location) => location.slug === "united_states" ? { ...location, parent: "north_america" } : location),
        { slug: "north_america", display: "North America", default_enabled: false, selected: false, new: false, count: 9, kind: "region", parent: null, uncovered_by: [], prominent: true },
      ],
    },
  }));
  await page.goto("/profile/direction?setup=1");
  await page.getByLabel("Hands-on, as the expert").check();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.locator(".stage-cell").filter({ hasText: "Staff" }).click();
  await page.locator(".stage-cell").filter({ hasText: "Staff" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Where are you based?").fill("silicon");
  await page.getByRole("button", { name: "Add Silicon Valley" }).click();
  const reach = page.getByRole("group", { name: /How far from Silicon Valley/ });
  await expect(reach.getByRole("button", { name: "North America" })).toBeVisible();
  expect(await reach.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  const remove = (await page.getByRole("button", { name: "Remove Silicon Valley" }).boundingBox())!;
  const switchBox = (await reach.boundingBox())!;
  expect(remove.y).toBeGreaterThanOrEqual(switchBox.y + switchBox.height - 1);
});

/* Two careers sites that cannot be asked about the same place share one
   sentence, and a place every source can ask about adds nothing to it. */
test("companies that cannot search a place share one note", async ({ page, isMobile }) => {
  if (!isMobile) await page.setViewportSize({ width: 1440, height: 900 });
  await install(page, FRESH);
  await page.unroute("/api/scope/catalog");
  await page.route("/api/scope/catalog", (route) => route.fulfill({
    json: {
      ...scopeCatalog,
      locations: [
        ...scopeCatalog.locations,
        { slug: "sweden", display: "Sweden", default_enabled: false, selected: false, new: false, count: 3, kind: "country", parent: "europe", uncovered_by: ["acme", "globex"], prominent: false },
      ],
    },
  }));
  await page.goto("/profile/direction?setup=1");
  await page.getByLabel("Hands-on, as the expert").check();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.locator(".stage-cell").filter({ hasText: "Staff" }).click();
  await page.locator(".stage-cell").filter({ hasText: "Staff" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Where are you based?").fill("swed");
  await page.getByRole("button", { name: "Add Sweden" }).click();

  const note = page.getByRole("note").filter({ hasText: "can't be searched for" });
  await expect(note).toHaveCount(1);
  await expect(note).toHaveText(/^The careers sites of \S+ and \S+ can't be searched for Sweden yet, so their roles there won't reach your radar\.$/);
  expect(await note.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("where-note.png"), fullPage: true });
});
