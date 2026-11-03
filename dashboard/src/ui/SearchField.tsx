import { InputHTMLAttributes, ReactNode, forwardRef } from "react";
import { Icon } from "./Icon";
import "./SearchField.css";

/* THE search field: type to filter what is on the screen.
 * docs/ui.md
 *
 * One primitive, so no screen hand-rolls a field at its own height. One
 * recipe, three sizes:
 *
 *   sm  28 / meta 13  — a filter inside a panel or popover
 *   md  36 / body 14  — a screen's toolbar search (the default)
 *   lg  48 / name 15  — the one-dominant-control pattern (Profile locations,
 *                       docs/ui.md): nothing else beside it
 *
 * The glyph leads, a key hint may trail, and the focus ring is the app's one
 * ring. The field announces itself by `label`.
 */
export type SearchFieldSize = "sm" | "md" | "lg";

export interface SearchFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "size" | "type"> {
  /** Accessible name — what is being searched. */
  label: string;
  value: string;
  onChange: (value: string) => void;
  size?: SearchFieldSize;
  /** A key hint or count after the text, outside the input. */
  trailing?: ReactNode;
  /** Class for the WRAPPER (layout hooks: width, flex). */
  className?: string;
}

export const SearchField = forwardRef<HTMLInputElement, SearchFieldProps>(function SearchField(
  { label, value, onChange, size = "md", trailing, className, ...rest },
  ref,
) {
  return (
    <label className={`ui-search ui-search-${size}${className ? ` ${className}` : ""}`}>
      <Icon name="search" size={size === "sm" ? 14 : 16} />
      <input
        ref={ref}
        type="search"
        className="ui-search-input"
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        {...rest}
      />
      {trailing != null && (
        <span className="ui-search-trailing" aria-hidden="true">
          {trailing}
        </span>
      )}
    </label>
  );
});
