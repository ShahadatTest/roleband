import { useMemo } from "react";
import type { AsyncResource } from "./useAsyncResource";

/** Hold an `AsyncResource`'s identity still while its contents are unchanged.
 *
 *  `useAsyncResource` builds its result from an object literal, so every render
 *  produces a new one. That is invisible to a screen that reads the fields, and
 *  fatal to a PROVIDER that publishes the resource through a context: the
 *  context value cannot be memoized, because one of its dependencies has a new
 *  identity every time. Every consumer then re-renders on any provider render,
 *  which on the Companies register is every cell.
 *
 *  An `AsyncResource` is exactly five read fields and three callbacks, and the
 *  callbacks are already stable, so the identity is fully determined by the
 *  fields. The literal below is typed, so a field added to the interface fails
 *  the build here rather than being dropped from the comparison in silence.
 *
 *  Opt-in rather than folded into `useAsyncResource`: stabilising that hook's
 *  own return would change identity semantics for every reader in the app, and
 *  the case that needs it is a provider handing a resource to a context. */
export function useStableResource<T>(resource: AsyncResource<T>): AsyncResource<T> {
  const { data, error, loading, refreshing, refreshError, mutate, retry, refresh } = resource;
  return useMemo(
    () => ({ data, error, loading, refreshing, refreshError, mutate, retry, refresh }),
    [data, error, loading, refreshing, refreshError, mutate, retry, refresh],
  );
}
