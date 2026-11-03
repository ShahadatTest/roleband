import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { decodeParams, readEntry, writeEntry, type ParamSnapshot } from "../hooks/filterMemory";

/* Filter memory for a screen whose lenses ARE the address (Notifications:
 * `?status=`, `?priority=`, `?category=`). Those already survive a reload,
 * because the address does; what they do not survive is leaving the screen and
 * coming back through the nav rail, which arrives at a bare URL.
 *
 * So: remember the query this screen was last left in, and put it back when
 * the reader returns to a bare one. Two rules make that safe.
 *
 *  1. **An address that speaks outranks memory.** A link, a deep link, Back —
 *     anything that already names one of these keys is an explicit choice, and
 *     memory stays out of it. Checked at mount and never again; a later
 *     navigation to a bare URL is the reader clearing the lens, not arriving.
 *  2. **One write, replacing.** The restore is `replace: true`, so returning
 *     to a remembered view does not put a state nobody chose into the back
 *     stack.
 *
 * The screen keeps its own setters and its own `Reset all`: this hook never
 * reads or writes a lens's VALUE, only the query string as a whole. Clearing
 * the params is therefore remembered like any other choice — reset, leave,
 * come back, and the list is still unfiltered.
 */
export function useRememberedParams(
  /** Storage key. Distinct from the `useRememberedState` scope of the same
   *  screen, if it has one — these are two different kinds of state. */
  scope: string,
  /** The params this screen owns. A module constant: it is joined into an
   *  effect dependency, so a fresh array literal per render would re-run. */
  keys: readonly string[],
): void {
  const [searchParams, setSearchParams] = useSearchParams();
  const key = `${scope}:params`;
  const keyList = keys.join(" ");

  /* Read through refs: `setSearchParams` is rebuilt on every navigation, and
     `searchParams` on every render, so listing either would re-fire the
     mount-only restore below — the failure `useSearchParam` documents, where
     a replace fires as the reader LEAVES and undoes the departure. */
  const writer = useRef(setSearchParams);
  writer.current = setSearchParams;
  const live = useRef(searchParams);
  live.current = searchParams;

  /* Did the reader ARRIVE with one of these keys? Captured before any effect
     runs, because the restore itself is about to change the answer. */
  const arrived = useRef<boolean | null>(null);
  if (arrived.current === null) arrived.current = keys.some((k) => searchParams.has(k));

  /** The restore's own write must not be read back as a choice — see below. */
  const skipWrite = useRef(false);

  useEffect(() => {
    if (arrived.current) return;
    const stored = decodeParams(readEntry(key), keyList ? keyList.split(" ") : []);
    const names = Object.keys(stored);
    if (names.length === 0) return;
    skipWrite.current = true;
    writer.current(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const name of names) {
          next.delete(name);
          for (const value of stored[name]) next.append(name, value);
        }
        return next;
      },
      { replace: true },
    );
    // Mount only: everything it reads is a ref or a stable string.
  }, [key, keyList]);

  useEffect(() => {
    /* The mount pass of this effect runs in the same commit as the restore
       above, BEFORE its navigation has landed — so what it would see is the
       bare address the restore is in the middle of replacing, and writing that
       would erase the very memory being restored. The landed navigation
       re-runs this effect with the real snapshot. */
    if (skipWrite.current) {
      skipWrite.current = false;
      return;
    }
    const snapshot: ParamSnapshot = {};
    for (const name of keyList ? keyList.split(" ") : []) {
      const values = live.current.getAll(name);
      if (values.length > 0) snapshot[name] = values;
    }
    writeEntry(key, snapshot);
  }, [key, keyList, searchParams]);
}
