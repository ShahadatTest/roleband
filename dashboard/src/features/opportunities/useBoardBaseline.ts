import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Filters, type JobList } from "../../api";
import { baselineFilters, baselineKey, countNarrowingFilters, type BoardLenses } from "./filters";

/** At most one cached baseline, never an unbounded history of typed queries.
 * The current unfiltered list is authoritative; otherwise measure one row.
 * An unknown/failed denominator stays unknown, with an explicit retry path. */
export function useBoardBaseline({ filters, lenses, list, version }: {
  filters: Filters;
  lenses: BoardLenses;
  list: JobList | null;
  version: string;
}) {
  const key = JSON.stringify([baselineKey(filters), version]);
  // Measured only where the toolbar shows it: a narrowing filter or lens on,
  // outside the Not-for-me lens. The mode alone is the population itself, and
  // its unfiltered total is the list's own.
  const narrowed = countNarrowingFilters(filters, lenses) > 0 && !filters.dismissed_only;
  const unfilteredTotal = !narrowed && list ? list.total : null;
  const params = useRef(filters);
  params.current = filters;
  const [cached, setCached] = useState<{ key: string; total: number } | null>(null);
  const [failure, setFailure] = useState<{ key: string; error: Error } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    if (!narrowed) {
      if (unfilteredTotal !== null) {
        setCached((current) => current?.key === key && current.total === unfilteredTotal
          ? current : { key, total: unfilteredTotal });
      }
      return;
    }
    if (cached?.key === key) return;
    const controller = new AbortController();
    setFailure(null);
    api.jobs(baselineFilters(params.current), controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setCached({ key, total: result.total });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setFailure({
          key, error: error instanceof Error ? error : new Error("Could not load unfiltered total"),
        });
      });
    return () => controller.abort();
  }, [key, narrowed, unfilteredTotal, cached, attempt]);

  return {
    total: narrowed && cached?.key === key ? cached.total : null,
    error: narrowed && cached?.key !== key && failure?.key === key ? failure.error : null,
    retry,
  };
}
