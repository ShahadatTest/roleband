import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  decodeShape,
  encodeShape,
  forgetEntry,
  readEntry,
  writeEntry,
  type MemoryShape,
} from "./filterMemory";

/* The React half of filter memory (`filterMemory.ts` is the store).
 *
 * Two hooks, because a filter surface keeps two different things and they have
 * different lifetimes:
 *
 *  - `useRememberedState` — WHAT is chosen. A drop-in for the `useState` a
 *    screen's filter object already lives in, restored at mount from the
 *    scope's stored blob and written back whenever it changes.
 *  - `useDisclosureMemory` — WHICH GROUPS ARE OPEN. The register's own
 *    furniture, kept apart from the chosen values on purpose: opening Company
 *    to look at it is not filtering by it, "Reset all" clears one and must not
 *    touch the other, and a version bump on the filter shape has no business
 *    folding somebody's rail back up.
 *
 * A screen whose filters live in the ADDRESS uses neither: that is
 * `routing/useRememberedParams.ts`, which remembers the query string instead.
 */

/** The value, its setter, and what memory actually supplied at mount.
 *
 * The third element is there for a screen that has to put a restored value
 * somewhere else as well — the Board's company is also URL state, and a
 * remembered company that never reaches the address would leave `/` meaning
 * "no company" while the register shows one. */
export type RememberedState<T> = [
  T,
  React.Dispatch<React.SetStateAction<T>>,
  { restored: Partial<T>; forget: () => void },
];

export function useRememberedState<T extends object>({
  scope,
  defaults,
  shape,
  override,
}: {
  /** The storage key for this surface: "board", "notifications", "companies". */
  scope: string;
  defaults: T;
  /** What may be remembered, and how each key is validated coming back.
   *  Declare it as a module constant — it is read once, at mount. */
  shape: MemoryShape<T>;
  /** Applied on top of memory at mount, for a key some other authority owns.
   *  The Board's company is in the address, and an address that names one is
   *  a link the reader followed — it outranks what they last chose here. */
  override?: Partial<T>;
}): RememberedState<T> {
  /* Read once. A shape and a scope that changed between renders would mean the
     surface's identity changed, which is a remount, not a state update. */
  const pinned = useRef({ scope, shape });
  const [restored] = useState<Partial<T>>(() =>
    decodeShape(pinned.current.shape, readEntry(pinned.current.scope)),
  );
  const [value, setValue] = useState<T>(() => ({ ...defaults, ...restored, ...override }));

  /* Write on change, and ONLY on a change to what is actually stored. The
     value a screen holds carries more than memory does — the Board's `filters`
     moves on every page turn — so serializing first and comparing is what
     keeps paging from touching the disk.
   
     Seeded with the MOUNT value, which makes arriving a no-op: a reader who
     opens a screen and touches nothing leaves no trace, and a link that
     overrides memory (`?company=`) does not overwrite it just by being
     followed. The first edit after that writes the whole surface, override
     included, because by then it is what the reader is looking at. */
  const written = useRef<string>(
    JSON.stringify(encodeShape(pinned.current.shape, { ...defaults, ...restored, ...override })),
  );
  useEffect(() => {
    const payload = encodeShape(pinned.current.shape, value);
    const line = JSON.stringify(payload);
    if (line === written.current) return;
    written.current = line;
    writeEntry(pinned.current.scope, payload);
  }, [value]);

  const forget = useCallback(() => {
    written.current = "";
    forgetEntry(pinned.current.scope);
  }, []);

  return [value, setValue, useMemo(() => ({ restored, forget }), [restored, forget])];
}

/* ---- which groups are open ------------------------------------------------ */

export interface DisclosureMemory {
  /** `fallback` is the group's own default; memory answers only for a group
   *  the reader has actually opened or closed. */
  isOpen: (id: string, fallback: boolean) => boolean;
  setOpen: (id: string, open: boolean) => void;
}

function decodeFlags(raw: unknown): Record<string, boolean> {
  if (raw == null || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: Record<string, boolean> = {};
  for (const [id, value] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof value === "boolean") out[id] = value;
  }
  return out;
}

/** Remembers which groups of a register the reader opened.
 *
 * Tri-state on purpose: a group is open, closed, or UNTOUCHED, and only the
 * first two are stored. A register may therefore change a group's default
 * later without silently overruling every reader who has already made that
 * group's choice — which is the whole difference between a default and a
 * setting. */
export function useDisclosureMemory(scope: string): DisclosureMemory {
  const key = useRef(`${scope}:open`);
  const [flags, setFlags] = useState<Record<string, boolean>>(() => decodeFlags(readEntry(key.current)));
  const written = useRef<string>(JSON.stringify(flags));

  useEffect(() => {
    const line = JSON.stringify(flags);
    if (line === written.current) return;
    written.current = line;
    writeEntry(key.current, flags);
  }, [flags]);

  return useMemo(
    () => ({
      isOpen: (id: string, fallback: boolean) => flags[id] ?? fallback,
      setOpen: (id: string, open: boolean) =>
        setFlags((prev) => (prev[id] === open ? prev : { ...prev, [id]: open })),
    }),
    [flags],
  );
}
