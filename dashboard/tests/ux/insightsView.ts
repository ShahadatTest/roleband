import type { Page } from "./fixtures";

/* Insights starts in its basic view. A spec that reads an advanced tab or
   panel turns the advanced view on before the page loads, as it is for a
   person who said yes to it once (`features/statistics/insightsView.ts`). */
export async function showAdvancedInsights(page: Page) {
  await page.addInitScript(() => localStorage.setItem("roleband.insights-view", "advanced"));
}
