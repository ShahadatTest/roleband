import "./ProgressBar.css";

// ProgressBar (F1 primitive): a determinate bar with its value exposed to
// assistive technology.

export interface ProgressBarProps {
  value: number;
  max: number;
  /** What is being counted; the accessible name. */
  label: string;
  className?: string;
}

export function ProgressBar({ value, max, label, className }: ProgressBarProps) {
  const bounded = Math.max(0, Math.min(value, max));
  const percent = max > 0 ? Math.round((100 * bounded) / max) : 0;
  return (
    <span
      className={`ui-progress${className ? ` ${className}` : ""}`}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={bounded}
    >
      <i style={{ width: `${percent}%` }} />
    </span>
  );
}
