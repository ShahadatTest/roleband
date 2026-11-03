import { timestamp as copyTimestamp , date } from "./copy/format";
export { fmtComp, fmtCompIn, fmtRange } from "./money";
/* Screen-only labels live in ./labels and are re-exported here, so importers
   keep writing `../format`. The shell loads THIS file, and a module the shell
   loads carries every export any lazy screen uses (a `duration` helper, or
   `LOC_LABEL` pulling all of locations.gen.ts); a re-export does not, because
   the package declares its modules side-effect-free. Only what the shell itself
   calls is defined in this file; `npm run build` names anything else. */
export { BAND_LABEL, BAND_ORDER, LOC_LABEL, WORKPLACE_LABEL, flagEmoji, isMetro, relDays } from "./labels";
import { shellFreshnessBehind, shellFreshnessChecked, shellFreshnessNever, shellScanScanning } from "./copy/gen/shell";
import {
  formatAgeDays,
  formatAgeHours,
  formatAgeJustNow,
  formatAgeMinutes,
  formatAgeNever,
} from "./copy/gen/format";
// Display helpers: currency, dates, labels, company brand colors.

// The only per-company literal in the dashboard. Kept in companies.json so the
// backend blueprint completeness test cross-checks it against tracker/blueprint.py
// (name + color must match; every blueprint company must be present).
import companies from "./companies.json";

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return date(iso, "full");
}

/* Count badges: a real number, or something that does not pretend to be one.
 *
 * `99+` alone is not a policy when one badge lives above it permanently. The
 * Review rail count is the pending duplicate/twin queue (`review_pending`),
 * which every scrape refills, so a `99+` badge saturates on day one and never
 * settles again: a red light that cannot turn off, carrying no information
 * past "a lot". A count badge is a call to action, and a call to action that
 * is always on is chrome.
 *
 * So the cap is where the badge STOPS CLAIMING to be a count rather than where
 * it starts lying about one: at or below it, the exact number; above it, a dot
 * — presence without a magnitude nobody can act on. The exact count is never
 * lost, because `label` is what every caller must put in the tooltip and the
 * accessible name at both sizes. That is also the first time a rail count is
 * announced at all: the rail items and the bell carry an `aria-label`, which
 * overrides their subtree, so the digits inside were never read out.
 *
 * 99 is the cap because it is the widest count the existing 17px badge box
 * holds without reflowing the rail or the bell.
 */
export const COUNT_BADGE_MAX = 99;

export interface CountBadge {
  /** Digits to paint, or null past the cap — paint a dot instead. */
  text: string | null;
  /** True past the cap. */
  dot: boolean;
  /** The exact count in words, for the tooltip and the accessible name. */
  label: string;
}

/** `say` is the catalog message that words the count ("7 unread"), so each
 *  language orders its own words; the number is formatted inside it. */
export function countBadge(count: number, say: (args: { count: number }) => string): CountBadge {
  const dot = count > COUNT_BADGE_MAX;
  return { text: dot ? null : String(count), dot, label: say({ count }) };
}

export const COMPANY: Record<string, { name: string; color: string }> = companies;

/** A record's OWN value for `key`, never one inherited from `Object.prototype`.
 *  Company slugs come from a 12,500-board directory and can be any word:
 *  `counts["constructor"]` is the `Object` function, and summing it turned the
 *  Followed companies toolbar into "309function Object() {...}0100...". */
export function ownValue<T>(record: Readonly<Record<string, T>> | null | undefined, key: string): T | undefined {
  return record && Object.prototype.hasOwnProperty.call(record, key) ? record[key] : undefined;
}

/* Every tracked company's own name ("PwC", "CrowdStrike"), from
 * `/api/companies/names`, set by main.tsx before the first render.
 * `COMPANY` names only the 11 built-ins, so before this every other company
 * printed as its slug ("fortinet", "palo-alto-networks"). The built-in table
 * and then the slug remain the answer when the read failed or a slug is not
 * a tracked company. */
let trackedNames: Readonly<Record<string, string>> = {};

export function setCompanyNames(names: Readonly<Record<string, string>>): void {
  trackedNames = names;
}

export function companyName(slug: string): string {
  return ownValue(trackedNames, slug) ?? ownValue(COMPANY, slug)?.name ?? slug;
}

export type FreshnessTone = "fresh" | "behind" | "stale" | "unknown";

// A moment as the settings registers print it: "Sat, Oct 4, 09:05". One
// grammar, not a raw toLocaleString() dump with seconds; the weekday is left
// out where a list of dates would repeat it.
export function formatWhen(iso: string, { weekday = true }: { weekday?: boolean } = {}): string {
  return copyTimestamp(new Date(iso), {
    ...(weekday ? { weekday: "short" as const } : {}),
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// How old something is, in the one phrasing the whole dashboard uses. Shared by
// the header freshness badge and the per-company sync picker so "3d ago" means
// the same thing wherever it appears.
export function ageLabel(hours: number | null | undefined): string {
  if (hours == null) return formatAgeNever();
  if (hours < 1 / 60) return formatAgeJustNow();
  if (hours < 1) return formatAgeMinutes({ count: Math.floor(hours * 60) });
  if (hours < 24) return formatAgeHours({ count: Math.round(hours) });
  return formatAgeDays({ count: Math.round(hours / 24) });
}

// Pure label logic for the data-freshness badge, given /api/status.
//
// The age is the newest scan's, so one company that cannot be read shows as
// behind beside a recent scan rather than ageing the whole badge. Red is kept
// for scans that have stopped: the newest one is older than the window.
export function freshnessLabel(
  s: {
    running: boolean;
    last_success_age_hours: number | null;
    last_scan_age_hours: number | null;
    stale: boolean;
    freshness_max_hours: number;
    scheduler: { unread: readonly unknown[] };
  } | null,
): { text: string; tone: FreshnessTone } {
  if (!s) return { text: "—", tone: "unknown" };
  if (s.running) return { text: shellScanScanning(), tone: "unknown" };
  // Null age means no followed company was ever read. It is not "a company is
  // behind": that state carries the age of the oldest scan.
  if (s.last_success_age_hours == null) {
    return { text: shellFreshnessNever(), tone: "unknown" };
  }
  const hours = s.last_scan_age_hours ?? s.last_success_age_hours;
  const age = ageLabel(hours);
  const behind = s.scheduler.unread.length;
  const text = behind > 0 ? shellFreshnessBehind({ age, count: behind }) : shellFreshnessChecked({ age });
  const tone = hours > s.freshness_max_hours ? "stale" : s.stale ? "behind" : "fresh";
  return { text, tone };
}
