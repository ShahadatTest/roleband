import type { FacetEntry } from "../../ui";
import {
  notificationsCategoryChanged,
  notificationsCategoryClosed,
  notificationsCategoryCoverage,
  notificationsCategoryForYou,
  notificationsCategoryLongOpen,
  notificationsCategoryPayDown,
  notificationsCategoryPayUp,
  notificationsCategoryRanOutOfTime,
  notificationsCategoryReminders,
  notificationsCategoryReposted,
  notificationsCategorySaved,
  notificationsCategoryScanFailed,
  notificationsCategoryScanProblems,
  notificationsCategoryScanning,
} from "../../copy/gen/notifications";

/* Notification filter semantics: the taxonomy the register is built from and
 * the reset/count rules that go with it. Kept out of the component for the
 * Board's reason (features/opportunities/filters.ts): a lens's reset scope and
 * its contribution to the "Filters · N" opener are decisions, and a decision
 * that lives inside JSX is one nobody can test on its own.
 */

/** The two closed sets the URL lenses read from. Declared once so the param
 *  hook, the segmented controls and the register's props cannot drift. */
export const STATUS_OPTIONS = ["all", "unread"] as const;
export const PRIORITY_OPTIONS = ["", "high"] as const;
export type NotificationStatus = (typeof STATUS_OPTIONS)[number];
export type NotificationPriority = (typeof PRIORITY_OPTIONS)[number];

/** The lenses the URL carries. Search and page stay in memory (Board parity:
 *  a query is not a lens, and a deep link to page 3 of a moving feed is not a
 *  place). */
export interface NotificationLenses {
  status: NotificationStatus;
  priority: NotificationPriority;
  categories: string[];
}

/* The category facet, in two groups so each stays under the register's
 * search threshold and reads as what it is: what the scraper did, and what
 * happened to a role. Declared order is the reading order (running before
 * failed; new before closed), like the Board's band ladder — not by count. */
export const SYNC_CATEGORIES: [string, () => string][] = [
  ["sync_started", notificationsCategoryScanning],
  ["sync_warning", notificationsCategoryScanProblems],
  // Not reached, or cut by RoleBand's own time limit, with nothing wrong at the
  // company. Filed apart so "Scan problems" counts only problems.
  ["sync_unfinished", notificationsCategoryRanOutOfTime],
  ["sync_failed", notificationsCategoryScanFailed],
  // A followed company RoleBand cannot scan cleanly, one row per company,
  // reconciled each scan. "Coverage" is the vocabulary's word for
  // whether RoleBand can read a company's careers page (docs/copy.md).
  ["coverage", notificationsCategoryCoverage],
];

/* Roles. Every entry here is about a role the user SAVED or is PURSUING --
 * the per-role channel writes nothing for anything else -- so the group reads
 * as one errand rather than a mix of your work and the whole board's churn.
 * `daily_digest` and `pursuit_due` lead because they are the two the user
 * opens the bell for; the rest are state changes on work already committed to.
 *
 * Not in the taxonomy: per-role match news (`new_match`, `high_comp_match`) is
 * the digest's, and the backend writes no `scraper_health` (it would duplicate
 * `sync_warning`), `sync_success` (a clean sync says nothing) or
 * `duplicate_listing`. */
export const ROLE_CATEGORIES: [string, () => string][] = [
  ["daily_digest", notificationsCategoryForYou],
  ["pursuit_due", notificationsCategoryReminders],
  ["saved_update", notificationsCategorySaved],
  ["comp_up", notificationsCategoryPayUp],
  ["comp_down", notificationsCategoryPayDown],
  ["repost", notificationsCategoryReposted],
  ["long_open_update", notificationsCategoryLongOpen],
  ["changed", notificationsCategoryChanged],
  ["closed", notificationsCategoryClosed],
];

export const CATEGORIES = [...SYNC_CATEGORIES, ...ROLE_CATEGORIES];

const SYNC_IDS = SYNC_CATEGORIES.map(([id]) => id);

export function categoryLabel(category: string): string {
  const found = CATEGORIES.find(([id]) => id === category);
  return found?.[1]() ?? category.replace(/_/g, " ");
}

export function facetEntries(
  pairs: [string, () => string][],
  counts: Record<string, number> | undefined,
): FacetEntry[] {
  // The label is read here, at render, so it follows a language switch.
  return pairs.map(([slug, display]) => ({ slug, display: display(), count: counts?.[slug] ?? 0 }));
}

/** Split a category selection into its two facet groups, so each group edits
 *  its own half without dropping the other's chosen values. */
export function splitCategories(categories: string[]): { sync: string[]; role: string[] } {
  return {
    sync: categories.filter((c) => SYNC_IDS.includes(c)),
    role: categories.filter((c) => !SYNC_IDS.includes(c)),
  };
}

/** How many filters are active, counted the way a reader would: one per lens
 *  off its default, one per chosen category. The SEARCH QUERY is deliberately
 *  not counted: it is the context the count is measured in, not a
 *  narrowing of it, exactly as `q` is `queryContext` on the Board. It is also
 *  what makes the number honest: this feeds the folded "Filters · N" opener,
 *  and a counted query would read as an active filter while the panel behind
 *  the opener held nothing at all. */
export function countActiveNotificationFilters(lenses: NotificationLenses): number {
  return (
    (lenses.status !== "all" ? 1 : 0) +
    (lenses.priority !== "" ? 1 : 0) +
    lenses.categories.length
  );
}

/** The lens keys Reset all clears from the URL. Its scope is every filter and
 *  lens and NOTHING else — the query survives, the same words meaning the same
 *  thing here as in the Board's toolbar.
 *
 *  The same three keys are what this screen REMEMBERS
 *  (`routing/useRememberedParams`), which is the one rule worth keeping in
 *  step: what the reader can clear in one click is exactly what comes back
 *  when they return. Clearing is itself remembered, so a reset survives the
 *  trip too. */
export const RESET_LENS_PARAMS = ["status", "priority", "category"] as const;

/** Storage key for this screen's lenses and, under `${SCOPE}:open`, for which
 *  of its groups the reader opened. */
export const NOTIF_MEMORY_SCOPE = "notifications";
