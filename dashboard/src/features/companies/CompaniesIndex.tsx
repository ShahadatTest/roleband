import { ADD_MORE_SLUG, DIRECTORY_SLUG, UNSORTED_SLUG, useCompanies } from "./CompaniesData";
import {
  companiesIndexAddMoreCompanies,
  companiesIndexSectors,
  companiesIndexSectorsAria,
  companiesIndexFollowedOf,
  companiesIndexMatchCount,
} from "../../copy/gen/companies";

/* The sector index: navigation for the register beside it.
 *
 * A sector is a place you scroll to, not a box you open, so the index never
 * hides a company: it only tells you where one is and how much of the sector
 * you already track.
 *
 * While a search is running the numerator stops being "tracked of members" and
 * becomes "how many rows match", so the progress bar under it is dropped: two
 * different quantities stacked on one another would show 10/10 above an empty
 * bar.
 */
interface IndexEntry {
  slug: string;
  display: string;
  count: string | null;
  /** Percent followed; `null` draws no bar. */
  bar: number | null;
  empty: boolean;
  dormant: boolean;
  trailing: boolean;
}

export function CompaniesIndex() {
  const { groups, focusedSector, focusSector, searching } = useCompanies();

  // The groups that are not sectors come last, below one rule, and the way
  // onto the list is always the final entry and always a destination.
  const trailing = (slug: string) => slug === UNSORTED_SLUG || slug === DIRECTORY_SLUG;
  const entries: IndexEntry[] = [
    ...groups.map((group) => ({
      slug: group.slug,
      display: group.display,
      count: searching
        ? companiesIndexMatchCount({ count: group.rows.length })
        : companiesIndexFollowedOf({ followed: group.trackedCount, total: group.members.length }),
      bar: searching
        ? null
        : group.members.length === 0
          ? 0
          : Math.round((100 * group.trackedCount) / group.members.length),
      empty: group.rows.length === 0,
      dormant: group.dormant,
      trailing: trailing(group.slug),
    })),
    {
      slug: ADD_MORE_SLUG,
      display: companiesIndexAddMoreCompanies(),
      count: null,
      bar: null,
      empty: false,
      dormant: false,
      trailing: true,
    },
  ];

  return (
    <nav className="ledger-index" aria-label={companiesIndexSectorsAria()}>
      {/* Not a heading: the <nav> already carries the name "Sectors", and an
          h2 here would put the register's sector headings inside the
          navigation as far as heading navigation is concerned. */}
      <span className="ledger-index-label" aria-hidden="true">{companiesIndexSectors()}</span>
      {entries.map((entry, index) => {
        const classes = [
          entry.trailing && !entries[index - 1]?.trailing ? "ledger-index-sep" : "",
          entry.dormant ? "is-dormant" : "",
        ]
          .filter(Boolean)
          .join(" ");
        return (
          <button
            key={entry.slug}
            type="button"
            className={classes}
            // Nothing to scroll to: a sector the current filters emptied is
            // listed so the map stays whole, but it is not a destination.
            disabled={entry.empty}
            aria-current={focusedSector === entry.slug ? "true" : undefined}
            onClick={() => focusSector(entry.slug)}
          >
            <span className="ledger-index-row">
              <span>{entry.display}</span>
              {entry.count !== null && <b>{entry.count}</b>}
            </span>
            {entry.bar !== null && (
              <span className="ledger-index-bar">
                <i style={{ width: `${entry.bar}%` }} />
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
