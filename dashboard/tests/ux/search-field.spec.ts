import { expect, test } from "./fixtures";
import { installEveryRoute } from "./routesHarness";

/* ONE RING ON A FOCUSED SEARCH FIELD. The rounded box is the field
   (ui/SearchField: the wrapper carries border, ground and focus halo), and the
   text input inside it is bare. shell.css's app-wide `input:focus-visible`
   ring must not out-rank the input's `outline: none` on specificity, or
   clicking into any search draws a square outline INSIDE the rounded halo.
   A click is what shows it: a text input matches :focus-visible on a pointer
   focus too. */

const SCREENS: { path: string; name: string; step?: string }[] = [
  { path: "/", name: "Search titles and descriptions" },
  { path: "/notifications", name: "Search notifications" },
  { path: "/settings/companies", name: "Search companies" },
  // A search reached through a step, not on arrival: Profile › Which roles.
  { path: "/profile/direction", name: "Filter roles", step: "Discipline" },
];

test.beforeEach(async ({ page }) => {
  await installEveryRoute(page);
});

for (const screen of SCREENS) {
  test(`${screen.path}: a focused search wears the one ring on its rounded field, no inner outline`, async ({ page }) => {
    await page.goto(screen.path);
    if (screen.step) {
      await page.getByRole("tablist", { name: "Steps" }).getByRole("tab", { name: new RegExp(`^${screen.step}( .*)?$`) }).click();
    }
    const input = page.getByRole("searchbox", { name: screen.name, exact: true }).first();
    await input.click();
    await expect(input).toBeFocused();
    expect(await input.evaluate((node) => node.matches(":focus-visible"))).toBe(true);
    // The input draws nothing of its own.
    await expect.poll(() => input.evaluate((node) => getComputedStyle(node).outlineStyle)).toBe("none");
    // The wrapper is the indicator: rounded, with the app's one ring.
    const field = input.locator("xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' ui-search ')][1]");
    await expect.poll(() => field.evaluate((node) => getComputedStyle(node).outlineStyle)).toBe("solid");
    expect(parseFloat(await field.evaluate((node) => getComputedStyle(node).outlineWidth))).toBeGreaterThanOrEqual(2);
    expect(parseFloat(await field.evaluate((node) => getComputedStyle(node).borderTopLeftRadius))).toBeGreaterThan(0);
  });
}
