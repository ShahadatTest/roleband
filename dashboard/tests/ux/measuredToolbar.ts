import { expect, type Page } from "@playwright/test";

/** Real browser geometry, including CSS-only reflow (no React/window signal). */
export async function expectMeasuredToolbar(page: Page, root: string, toolbar: string, property: string) {
  const measure = () => page.evaluate(({ root, toolbar, property }) => {
    const host = document.querySelector<HTMLElement>(root)!;
    const band = document.querySelector<HTMLElement>(toolbar)!;
    return {
      actual: band.getBoundingClientRect().height,
      published: Number.parseFloat(host.style.getPropertyValue(property)),
    };
  }, { root, toolbar, property });
  await expect.poll(async () => {
    const size = await measure();
    return Math.abs(size.actual - size.published);
  }).toBeLessThan(1);
  const initial = await measure();

  // A text-spacing override can grow a band without any React render. Changing
  // its padding is a deterministic equivalent, independent of fixture wording.
  await page.locator(toolbar).evaluate((node) => {
    node.style.paddingBottom = `${Number.parseFloat(getComputedStyle(node).paddingBottom) + 31}px`;
  });
  await expect.poll(async () => (await measure()).actual - initial.actual).toBeGreaterThan(30);
  await expect.poll(async () => {
    const size = await measure();
    return Math.abs(size.actual - size.published);
  }).toBeLessThan(1);
}
