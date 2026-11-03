import { ButtonHTMLAttributes, forwardRef } from "react";
import "./FilterChip.css";

/* A pill that turns one facet of a view on or off — a company filter, a
 * notification category, a skill family.
 *
 * `selected` is rendered as `aria-pressed`, so the state a reader sees and the
 * state a screen reader hears are the same fact. That is the whole reason the
 * prop exists rather than callers passing a class: a class is not announced
 * (docs/ui.md).
 */
export interface FilterChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  selected?: boolean;
}

export const FilterChip = forwardRef<HTMLButtonElement, FilterChipProps>(
  function FilterChip({ selected = false, className, type = "button", ...rest }, ref) {
    return (
      <button
        ref={ref}
        type={type}
        aria-pressed={selected}
        className={`ui-chip${className ? ` ${className}` : ""}`}
        {...rest}
      />
    );
  },
);
