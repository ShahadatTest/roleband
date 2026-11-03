import { useCallback, useEffect, useRef, useState } from "react";
import type { DependencyList } from "react";
import { keepAnswer, keptAnswer, writesSettled } from "../api/keptAnswers";

export interface AsyncResource<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  /** A preserve-data refresh is in flight. `data` is still the last good value,
   *  so a screen shows rows and a quiet activity hint, never a spinner. */
  refreshing: boolean;
  /** Why the last preserve-data refresh failed, while `data` stays good.
   *  Separate from `error` on purpose: a failed background poll must not blank
   *  a screen that is still showing valid rows, but it must not vanish either:
   *  polls may be quiet, never silent. */
  refreshError: Error | null;
  mutate: (update: (current: T | null) => T | null) => void;
  /** Reload from scratch: clears data and shows the loading state. */
  retry: () => void;
  /** Re-run the current request. `preserveData` keeps the rows mounted and
   *  routes any failure to `refreshError` instead of `error`. Resolves when
   *  this attempt settles — awaiting it is how a caller sequences a mutation
   *  against the reload that follows it. */
  refresh: (options?: { preserveData?: boolean }) => Promise<void>;
}

/**
 * The one read-state vocabulary.
 *
 * Two orderings are enforced, and they are not the same:
 *
 *  - INPUTS CHANGE. The request key is derived during render, so the frame that
 *    changes the inputs already reports `loading` with no data: a screen never
 *    paints last query's rows under this query's heading.
 *  - REQUESTS RACE. Every start — mount, dep change, retry, refresh — takes the
 *    next generation, and only the newest generation may write. This is what a
 *    per-effect `active` flag cannot do: a poll and a row action are two starts
 *    against the SAME inputs, so nothing about the deps distinguishes them and
 *    without it the slower one wins by finishing last.
 *
 * The request receives an AbortSignal. Honouring it is optional — the guards
 * above already make a superseded response inert — but a transport that does
 * stops paying for work whose answer is already discarded.
 *
 * `keep` names a read whose last answer outlives the screen (api/keptAnswers):
 * opened again with the same inputs, it paints that answer at once and refreshes
 * it as a preserve-data refresh. Its dependencies are plain data, since they are
 * part of the name; a function among them keeps nothing. `retry` never paints a
 * kept answer: it is the reload from scratch.
 */
export function useAsyncResource<T>(
  request: (signal: AbortSignal) => Promise<T>,
  dependencies: DependencyList,
  options?: { keep?: string },
): AsyncResource<T> {
  const requestRef = useRef(request);
  requestRef.current = request;
  const [attempt, setAttempt] = useState(0);
  const keyRef = useRef<{
    dependencies: DependencyList;
    attempt: number;
    key: symbol;
    kept: string | null;
    seed: { value: unknown } | undefined;
  } | null>(null);
  const changed =
    keyRef.current === null ||
    keyRef.current.attempt !== attempt ||
    keyRef.current.dependencies.length !== dependencies.length ||
    dependencies.some((value, index) => !Object.is(value, keyRef.current!.dependencies[index]));
  // The null check is repeated here (it is also the first clause of
  // `changed`) because TS narrows a mutable ref property only through a
  // direct test, never through an alias.
  if (keyRef.current === null || changed) {
    const kept = options?.keep === undefined ? null : keptName(options.keep, dependencies);
    const retried = keyRef.current !== null && keyRef.current.attempt !== attempt;
    keyRef.current = {
      dependencies: [...dependencies],
      attempt,
      key: Symbol("async-resource"),
      kept,
      seed: kept === null || retried ? undefined : keptAnswer(kept),
    };
  }
  const { key: requestKey, kept, seed } = keyRef.current;

  type State = {
    requestKey: symbol;
    data: T | null;
    error: Error | null;
    loading: boolean;
    refreshing: boolean;
    refreshError: Error | null;
  };
  const [state, setState] = useState<State>(() => seeded<T>(requestKey, seed));

  // The generation every write is checked against. A ref, not state: it must be
  // readable and writable synchronously from inside a settled promise.
  const generation = useRef(0);
  const mounted = useRef(true);
  const inFlight = useRef<AbortController | null>(null);
  // The key a refresh belongs to. A refresh that resolves after the inputs
  // changed answers a question nobody is asking any more.
  const keyForWrites = useRef(requestKey);
  keyForWrites.current = requestKey;
  const keptForWrites = useRef(kept);
  keptForWrites.current = kept;

  const toError = (error: unknown) =>
    error instanceof Error ? error : new Error("Request failed");

  /** Start one attempt. `preserveData` decides both what the screen shows while
   *  it runs and where a failure lands; a kept answer to `seed` it with is
   *  preserved data. */
  const start = useCallback((
    key: symbol,
    preserveData: boolean,
    keptAs: string | null,
    seed?: { value: unknown },
  ): Promise<void> => {
    const mine = ++generation.current;
    const since = writesSettled();
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    // A superseded or unmounted attempt writes nothing. Checked at settle time,
    // so it covers a request that was already in flight when the newer one began.
    const isCurrent = () => mounted.current && generation.current === mine && keyForWrites.current === key;

    const preserve = preserveData || seed !== undefined;
    setState((prev) =>
      seed
        ? seeded<T>(key, seed)
        : preserve
          ? { ...prev, requestKey: key, refreshing: true, refreshError: null }
          : { requestKey: key, data: null, error: null, loading: true, refreshing: false, refreshError: null },
    );

    let settled: Promise<T>;
    try {
      settled = requestRef.current(controller.signal);
    } catch (error: unknown) {
      // A request function that throws synchronously is still a failed request.
      settled = Promise.reject(error);
    }

    return settled.then(
      (data) => {
        if (!isCurrent()) return;
        if (keptAs !== null) keepAnswer(keptAs, data, since);
        setState({ requestKey: key, data, error: null, loading: false, refreshing: false, refreshError: null });
      },
      (error: unknown) => {
        if (!isCurrent()) return;
        if (controller.signal.aborted) return;
        setState((prev) =>
          preserve
            ? { ...prev, refreshing: false, refreshError: toError(error) }
            : { requestKey: key, data: null, error: toError(error), loading: false, refreshing: false, refreshError: null },
        );
      },
    );
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      // Nothing may write after unmount, and the transport stops paying for an
      // answer with no reader.
      inFlight.current?.abort();
    };
  }, []);

  useEffect(() => {
    void start(requestKey, false, kept, seed);
  }, [requestKey, kept, seed, start]);

  const mutate = useCallback((update: (current: T | null) => T | null) => {
    setState((current) => ({ ...current, data: update(current.data) }));
  }, []);
  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  const refresh = useCallback(
    (options?: { preserveData?: boolean }) =>
      start(keyForWrites.current, options?.preserveData ?? false, keptForWrites.current),
    [start],
  );

  if (state.requestKey !== requestKey) {
    // The inputs changed in THIS render; the effect has not run yet. Report the
    // load that is about to start rather than the previous query's answer: this
    // query's kept answer if it has one, else nothing.
    const next = seeded<T>(requestKey, seed);
    return {
      data: next.data, error: null, loading: next.loading, refreshing: next.refreshing, refreshError: null,
      mutate, retry, refresh,
    };
  }
  return {
    data: state.data,
    error: state.error,
    loading: state.loading,
    refreshing: state.refreshing,
    refreshError: state.refreshError,
    mutate,
    retry,
    refresh,
  };
}

/** The name a kept answer is filed under, or null when a dependency is not
 *  plain data and so cannot be part of a name. */
function keptName(keep: string, dependencies: DependencyList): string | null {
  const plain = dependencies.every((value) =>
    typeof value !== "function" && typeof value !== "symbol" && typeof value !== "bigint");
  return plain ? `${keep}:${JSON.stringify(dependencies)}` : null;
}

/** The state a request starts in: its kept answer, refreshing, or a load. */
function seeded<T>(requestKey: symbol, seed: { value: unknown } | undefined) {
  return seed
    ? { requestKey, data: seed.value as T, error: null, loading: false, refreshing: true, refreshError: null }
    : { requestKey, data: null, error: null, loading: true, refreshing: false, refreshError: null };
}

/** Re-read a resource in place when `value` changes after mount, never for the
 *  value it mounted with.
 *
 *  For an epoch a screen re-reads on (`useSyncEpoch().referenceVersion`): the
 *  resource already fetched on mount, so reacting to the mount's value too is a
 *  second request for the same thing. Remembering the last value seen is what
 *  makes it a change; `value > 0` is not, since every mount after the first
 *  change sees a positive value. `refresh` is read at the change, so a new
 *  identity neither fires it nor goes stale. Lives here, not in a module of its
 *  own: every caller already loads this one, and a new shared chunk is a name
 *  the shell's preload table carries. */
export function useRefetchOn(value: unknown, refresh: AsyncResource<unknown>["refresh"]): void {
  const seen = useRef(value);
  const latest = useRef(refresh);
  useEffect(() => {
    latest.current = refresh;
  });
  useEffect(() => {
    if (Object.is(seen.current, value)) return;
    seen.current = value;
    void latest.current({ preserveData: true });
  }, [value]);
}
