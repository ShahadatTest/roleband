import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import "./Switch.css";

/* THE on/off control (docs/ui.md): a single boolean the screen
 * commits IMMEDIATELY, which is what separates it from a checkbox in a form
 * whose Save button is the commit. One primitive, so no screen spells its own
 * switch or labelled row.
 *
 * Three things the primitive owns so a wearer cannot get them wrong:
 *
 * 1. The hit target is the LABEL, not the track. 32x18 is the right size for
 *    a 34px register row and far below any pointer minimum, so the wrapper
 *    stretches to the row and the control does not have to distort to be
 *    reachable. Wrapping in a <label> also means the padding is live, which a
 *    `<span>` wrapper's is not.
 * 2. An accessible name is not optional. `label` names a bare switch;
 *    `children` puts the name on screen beside it. The props type demands one
 *    or the other, so a nameless switch does not compile.
 * 3. `indeterminate` is a DOM property with no attribute, so React cannot set
 *    it from JSX. A wearer that wants the half-state gets it from the prop
 *    instead of reaching for a ref of its own.
 */

interface SwitchBase {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  /** The half-state: some of what this switch governs is on. */
  indeterminate?: boolean;
  /** id of the element(s) that explain the switch. */
  describedBy?: string;
  title?: string;
  className?: string;
  /** `label` is third-party text, such as a company's name. */
  labelIsContent?: boolean;
}

export type SwitchProps = SwitchBase &
  (
    | { children: ReactNode; label?: string }
    | { children?: undefined; label: string }
  );

export function Switch({
  checked,
  onChange,
  children,
  label,
  disabled,
  indeterminate = false,
  describedBy,
  title,
  className,
  labelIsContent = false,
}: SwitchProps) {
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (input.current) input.current.indeterminate = indeterminate;
  }, [indeterminate]);

  return (
    <label
      className={`ui-switch${children != null ? " is-labelled" : ""}${className ? ` ${className}` : ""}`}
      title={title}
    >
      <input
        ref={input}
        className="ui-switch-track"
        type="checkbox"
        checked={checked}
        disabled={disabled}
        aria-label={label}
        // A name RoleBand did not write (a company's): the pseudo-locale scan
        // reads it as content, as it reads `ui/Content`.
        data-copy={labelIsContent ? "content" : undefined}
        aria-describedby={describedBy}
        onChange={(event) => onChange(event.target.checked)}
      />
      {children}
    </label>
  );
}
