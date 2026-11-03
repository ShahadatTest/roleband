import { expect, test, type Page } from "./fixtures";
import { levelGuideFixture } from "../../src/test/fixtures";
import { msg } from "../../src/test/msg";
import { installEveryRoute } from "./routesHarness";

/* Insights opens in its basic view: four tabs, and a switch that asks once
   before it lists the other six. These specs run on a first visit, with no
   view stored, unlike the Insights specs that seed the advanced view. */

const OVERVIEW = msg("shell-tab-insights-overview");
const HIRING = msg("shell-tab-insights-hiring");
const PAY = msg("shell-tab-insights-pay");
const LEVELS = msg("shell-tab-insights-levels");
const SKILLS = msg("shell-tab-insights-skills");
const BASIC_TABS = [OVERVIEW, HIRING, PAY, SKILLS];
const ALL_TABS = [
  OVERVIEW, HIRING, msg("shell-tab-insights-pace"), PAY, LEVELS, msg("shell-tab-insights-stock"),
  SKILLS, msg("shell-tab-insights-trends"), msg("shell-tab-insights-overlap"), msg("shell-tab-insights-groups"),
];

const tabs = (page: Page) => page.getByRole("tablist").getByRole("tab");
const advancedSwitch = (page: Page) =>
  page.getByRole("checkbox", { name: msg("insights-statistics-view-advanced-view") });
const warning = (page: Page) =>
  page.getByRole("dialog", { name: msg("insights-statistics-view-advanced-warning-title") });

test.beforeEach(async ({ page }) => {
  await installEveryRoute(page);
});

test("a first visit lists the four basic tabs, with the advanced view off", async ({ page }) => {
  await page.goto("/statistics/overview");
  await expect(page.getByRole("tab", { name: OVERVIEW })).toHaveAttribute("aria-selected", "true");
  await expect(tabs(page)).toHaveText(BASIC_TABS);
  await expect(advancedSwitch(page)).not.toBeChecked();
});

test("turning the advanced view on asks first, and a yes lists every tab and outlives a reload", async ({ page }) => {
  await page.goto("/statistics/overview");
  const toggle = advancedSwitch(page);

  // Escape is a no: nothing changes, and the next turn on asks again.
  await toggle.click();
  await expect(warning(page)).toBeVisible();
  await expect(warning(page)).toContainText(msg("insights-statistics-view-advanced-warning-body"));
  expect(await warning(page).evaluate((el) => el.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(warning(page)).toBeHidden();
  await expect(toggle).not.toBeChecked();
  await expect(tabs(page)).toHaveText(BASIC_TABS);

  await toggle.click();
  await warning(page).getByRole("button", { name: msg("insights-statistics-view-show-me-everything") }).click();
  await expect(warning(page)).toBeHidden();
  await expect(toggle).toBeChecked();
  await expect(tabs(page)).toHaveText(ALL_TABS);

  await page.reload();
  await expect(advancedSwitch(page)).toBeChecked();
  await expect(tabs(page)).toHaveText(ALL_TABS);

  // Once said yes to, the switch goes both ways without asking.
  await advancedSwitch(page).click();
  await expect(tabs(page)).toHaveText(BASIC_TABS);
  await advancedSwitch(page).click();
  await expect(warning(page)).toBeHidden();
  await expect(tabs(page)).toHaveText(ALL_TABS);
});

test("a link to an advanced tab opens it in the basic view, with an offer of the rest", async ({ page }) => {
  await page.route("/api/statistics/levels", (route) => route.fulfill({ json: levelGuideFixture }));
  await page.route("/api/settings", (route) => route.fulfill({ json: { enabled_role_tracks: [] } }));
  await page.goto("/statistics/levels");

  await expect(page.getByRole("tab", { name: LEVELS })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText(msg("insights-statistics-view-part-of-advanced-view"))).toBeVisible();
  await expect(tabs(page)).toHaveText([OVERVIEW, HIRING, PAY, LEVELS, SKILLS]);

  await page.getByRole("tab", { name: OVERVIEW }).click();
  await expect(page).toHaveURL(/\/statistics\/overview$/);
  await expect(page.getByText(msg("insights-statistics-view-part-of-advanced-view"))).toBeHidden();
  await expect(tabs(page)).toHaveText(BASIC_TABS);
});
