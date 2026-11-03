import { ReactNode } from "react";
import "./Badge.css";

// Badge (F1 primitive): tone × variant × size, tokens only. A `tag` is the
// job row's read-only label: the same tones and fills in a rect at the row's
// own type floor, so a row's labels have one owner.

/** `principal` and `director` are the level bands' categorical hues, not
 *  status: they say which band, never good or bad. */
export type BadgeTone = "neutral" | "info" | "success" | "warning" | "danger" | "accent" | "principal" | "director";
/** `tint` is the soft ground with its own edge: a label that sits among others
 *  on a row and needs its outline to stay apart from them. */
export type BadgeVariant = "solid" | "soft" | "outline" | "tint";
export type BadgeSize = "sm" | "md";
export type BadgeShape = "pill" | "tag";

export interface BadgeProps {
  children: ReactNode;
  tone?: BadgeTone;
  variant?: BadgeVariant;
  /** A pill's size; a tag has one size, the row's. */
  size?: BadgeSize;
  shape?: BadgeShape;
  /** A dashed edge: a value shown but not confirmed. */
  dashed?: boolean;
  title?: string;
  className?: string;
}

export function Badge({
  children,
  tone = "neutral",
  variant = "soft",
  size = "md",
  shape = "pill",
  dashed = false,
  title,
  className,
}: BadgeProps) {
  const geometry = shape === "tag" ? "ui-badge-tag" : `ui-badge-${size}`;
  return (
    <span
      className={`ui-badge ui-badge-${tone} ui-badge-${variant} ${geometry}${dashed ? " ui-badge-dashed" : ""}${
        className ? ` ${className}` : ""
      }`}
      title={title}
    >
      {children}
    </span>
  );
}
