import { useEffect, useState } from "react";

/* Reactive matchMedia. Returns false where matchMedia is unavailable (jsdom),
   so unit tests exercise the wide-viewport branch.

   Three signals, not one, because this app runs on hosts where events are
   simply never delivered: DevTools-protocol viewport emulation re-evaluates
   media queries without dispatching EITHER the MediaQueryList change event or
   window resize (`matches` flips with neither event fired), and
   SyncContribution.tsx documents a host that drops resize notifications
   outright. So alongside the two events, a `typeof`-guarded ResizeObserver on
   the document element re-checks `.matches` on any viewport reflow. Every
   path re-reads `.matches` rather than trusting its trigger, so a duplicate
   delivery is a no-op set. */
export function useMediaQuery(query: string): boolean {
  const supported = typeof window !== "undefined" && typeof window.matchMedia === "function";
  const [matches, setMatches] = useState(() => (supported ? window.matchMedia(query).matches : false));

  useEffect(() => {
    if (!supported) return;
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    window.addEventListener("resize", onChange);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(onChange);
    observer?.observe(document.documentElement);
    return () => {
      mql.removeEventListener("change", onChange);
      window.removeEventListener("resize", onChange);
      observer?.disconnect();
    };
  }, [query, supported]);

  return matches;
}
