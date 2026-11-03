import { commonTryAgain } from "../copy/gen/common";
import { uiLoadFailed, uiLoadFailedHint, uiLoading } from "../copy/gen/ui";
import { Button } from "./Button";

// AsyncBoundary reuses it for its default loading and error renders.
//
// The class names below are the shared ones (.loading/.spinner/.panel/
// .empty-hint): this primitive renders on every screen, so it cannot pick a
// scope, and design/overlays.css states them once, unscoped. The retry
// control is the promoted Button — it is the primitive's own, not a screen's
// class.
export function ResourceLoadState({
  error,
  loading,
  failed,
  onRetry,
  gone,
}: {
  error: Error | null;
  /** "Loading this page…": the whole line, from the catalog. Whole, never a
      noun the primitive completes: a sentence assembled from a fragment
      cannot be translated. */
  loading?: string;
  /** "Couldn't load this page": the whole heading, from the catalog. */
  failed?: string;
  /** Re-runs the request. Omit only for a loading line that will resolve
      on its own; an error with no way out is the state this exists to end. */
  onRetry?: () => void;
  /** Set when the thing is gone (the caller read a 404): said
      instead of the failure line, and with no Try again, which cannot bring
      it back. The caller decides; this tier does not read HTTP statuses. */
  gone?: string;
}) {
  if (!error) {
    return (
      <div className="loading" role="status">
        <div className="spinner" aria-hidden="true" /> {loading ?? uiLoading()}
      </div>
    );
  }

  return (
    <div className="panel" role="alert">
      <h3>{failed ?? uiLoadFailed()}</h3>
      {/* The person's words: "The API request failed. Check the service" named
          machinery they cannot act on (docs/copy.md rule 6). */}
      <div className="empty-hint">{gone ?? uiLoadFailedHint()}</div>
      {onRetry && !gone && <Button onClick={onRetry}>{commonTryAgain()}</Button>}
    </div>
  );
}
