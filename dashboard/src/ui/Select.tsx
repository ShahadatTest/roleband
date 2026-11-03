import { useId } from "react";
import { Icon } from "./Icon";
import "./Select.css";

/* THE native select in the app's control rank (docs/ui.md):
 * one value from a closed set too long for a Segmented, in a 36px `md` box
 * beside a SearchField.
 *
 * Two platform behaviours are owned here, not inherited:
 *
 * 1. The popup indicator. A select wears the platform's chevron OR ours,
 *    never both. The wrapper suppresses the native one and places an `Icon`
 *    in the gap it reserves — at the SAME inset the text has, so the two
 *    sides of the control are symmetric by construction.
 *
 * 2. The focus ring's trigger. Chromium matches `:focus-visible` on a
 *    MOUSE-focused select (it classes selects with keyboard controls), and a
 *    native select emits no close event — so a click, then Escape or the same
 *    value again, would leave the keyboard ring on until the next click anywhere.
 *    Pointer focus is marked with `data-pointer` and the ring rule excludes
 *    it; a key press or a Tab-in clears the mark and paints the ring. Keyboard
 *    users keep 2.4.7; mouse users get a control at rest.
 */
export interface SelectOption<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
}

export interface SelectProps<T extends string> {
  /** Accessible name — what is being chosen. */
  label: string;
  value: T;
  onChange: (value: T) => void;
  options: readonly SelectOption<T>[];
  disabled?: boolean;
  id?: string;
  className?: string;
  /** Why the choice reads as it does: its accessible description, and its
   *  title on hover. */
  description?: string;
}

export function Select<T extends string>({ label, value, onChange, options, disabled, id, className, description }: SelectProps<T>) {
  const describedId = useId();
  return (
    <span className={`ui-select${className ? ` ${className}` : ""}`} title={description}>
      {description && <span id={describedId} className="sr-only">{description}</span>}
      <select
        id={id}
        aria-label={label}
        aria-describedby={description ? describedId : undefined}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as T)}
        onPointerDown={(e) => {
          e.currentTarget.dataset.pointer = "";
        }}
        onKeyDown={(e) => {
          // Escape only dismisses the popup the pointer opened; it is not the
          // keyboard taking over. Any other key (arrows, typeahead, Enter) is.
          if (e.key === "Escape") return;
          delete e.currentTarget.dataset.pointer;
        }}
        onBlur={(e) => {
          // On macOS Chrome the popup is its own window: opening it blurs
          // the element while it STAYS document.activeElement, and closing
          // it focuses again. Clearing the mark on that blur would put the
          // ring on after a click that chose nothing. Only a blur that
          // actually moved focus ends pointer mode.
          const el = e.currentTarget;
          setTimeout(() => {
            if (document.activeElement !== el) delete el.dataset.pointer;
          }, 0);
        }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
      </select>
      <Icon name="chevronDown" size={14} />
    </span>
  );
}
