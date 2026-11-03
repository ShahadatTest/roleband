import "./Spinner.css";

// Spinner (F1 primitive): an inline busy indicator for a value that is still
// arriving while its surroundings are already usable — a table cell whose
// aggregate loads after the row, a button mid-request. It is deliberately NOT
// a page state: a whole view waiting on its data belongs in AsyncBoundary.
//
// `label` is what a screen reader announces. It is required because a bare
// spinning box tells assistive tech nothing; pass what is loading, not
// "loading" ("Open roles loading" beats "Loading…").

export type SpinnerSize = "sm" | "md";

export interface SpinnerProps {
  label: string;
  size?: SpinnerSize;
  className?: string;
}

export function Spinner({ label, size = "md", className }: SpinnerProps) {
  return (
    <span
      role="status"
      aria-label={label}
      className={`ui-spinner${size === "sm" ? " sm" : ""}${className ? ` ${className}` : ""}`}
    />
  );
}
