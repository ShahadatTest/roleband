import { useCallback, useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";

/* Path-based sub-tab selection for a nested section (e.g. `/statistics/:tab`).
   The active tab lives in the URL path, so it is deep-linkable and survives
   reload/back. A missing or unknown `:tab` redirects to `fallback` (replace, so
   a stale deep link doesn't leave a dead history entry). Switching tabs pushes
   (a sub-tab is a real, back-navigable destination; a filter or lens is not,
   and lives in the query). */
export function useTabRoute<T extends string>(opts: {
  base: string;
  slugs: readonly T[];
  fallback: T;
}): { tab: T; setTab: (t: T) => void } {
  const { base, slugs, fallback } = opts;
  const navigate = useNavigate();
  const { tab: raw } = useParams();
  const valid = raw != null && (slugs as readonly string[]).includes(raw);
  const tab = (valid ? raw : fallback) as T;

  useEffect(() => {
    if (!valid) navigate(`${base}/${fallback}`, { replace: true });
  }, [valid, base, fallback, navigate]);

  const setTab = useCallback((t: T) => navigate(`${base}/${t}`), [navigate, base]);

  return { tab, setTab };
}
