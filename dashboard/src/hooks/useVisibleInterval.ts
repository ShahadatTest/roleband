import { useEffect, useRef } from "react";

/* Run `poll` now and every `ms` while the page is visible. A hidden tab or a
   window behind others polls nothing: the reads behind these polls are the
   app's heaviest, and a second window would double them for a screen no one
   sees. Coming back reads once at once, then on the cadence again.

   A new cadence or a new `poll` keeps the clock: the next read comes `ms` after
   the last one, not at once. The status poll switches to its fast cadence
   because of the answer it just read, and reading again at once would ask the
   same question twice. A remount reads at once: the reader may have dropped
   the answer of a read it started before it unmounted (SyncState retires
   them), and StrictMode's practice unmount keeps this hook's refs. */
export function useVisibleInterval(poll: () => void, ms: number): void {
  const last = useRef<number | null>(null);
  useEffect(() => () => {
    last.current = null;
  }, []);
  useEffect(() => {
    let timer: number | null = null;
    const read = () => {
      last.current = Date.now();
      poll();
    };
    const schedule = (wait: number) => {
      timer = window.setTimeout(() => {
        read();
        schedule(ms);
      }, wait);
    };
    const start = (atOnce: boolean) => {
      if (timer !== null) return;
      const since = last.current === null ? Infinity : Date.now() - last.current;
      if (atOnce || since >= ms) {
        read();
        schedule(ms);
      } else {
        schedule(ms - since);
      }
    };
    const stop = () => {
      if (timer === null) return;
      window.clearTimeout(timer);
      timer = null;
    };
    const follow = () => (document.visibilityState === "hidden" ? stop() : start(true));
    if (document.visibilityState !== "hidden") start(false);
    document.addEventListener("visibilitychange", follow);
    return () => {
      document.removeEventListener("visibilitychange", follow);
      stop();
    };
  }, [poll, ms]);
}
