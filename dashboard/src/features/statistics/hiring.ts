/* The Hiring tab's bounded views. Pure, so the rules are unit-tested.
 *
 * Many companies have a single open role, so a full ranking is a long tail
 * nobody reads: a view shows the leaders and folds the rest into ONE row that
 * still counts them. */

import type { HiringCompany } from "../../api";

export interface CompanyRest {
  companies: number;
  open: number;
  newToday: number;
  closedToday: number;
}

/** The first `limit` companies (already ranked and scoped by the server),
 *  and the rest folded into one row. `rest` is null when nothing is
 *  folded. A company with nothing open is not hiring, whatever closed today. */
export function topCompanies(
  companies: readonly HiringCompany[],
  limit = 15,
): { rows: HiringCompany[]; rest: CompanyRest | null; total: number } {
  const ranked = companies.filter((c) => c.open > 0);
  const rows = ranked.slice(0, limit);
  const folded = ranked.slice(limit);
  const rest = folded.length
    ? folded.reduce<CompanyRest>(
        (acc, c) => ({
          companies: acc.companies + 1,
          open: acc.open + c.open,
          newToday: acc.newToday + c.new_today,
          closedToday: acc.closedToday + c.closed_today,
        }),
        { companies: 0, open: 0, newToday: 0, closedToday: 0 },
      )
    : null;
  return { rows, rest, total: ranked.length };
}

/** Companies whose name contains the query, case- and accent-insensitive. */
export function matchCompanies(
  companies: readonly HiringCompany[],
  query: string,
  name: (slug: string) => string,
): HiringCompany[] {
  const fold = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
  const q = fold(query.trim());
  if (!q) return companies.slice();
  return companies.filter((c) => fold(name(c.company)).includes(q) || c.company.includes(q));
}
