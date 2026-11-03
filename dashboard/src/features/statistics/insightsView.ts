/* Which Insights a person sees: the basic view, the tabs and panels most
 * readers want, or the advanced view with every chart. Kept on this device,
 * as the theme is.
 *
 * Storage can throw on access (blocked site data, a private window, a full
 * quota), so a failed read is "never chosen" and a failed write is dropped:
 * the switch still works for this visit. */

export type InsightsView = "basic" | "advanced";

const KEY = "roleband.insights-view";

/** The tabs only the advanced view lists. A link to one still opens it. */
export const ADVANCED_TABS: ReadonlySet<string> = new Set([
  "velocity",
  "levels",
  "trajectory",
  "trends",
  "overlap",
  "clusters",
]);

/** The stored view, or null when the person has never turned the advanced
 *  view on: Insights starts basic, and the first turn on asks first. Turning
 *  it off again stores "basic", so a later turn on does not ask twice. */
export function readInsightsView(): InsightsView | null {
  try {
    const saved = localStorage.getItem(KEY);
    return saved === "basic" || saved === "advanced" ? saved : null;
  } catch {
    return null;
  }
}

export function writeInsightsView(view: InsightsView): void {
  try {
    localStorage.setItem(KEY, view);
  } catch {
    // Not remembered: the next visit starts basic.
  }
}
