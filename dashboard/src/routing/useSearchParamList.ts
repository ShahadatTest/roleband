import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

/* A multi-value query-param lens (e.g. `?company=a&company=b`). Same rules as
   useSearchParam — filters live in the query, setter replaces by default and
   preserves every other param. The returned array is a fresh reference each
   render (it comes from getAll), so use it as a seed/derived value, not as a
   useEffect/useMemo dependency. */
export function useSearchParamList(
  key: string,
  opts: { replace?: boolean } = {},
): [string[], (vals: string[]) => void] {
  const { replace = true } = opts;
  const [searchParams, setSearchParams] = useSearchParams();
  const values = searchParams.getAll(key);

  const setValues = useCallback(
    (vals: string[]) => {
      // A lens with nothing to change must not NAVIGATE. `setSearchParams`
      // always does, and it resolves against the location its closure was built
      // in -- so a mirror that re-fires as the user leaves (the board writes
      // `filters.company` from an effect whose deps include this setter) lands
      // a replace on the old route and undoes the palette's push. Same values in
      // the same order = nothing to write.
      const current = searchParams.getAll(key);
      if (current.length === vals.length && current.every((v, i) => v === vals[i])) return;
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete(key);
          vals.forEach((v) => next.append(key, v));
          return next;
        },
        { replace },
      );
    },
    [searchParams, setSearchParams, key, replace],
  );

  return [values, setValues];
}
