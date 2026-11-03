import { commonTryAgain } from "../copy/gen/common";
import { sharedEmpty, sharedRefreshFailed } from "../copy/gen/shared";
import { ReactNode } from "react";
import type { AsyncResource } from "../hooks/useAsyncResource";
import { Button } from "./Button";
import { EmptyState } from "./EmptyState";
import { ResourceLoadState } from "./ResourceLoadState";

// AsyncBoundary (F1 primitive): canonical loading/error/empty/ready shell over
// a useAsyncResource result. Reuses ResourceLoadState for the default loading
// and error renders (no fork); slots override presentation, never the state
// machine. Hand-rolled loading states are ratchet-tracked.

export interface AsyncBoundaryProps<T> {
  /** Result of useAsyncResource (mutate not required).
   *
   *  `refreshError` is optional so a hand-built resource still type-checks, but
   *  passing the whole hook result is the point: it is the only thing that
   *  renders a failed background refresh. */
  resource: Pick<AsyncResource<T>, "data" | "error" | "loading" | "retry"> & {
    refreshError?: Error | null;
  };
  /** "Loading your saved roles…": the whole loading line, from the catalog,
   *  as are the messages below: a sentence assembled from a noun cannot be
   *  translated. Unused when `skeleton` is given. */
  loading?: string;
  /** "Couldn't load your saved roles": the whole failure heading. */
  failed?: string;
  /** "No scan schedule yet": the default empty state's title. Unused when
   *  `empty` is given. */
  emptyTitle?: string;
  /** "Couldn't refresh plugins. Showing the last result.": said above the
   *  data a failed background refresh left on screen. */
  refreshFailed?: string;
  /** Ready render — only called with loaded, non-empty data. */
  children: (data: T) => ReactNode;
  /** Loading slot (e.g. skeleton rows). Defaults to the spinner line. */
  skeleton?: ReactNode;
  /** When provided and true for the loaded data, renders the empty slot. */
  isEmpty?: (data: T) => boolean;
  /** Empty slot. Defaults to the radar EmptyState. */
  empty?: ReactNode;
}

export function AsyncBoundary<T>({
  resource,
  children,
  skeleton,
  isEmpty,
  empty,
  loading: loadingLine,
  failed,
  emptyTitle,
  refreshFailed,
}: AsyncBoundaryProps<T>) {
  const { data, error, loading, retry, refreshError } = resource;
  if (loading) {
    return <>{skeleton ?? <ResourceLoadState error={null} loading={loadingLine} onRetry={retry} />}</>;
  }
  if (error) {
    return <ResourceLoadState error={error} failed={failed} onRetry={retry} />;
  }
  /* A resolved-null payload is EMPTY, not failed. "Couldn't load" over an
     Error this component fabricated tells the user to retry a request that
     already succeeded, and hides a real empty state behind a false failure. */
  if (data == null || isEmpty?.(data)) {
    return <>{empty ?? <EmptyState title={emptyTitle ?? sharedEmpty()} />}</>;
  }
  /* No refresh error: return the children EXACTLY as before, a single child and
     not a one-element array. Wrapping them alongside a null sibling changes the
     shape React reconciles, which remounts the subtree on the
     loading -> ready transition — enough to detach a node a test had already
     matched, and enough to lose DOM state (focus, scroll, a playing media
     element) in a real screen. */
  if (!refreshError) return <>{children(data)}</>;

  return (
    <>
      {/* A failed REFRESH keeps its data on screen by design (that is why
          `useAsyncResource` routes it to `refreshError` instead of `error`),
          and this is where it renders: unrendered, a failing poll leaves a
          frozen list looking freshly loaded. Stale is survivable; stale and
          confident is not. */}
      <div className="empty-hint" role="status">
        {refreshFailed ?? sharedRefreshFailed()}{" "}
        <Button variant="ghost" size="sm" onClick={retry}>
          {commonTryAgain()}
        </Button>
      </div>
      {children(data)}
    </>
  );
}
