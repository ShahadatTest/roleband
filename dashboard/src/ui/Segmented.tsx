import { ReactNode } from "react";
import "./Segmented.css";

/* THE segmented control: one value chosen from a short closed set, shown as a
 * sunken track with the chosen segment in the chosen wash. docs/ui.md
 *
 * One primitive, because a recipe written per screen remembers a different
 * subset of the states each time, and one copy may announce nothing to a
 * screen reader. Selection is `aria-pressed`, the one convention every
 * control in src/ui/ uses; the stylesheet keys off the attribute, so the
 * accessible name and the paint cannot disagree.
 *
 * Geometry is the control scale's `sm` rank (28 / 10 / radius-sm / meta), the
 * same box as a small Button and a FilterChip. A 36px switch with count
 * badges (the Review view switch) is a tab bar, not a segmented control: it
 * is ui/TabBar.
 */
export interface SegmentedOption<T extends string> {
  value: T;
  label: ReactNode;
  disabled?: boolean;
}

export interface SegmentedProps<T extends string> {
  /** Accessible name of the group — what is being chosen. */
  label: string;
  value: T;
  onChange: (value: T) => void;
  options: readonly SegmentedOption<T>[];
  className?: string;
}

export function Segmented<T extends string>({ label, value, onChange, options, className }: SegmentedProps<T>) {
  return (
    <div className={`ui-seg${className ? ` ${className}` : ""}`} role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className="ui-seg-btn"
          aria-pressed={option.value === value}
          disabled={option.disabled}
          onClick={() => {
            if (option.value !== value) onChange(option.value);
          }}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
