/* Why a list is empty — measured, not guessed.
 *
 * An empty message picked by an if/else chain is wrong whenever the filters
 * COMBINE. With the predicate `(!trackedOnly || tracked) && matchesSearch` and
 * the message `query ? … : trackedOnly ? …`, searching "stripe" with Tracked
 * only on answers "No companies match “stripe”." about a company that ships in
 * the catalog — and the rational next move from that sentence is Add by link,
 * which duplicates a company the app already has.
 *
 * So the rule is not a copy rule: a message may only name a filter that is
 * actually holding rows back, and "actually" has to be a measurement — re-run
 * the list's own predicate with that ONE filter released and count what comes
 * back. An active filter that releases nothing is not the reason and must not
 * be blamed: the register's `showPlanned` is off in plenty of empties it did
 * not cause, because a search already forces planned rows visible.
 *
 * `released` must come from the predicate the list itself used. Re-deriving it
 * from a second, parallel condition lets the two drift out of step.
 */

export type NarrowingFilter<K extends string = string> = {
  key: K;
  /** Is the filter on right now? */
  active: boolean;
  /** Rows that would show if THIS filter alone were released, everything else
   *  left as it is. */
  released: number;
};

/**
 * The filters responsible for an empty list, in the order given.
 *
 * Only meaningful when the list IS empty — the caller checks that first, since
 * only it knows what "empty" means for its own rows. An empty result means no
 * filter is to blame and the underlying set itself has nothing in it, which is
 * a different state with a different recovery (seed it, don't widen it).
 */
export function narrowedBy<K extends string>(
  filters: readonly NarrowingFilter<K>[],
): NarrowingFilter<K>[] {
  return filters.filter((filter) => filter.active && filter.released > 0);
}
