/* The dashboard runs under its Content-Security-Policy (csp-policy.json, served
   by the API and, for the build, by `vite preview`): every route renders with
   no script, style, font, image or connection the policy refuses. A refusal is
   a feature the browser silently broke, so one fails the sweep by name. */

import { expect, test } from "./fixtures";
import { installEveryRoute } from "./routesHarness";
import { uxProfile } from "./runProfile";

const ROUTES = [
  "/", "/favorites", "/profile", "/compare", "/statistics", "/company", "/review",
  "/notifications", "/settings", "/settings/privacy", "/welcome",
];

test("every route renders under the Content-Security-Policy with nothing refused", async ({ page }) => {
  test.skip(uxProfile().mode === "dev", "the policy is served with the build: use ROLEBAND_UX_MODE=build");
  test.slow();
  await installEveryRoute(page);
  const refused: string[] = [];
  page.on("console", (message) => {
    if (/Content Security Policy/i.test(message.text())) refused.push(message.text());
  });
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (event) => {
      (window as unknown as { __refused: string[] }).__refused ??= [];
      (window as unknown as { __refused: string[] }).__refused.push(`${event.violatedDirective} ${event.blockedURI}`);
    });
  });

  for (const path of ROUTES) {
    const response = await page.goto(path);
    expect(response?.headers()["content-security-policy"], `${path} is served without the policy`)
      .toContain("script-src 'self'");
    await expect(page.getByRole("main").first()).toBeVisible();
    // The theme is set before first paint by a script the policy must allow.
    await expect(page.locator("html")).toHaveAttribute("data-theme", /light|dark/);
    const seen = await page.evaluate(() => (window as unknown as { __refused?: string[] }).__refused ?? []);
    refused.push(...seen.map((line) => `${path}: ${line}`));
  }
  expect(refused, refused.join("\n")).toEqual([]);
});
