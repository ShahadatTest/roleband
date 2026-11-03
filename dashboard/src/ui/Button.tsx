import { ButtonHTMLAttributes, forwardRef } from "react";
import "./Button.css";

/* THE app button. Every clickable thing in the app is this component or one of
 * the named selection controls beside it — see docs/ui.md, which
 * carries the catalog and the mapping from every legacy spelling. It carries
 * the size scale and the states a screen-local class forgets.
 *
 * Variants, by INTENT rather than by look:
 *   primary  commits state (Save, Submit, Start sync). One per view, usually.
 *   ghost    the default rank: openers, Cancel, diagnostics, row actions.
 *   icon     icon-only square. REQUIRES an aria-label from the caller.
 *   link     a quiet verb inside running text. No box.
 *   danger   destructive and irreversible. Rare on purpose.
 *
 * Size is the control scale (28 / 36 / 44), never a literal: `sm` is for dense
 * rows and toolbars, `md` is the default, `lg` is for a page's one big CTA.
 * `link` takes no size — it is text, and inherits the line it sits in.
 */
export type ButtonVariant = "primary" | "ghost" | "icon" | "link" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "ghost", size = "md", className, type = "button", ...rest },
  ref,
) {
  // `link` is text in a sentence, so it takes no box from the size scale.
  const sized = variant === "link" ? "" : ` ui-btn-${size}`;
  const classes = `ui-btn ui-btn-${variant}${sized}${className ? ` ${className}` : ""}`;
  return <button ref={ref} type={type} className={classes} {...rest} />;
});
