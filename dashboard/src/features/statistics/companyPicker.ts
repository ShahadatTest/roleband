/* The Skills and Overlap company pickers: one searchable list, most open roles
 * first, of the companies on the Insights scope's side. Pure, so the side rule
 * is unit-tested.
 *
 * The routes AND a picked company with the scope, so a company off the side
 * can only ever answer with nothing: the picker never offers one. */

import type { CompanyList, Facets, InsightsScope } from "../../api";
import { compare } from "../../copy/format";
import type { FilterSelectOption } from "../../ui";

/** The `source` of a company the whole-set follow brought in
 *  (`company_directory.FOLLOWED_WITH_SET`): the Other companies side
 *  (`InsightsScope` in `backend/tracker/db/queries/insights.py`). A company
 *  followed by name from the directory is the reader's own. */
const FOLLOWED_WITH_SET = "directory-set";

/** The companies on the Other companies side. */
export function otherCompanies(list: CompanyList): ReadonlySet<string> {
  return new Set(list.companies.filter((c) => c.source === FOLLOWED_WITH_SET).map((c) => c.slug));
}

/** The picker's options for one side. A narrowed side offers nothing until
 *  `other` is known, so the picker never offers a company off it. */
export function companyPickerOptions(
  facets: Facets | null,
  side: InsightsScope["side"],
  other: ReadonlySet<string> | null,
): FilterSelectOption[] {
  if (!facets) return [];
  const onSide = (slug: string) => side === "all" || (other !== null && other.has(slug) === (side === "other"));
  return Object.entries(facets.companies)
    .filter(([slug]) => onSide(slug))
    .map(([slug, meta]) => ({ value: slug, label: meta.display, count: facets.counts.company[slug] ?? 0 }))
    .filter((o) => o.count > 0)
    .sort((a, b) => b.count - a.count || compare(a.label, b.label));
}
