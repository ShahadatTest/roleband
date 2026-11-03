/* Filter memory — the store behind "the app remembers how you narrowed it".
 *
 * A reader who filtered the radar down to three companies last night should
 * find those three companies there this morning, and should not have to say
 * so again after a reload, a nav-rail round trip, or a restart. Filters that
 * live in the address survive a reload on their own; filters held in
 * `useState` die with the screen unless they are remembered here.
 *
 * Three rules this file exists to hold:
 *
 *  1. **What comes back off disk is untrusted data, not state.** A stored blob
 *     outlives the code that wrote it: a shipped key can change type, a facet
 *     slug can be retired, and a user can edit localStorage by hand. So a
 *     scope declares a SHAPE — one decoder per key it is willing to restore —
 *     and `decodeShape` returns only what that shape accepts. A key the shape
 *     does not name is not persisted and cannot be restored, which makes the
 *     shape the whitelist as well as the validator.
 *  2. **Storage can always fail.** Private windows, blocked site data and a
 *     full quota all throw on access rather than returning null, and Safari
 *     throws on `setItem` in private mode specifically. Every entry point is
 *     total: a failed read is "nothing remembered", a failed write is
 *     dropped. Nothing here may take a screen down.
 *  3. **A version is part of the key, not part of the payload.** Bumping
 *     MEMORY_VERSION retires every stored blob at once without a migration,
 *     and the stale keys are swept on first use rather than left to sit.
 *
 * This is the storage half only, and it is pure — no React. The hooks are
 * `useFilterMemory.ts`; the address-backed variant is
 * `routing/useRememberedParams.ts`.
 */

/** Bump to retire every stored blob (see rule 3). */
export const MEMORY_VERSION = 1;

const PREFIX = "roleband.filters";
const CURRENT = `${PREFIX}.v${MEMORY_VERSION}:`;

/** A stored array is bounded on both axes: a corrupt or hand-edited blob must
 *  not be able to build a 10,000-term query string out of one restore. */
const MAX_VALUES = 200;
const MAX_VALUE_LENGTH = 120;

function storage(): Storage | null {
  try {
    // Reading the property itself throws when site data is blocked.
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

let swept = false;

/** Module state that outlives a component, so a test suite has to be able to
 *  put it back — the reason `useWriteQueue` exports `resetWriteQueues`. Called
 *  from `src/test/setup.ts` between tests; nothing in the app calls it. */
export function resetMemorySweep(): void {
  swept = false;
}

/** Drop every entry this module wrote under an older version. Runs once per
 *  page life, on first use, because a version bump that leaves its predecessor
 *  behind never frees the space and never tells anyone. */
function sweepOldVersions(store: Storage) {
  if (swept) return;
  swept = true;
  try {
    const stale = [];
    for (let i = 0; i < store.length; i++) {
      const key = store.key(i);
      if (key && key.startsWith(`${PREFIX}.v`) && !key.startsWith(CURRENT)) stale.push(key);
    }
    for (const key of stale) store.removeItem(key);
  } catch {
    /* A sweep is housekeeping; failing it costs nothing. */
  }
}

export function readEntry(key: string): unknown {
  const store = storage();
  if (!store) return null;
  sweepOldVersions(store);
  try {
    const raw = store.getItem(CURRENT + key);
    return raw == null ? null : JSON.parse(raw);
  } catch {
    // Unparseable is indistinguishable from absent, and treating it as absent
    // is what stops one bad blob from being a permanent broken screen.
    return null;
  }
}

export function writeEntry(key: string, value: unknown): void {
  const store = storage();
  if (!store) return;
  sweepOldVersions(store);
  try {
    store.setItem(CURRENT + key, JSON.stringify(value));
  } catch {
    /* Quota, private mode, blocked site data. The screen still works. */
  }
}

export function forgetEntry(key: string): void {
  const store = storage();
  if (!store) return;
  try {
    store.removeItem(CURRENT + key);
  } catch {
    /* As above. */
  }
}

/* ---- the shape: one decoder per restorable key ---------------------------- */

/** Returns the value when the raw JSON is acceptable, `undefined` when it is
 *  not. `undefined` means "keep the default" — never "the default is wrong". */
export type Decoder<V> = (raw: unknown) => V | undefined;

/** What a scope is willing to remember. A key absent from the shape is neither
 *  written nor restored, so this is the persistence whitelist. */
export type MemoryShape<T> = { [K in keyof T]?: Decoder<T[K]> };

/** A facet selection: a bounded list of short strings. Values are NOT checked
 *  against the live vocabulary — a slug retired since the write simply matches
 *  nothing, which is the same outcome as an empty facet, while a round trip
 *  through the facets endpoint would make restoring wait on a request. */
export const slugs: Decoder<string[]> = (raw) => {
  if (!Array.isArray(raw)) return undefined;
  const clean = raw.filter(
    (value): value is string => typeof value === "string" && value.length > 0 && value.length <= MAX_VALUE_LENGTH,
  );
  return clean.slice(0, MAX_VALUES);
};

export const flag: Decoder<boolean> = (raw) => (typeof raw === "boolean" ? raw : undefined);

/** A number-or-nothing field (a comp floor, a posted-within window). NaN and
 *  Infinity are what `JSON.parse` gives back for a hand-edited blob, and both
 *  reach the wire as `base_min=null`-shaped nonsense, so both are refused. */
export const amount: Decoder<number | null> = (raw) => {
  if (raw === null) return null;
  return typeof raw === "number" && Number.isFinite(raw) ? raw : undefined;
};

/** A closed set — the only decoder that can say "this stored value is not one
 *  of the set", because it is the only one handed the vocabulary. */
export const oneOf =
  <T extends string>(options: readonly T[]): Decoder<T> =>
  (raw) =>
    typeof raw === "string" && (options as readonly string[]).includes(raw) ? (raw as T) : undefined;

/** Free text, bounded. A closed set, such as a sort key (`JobSort`), takes
 *  `oneOf` instead. */
export const text: Decoder<string> = (raw) =>
  typeof raw === "string" && raw.length <= MAX_VALUE_LENGTH ? raw : undefined;

/** Everything the shape accepts out of one stored blob. Keys the shape does
 *  not name, and values it refuses, are simply absent from the result — so the
 *  caller's own defaults show through. */
export function decodeShape<T>(shape: MemoryShape<T>, raw: unknown): Partial<T> {
  if (raw == null || typeof raw !== "object" || Array.isArray(raw)) return {};
  const stored = raw as Record<string, unknown>;
  const out: Partial<T> = {};
  for (const key of Object.keys(shape) as (keyof T)[]) {
    if (!(key in stored)) continue;
    const decode = shape[key];
    if (!decode) continue;
    const value = decode(stored[key as string]);
    if (value !== undefined) out[key] = value;
  }
  return out;
}

/** The payload to store: the shaped keys of a live value, and nothing else.
 *  Paging, the search query and transport keys stay out of memory by being
 *  out of the shape. */
export function encodeShape<T extends object>(shape: MemoryShape<T>, value: T): Partial<T> {
  const out: Partial<T> = {};
  for (const key of Object.keys(shape) as (keyof T)[]) {
    if (value[key] !== undefined) out[key] = value[key];
  }
  return out;
}

/* ---- the address variant: remembered query params ------------------------- */

/** A snapshot of the query params a screen owns, in URL order. Each key maps
 *  to every value it carries, because a facet lens repeats its key. */
export type ParamSnapshot = Record<string, string[]>;

export function decodeParams(raw: unknown, keys: readonly string[]): ParamSnapshot {
  if (raw == null || typeof raw !== "object" || Array.isArray(raw)) return {};
  const stored = raw as Record<string, unknown>;
  const out: ParamSnapshot = {};
  for (const key of keys) {
    const values = slugs(stored[key]);
    if (values && values.length > 0) out[key] = values;
  }
  return out;
}
