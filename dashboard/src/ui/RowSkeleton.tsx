import "./RowSkeleton.css";

/** The loading shape of a list of rows, for `AsyncBoundary`'s `skeleton` slot.
 *  Hidden from assistive tech: the boundary's own state says it is loading. */
export function RowSkeleton({ rows = 8, cells = 4 }: { rows?: number; cells?: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, i) => (
        <div className="ui-skel-row" key={i} aria-hidden="true">
          {Array.from({ length: cells }, (_, j) => <span className="ui-skel" key={j} />)}
        </div>
      ))}
    </>
  );
}
