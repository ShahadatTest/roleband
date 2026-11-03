import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

/* A single query-param lens (e.g. `?window=90`, `?status=unread`). Filters and
   lenses live in the query string, not the path, and default to `replace` so adjusting the current view never buries the
   back button. Reads are tolerant: an absent or out-of-whitelist value returns
   `fallback` without redirecting. Setting the value back to `fallback` deletes
   the key so default views keep clean URLs. Other params are preserved. */
export function useSearchParam<T extends string>(
  key: string,
  opts: { options: readonly T[]; fallback: T; replace?: boolean },
): [T, (v: T) => void] {
  const { options, fallback, replace = true } = opts;
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get(key);
  const value = (raw != null && (options as readonly string[]).includes(raw) ? raw : fallback) as T;

  const setValue = useCallback(
    (v: T) => {
      // A lens with nothing to change must not NAVIGATE, the same rule
      // `useSearchParamList` follows.
      // `setSearchParams` always navigates, and it resolves against the
      // location its closure was built in, so a mirror that re-fires as the
      // reader LEAVES lands a replace on the old route and undoes the
      // departure: every navigation off the board would bounce straight back.
      if (value === v) return;
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (v === fallback) next.delete(key);
          else next.set(key, v);
          return next;
        },
        { replace },
      );
    },
    [setSearchParams, key, fallback, replace, value],
  );

  return [value, setValue];
}
