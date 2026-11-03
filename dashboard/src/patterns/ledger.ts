/* The facts ledger's model, shared by Compare and Duplicates: one row per
 * attribute, read across every column, and one rule for folding agreement.
 * Each screen draws the rows its own way (Compare's columns share a grid
 * with their heads and descriptions; Duplicates' two columns are a table);
 * what a row is, when two columns disagree on it and which rows fold
 * together is decided here once. */

export interface LedgerRow<T> {
  key: string;
  label: string;
  /** The full words behind a short label (Est. TC), for hover and screen readers. */
  fullLabel?: string;
  /** A comparable string. Columns disagree on a row when their diff keys
   *  differ, so a diff key depends on nothing but the item, and does not
   *  collapse values a reader can tell apart. */
  diff: (item: T) => string;
  /** False for a row that stays at full size even when every column agrees:
   *  an identity the reader checks by eye, such as a title or a link. */
  collapsible?: boolean;
}

export type LedgerGroup<R> = { kind: "row"; row: R } | { kind: "run"; rows: R[] };

/** Agreeing rows fold into one counted line from this many on: one line
 *  that names the fields it holds is shorter than two that repeat "Same". */
export const MIN_RUN = 2;

export function rowDiffers<T>(row: LedgerRow<T>, items: readonly T[]): boolean {
  return new Set(items.map(row.diff)).size > 1;
}

/** The rows in order, with every run of MIN_RUN or more consecutive
 *  collapsible rows the columns agree on folded into one group. What is left
 *  at full size is what differs, and the rows that never fold. */
export function groupLedger<T, R extends LedgerRow<T>>(rows: readonly R[], items: readonly T[]): LedgerGroup<R>[] {
  const groups: LedgerGroup<R>[] = [];
  let run: R[] = [];
  const flush = () => {
    if (run.length >= MIN_RUN) groups.push({ kind: "run", rows: run });
    else run.forEach((row) => groups.push({ kind: "row", row }));
    run = [];
  };
  for (const row of rows) {
    if (row.collapsible !== false && !rowDiffers(row, items)) {
      run.push(row);
    } else {
      flush();
      groups.push({ kind: "row", row });
    }
  }
  flush();
  return groups;
}
