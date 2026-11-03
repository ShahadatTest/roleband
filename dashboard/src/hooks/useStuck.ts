import { useEffect, useState, type RefObject } from "react";

/** Whether a sticky element is pinned right now, read off a marker placed
    just above it: once the marker has scrolled out of its scroller, the
    element below it is stuck. A pinned bar needs a surface to cover what
    scrolls beneath it; a bar at rest does not, and should look like every
    other bar (the Duplicates tab row). No IntersectionObserver
    (jsdom), never stuck. */
export function useStuck(marker: RefObject<HTMLElement | null>): boolean {
  const [stuck, setStuck] = useState(false);
  useEffect(() => {
    const element = marker.current;
    if (!element || typeof IntersectionObserver === "undefined") return;
    let root: HTMLElement | null = element.parentElement;
    while (root && !/(auto|scroll)/.test(getComputedStyle(root).overflowY)) root = root.parentElement;
    const observer = new IntersectionObserver(([entry]) => setStuck(!entry.isIntersecting), { root });
    observer.observe(element);
    return () => observer.disconnect();
  }, [marker]);
  return stuck;
}
